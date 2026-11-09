"""Verify redaction, hashed lineage, bounded queues and truthful trace-delivery health.

Fake exporters and mocked stored-observation responses separate enqueue/export
from verified storage; these tests do not require live collector availability.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from subsea_copilot import telemetry as module


@pytest.fixture
def runtime(monkeypatch):
    for name in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "SUBSEA_TELEMETRY_ENABLED",
        "SUBSEA_LANGFUSE_ENABLED",
        "SUBSEA_JAEGER_ENABLED",
        "SUBSEA_TRACE_CONTENT",
        "SUBSEA_SYNTHETIC_ONLY",
        "SUBSEA_LANGFUSE_OTLP_ENDPOINT",
        "SUBSEA_TRACE_SYNC",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUBSEA_TRACE_SYNC", "1")
    path = Path.cwd() / ".test-artifacts" / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)
    if not any(path.parent.iterdir()):
        path.parent.rmdir()


class Exporter(SpanExporter):
    def __init__(self, fail=False, raises=False):
        self.spans = []
        self.fail = fail
        self.raises = raises

    def export(self, spans):
        if self.raises:
            raise RuntimeError("secret synthetic-error")
        self.spans.extend(spans)
        return SpanExportResult.FAILURE if self.fail else SpanExportResult.SUCCESS

    def shutdown(self):
        pass


def configured(monkeypatch, exporter):
    kwargs = []
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-synthetic")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-synthetic")

    def build(**values):
        kwargs.append(values)
        return exporter

    monkeypatch.setattr(module, "OTLPSpanExporter", build)
    return kwargs


def test_json_redaction_preserves_structure_and_unchanged_fingerprints():
    original = '{"feedback": "token=fixture-private", "other": ["Bearer fixture-private"]}'
    redacted = module._redact_content(original)
    assert json.loads(redacted) == {"feedback": "[REDACTED]", "other": ["[REDACTED]"]}
    nested = json.dumps({"content": original})
    assert json.loads(json.loads(module._redact_content(nested))["content"]) == (
        json.loads(redacted)
    )
    unchanged = '{ "feedback" : "Maintenance context must match compared instruments." }'
    assert module._redact_content(unchanged) == unchanged


@pytest.mark.parametrize("port", [3001, 3101])
def test_trace_viewer_links_identify_the_run_on_the_configured_local_host(
    monkeypatch, runtime, port
):
    monkeypatch.setenv(
        "SUBSEA_LANGFUSE_OTLP_ENDPOINT",
        f"http://127.0.0.1:{port}/api/public/otel/v1/traces",
    )
    telemetry = module.Telemetry(runtime)
    try:
        assert telemetry.trace_url("a" * 32) == (
            f"http://127.0.0.1:{port}/project/subsea-copilot/traces/{'a' * 32}"
        )
        assert telemetry.trace_url("not-a-trace") is None
    finally:
        telemetry.close()


def test_native_langfuse_tree_session_hash_and_visibility_separate(monkeypatch, runtime):
    exporter = Exporter()
    kwargs = configured(monkeypatch, exporter)
    telemetry = module.Telemetry(runtime)
    with telemetry.span(
        "agent.attempt",
        {
            "tenant_id": "synthetic-tenant",
            "site_id": "synthetic-site",
            "replay_generation_id": "generation",
            "episode_id": "episode",
            "task_id": "task",
        },
        root=True,
    ) as root:
        metadata = telemetry.trace_metadata()
        for name in ("generation", "tool", "guardrail"):
            with telemetry.span(name) as span:
                span.set_attribute("gen_ai.request.model", "synthetic-model")
                span.set_attribute("prompt", "must not be recorded")
                span.set_attribute("password", "must not be recorded")
        assert root.get_span_context().is_valid
    with telemetry.span("window.compute", root=True):
        pass
    assert kwargs[0]["endpoint"] == "http://127.0.0.1:3001/api/public/otel/v1/traces"
    assert kwargs[0]["headers"]["Authorization"].startswith("Basic ")
    observations = exporter.spans[:4]
    assert {item.attributes["langfuse.observation.type"] for item in observations} == {
        "agent",
        "generation",
        "tool",
        "guardrail",
    }
    assert len({item.context.trace_id for item in observations}) == 1
    sessions = {item.attributes["langfuse.session.id"] for item in observations}
    assert sessions == {metadata["session_id"]}
    assert observations[-1].attributes["tenant_id"] != "synthetic-tenant"
    assert all("prompt" not in item.attributes for item in observations)
    assert exporter.spans[-1].attributes["langfuse.observation.type"] == "span"
    health = telemetry.health()
    assert health["destinations"]["langfuse"]["exporter_accepted"] is True
    assert health["stored_trace_visibility"] == "unverified"
    assert health["status"] == "pending"
    assert telemetry.flush()
    telemetry.close()
    assert "synthetic-tenant" not in (runtime / "telemetry-audit.jsonl").read_text()


@pytest.mark.parametrize("raises", [False, True])
def test_export_rejection_is_warning_without_business_exception(monkeypatch, runtime, raises):
    configured(monkeypatch, Exporter(fail=True, raises=raises))
    telemetry = module.Telemetry(runtime)
    with telemetry.span("agent", root=True):
        pass
    health = telemetry.health()
    assert health["status"] == "warning"
    assert health["destinations"]["langfuse"]["status"] == "unavailable"
    assert health["stored_trace_visibility"] == "unverified"
    assert "synthetic-error" not in json.dumps(health)
    assert telemetry.flush() is False
    telemetry.close()


def test_disabled_and_misconfigured_without_network(monkeypatch, runtime):
    telemetry = module.Telemetry(runtime)
    assert telemetry.health()["status"] == "disabled"
    telemetry.close()
    monkeypatch.setenv("SUBSEA_LANGFUSE_ENABLED", "1")
    telemetry = module.Telemetry(runtime)
    assert telemetry.health()["destinations"]["langfuse"]["status"] == "misconfigured"
    assert not telemetry.flush()
    telemetry.close()
    configured(monkeypatch, Exporter())
    monkeypatch.setenv("SUBSEA_LANGFUSE_OTLP_ENDPOINT", "https://hosted.example/traces")
    telemetry = module.Telemetry(runtime)
    assert telemetry.health()["status"] == "warning"
    telemetry.close()


def test_content_requires_synthetic_opt_in_and_redaction(monkeypatch, runtime):
    exporter = Exporter()
    configured(monkeypatch, exporter)
    monkeypatch.setenv("SUBSEA_TRACE_CONTENT", "1")
    telemetry = module.Telemetry(runtime)
    with telemetry.span("generation", {"input": "not synthetic"}, root=True):
        pass
    assert "input" not in exporter.spans[-1].attributes
    telemetry.close()
    monkeypatch.setenv("SUBSEA_SYNTHETIC_ONLY", "1")
    telemetry = module.Telemetry(runtime)
    with telemetry.span("generation", root=True) as span:
        span.set_attribute("input", "password=synthetic-secret " + "x" * 5000)
        span.set_attribute("reasoning", "private reasoning")
    # Reasoning is never appropriate content, even in synthetic rehearsal.
    assert "reasoning" not in exporter.spans[-1].attributes
    assert "synthetic-secret" not in exporter.spans[-1].attributes["input"]
    assert 5000 <= len(exporter.spans[-1].attributes["input"]) <= module.TRACE_CONTENT_LIMIT
    telemetry.close()


def test_detailed_json_capture_preserves_safe_bytes_and_redacts_private_fields():
    import json

    safe = '{ "case": "G1", "public_output": "Pressure evidence remains uncertain." }'
    assert module._safe("input", safe, True) == safe
    unsafe = json.dumps(
        {
            "password": "synthetic-test-only",
            "content": [{"type": "thinking", "thinking": "private-provider-thought"}],
            "public_output": "Missing readings stay unknown.",
        }
    )
    captured = str(module._safe("output", unsafe, True))
    assert "synthetic-test-only" not in captured
    assert "private-provider-thought" not in captured
    assert "Missing readings stay unknown." in captured
    oversized = str(module._safe("input", "x" * 400000, True))
    assert "[Capture truncated at 196608 characters]" in oversized


def test_exception_message_not_exported_and_root_trace_separation(monkeypatch, runtime):
    exporter = Exporter()
    configured(monkeypatch, exporter)
    telemetry = module.Telemetry(runtime)
    with telemetry.span("agent", {"tenant_id": "tenant", "episode_id": "episode"}, root=True):
        with pytest.raises(ValueError):
            with telemetry.span("tool"):
                raise ValueError("password=synthetic-private")
    with telemetry.span("agent", {"tenant_id": "tenant", "episode_id": "episode"}, root=True):
        pass
    assert exporter.spans[0].events[0].attributes == {"error.type": "ValueError"}
    assert exporter.spans[-1].context.trace_id != exporter.spans[-2].context.trace_id
    assert (
        exporter.spans[-1].attributes["langfuse.session.id"]
        == (exporter.spans[-2].attributes["langfuse.session.id"])
    )
    telemetry.close()


def test_jaeger_is_real_independent_exporter(monkeypatch, runtime):
    exporter = Exporter()
    kwargs = configured(monkeypatch, exporter)
    monkeypatch.setenv("SUBSEA_JAEGER_ENABLED", "1")
    telemetry = module.Telemetry(runtime)
    with telemetry.span("window", root=True):
        pass
    assert kwargs[1]["endpoint"] == "http://127.0.0.1:4319/v1/traces"
    assert kwargs[1]["headers"] == {}
    assert telemetry.health()["destinations"]["jaeger"]["exporter_accepted"]
    telemetry.close()


def test_stored_trace_verification_requires_matching_identity(monkeypatch, runtime):
    configured(monkeypatch, Exporter())
    telemetry = module.Telemetry(runtime)
    trace_id = "a" * 32

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            assert size == 100001
            return json.dumps(
                {
                    "data": [
                        {
                            "id": "synthetic-generation",
                            "traceId": trace_id,
                            "type": "GENERATION",
                            "parentObservationId": "synthetic-root",
                            "sessionId": "b" * 64,
                        }
                    ],
                    "meta": {},
                }
            ).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == (
                "http://127.0.0.1:3001/api/public/v2/observations"
                f"?traceId={trace_id}&fields=core,basic&limit=100"
            )
            assert timeout == 3
            return Response()

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *args: Opener())
    assert telemetry.verify_trace(trace_id)
    assert telemetry.health()["stored_trace_visibility"] == "verified"
    assert not telemetry.verify_trace(trace_id, required_types=["generation", "tool", "guardrail"])
    assert telemetry.health()["verified_observation_tree_count"] == 0
    assert telemetry.health()["status"] == "warning"
    assert not telemetry.verify_trace("not-a-trace")
    telemetry.close()


@pytest.mark.parametrize("breakage", [None, "missing_parent", "cycle", "session", "missing_type"])
def test_v4_stored_tree_checks_connectivity_and_hashed_session(breakage):
    rows = [
        {
            "id": kind,
            "type": kind.upper(),
            "sessionId": "b" * 64,
            "parentObservationId": None if kind == "agent" else "agent",
        }
        for kind in ("agent", "generation", "tool", "guardrail")
    ]
    if breakage == "missing_parent":
        rows[1]["parentObservationId"] = "unknown"
    elif breakage == "cycle":
        rows[1]["parentObservationId"] = "generation"
    elif breakage == "session":
        rows[1]["sessionId"] = "c" * 64
    elif breakage == "missing_type":
        rows.pop()
    assert module._stored_tree_matches(rows, ["agent", "generation", "tool", "guardrail"]) == (
        breakage is None
    )


@pytest.mark.parametrize("raises", [False, True])
def test_flush_failure_and_close_preserve_typed_warning(monkeypatch, runtime, raises):
    configured(monkeypatch, Exporter())
    telemetry = module.Telemetry(runtime)

    def flush(**kwargs):
        if raises:
            raise RuntimeError("password=synthetic-secret")
        return False

    monkeypatch.setattr(telemetry.provider, "force_flush", flush)
    assert telemetry.flush() is False
    telemetry.close()
    health = telemetry.health()
    assert health["status"] == "warning"
    assert health["closed"] is True
    assert health["flush_failed"] is True
    assert health["flush_diagnostic"]["error_type"] == (
        "RuntimeError" if raises else "provider_flush_failed"
    )
    assert "synthetic-secret" not in json.dumps(health)


def test_stored_visibility_failure_is_warning(monkeypatch, runtime):
    configured(monkeypatch, Exporter())
    telemetry = module.Telemetry(runtime)

    class Opener:
        def open(self, *args, **kwargs):
            raise OSError("password=synthetic-secret")

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *args: Opener())
    assert telemetry.verify_trace("a" * 32) is False
    assert telemetry.health()["status"] == "warning"
    assert telemetry.health()["stored_trace_visibility"] == "not_visible"
    assert "synthetic-secret" not in json.dumps(telemetry.health())
    telemetry.close()


@pytest.mark.parametrize(
    "invalid", [{"trace_id": "x", "span_id": "a" * 16}, {"trace_id": "a" * 32, "span_id": "0" * 16}]
)
def test_invalid_persisted_parent_does_not_start_an_unrelated_trace(runtime, invalid):
    telemetry = module.Telemetry(runtime)
    try:
        with pytest.raises(ValueError, match="persisted trace context"):
            with telemetry.span("agent.child", parent=invalid):
                pytest.fail("Invalid persisted parent must not be accepted")
    finally:
        telemetry.close()


def test_stored_investigation_tree_verification_reads_all_pages(monkeypatch, runtime):
    configured(monkeypatch, Exporter())
    telemetry = module.Telemetry(runtime)
    trace_id = "a" * 32
    root = {
        "id": "root",
        "type": "AGENT",
        "traceId": trace_id,
        "sessionId": "b" * 64,
        "parentObservationId": None,
    }
    children = [
        {**root, "id": str(index), "type": kind, "parentObservationId": "root"}
        for index, kind in enumerate(["GENERATION", "TOOL", "GUARDRAIL"] + ["SPAN"] * 97)
    ]
    pages = [{"data": children, "meta": {"cursor": "next/page"}}, {"data": [root], "meta": {}}]
    urls = []

    class Response:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, bound):
            return json.dumps(self.value).encode()

    class Opener:
        def open(self, request, timeout):
            urls.append(request.full_url)
            return Response(pages.pop(0))

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *args: Opener())
    try:
        assert telemetry.verify_trace(trace_id, ["agent", "generation", "tool", "guardrail"])
        assert len(urls) == 2
        assert urls[1].endswith("&cursor=next%2Fpage")
        assert telemetry.health()["verified_observation_tree_count"] == 1
    finally:
        telemetry.close()


def test_episode_session_is_stable_across_tasks_resumptions_and_generation_alias(
    monkeypatch,
    runtime,
):
    exporter = Exporter()
    configured(monkeypatch, exporter)
    telemetry = module.Telemetry(runtime)
    identities = {
        "tenant_id": "tenant",
        "site_id": "site",
        "replay_generation_id": "generation",
        "episode_id": "episode",
    }
    with telemetry.span("agent", {**identities, "task_id": "parent", "run_id": "run-a"}, root=True):
        parent = telemetry.trace_metadata()
        with telemetry.span("tool", {"task_id": "child", "run_id": "run-b"}):
            child = telemetry.trace_metadata()
    alias = {key: value for key, value in identities.items() if key != "replay_generation_id"}
    alias["generation_id"] = "generation"
    with telemetry.span("agent", {**alias, "task_id": "child", "run_id": "run-c"}, root=True):
        resumed = telemetry.trace_metadata()
    assert parent["session_id"] == child["session_id"] == resumed["session_id"]
    assert parent["trace_id"] == child["trace_id"] != resumed["trace_id"]
    with telemetry.span("agent", {**identities, "episode_id": "other"}, root=True):
        assert telemetry.trace_metadata()["session_id"] != parent["session_id"]
    telemetry.close()


def test_default_batch_queue_does_not_block_windows_on_hung_exporter(monkeypatch, runtime):
    monkeypatch.delenv("SUBSEA_TRACE_SYNC", raising=False)

    class SlowExporter(Exporter):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def export(self, spans):
            self.started.set()
            self.release.wait(timeout=3)
            return super().export(spans)

    exporter = SlowExporter()
    configured(monkeypatch, exporter)
    telemetry = module.Telemetry(runtime)
    try:
        with telemetry.span("window.compute", root=True):
            pass
        health = telemetry.health()
        assert health["synchronous_export"] is False
        assert health["destinations"]["langfuse"]["processor"] == "batch"
        assert health["destinations"]["langfuse"]["queue_capacity"] == 256
        assert health["destinations"]["langfuse"]["status"] == "queued"
        assert health["destinations"]["langfuse"]["exporter_accepted"] is False
        assert exporter.started.wait(timeout=2)
        started = time.monotonic()
        with telemetry.span("window.compute", root=True):
            pass
        assert time.monotonic() - started < 0.2
        assert telemetry.health()["destinations"]["langfuse"]["pending_spans"] == 2
        exporter.release.set()
        assert telemetry.flush()
        assert telemetry.health()["destinations"]["langfuse"]["pending_spans"] == 0
        assert telemetry.health()["stored_trace_visibility"] == "unverified"
    finally:
        exporter.release.set()
        telemetry.close()


def test_bounded_batch_queue_drops_cannot_be_reported_as_success(monkeypatch, runtime):
    monkeypatch.delenv("SUBSEA_TRACE_SYNC", raising=False)

    class SlowExporter(Exporter):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def export(self, spans):
            self.started.set()
            self.release.wait(timeout=3)
            return super().export(spans)

    exporter = SlowExporter()
    configured(monkeypatch, exporter)
    telemetry = module.Telemetry(runtime)
    try:
        for _ in range(64):
            with telemetry.span("window.compute", root=True):
                pass
        assert exporter.started.wait(timeout=2)
        for _ in range(300):
            with telemetry.span("window.compute", root=True):
                pass
        exporter.release.set()
        assert telemetry.flush() is False
        assert telemetry.health()["status"] == "warning"
        assert telemetry.health()["destinations"]["langfuse"]["pending_spans"] > 0
    finally:
        exporter.release.set()
        telemetry.close()
