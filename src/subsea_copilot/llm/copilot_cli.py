"""Bounded stdin/JSONL transport; model tool requests never execute in the CLI."""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field, field_validator

from subsea_copilot.prompts import load_prompt

_REMOVED_ENV = {
    "COPILOT_AGENT_SESSION_ID",
    "COPILOT_CLI",
    "COPILOT_CLI_BINARY_VERSION",
    "COPILOT_CLI_RESOLVED_DIST_DIR",
    "COPILOT_LOADER_PID",
    "COPILOT_ALLOW_ALL",
    "COPILOT_CUSTOM_INSTRUCTIONS_DIRS",
}
_ERROR_MESSAGES = {
    "cli_missing": "Copilot executable is unavailable.",
    "cli_start_failed": "Copilot process could not start.",
    "proxy_auth": "Copilot authentication was rejected.",
    "proxy_quota": "Copilot quota is unavailable.",
    "proxy_error": "Copilot request failed.",
    "timeout": "Copilot request exceeded its deadline.",
    "input_too_large": "Prompt exceeds the configured bound.",
    "output_too_large": "Provider capture exceeds the configured bound.",
    "empty_response": "No final assistant response was returned.",
    "invalid_structured_output": "Response does not match the structured envelope.",
    "invalid_tool_call": "Response contains an invalid application tool request.",
    "unsupported_request": "Unsupported model invocation option.",
    "capture_cleanup_failed": "Owned Copilot capture cleanup failed; no response accepted.",
}
LOGGER = logging.getLogger(__name__)
_VERSION_CACHE: dict[tuple[str, int, int], str | None] = {}
_VERSION_LOCK = threading.Lock()


def _child_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Preserve GitHub authentication, never application/exporter credentials."""
    return {
        key: value
        for key, value in source.items()
        if key.upper() not in _REMOVED_ENV
        and key.upper()
        not in {
            "DATABASE_URL",
            "PGPASSWORD",
            "PGPASSFILE",
            "LANGCHAIN_API_KEY",
        }
        and not key.upper().startswith(
            (
                "COPILOT_ALLOW_ALL",
                "COPILOT_CUSTOM_INSTRUCTIONS",
                "SUBSEA_",
                "LF_",
                "LANGFUSE_",
                "LANGSMITH_",
                "OTEL_",
            )
        )
    }


class _WindowsJob:
    """An owned job closes orphaned descendants even if the CLI exits first."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class Limits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", Counters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (
            not self.handle
            or not kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            )
            or not kernel.AssignProcessToJobObject(self.handle, int(process.__dict__["_handle"]))
        ):
            self.close()
            raise OSError("Cannot isolate the owned process tree.")

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class ProviderError(Exception):
    """Only categorized, content-free diagnostics cross the transport boundary."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code if code in _ERROR_MESSAGES else "proxy_error"
        super().__init__(_ERROR_MESSAGES[self.code])
        self.metadata: dict[str, Any] = {}


def _json(raw: str) -> Any:
    def object_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError
            value[key] = item
        return value

    def constant(value: str) -> None:
        raise ValueError

    return json.loads(raw, object_pairs_hook=object_hook, parse_constant=constant)


def _schemas(tools: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    names = set()
    for tool in tools:
        if not isinstance(tool, dict):
            raise ProviderError("unsupported_request")
        body = tool.get("function", tool)
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            raise ProviderError("unsupported_request")
        name = body["name"]
        parameters = body.get("parameters", body.get("input_schema"))
        if not name or name in names or not isinstance(parameters, dict):
            raise ProviderError("unsupported_request")
        if parameters.get("type") != "object":
            raise ProviderError("unsupported_request")
        names.add(name)
        result.append(
            {"name": name, "description": body.get("description", ""), "parameters": parameters}
        )
    return result


def _stop(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=5,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)  # type: ignore[attr-defined]
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _run_transport(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    prompt: bytes,
    deadline: float,
    stdout_limit: int,
    stderr_limit: int,
) -> tuple[int, bytes, bytes]:
    """Drain both pipes concurrently without unbounded communicate() buffers."""
    if time.monotonic() >= deadline:
        raise ProviderError("timeout")
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    except OSError:
        raise ProviderError("cli_start_failed") from None
    job = None
    if os.name == "nt":
        try:
            job = _WindowsJob(process)
        except OSError:
            _stop(process)
            raise ProviderError("cli_start_failed") from None
    buffers = [bytearray(), bytearray()]
    exceeded = threading.Event()
    failed = threading.Event()

    def drain(pipe: Any, index: int, limit: int) -> None:
        try:
            while chunk := pipe.read(8192):
                remaining = limit - len(buffers[index])
                buffers[index].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded.set()
                    break
        except OSError:
            failed.set()
        finally:
            pipe.close()

    def write() -> None:
        try:
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.close()
        except (OSError, BrokenPipeError):
            failed.set()

    workers = [
        threading.Thread(target=drain, args=(process.stdout, 0, stdout_limit), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, 1, stderr_limit), daemon=True),
        threading.Thread(target=write, daemon=True),
    ]
    for worker in workers:
        worker.start()
    error = None
    try:
        while process.poll() is None or any(worker.is_alive() for worker in workers):
            if exceeded.is_set():
                error = "output_too_large"
                break
            if time.monotonic() >= deadline:
                error = "timeout"
                break
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    finally:
        if job is not None:
            job.close()
        if error or process.poll() is None or any(worker.is_alive() for worker in workers):
            _stop(process)
        for worker in workers:
            worker.join(timeout=1)
    if exceeded.is_set():
        error = "output_too_large"
    if error:
        raise ProviderError(error)
    if failed.is_set() and process.returncode == 0:
        raise ProviderError("proxy_error")
    return process.returncode or 0, bytes(buffers[0]), bytes(buffers[1])


def _cleanup_capture(capture: Path, *, deadline: float) -> int:
    """Windows can release a terminated CLI's directory handles asynchronously."""
    for attempt in range(1, 5):
        try:
            shutil.rmtree(capture)
            return attempt
        except FileNotFoundError:
            if not capture.exists():
                return attempt
            break
        except PermissionError:
            remaining = deadline - time.monotonic()
            if attempt == 4 or remaining <= 0:
                break
            time.sleep(min(0.05 * 2 ** (attempt - 1), remaining))
        except OSError:
            break
    error = ProviderError("capture_cleanup_failed")
    error.metadata["capture_cleanup_attempts"] = attempt
    raise error


def _events(raw: bytes) -> list[dict[str, Any]]:
    result = []
    try:
        for line in raw.decode("utf-8").splitlines():
            if line.strip():
                value = _json(line)
                if not isinstance(value, dict):
                    raise ValueError
                result.append(value)
    except (ValueError, UnicodeError):
        raise ProviderError("invalid_structured_output") from None
    return result


def _cli_version(
    executable: str,
    *,
    cwd: Path,
    env: dict[str, str],
    deadline: float,
) -> str | None:
    """Cache a bounded non-inference lookup, invalidated when the binary changes."""
    try:
        stat = Path(executable).stat()
        key = (str(Path(executable).resolve()), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None
    with _VERSION_LOCK:
        if key in _VERSION_CACHE:
            return _VERSION_CACHE[key]
    version = None
    try:
        code, stdout, _ = _run_transport(
            [executable, "--version"],
            cwd=cwd,
            env=_child_environment(env),
            prompt=b"",
            deadline=min(deadline, time.monotonic() + 2),
            stdout_limit=4096,
            stderr_limit=4096,
        )
        if code == 0:
            match = re.search(
                r"\b\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\b",
                stdout.decode("utf-8", errors="replace"),
            )
            if match:
                version = match.group(0)[:100]
    except ProviderError:
        pass
    with _VERSION_LOCK:
        _VERSION_CACHE[key] = version
    return version


def _owned_metadata_events(
    env: Mapping[str, str],
    request_id: str,
    *,
    deadline: float,
    limit: int,
) -> list[dict[str, Any]]:
    """Read only this generated session, retaining no content or private reasoning."""
    try:
        if str(uuid.UUID(request_id)) != request_id or time.monotonic() >= deadline:
            return []
        configured = env.get("COPILOT_HOME")
        owner_home = env.get("HOME") or env.get("USERPROFILE")
        if not configured and not owner_home:
            return []
        root = Path(configured) if configured else Path(str(owner_home)) / ".copilot"
        session = root / "session-state" / request_id
        path = session / "events.jsonl"
        if session.is_symlink() or path.is_symlink() or path.stat().st_size > limit:
            return []
        with path.open("rb") as file:
            raw = file.read(limit + 1)
        if len(raw) > limit:
            return []
        result = []
        for line in raw.decode("utf-8").splitlines():
            if time.monotonic() >= deadline:
                return []
            if not line.strip():
                continue
            event = _json(line)
            if not isinstance(event, dict) or event.get("agentId"):
                continue
            data = event.get("data")
            kind = event.get("type")
            if not isinstance(data, dict) or data.get("agentId"):
                continue
            selected: dict[str, Any] = {}
            if kind == "session.start":
                value = data.get("copilotVersion")
                if isinstance(value, str):
                    selected["copilotVersion"] = value[:100]
            elif kind == "session.usage_record":
                usage = data.get("usage")
                if isinstance(usage, dict):
                    selected["usage"] = {
                        key: value
                        for key, value in usage.items()
                        if key
                        in {
                            "inputTokens",
                            "outputTokens",
                            "cacheReadTokens",
                            "cacheWriteTokens",
                            "reasoningTokens",
                            "model",
                        }
                        and (type(value) is int or isinstance(value, str))
                    }
            elif kind in {"session.model_change", "model.model_call_success"}:
                for key in ("model", "newModel"):
                    if isinstance(data.get(key), str):
                        selected[key] = data[key][:200]
            if selected:
                result.append({"type": kind, "data": selected})
        return result
    except (OSError, ValueError, UnicodeError):
        return []


def _final(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        data = event.get("data")
        if (
            event.get("type") == "assistant.message"
            and not event.get("agentId")
            and isinstance(data, dict)
            and not data.get("agentId")
            and data.get("phase") != "thinking"
            and isinstance(data.get("content"), str)
        ):
            return str(data["content"])
    raise ProviderError("empty_response")


def _decode(content: str, allowed: set[str]) -> AIMessage:
    stage = "outer_json"
    try:
        envelope = _json(content)
        stage = "envelope_shape"
        if not isinstance(envelope, dict) or set(envelope) != {"kind", "value"}:
            raise ValueError
        if envelope["kind"] == "final":
            value = envelope["value"]
            stage = "final_value_type"
            if not isinstance(value, dict):
                raise ValueError
            return AIMessage(content=json.dumps(
                value, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
            ))
        stage = "envelope_kind"
        if envelope["kind"] != "tool_calls":
            raise ValueError
    except (ValueError, TypeError):
        error = ProviderError("invalid_structured_output")
        error.metadata["response_validation_stage"] = stage
        raise error from None
    calls = envelope["value"]
    if not isinstance(calls, list) or not 1 <= len(calls) <= 24:
        raise ProviderError("invalid_tool_call")
    decoded = []
    summaries = {}
    for call in calls:
        if (
            not isinstance(call, dict)
            or set(call) - {"name", "arguments", "decision_summary"}
            or not isinstance(call.get("name"), str)
            or call["name"] not in allowed
            or not isinstance(call.get("arguments"), dict)
            or not isinstance(call.get("decision_summary", ""), str)
            or len(call.get("decision_summary", "")) > 1000
        ):
            raise ProviderError("invalid_tool_call")
        call_id = f"subsea_{uuid.uuid4().hex}"
        decoded.append({"id": call_id, "name": call["name"], "args": call["arguments"]})
        summaries[call_id] = call.get("decision_summary", "")
    return AIMessage(
        content="", tool_calls=decoded, additional_kwargs={"decision_summaries": summaries}
    )


def _metadata(events: list[dict[str, Any]], requested: str | None) -> dict[str, Any]:
    observed = None
    source = "requested_only" if requested else "unknown"
    records = []
    version = None
    for event in events:
        data = event.get("data")
        if not isinstance(data, dict) or event.get("agentId"):
            continue
        kind = event.get("type")
        if kind == "session.start":
            candidate_version = data.get("copilotVersion")
            if isinstance(candidate_version, str):
                version = candidate_version[:100]
        if kind == "session.usage_record" and isinstance(data.get("usage"), dict):
            records.append(data["usage"])
        if kind in {
            "assistant.message",
            "model.call_start",
            "model.call_final_result",
            "model.model_call_success",
            "session.model_change",
            "session.usage_record",
        }:
            candidate = data.get("model", data.get("newModel"))
            if kind == "session.usage_record":
                candidate = data.get("usage", {}).get("model", candidate)
            if isinstance(candidate, str) and candidate and len(candidate) <= 200:
                observed, source = candidate, "cli_event"
    usage = {}
    for key, provider_key in {
        "input_tokens": "inputTokens",
        "output_tokens": "outputTokens",
        "cache_read_tokens": "cacheReadTokens",
        "cache_write_tokens": "cacheWriteTokens",
        "reasoning_tokens": "reasoningTokens",
    }.items():
        values = [record.get(provider_key) for record in records]
        usage[key] = (
            sum(values)
            if values and all(type(value) is int and value >= 0 for value in values)
            else None
        )
    return {
        "requested_model": requested,
        "observed_model": observed,
        "model_identity_source": source,
        "usage": usage,
        "usage_available": any(value is not None for value in usage.values()),
        "usage_source": "cli_event" if records else "unknown",
        "cli_version": version,
        "cli_version_source": "cli_event" if isinstance(version, str) else "unknown",
    }


PROMPT_INSTRUCTIONS = load_prompt("transport").content.removesuffix("\n")


def render_prompt(messages: Sequence[BaseMessage], tools: Sequence[Any]) -> str:
    """Use the same wire envelope for context accounting, fingerprints and transport."""
    conversation = []
    for message in messages:
        if not isinstance(message.content, str):
            raise ProviderError("unsupported_request")
        item: dict[str, Any] = {"role": message.type, "content": message.content}
        try:
            if message.type == "system" and "\nBOUND_CONTEXT\n" in message.content:
                text, context = message.content.split("\nBOUND_CONTEXT\n", 1)
                item.update(content=text, bound_context=_json(context))
            elif (
                message.type == "tool" and message.content.startswith("{")
                or message.type == "human"
                and message.content.startswith(('{"application_intake":', '{"repair":'))
            ):
                item["content"] = _json(message.content)
        except ValueError:
            raise ProviderError("unsupported_request") from None
        if isinstance(message, ToolMessage):
            item["tool_call_id"] = message.tool_call_id
        if isinstance(message, AIMessage) and message.tool_calls:
            item["tool_calls"] = message.tool_calls
        conversation.append(item)
    try:
        prompt = json.dumps(
            {
                "instructions": PROMPT_INSTRUCTIONS,
                "conversation": conversation,
                "application_tools": _schemas(tools),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        prompt.encode("utf-8")
        return prompt
    except (ValueError, TypeError, UnicodeError):
        raise ProviderError("unsupported_request") from None


class CopilotCLIChatModel(BaseChatModel):
    runtime_dir: Path
    model_id: str | None = None
    timeout_seconds: float = Field(default=180, gt=0)
    max_prompt_chars: int = Field(default=144000, gt=0)
    max_final_chars: int = Field(default=36000, gt=0)
    max_capture_bytes: int = Field(default=6000000, gt=0)
    max_stderr_bytes: int = Field(default=192000, gt=0)

    @field_validator("model_id")
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        return None if value is None or value.lower() == "auto" else value

    @property
    def _llm_type(self) -> str:
        return "subsea-copilot-cli"

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        return {"model_id": self.model_id, "timeout_seconds": self.timeout_seconds}

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        if tool_choice not in (None, "auto") or kwargs:
            raise ProviderError("unsupported_request")
        return self.bind(tools=_schemas(tools))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        started = time.monotonic()
        if stop or set(kwargs) - {"tools", "timeout"}:
            raise ProviderError("unsupported_request")
        timeout = kwargs.get("timeout", self.timeout_seconds)
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ProviderError("timeout")
        deadline = started + min(float(timeout), self.timeout_seconds)
        tools = _schemas(kwargs.get("tools", []))
        prompt = render_prompt(messages, tools)
        prompt_bytes = prompt.encode("utf-8")
        if len(prompt) > self.max_prompt_chars:
            failure = ProviderError("input_too_large")
            failure.metadata = {
                "prompt_chars": len(prompt),
                "message_chars": [len(message.content) for message in messages],
                "tool_schema_chars": len(json.dumps(tools, separators=(",", ":"))),
            }
            raise failure
        request_id = str(uuid.uuid4())
        metadata: dict[str, Any] = {
            **_metadata([], self.model_id),
            "transport_protocol": "native-final-object-v2",
            "request_id": request_id,
            "prompt_hash": hashlib.sha256(prompt_bytes).hexdigest(),
        }
        capture = self.runtime_dir / "captures" / request_id
        primary_error: ProviderError | None = None
        try:
            executable = shutil.which("copilot")
            if not executable or Path(executable).suffix.lower() in {".bat", ".cmd"}:
                raise ProviderError("cli_missing")
            work, logs = capture / "work", capture / "logs"
            work.mkdir(parents=True)
            logs.mkdir()
            env = _child_environment(os.environ)
            command = [
                executable,
                "-C",
                str(work),
                "--session-id",
                request_id,
                "--output-format",
                "json",
                "--stream",
                "on",
                "--available-tools",
                "subsea_no_such_tool",
                "--no-custom-instructions",
                "--disable-builtin-mcps",
                "--no-ask-user",
                "--no-auto-update",
                "--disallow-temp-dir",
                "--deny-tool=shell",
                "--deny-tool=write",
                "--deny-tool=url",
                "--log-dir",
                str(logs),
            ]
            if self.model_id:
                command.extend(["--model", self.model_id])
            version = _cli_version(executable, cwd=work, env=env, deadline=deadline)
            if version:
                metadata.update(cli_version=version, cli_version_source="executable_version")
            code, stdout, stderr = _run_transport(
                command,
                cwd=work,
                env=env,
                prompt=prompt_bytes,
                deadline=deadline,
                stdout_limit=self.max_capture_bytes,
                stderr_limit=self.max_stderr_bytes,
            )
            metadata.update(stdout_bytes=len(stdout), stderr_bytes=len(stderr))
            # Diagnostic matching is local; raw provider text is never raised or persisted.
            diagnostic = (stderr + stdout).decode("utf-8", errors="replace").lower()
            events = _events(stdout) if code == 0 else []
            has_error = code != 0 or any(
                event.get("type") in {"session.error", "error"} for event in events
            )
            if has_error:
                if any(word in diagnostic for word in ("quota", "rate limit", "429")):
                    raise ProviderError("proxy_quota")
                if any(
                    word in diagnostic for word in ("401", "403", "unauthorized", "auth", "login")
                ):
                    raise ProviderError("proxy_auth")
                raise ProviderError("proxy_error")
            reported = _metadata(events, self.model_id)
            persisted = _metadata(
                _owned_metadata_events(
                    env,
                    request_id,
                    deadline=deadline,
                    limit=self.max_capture_bytes,
                ),
                self.model_id,
            )
            if not reported["observed_model"] and persisted["observed_model"]:
                reported["observed_model"] = persisted["observed_model"]
                reported["model_identity_source"] = "owned_session"
            if reported["usage_source"] == "unknown" and persisted["usage_source"] != "unknown":
                reported["usage"] = persisted["usage"]
                reported["usage_available"] = persisted["usage_available"]
                reported["usage_source"] = "owned_session"
            if version:
                reported.update(cli_version=version, cli_version_source="executable_version")
            elif not reported["cli_version"] and persisted["cli_version"]:
                reported.update(
                    cli_version=persisted["cli_version"],
                    cli_version_source="owned_session",
                )
            metadata.update(reported)
            content = _final(events)
            if len(content) > self.max_final_chars:
                raise ProviderError("output_too_large")
            response = _decode(content, {tool["name"] for tool in tools})
            metadata["result_hash"] = hashlib.sha256(content.encode()).hexdigest()
            metadata["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
            if time.monotonic() >= deadline:
                raise ProviderError("timeout")
            response.response_metadata = metadata
            return ChatResult(generations=[ChatGeneration(message=response)], llm_output=metadata)
        except ProviderError as exc:
            primary_error = exc
            exc.metadata.update(metadata, duration_ms=round((time.monotonic() - started) * 1000, 3))
            raise
        except OSError:
            primary_error = ProviderError("cli_start_failed")
            primary_error.metadata.update(
                metadata, duration_ms=round((time.monotonic() - started) * 1000, 3)
            )
            raise primary_error from None
        finally:
            if capture.exists():
                try:
                    metadata["capture_cleanup_attempts"] = _cleanup_capture(
                        capture, deadline=deadline
                    )
                    if primary_error is not None:
                        primary_error.metadata["capture_cleanup_attempts"] = metadata[
                            "capture_cleanup_attempts"
                        ]
                except ProviderError as cleanup:
                    LOGGER.error(
                        "Owned capture cleanup failed request_id=%s attempts=%s",
                        request_id,
                        cleanup.metadata["capture_cleanup_attempts"],
                    )
                    if primary_error is not None:
                        primary_error.metadata.update(
                            cleanup.metadata, capture_cleanup_error=cleanup.code
                        )
                    else:
                        cleanup.metadata.update(
                            metadata,
                            duration_ms=round((time.monotonic() - started) * 1000, 3),
                        )
                        raise
