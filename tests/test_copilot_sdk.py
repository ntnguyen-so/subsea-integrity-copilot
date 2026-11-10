"""Warm-process reuse must not become shared conversation or native tool authority."""

import asyncio
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from subsea_copilot.llm import copilot_sdk as sdk
from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel, ProviderError


class Event:
    agent_id = None

    def __init__(self, kind, data):
        self.type = SimpleNamespace(value=kind)
        self.data = SimpleNamespace(**data)
        self.value = {"type": kind, "data": data}

    def to_dict(self):
        return self.value


@pytest.fixture
def clients(monkeypatch, tmp_path):
    instances = []

    class Client:
        def __init__(self, **options):
            self.options = options
            self.sessions = []
            self.deleted = []
            self.aborted = []
            self.stopped = False
            self._cli_process = Mock(spec=subprocess.Popen)
            self._cli_process.poll.return_value = 0
            instances.append(self)

        async def start(self):
            await asyncio.sleep(0)

        async def get_status(self):
            return SimpleNamespace(version="1.0.synthetic")

        async def create_session(self, **options):
            owner = self

            class Session:
                session_id = options["session_id"]

                async def send_and_wait(self, prompt, **kwargs):
                    if "slow" in prompt:
                        await asyncio.sleep(10)
                    if "provider-error" in prompt:
                        raise RuntimeError("401 private-token private-prompt")
                    if "native-tool" in prompt:
                        options["on_event"](Event("tool.execution_start", {
                            "toolName": "read_file",
                        }))
                    content = json.dumps({"kind": "final", "value": {"outcome": "supported"}})
                    if "malformed" in prompt:
                        content = "private malformed content"
                    options["on_event"](Event("assistant.usage", {
                        "model": "gpt-6.1-sol", "inputTokens": 21, "outputTokens": 7,
                        "cacheReadTokens": 5, "cacheWriteTokens": 0, "reasoningTokens": 2,
                    }))
                    options["on_event"](Event("assistant.message", {"content": content}))
                    return Event("assistant.message", {"content": content})

                async def abort(self):
                    owner.aborted.append(self.session_id)

            self.sessions.append(options)
            return Session()

        async def delete_session(self, session_id):
            self.deleted.append(session_id)
            if self.options.get("cleanup_fails"):
                raise RuntimeError("private cleanup failure")

        async def force_stop(self):
            self.stopped = True

        async def stop(self):
            self.stopped = True

    monkeypatch.setattr(sdk, "CopilotClient", Client)
    monkeypatch.setattr(sdk, "_WindowsJob", lambda process: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(sdk.shutil, "which", lambda name: str(tmp_path / "copilot.exe"))
    monkeypatch.setenv("SUBSEA_COPILOT_TRANSPORT", "sdk")
    yield instances
    sdk.close_hosts()
    assert all(client.stopped for client in instances)


def test_warm_runtime_reuses_process_not_session_and_retains_observed_usage(clients, tmp_path):
    model = CopilotCLIChatModel(runtime_dir=tmp_path, model_id="gpt-6.1-sol")
    first = model.invoke("first snapshot")
    second = model.invoke("second snapshot")
    assert len(clients) == 1
    client = clients[0]
    sessions = client.sessions
    assert sessions[0]["session_id"] != sessions[1]["session_id"]
    assert client.deleted == [row["session_id"] for row in sessions]
    assert client.aborted == []
    for row in sessions:
        assert row["available_tools"] == [] and row["tools"] == []
        assert row["excluded_tools"] == ["builtin:*", "mcp:*", "custom:*"]
        assert not row["enable_config_discovery"]
        assert not row["enable_session_store"]
        assert not row["enable_file_hooks"] and not row["enable_host_git_operations"]
        assert row["on_permission_request"](None, None).kind == "reject"
        assert row["memory"] == {"enabled": False}
        assert not row["manage_schedule_enabled"]
    assert first.response_metadata["request_id"] != second.response_metadata["request_id"]
    assert second.response_metadata["observed_model"] == "gpt-6.1-sol"
    assert second.response_metadata["usage"]["input_tokens"] == 21
    assert second.response_metadata["usage"]["output_tokens"] == 7
    assert second.response_metadata["usage_source"] == "sdk_event"


def test_concurrent_roots_have_separate_sessions_and_one_warm_host(clients, tmp_path):
    def invoke(index):
        return CopilotCLIChatModel(runtime_dir=tmp_path).invoke(f"snapshot {index}")

    with ThreadPoolExecutor(max_workers=3) as executor:
        responses = list(executor.map(invoke, range(3)))
    assert len(clients) == 1
    assert len({row.response_metadata["request_id"] for row in responses}) == 3
    assert len(clients[0].deleted) == 3


def test_timed_out_session_is_aborted_deleted_and_not_reused(clients, tmp_path):
    model = CopilotCLIChatModel(runtime_dir=tmp_path)
    with pytest.raises(ProviderError) as failure:
        model.invoke("slow snapshot", timeout=0.1)
    assert failure.value.code == "timeout"
    assert clients[0].aborted == clients[0].deleted
    assert len(clients[0].deleted) == 1
    assert model.invoke("another snapshot").content == '{"outcome":"supported"}'
    assert len(clients) == 1


@pytest.mark.parametrize(
    ("text", "options", "code"),
    [
        ("malformed", {}, "invalid_structured_output"),
        ("provider-error", {}, "proxy_auth"),
        ("native-tool", {}, "invalid_tool_call"),
        ("normal", {"max_final_chars": 1}, "output_too_large"),
        ("normal", {"max_capture_bytes": 1}, "output_too_large"),
    ],
)
def test_failed_calls_remain_explicit_and_cleaned(clients, tmp_path, text, options, code):
    model = CopilotCLIChatModel(runtime_dir=tmp_path, **options)
    with pytest.raises(ProviderError) as failure:
        model.invoke(text)
    assert failure.value.code == code
    assert "private" not in str(failure.value)
    assert clients[0].deleted


def test_failed_cleanup_withholds_valid_result_and_stops_owned_host(clients, tmp_path):
    model = CopilotCLIChatModel(runtime_dir=tmp_path)
    model.invoke("first snapshot")
    clients[0].options["cleanup_fails"] = True
    with pytest.raises(ProviderError) as failure:
        model.invoke("second snapshot")
    assert failure.value.code == "capture_cleanup_failed"
    assert clients[0].stopped


def test_failed_start_stops_owned_process_without_retrying_call(clients, tmp_path, monkeypatch):
    async def fail_start(self):
        raise RuntimeError("private startup failure")

    monkeypatch.setattr(sdk.CopilotClient, "start", fail_start)
    with pytest.raises(ProviderError) as failure:
        CopilotCLIChatModel(runtime_dir=tmp_path).invoke("snapshot")
    assert failure.value.code == "proxy_error"
    assert "private" not in str(failure.value)
    assert len(clients) == 1
    assert clients[0].stopped and clients[0].sessions == []


def test_creation_timeout_deletes_known_session_even_without_returned_handle(
    clients, tmp_path, monkeypatch,
):
    original = sdk.CopilotClient.create_session

    async def delayed_create(self, **options):
        await original(self, **options)
        await asyncio.sleep(10)

    monkeypatch.setattr(sdk.CopilotClient, "create_session", delayed_create)
    with pytest.raises(ProviderError) as failure:
        CopilotCLIChatModel(runtime_dir=tmp_path).invoke("snapshot", timeout=0.1)
    assert failure.value.code == "timeout"
    assert clients[0].deleted == [clients[0].sessions[0]["session_id"]]
    assert clients[0].aborted == []


def test_stalled_session_cleanup_is_bounded_and_retires_only_its_host(
    clients, tmp_path, monkeypatch,
):
    model = CopilotCLIChatModel(runtime_dir=tmp_path)
    model.invoke("first snapshot")
    monkeypatch.setattr(sdk, "_SESSION_CLEANUP_TIMEOUT_SECONDS", 0.05)

    async def stalled_delete(session_id):
        await asyncio.sleep(10)

    monkeypatch.setattr(clients[0], "delete_session", stalled_delete)
    with pytest.raises(ProviderError) as failure:
        model.invoke("second snapshot", timeout=1)
    assert failure.value.code == "capture_cleanup_failed"
    assert clients[0].stopped
    assert model.invoke("fresh snapshot").content == '{"outcome":"supported"}'
    assert len(clients) == 2 and not clients[1].stopped


def test_cleanup_queue_does_not_limit_parallel_inference(clients, tmp_path, monkeypatch):
    ready = asyncio.Event()
    active = maximum = deleting = maximum_deleting = 0
    original_create = sdk.CopilotClient.create_session
    original_delete = sdk.CopilotClient.delete_session

    async def create(self, **options):
        session = await original_create(self, **options)
        original_send = session.send_and_wait

        async def send(prompt, **kwargs):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            if active == 3:
                ready.set()
            await asyncio.wait_for(ready.wait(), timeout=2)
            result = await original_send(prompt, **kwargs)
            active -= 1
            return result

        session.send_and_wait = send
        return session

    async def delete(self, session_id):
        nonlocal deleting, maximum_deleting
        deleting += 1
        maximum_deleting = max(maximum_deleting, deleting)
        try:
            await asyncio.sleep(0.02)
            await original_delete(self, session_id)
        finally:
            deleting -= 1

    monkeypatch.setattr(sdk.CopilotClient, "create_session", create)
    monkeypatch.setattr(sdk.CopilotClient, "delete_session", delete)
    model = CopilotCLIChatModel(runtime_dir=tmp_path)
    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(lambda index: model.invoke(f"snapshot {index}"), range(3)))
    assert maximum == 3
    assert maximum_deleting == 1
    assert len(clients) == 1 and len(clients[0].deleted) == 3


def test_late_cleanup_from_retired_client_cannot_kill_replacement(
    clients, tmp_path, monkeypatch,
):
    from contextlib import nullcontext

    model = CopilotCLIChatModel(runtime_dir=tmp_path)
    model.invoke("first snapshot")
    monkeypatch.setattr(sdk._HOSTS[tmp_path.resolve()], "cleanup_lock", nullcontext())
    old = clients[0]
    waiting = threading.Event()
    release = threading.Event()
    attempts = 0

    async def failed_delete(session_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            waiting.set()
            while not release.is_set():
                await asyncio.sleep(0.001)
        raise RuntimeError("private cleanup failure")

    monkeypatch.setattr(old, "delete_session", failed_delete)
    with ThreadPoolExecutor(max_workers=1) as executor:
        late = executor.submit(model.invoke, "old in-flight snapshot")
        try:
            assert waiting.wait(timeout=2)
            with pytest.raises(ProviderError, match="cleanup"):
                model.invoke("retire old runtime")
            model.invoke("replacement snapshot")
            assert len(clients) == 2 and not clients[1].stopped
        finally:
            release.set()
        with pytest.raises(ProviderError, match="cleanup"):
            late.result(timeout=2)
    assert old.stopped
    assert not clients[1].stopped
    model.invoke("reuse replacement")
    assert len(clients) == 2
