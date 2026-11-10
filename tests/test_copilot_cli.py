"""Verify bounded tool-disabled transport, strict envelopes and sanitized provenance.

Mocked CLI events and local stub subprocesses test isolation, deadlines, capture
and cleanup without live inference or claims about provider reasoning quality.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from subsea_copilot.llm import copilot_cli as cli


@pytest.fixture(autouse=True)
def legacy_transport(monkeypatch):
    monkeypatch.setenv("SUBSEA_COPILOT_TRANSPORT", "cli")


@pytest.fixture
def runtime():
    path = Path.cwd() / ".test-artifacts" / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)
    if not any(path.parent.iterdir()):
        path.parent.rmdir()


def event(content, **extra):
    return {"type": "assistant.message", "data": {"content": content}, **extra}


def wire(events):
    return "\n".join(json.dumps(item) for item in events).encode()


def final():
    return json.dumps({"kind": "final", "value": {"outcome": "supported"}})


@pytest.mark.parametrize(
    ("content", "stage"),
    [
        ("not JSON", "outer_json"),
        ('{"FINAL":"private-response-content"}', "envelope_shape"),
        ('{"kind":"final","value":"{}"}', "final_value_type"),
        ('{"kind":"final","value":[]}', "final_value_type"),
        ('{"kind":"unknown","value":[]}', "envelope_kind"),
    ],
)
def test_rejected_response_records_only_content_free_validation_stage(content, stage):
    with pytest.raises(cli.ProviderError) as rejected:
        cli._decode(content, set())
    assert rejected.value.code == "invalid_structured_output"
    assert rejected.value.metadata == {"response_validation_stage": stage}


def test_tool_envelope_preserves_public_parameter_reason_and_triggering_references():
    result = cli._decode(json.dumps({"kind": "tool_calls", "value": [{
        "name": "history.compare", "arguments": {"start_seconds": 100, "end_seconds": 120},
        "decision_summary": "Resolve an unexplained late paired decline.",
        "parameter_summary": "Use the final 20s to separate it from the earlier operating step.",
        "source_references": ["original-profile"],
    }]}), {"history.compare"})
    identifier = result.tool_calls[0]["id"]
    assert result.additional_kwargs["parameter_summaries"][identifier].startswith(
        "Use the final 20s"
    )
    assert result.additional_kwargs["decision_source_references"][identifier] == [
        "original-profile"
    ]
    assert "parameter_summary" not in result.tool_calls[0]["args"]


@pytest.mark.parametrize("extra", [
    {"parameter_summary": 4}, {"parameter_summary": "x" * 1001},
    {"source_references": "not-a-list"}, {"source_references": [None]},
    {"source_references": [""]}, {"source_references": ["x" * 201]},
    {"source_references": ["ref"] * 33},
])
def test_tool_envelope_rejects_malformed_public_selection_details(extra):
    with pytest.raises(cli.ProviderError) as rejected:
        cli._decode(json.dumps({"kind": "tool_calls", "value": [{
            "name": "evidence.get", "arguments": {}, **extra,
        }]}), {"evidence.get"})
    assert rejected.value.code == "invalid_tool_call"


def stub(monkeypatch, events, inspect=None, code=0, stderr=b""):
    calls = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(Path(sys.executable)))
    monkeypatch.setattr(cli, "_cli_version", lambda *args, **kwargs: None)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if inspect:
            inspect(command, kwargs)
        return code, wire(events), stderr

    monkeypatch.setattr(cli, "_run_transport", run)
    return calls


def test_isolated_flags_stdin_environment_and_unknown_metadata(monkeypatch, runtime):
    for key in cli._REMOVED_ENV:
        monkeypatch.setenv(key, "synthetic-parent-control")
    monkeypatch.setenv("COPILOT_ALLOW_ALL_TOOLS", "1")
    monkeypatch.setenv("GH_TOKEN", "synthetic-auth-preserved")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "synthetic-auth-preserved")
    secrets = (
        "SUBSEA_DB_ADMIN_PASSWORD",
        "SUBSEA_DB_APP_PASSWORD",
        "SUBSEA_DB_TOOL_PASSWORD",
        "SUBSEA_DB_CHECKPOINT_PASSWORD",
        "SUBSEA_OPERATOR_PASSWORD",
        "LF_POSTGRES_PASSWORD",
        "LF_CLICKHOUSE_PASSWORD",
        "LF_REDIS_PASSWORD",
        "LF_MINIO_PASSWORD",
        "LF_SALT",
        "LF_ENCRYPTION_KEY",
        "LF_NEXTAUTH_SECRET",
        "LF_ADMIN_PASSWORD",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "OTEL_EXPORTER_OTLP_HEADERS",
    )
    for name in secrets:
        monkeypatch.setenv(name, "synthetic-application-secret")

    def inspect(command, kwargs):
        work = runtime / "captures" / command[4] / "work"
        assert command == [
            sys.executable,
            "-C",
            str(work),
            "--session-id",
            command[4],
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
            str(work.parent / "logs"),
        ]
        assert kwargs["cwd"] == work
        assert not list(work.iterdir())
        assert kwargs["env"]["GH_TOKEN"] == "synthetic-auth-preserved"
        assert kwargs["env"]["COPILOT_GITHUB_TOKEN"] == "synthetic-auth-preserved"
        assert not cli._REMOVED_ENV.intersection(kwargs["env"])
        assert "COPILOT_ALLOW_ALL_TOOLS" not in kwargs["env"]
        assert not set(secrets).intersection(kwargs["env"])
        prompt = json.loads(kwargs["prompt"])
        assert prompt["conversation"] == [{"role": "human", "content": "synthetic request"}]
        assert kwargs["deadline"] - time.monotonic() <= 0.301
        assert kwargs["stdout_limit"] == 6000000

    stub(monkeypatch, [event(final())], inspect)

    def version(executable, **kwargs):
        assert not set(secrets).intersection(kwargs["env"])
        assert kwargs["env"]["GH_TOKEN"] == "synthetic-auth-preserved"
        return "1.0.999"

    monkeypatch.setattr(cli, "_cli_version", version)
    response = cli.CopilotCLIChatModel(runtime_dir=runtime).invoke(
        [HumanMessage(content="synthetic request")], timeout=0.3
    )
    assert response.content == '{"outcome":"supported"}'
    assert response.response_metadata["observed_model"] is None
    assert response.response_metadata["model_identity_source"] == "unknown"
    assert all(value is None for value in response.response_metadata["usage"].values())
    assert len(response.response_metadata["prompt_hash"]) == 64
    assert not list((runtime / "captures").iterdir())


def test_top_level_final_not_thinking_or_subagent_and_usage(monkeypatch, runtime):
    events = [
        event(final(), parentId="prior-event-id"),
        {"type": "assistant.message", "data": {"content": "private", "phase": "thinking"}},
        event("subagent", agentId="child"),
        {
            "type": "session.usage_record",
            "data": {
                "usage": {
                    "model": "synthetic-model",
                    "inputTokens": 7,
                    "outputTokens": 3,
                }
            },
        },
    ]
    stub(monkeypatch, events)
    response = cli.CopilotCLIChatModel(runtime_dir=runtime, model_id="pin").invoke("synthetic")
    assert response.content == '{"outcome":"supported"}'
    assert response.response_metadata["observed_model"] == "synthetic-model"
    assert response.response_metadata["model_identity_source"] == "cli_event"
    assert response.response_metadata["usage"]["input_tokens"] == 7
    assert response.response_metadata["usage"]["reasoning_tokens"] is None


def test_binding_tools_ids_and_conversation_round_trip(monkeypatch, runtime):
    content = json.dumps(
        {
            "kind": "tool_calls",
            "value": [
                {
                    "name": "quality.coverage",
                    "arguments": {},
                    "decision_summary": "Check coverage",
                }
            ],
        }
    )
    calls = stub(monkeypatch, [event(content)])
    model = cli.CopilotCLIChatModel(runtime_dir=runtime).bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "quality.coverage",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )
    first = model.invoke("synthetic")
    second = model.invoke(
        [
            HumanMessage(content="synthetic"),
            first,
            ToolMessage(content='{"coverage":1}', tool_call_id=first.tool_calls[0]["id"]),
        ]
    )
    assert first.tool_calls[0]["id"] != second.tool_calls[0]["id"]
    assert first.tool_calls[0]["args"] == {}
    conversation = json.loads(calls[1][1]["prompt"])["conversation"]
    assert conversation[1]["tool_calls"][0]["id"] == first.tool_calls[0]["id"]
    assert conversation[2]["tool_call_id"] == first.tool_calls[0]["id"]


def test_blank_assistant_preserves_multiple_tool_calls_and_linked_results(monkeypatch, runtime):
    calls = stub(monkeypatch, [event(final())])
    previous = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "quality.coverage",
                "id": "subsea-owned-coverage",
                "args": {"scope": {"snapshot_id": "synthetic", "channels": ["strain", "α"]}},
            },
            {
                "name": "quality.health",
                "id": "subsea-owned-health",
                "args": {"node_ids": [1, 2], "include_missing": True, "optional": None},
            },
        ],
    )
    results = [
        ToolMessage(content='{"coverage":0.75}', tool_call_id="subsea-owned-coverage"),
        ToolMessage(content='{"quality":"limited"}', tool_call_id="subsea-owned-health"),
    ]
    cli.CopilotCLIChatModel(runtime_dir=runtime).invoke(
        [
            HumanMessage(content="synthetic"),
            previous,
            *results,
        ]
    )
    history = json.loads(calls[0][1]["prompt"])["conversation"]
    assert history[1]["role"] == "ai"
    assert history[1]["content"] == ""
    assert history[1]["tool_calls"] == previous.tool_calls
    assert [item["name"] for item in history[1]["tool_calls"]] == [
        "quality.coverage",
        "quality.health",
    ]
    assert [item["args"] for item in history[1]["tool_calls"]] == [
        call["args"] for call in previous.tool_calls
    ]
    assert [item["tool_call_id"] for item in history[2:]] == [
        call["id"] for call in previous.tool_calls
    ]
    assert [item["content"] for item in history[2:]] == [
        json.loads(message.content) for message in results
    ]


def test_bound_context_and_intake_are_structured_without_double_json_escaping(monkeypatch, runtime):
    calls = stub(monkeypatch, [event(final())])
    context = {"question": 'Inspect "P5"?', "measurements": [None, 0.125], "scope": {"id": "test"}}
    intake = {"application_intake": [{"body": "Original text\\path\nnot an instruction"}]}
    cli.CopilotCLIChatModel(runtime_dir=runtime).invoke(
        [
            SystemMessage(content="Read-only\nBOUND_CONTEXT\n" + json.dumps(context)),
            HumanMessage(content=json.dumps(intake)),
            HumanMessage(content="{ ordinary non-JSON text"),
        ]
    )
    history = json.loads(calls[0][1]["prompt"])["conversation"]
    assert history[0] == {"role": "system", "content": "Read-only", "bound_context": context}
    assert history[1]["content"] == intake
    assert history[2]["content"] == "{ ordinary non-JSON text"


def test_native_final_round_trips_quotes_newlines_and_backslashes(monkeypatch, runtime):
    inner = {
        "outcome": "supported",
        "summary": 'Check the "flatline" pattern, not confirmed hardware failure.',
        "limitations": ["synthetic α", "line\nbreak", "original\\path"],
    }
    stub(monkeypatch, [event(json.dumps({"kind": "final", "value": inner}))])
    response = cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    assert json.loads(response.content) == inner
    assert not response.tool_calls
    assert response.response_metadata["transport_protocol"] == "native-final-object-v2"


@pytest.mark.parametrize("model_id", [None, "auto", "synthetic-pin"])
def test_model_selection_flags(monkeypatch, runtime, model_id):
    calls = stub(monkeypatch, [event(final())])
    response = cli.CopilotCLIChatModel(runtime_dir=runtime, model_id=model_id).invoke("synthetic")
    command = calls[0][0]
    if model_id == "synthetic-pin":
        assert command[-2:] == ["--model", model_id]
        assert response.response_metadata["model_identity_source"] == "requested_only"
        assert response.response_metadata["observed_model"] is None
    else:
        assert "--model" not in command


@pytest.mark.parametrize(
    "content,code",
    [
        ('{"kind":"final","value":[]}', "invalid_structured_output"),
        ('{"kind":"final","value":"not JSON"}', "invalid_structured_output"),
        ('{"kind":"final","value":"{\\"outcome\\":\\"supported\\"}"}', "invalid_structured_output"),
        ('{"kind":"final","value":"[]"}', "invalid_structured_output"),
        ('{"kind":"final","value":{"value":NaN}}', "invalid_structured_output"),
        ('{"kind":"final","kind":"final","value":{}}', "invalid_structured_output"),
        ('{"kind":"final","value":{},"extra":1}', "invalid_structured_output"),
        ("```json\n{}\n```", "invalid_structured_output"),
        ('{"kind":"tool_calls","value":[]}', "invalid_tool_call"),
        ('{"kind":"tool_calls","value":[{"name":"shell","arguments":{}}]}', "invalid_tool_call"),
        (
            '{"kind":"tool_calls","value":[{"name":"coverage","arguments":{},"id":"model"}]}',
            "invalid_tool_call",
        ),
    ],
)
def test_invalid_structured_and_tools(monkeypatch, runtime, content, code):
    stub(monkeypatch, [event(content)])
    with pytest.raises(cli.ProviderError) as error:
        cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    assert error.value.code == code
    assert "shell" not in str(error.value)


@pytest.mark.parametrize(
    "stderr,code",
    [
        (b"Unauthorized synthetic-token", "proxy_auth"),
        (b"Quota 429 synthetic-token", "proxy_quota"),
        (b"Unknown synthetic-token", "proxy_error"),
    ],
)
def test_sanitized_provider_errors_no_retry(monkeypatch, runtime, stderr, code):
    calls = stub(monkeypatch, [], code=1, stderr=stderr)
    with pytest.raises(cli.ProviderError) as error:
        cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    assert error.value.code == code
    assert "synthetic-token" not in str(error.value)
    assert len(calls) == 1


def test_transient_directory_lock_retries_cleanup_not_inference(monkeypatch, runtime):
    calls = stub(monkeypatch, [event(final())])
    remove = cli.shutil.rmtree
    attempts = []

    def locked_once(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise PermissionError("synthetic-private-path")
        remove(path)

    with monkeypatch.context() as patch:
        patch.setattr(cli.shutil, "rmtree", locked_once)
        response = cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    assert response.content == '{"outcome":"supported"}'
    assert response.response_metadata["capture_cleanup_attempts"] == 2
    assert len(calls) == 1
    assert len(attempts) == 2
    assert not list((runtime / "captures").iterdir())


@pytest.mark.parametrize("provider_code", [0, 1])
def test_persistent_cleanup_lock_fails_closed_preserves_metadata_and_auth(
    monkeypatch, runtime, provider_code, caplog
):
    calls = stub(
        monkeypatch,
        [event(final())],
        code=provider_code,
        stderr=b"Unauthorized synthetic-private-token" if provider_code else b"",
    )
    attempts = []

    def always_locked(path):
        attempts.append(path)
        raise PermissionError("synthetic-private-path")

    with monkeypatch.context() as patch:
        patch.setattr(cli.shutil, "rmtree", always_locked)
        with pytest.raises(cli.ProviderError) as failure:
            cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    assert failure.value.code == ("proxy_auth" if provider_code else "capture_cleanup_failed")
    assert failure.value.metadata["capture_cleanup_attempts"] == 4
    assert failure.value.metadata["request_id"]
    if provider_code:
        assert failure.value.metadata["capture_cleanup_error"] == "capture_cleanup_failed"
    assert len(calls) == 1
    assert len(attempts) == 4
    assert "synthetic-private" not in str(failure.value) + caplog.text


def test_cleanup_lock_does_not_extend_expired_deadline(monkeypatch, runtime):
    attempts = []

    def locked(path):
        attempts.append(path)
        raise PermissionError

    with monkeypatch.context() as patch:
        patch.setattr(cli.shutil, "rmtree", locked)
        with pytest.raises(cli.ProviderError) as failure:
            cli._cleanup_capture(runtime, deadline=0)
    assert failure.value.code == "capture_cleanup_failed"
    assert len(attempts) == 1


def test_prompt_and_response_bounds_missing_empty(monkeypatch, runtime):
    calls = stub(monkeypatch, [])
    with pytest.raises(cli.ProviderError, match="Prompt"):
        cli.CopilotCLIChatModel(runtime_dir=runtime, max_prompt_chars=1).invoke("synthetic")
    assert not calls
    with pytest.raises(cli.ProviderError) as error:
        cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    assert error.value.code == "empty_response"
    stub(monkeypatch, [event(final())])
    with pytest.raises(cli.ProviderError) as error:
        cli.CopilotCLIChatModel(runtime_dir=runtime, max_final_chars=2).invoke("synthetic")
    assert error.value.code == "output_too_large"
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(cli.ProviderError) as error:
        cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    assert error.value.code == "cli_missing"


@pytest.mark.parametrize(
    "script,expected",
    [
        ("import sys;sys.stdout.buffer.write(b'x'*50000);sys.stdout.flush()", "output_too_large"),
        ("import sys;sys.stderr.buffer.write(b'x'*50000);sys.stderr.flush()", "output_too_large"),
        ("import time;time.sleep(30)", "timeout"),
    ],
)
def test_real_stub_process_bounds_and_deadline(runtime, script, expected):
    started = time.monotonic()
    with pytest.raises(cli.ProviderError) as error:
        cli._run_transport(
            [sys.executable, "-c", script],
            cwd=runtime,
            env=dict(os.environ),
            prompt=b"",
            deadline=started + 0.5,
            stdout_limit=100,
            stderr_limit=100,
        )
    assert error.value.code == expected
    assert time.monotonic() - started < 6


def test_actual_process_shell_false_and_two_pipes(monkeypatch, runtime):
    original = cli.subprocess.Popen
    observed = []

    def popen(command, **kwargs):
        observed.append(kwargs)
        return original(command, **kwargs)

    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    code, stdout, stderr = cli._run_transport(
        [
            sys.executable,
            "-c",
            "import sys;data=sys.stdin.buffer.read();"
            "sys.stdout.buffer.write(data);sys.stderr.buffer.write(b'diagnostic')",
        ],
        cwd=runtime,
        env=dict(os.environ),
        prompt=b"synthetic",
        deadline=time.monotonic() + 3,
        stdout_limit=100,
        stderr_limit=100,
    )
    assert (code, stdout, stderr) == (0, b"synthetic", b"diagnostic")
    assert observed[0]["shell"] is False


def test_orphaned_descendant_pipe_is_terminated_at_deadline(runtime):
    script = (
        "import subprocess,sys;"
        "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
    )
    started = time.monotonic()
    with pytest.raises(cli.ProviderError) as error:
        cli._run_transport(
            [sys.executable, "-c", script],
            cwd=runtime,
            env=dict(os.environ),
            prompt=b"",
            deadline=started + 0.3,
            stdout_limit=100,
            stderr_limit=100,
        )
    assert error.value.code == "timeout"
    assert time.monotonic() - started < 2


def test_tool_schema_type_rejected(runtime):
    with pytest.raises(cli.ProviderError):
        cli.CopilotCLIChatModel(runtime_dir=runtime).bind_tools(
            [
                {"name": "coverage", "parameters": {"type": "array"}},
            ]
        )
    with pytest.raises(cli.ProviderError):
        cli.CopilotCLIChatModel(runtime_dir=runtime).invoke(
            [AIMessage(content="synthetic")], timeout=0
        )


def test_version_lookup_bounded_cached_and_not_inference(monkeypatch, runtime):
    cli._VERSION_CACHE.clear()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command == [sys.executable, "--version"]
        assert kwargs["cwd"] == runtime
        assert kwargs["prompt"] == b""
        assert kwargs["stdout_limit"] == kwargs["stderr_limit"] == 4096
        assert kwargs["deadline"] - time.monotonic() <= 2.001
        assert "SUBSEA_DB_ADMIN_PASSWORD" not in kwargs["env"]
        assert "LANGFUSE_SECRET_KEY" not in kwargs["env"]
        assert kwargs["env"]["GH_TOKEN"] == "synthetic-auth"
        return 0, b"GitHub Copilot CLI 0.0.999\n", b""

    monkeypatch.setattr(cli, "_run_transport", run)
    kwargs = {
        "cwd": runtime,
        "deadline": time.monotonic() + 5,
        "env": {
            "SUBSEA_DB_ADMIN_PASSWORD": "synthetic-secret",
            "LANGFUSE_SECRET_KEY": "synthetic-secret",
            "GH_TOKEN": "synthetic-auth",
        },
    }
    assert cli._cli_version(sys.executable, **kwargs) == "0.0.999"
    assert cli._cli_version(sys.executable, **kwargs) == "0.0.999"
    assert len(calls) == 1
    cli._VERSION_CACHE.clear()


def test_owned_session_fallback_uses_only_metadata_no_double_count(monkeypatch, runtime):
    home = runtime / "owned-home"
    monkeypatch.setenv("COPILOT_HOME", str(home))

    def inspect(command, kwargs):
        session = home / "session-state" / command[4]
        session.mkdir(parents=True)
        (session / "events.jsonl").write_bytes(
            wire(
                [
                    {"type": "session.start", "data": {"copilotVersion": "0.0.999"}},
                    {
                        "type": "session.usage_record",
                        "data": {
                            "usage": {
                                "model": "synthetic-observed",
                                "inputTokens": 10,
                                "outputTokens": 5,
                                "reasoningTokens": 2,
                                "reasoningSummary": "DO NOT RETAIN",
                            }
                        },
                    },
                    {
                        "type": "assistant.message",
                        "data": {
                            "content": "DO NOT RETAIN",
                            "phase": "thinking",
                        },
                    },
                ]
            )
        )
        extracted = cli._owned_metadata_events(
            kwargs["env"],
            command[4],
            deadline=kwargs["deadline"],
            limit=2000000,
        )
        assert "DO NOT RETAIN" not in json.dumps(extracted)

    stub(monkeypatch, [event(final())], inspect)
    response = cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    metadata = response.response_metadata
    assert metadata["cli_version"] == "0.0.999"
    assert metadata["cli_version_source"] == "owned_session"
    assert metadata["usage_source"] == "owned_session"
    assert metadata["usage"]["input_tokens"] == 10
    assert metadata["usage"]["cache_read_tokens"] is None
    assert metadata["observed_model"] == "synthetic-observed"
    assert metadata["model_identity_source"] == "owned_session"
    calls = stub(
        monkeypatch,
        [
            event(final()),
            {
                "type": "session.usage_record",
                "data": {
                    "usage": {
                        "inputTokens": 10,
                        "outputTokens": 5,
                    }
                },
            },
        ],
        inspect,
    )
    second = cli.CopilotCLIChatModel(runtime_dir=runtime).invoke("synthetic")
    assert second.response_metadata["usage"]["input_tokens"] == 10
    assert second.response_metadata["usage_source"] == "cli_event"
    assert len(calls) == 1


def test_owned_metadata_read_is_bounded_and_invalid_identity_never_reads(runtime):
    request_id = str(uuid.uuid4())
    home = runtime / "owned-home"
    session = home / "session-state" / request_id
    session.mkdir(parents=True)
    (session / "events.jsonl").write_bytes(b"x" * 101)
    env = {"COPILOT_HOME": str(home)}
    kwargs = {"deadline": time.monotonic() + 5, "limit": 100}
    assert cli._owned_metadata_events(env, request_id, **kwargs) == []
    assert cli._owned_metadata_events(env, "..", **kwargs) == []
    assert cli._owned_metadata_events(env, request_id, deadline=0, limit=200) == []
