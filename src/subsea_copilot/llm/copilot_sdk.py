"""Warm owned CLI runtime; each inference still gets a fresh tool-disabled session."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from copilot import CopilotClient, RuntimeConnection
from copilot.rpc import PermissionDecisionReject
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .copilot_cli import (
    CopilotCLIChatModel,
    ProviderError,
    _child_environment,
    _decode,
    _metadata,
    _schemas,
    _WindowsJob,
    render_prompt,
)

LOGGER = logging.getLogger(__name__)
_HOSTS: dict[Path, RuntimeHost] = {}
_HOST_LOCK = threading.Lock()


class RuntimeHost:
    def __init__(self, directory: Path) -> None:
        self.directory = directory / "copilot-sdk"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self.loop.run_forever, name="copilot-sdk", daemon=True,
        )
        self.thread.start()
        self.client: CopilotClient | None = None
        self.start_lock = asyncio.Lock()
        self.job: _WindowsJob | None = None
        self.version: str | None = None
        self.process: subprocess.Popen[bytes] | None = None

    async def _client(self) -> CopilotClient:
        async with self.start_lock:
            if self.client is None:
                executable = shutil.which("copilot")
                if not executable or Path(executable).suffix.lower() in {".cmd", ".bat"}:
                    raise ProviderError("cli_missing")
                client = CopilotClient(
                    connection=RuntimeConnection.for_stdio(path=executable, args=(
                        "--disable-builtin-mcps", "--no-custom-instructions", "--no-ask-user",
                    )),
                    working_directory=str(self.directory),
                    env=_child_environment(os.environ), log_level="none",
                    use_logged_in_user=True,
                )
                self.client = client
                try:
                    await client.start()
                    process = getattr(client, "_cli_process", None)
                    if not isinstance(process, subprocess.Popen):
                        raise ProviderError("cli_start_failed")
                    self.process = process
                    if os.name == "nt":
                        # The pinned SDK owns this Popen; retain the existing orphan-tree guard.
                        self.job = _WindowsJob(process)
                    self.version = (await client.get_status()).version
                except BaseException:
                    self.client = None
                    await client.force_stop()
                    if self.job:
                        self.job.close()
                        self.job = None
                    raise
            return self.client

    async def invoke(
        self, prompt: str, model: CopilotCLIChatModel, request_id: str, deadline: float,
    ) -> tuple[str, dict[str, Any]]:
        started = time.monotonic()
        remaining = deadline - started
        cleanup_budget = min(3.0, remaining * 0.1)
        events: list[dict[str, Any]] = []
        size = 0
        rejected: ProviderError | None = None
        session = None
        completed = False
        creation_started = False

        def observe(event: Any) -> None:
            nonlocal size, rejected
            if event.agent_id:
                return
            kind = event.type.value
            if kind.startswith("tool.execution"):
                rejected = ProviderError("invalid_tool_call")
            if kind not in {
                "assistant.message", "assistant.usage", "session.model_change",
                "session.start", "model.model_call_success",
            }:
                return
            value = event.to_dict()
            size += len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
            if size > model.max_capture_bytes:
                rejected = ProviderError("output_too_large")
                return
            if kind == "assistant.usage":
                data = value["data"]
                value = {"type": "session.usage_record", "data": {"usage": {
                    key: data.get(key) for key in (
                        "model", "inputTokens", "outputTokens", "cacheReadTokens",
                        "cacheWriteTokens", "reasoningTokens",
                    )
                }}}
            events.append(value)

        try:
            async with asyncio.timeout(max(0, remaining - cleanup_budget)):
                client = await self._client()
                ready = time.monotonic()
                creation_started = True
                session = await client.create_session(
                    session_id=request_id, model=model.model_id,
                    available_tools=[], excluded_tools=["builtin:*", "mcp:*", "custom:*"],
                    tools=[], mcp_servers={}, custom_agents=[],
                    on_permission_request=lambda request, invocation: PermissionDecisionReject(),
                    enable_config_discovery=False, skip_custom_instructions=True,
                    enable_file_hooks=False, enable_host_git_operations=False,
                    enable_skills=False, enable_session_store=False,
                    enable_session_telemetry=False,
                    memory={"enabled": False}, skip_embedding_retrieval=True,
                    enable_on_demand_instruction_discovery=False,
                    custom_agents_local_only=True, coauthor_enabled=False,
                    manage_schedule_enabled=False,
                    skill_directories=[], agent_directories=[], hook_directories=[],
                    plugin_directories=[], instruction_directories=[],
                    system_message={
                        "mode": "replace",
                        "content": "Return only the structured envelope requested in the prompt.",
                    },
                    on_event=observe,
                )
                response = await session.send_and_wait(
                    prompt, timeout=max(0.001, deadline - time.monotonic() - cleanup_budget),
                )
                if rejected:
                    raise rejected
                content = getattr(response.data, "content", None) if response else None
                if not isinstance(content, str):
                    raise ProviderError("empty_response")
                if len(content) > model.max_final_chars:
                    raise ProviderError("output_too_large")
                metadata = _metadata(events, model.model_id)
                metadata.update(
                    model_identity_source="sdk_event"
                    if metadata["observed_model"] else metadata["model_identity_source"],
                    runtime_ready_ms=round((ready - started) * 1000, 3),
                    transport="persistent-sdk",
                    cli_version=self.version, cli_version_source="sdk_status",
                    usage_source="sdk_event" if metadata["usage_available"] else "unknown",
                )
                completed = True
                return content, metadata
        except TimeoutError:
            raise ProviderError("timeout") from None
        finally:
            if creation_started and self.client is not None:
                try:
                    async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                        if session is not None and not completed:
                            await session.abort()
                        await self.client.delete_session(request_id)
                except Exception:
                    LOGGER.error("Owned SDK session cleanup failed request_id=%s", request_id)
                    client, self.client = self.client, None
                    if self.job:
                        self.job.close()
                        self.job = None
                    await client.force_stop()
                    raise ProviderError("capture_cleanup_failed") from None

    def close(self, *, graceful: bool = True) -> None:
        async def shutdown() -> None:
            if self.client is not None:
                await self.client.stop()

        try:
            if graceful:
                asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=10)
        except Exception:
            LOGGER.error("Graceful Copilot SDK shutdown failed; forcing owned runtime stop")
        finally:
            if self.job:
                self.job.close()
                self.job = None
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
            if not self.thread.is_alive():
                self.loop.close()


def close_hosts(*, graceful: bool = True) -> None:
    with _HOST_LOCK:
        hosts = list(_HOSTS.values())
        _HOSTS.clear()
    for host in hosts:
        host.close(graceful=graceful)


# Interpreter executor teardown precedes atexit; only synchronous owned-process cleanup is safe.
atexit.register(lambda: close_hosts(graceful=False))


def generate(
    model: CopilotCLIChatModel, messages: list[BaseMessage], stop: list[str] | None,
    kwargs: dict[str, Any],
) -> ChatResult:
    started = time.monotonic()
    if stop or set(kwargs) - {"tools", "timeout"}:
        raise ProviderError("unsupported_request")
    timeout = kwargs.get("timeout", model.timeout_seconds)
    if (
        not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0
    ):
        raise ProviderError("timeout")
    deadline = started + min(timeout, model.timeout_seconds)
    tools = _schemas(kwargs.get("tools", []))
    prompt = render_prompt(messages, tools)
    if len(prompt) > model.max_prompt_chars:
        raise ProviderError("input_too_large")
    request_id = str(uuid.uuid4())
    metadata: dict[str, Any] = {
        "request_id": request_id, "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
        "transport_protocol": "native-final-object-v2",
        "transport": "persistent-sdk",
    }
    with _HOST_LOCK:
        directory = model.runtime_dir.resolve()
        if directory not in _HOSTS:
            _HOSTS[directory] = RuntimeHost(directory)
        host = _HOSTS[directory]
        future = asyncio.run_coroutine_threadsafe(
            host.invoke(prompt, model, request_id, deadline), host.loop,
        )
    try:
        content, observed = future.result(timeout=max(0.001, deadline - time.monotonic()))
        metadata.update(observed)
        response = _decode(content, {tool["name"] for tool in tools})
        metadata.update(
            result_hash=hashlib.sha256(content.encode()).hexdigest(),
            duration_ms=round((time.monotonic() - started) * 1000, 3),
        )
        response.response_metadata = metadata
        return ChatResult(generations=[ChatGeneration(message=response)], llm_output=metadata)
    except concurrent.futures.TimeoutError:
        future.cancel()
        error = ProviderError("timeout")
    except ProviderError as exc:
        error = exc
    except Exception as exc:
        # Provider exception text can contain prompts or credentials; only classify it locally.
        diagnostic = str(exc).lower()
        error = ProviderError(
            "proxy_quota" if any(word in diagnostic for word in ("quota", "429", "rate limit"))
            else "proxy_auth" if any(word in diagnostic for word in ("401", "403", "auth"))
            else "proxy_error"
        )
    error.metadata.update(metadata, duration_ms=round((time.monotonic() - started) * 1000, 3))
    raise error
