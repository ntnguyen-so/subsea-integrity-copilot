"""Native OTLP fanout with content-free local audit and truthful exporter health."""

from __future__ import annotations

import base64
import contextvars
import hashlib
import json
import math
import os
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Link, SpanContext, Status, StatusCode, TraceFlags

from subsea_copilot.redaction import SENSITIVE_KEYS as _SENSITIVE
from subsea_copilot.redaction import redact_content as _redact_content

_SCOPE: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("subsea_trace_scope")
_IDENTITIES = {"tenant_id", "site_id", "replay_generation_id", "generation_id", "episode_id"}
_SESSION_IDENTITIES = ("tenant_id", "site_id", "replay_generation_id", "episode_id")
_CONTENT = re.compile(r"prompt(?![._](?:hash|sha256|chars))|content|input$|output$|reasoning", re.I)
_SAFE_STRING = re.compile(
    r"(?:^|[._])(?:id|hash|sha256|name|role|phase|mode|purpose|outcome|status|code|model|source|tool|"
    r"version|requested_model|observed_model|model_identity_source|error|type|session)$"
)
TRACE_CONTENT_LIMIT = 192 * 1024


def _enabled(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in {"1", "true", "yes"}


def _loopback(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    return (
        parts.scheme == "http"
        and parts.hostname in {"127.0.0.1", "::1", "localhost"}
        and parts.username is None
        and parts.password is None
        and not parts.query
        and not parts.fragment
    )


def _hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _safe(key: str, value: object, content_enabled: bool) -> object | None:
    if (
        len(key) > 180
        or _SENSITIVE.search(key)
        or ("reasoning" in key.lower() and not key.endswith("_tokens"))
    ):
        return None
    if key.rsplit(".", 1)[-1] in _IDENTITIES:
        return _hash(value)
    if _CONTENT.search(key):
        if not content_enabled or not isinstance(value, str):
            return None
        value = _redact_content(value)
        return (
            value
            if len(value) <= TRACE_CONTENT_LIMIT
            else (
                value[:TRACE_CONTENT_LIMIT]
                + f"\n[Capture truncated at {TRACE_CONTENT_LIMIT} characters]"
            )
        )
    if type(value) in {bool, int, float}:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, str) and _SAFE_STRING.search(key):
        return value[:200]
    return None


class _ObservedExporter(SpanExporter):
    def __init__(self, delegate: SpanExporter) -> None:
        self.delegate = delegate
        self.accepted_batches = 0
        self.failed_batches = 0
        self.status = "pending"
        self.enqueued_spans = 0
        self.completed_spans = 0
        self.lock = threading.Lock()

    def queued(self) -> None:
        with self.lock:
            self.enqueued_spans += 1

    def export(self, spans: Sequence[Any]) -> SpanExportResult:
        try:
            result = self.delegate.export(spans)
        except Exception:
            result = SpanExportResult.FAILURE
        with self.lock:
            self.completed_spans += len(spans)
            if result == SpanExportResult.SUCCESS:
                self.accepted_batches += 1
                self.status = "accepted"
            else:
                self.failed_batches += 1
                self.status = "unavailable"
        return result

    def shutdown(self) -> None:
        try:
            self.delegate.shutdown()
        except Exception:
            with self.lock:
                self.status = "unavailable"

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            pending = max(0, self.enqueued_spans - self.completed_spans)
            return {
                "status": "queued" if pending and self.status != "unavailable" else self.status,
                "accepted_batches": self.accepted_batches,
                "failed_batches": self.failed_batches,
                "exporter_accepted": self.accepted_batches > 0,
                "enqueued_spans": self.enqueued_spans,
                "completed_spans": self.completed_spans,
                "pending_spans": pending,
            }


class _QueuedProcessor(SpanProcessor):
    def __init__(self, exporter: _ObservedExporter, synchronous: bool) -> None:
        self.exporter = exporter
        self.delegate: SpanProcessor = (
            SimpleSpanProcessor(exporter)
            if synchronous
            else BatchSpanProcessor(
                exporter,
                max_queue_size=256,
                max_export_batch_size=64,
                schedule_delay_millis=1000,
                export_timeout_millis=3000,
            )
        )

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self.delegate.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        if span.context and span.context.trace_flags.sampled:
            self.exporter.queued()
        self.delegate.on_end(span)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self.delegate.shutdown()


def _stored_tree_matches(
    observations: list[dict[str, Any]],
    required_types: Sequence[str],
) -> bool:
    required = {kind.lower() for kind in required_types}
    if not required <= {str(item.get("type", "")).lower() for item in observations}:
        return False
    if "agent" not in required:
        return True
    by_id = {item.get("id"): item for item in observations if isinstance(item.get("id"), str)}
    if len(by_id) != len(observations):
        return False
    roots = [
        item
        for item in observations
        if str(item.get("type", "")).lower() == "agent" and not item.get("parentObservationId")
    ]
    if len(roots) != 1:
        return False
    root_id = roots[0]["id"]
    sessions = {str(item.get("sessionId")) for item in observations}
    if len(sessions) != 1 or not re.fullmatch(r"[0-9a-f]{64}", str(next(iter(sessions)))):
        return False
    for item in observations:
        if item.get("parentObservationId") is not None and not isinstance(
            item.get("parentObservationId"), str
        ):
            return False
        current = item["id"]
        seen = set()
        while current != root_id:
            if current in seen or current not in by_id:
                return False
            seen.add(current)
            current = by_id[current].get("parentObservationId")
    return True


class _SafeSpan:
    def __init__(
        self,
        span: trace.Span,
        content_enabled: bool,
        attributes: Mapping[str, object],
    ) -> None:
        self._span = span
        self._content_enabled = content_enabled
        self._attributes = dict(attributes)

    def set_attribute(self, key: str, value: object) -> None:
        safe = _safe(key, value, self._content_enabled)
        if safe is not None:
            self._attributes[key] = safe
            self._span.set_attribute(key, safe)  # type: ignore[arg-type]

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        for key, value in attributes.items():
            self.set_attribute(key, value)

    def update_name(self, name: str) -> None:
        self._span.update_name(_redact_content(name)[:200])

    def add_event(
        self,
        name: str,
        attributes: Mapping[str, object] | None = None,
        timestamp: int | None = None,
    ) -> None:
        safe: dict[str, Any] = {
            key: cleaned
            for key, value in (attributes or {}).items()
            if (cleaned := _safe(key, value, self._content_enabled)) is not None
        }
        self._span.add_event(name[:100], safe, timestamp)

    def set_status(self, status: Status | StatusCode, description: str | None = None) -> None:
        code = status.status_code if isinstance(status, Status) else status
        self._span.set_status(Status(code))

    def record_exception(self, exception: BaseException, **kwargs: Any) -> None:
        self._span.add_event("error", {"error.type": type(exception).__name__[:100]})
        self.set_status(StatusCode.ERROR)

    def get_span_context(self) -> SpanContext:
        return self._span.get_span_context()

    def is_recording(self) -> bool:
        return self._span.is_recording()


class Telemetry:
    """span(name, attributes=None, root=False); no global provider mutation."""

    def __init__(self, runtime_dir: Path | None = None) -> None:
        self.runtime_dir = runtime_dir or Path(
            os.environ.get(
                "SUBSEA_RUNTIME_DIR",
                str(Path(os.environ.get("LOCALAPPDATA", ".")) / "SubseaCopilot"),
            )
        )
        self.content_enabled = _enabled("SUBSEA_TRACE_CONTENT") and _enabled(
            "SUBSEA_SYNTHETIC_ONLY"
        )
        self.synchronous_export = _enabled("SUBSEA_TRACE_SYNC")
        self.provider = TracerProvider(resource=Resource.create({"service.name": "subsea-copilot"}))
        self.tracer = self.provider.get_tracer("subsea.agent")
        self._exporters: dict[str, _ObservedExporter] = {}
        self._configuration: dict[str, dict[str, object]] = {}
        self._visible: set[str] = set()
        self._verified_trees: set[str] = set()
        self._visibility_status = "unverified"
        self._audit_failed = False
        self._audit_writes = 0
        self._audit_lock = threading.Lock()
        self._closed = False
        self._flush_failed = False
        self._flush_diagnostic: dict[str, object] = {"status": "not_attempted", "error_type": None}
        self._public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        self._secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
        self._langfuse_endpoint = os.environ.get(
            "SUBSEA_LANGFUSE_OTLP_ENDPOINT",
            "http://127.0.0.1:3001/api/public/otel/v1/traces",
        )
        global_enabled = _enabled("SUBSEA_TELEMETRY_ENABLED", True)
        for name, enabled, endpoint in (
            (
                "langfuse",
                _enabled("SUBSEA_LANGFUSE_ENABLED", bool(self._public_key or self._secret_key)),
                self._langfuse_endpoint,
            ),
            (
                "jaeger",
                _enabled("SUBSEA_JAEGER_ENABLED"),
                os.environ.get("SUBSEA_JAEGER_OTLP_ENDPOINT", "http://127.0.0.1:4319/v1/traces"),
            ),
        ):
            self._configuration[name] = {"status": "disabled"}
            if not global_enabled or not enabled:
                continue
            if not _loopback(endpoint) or (
                name == "langfuse" and not (self._public_key and self._secret_key)
            ):
                self._configuration[name] = {"status": "misconfigured"}
                continue
            headers = {}
            if name == "langfuse":
                authorization = base64.b64encode(
                    f"{self._public_key}:{self._secret_key}".encode()
                ).decode()
                headers = {
                    "Authorization": f"Basic {authorization}",
                    "x-langfuse-ingestion-version": "4",
                }
            try:
                exporter = _ObservedExporter(
                    OTLPSpanExporter(endpoint=endpoint, headers=headers, timeout=3)
                )
                self._exporters[name] = exporter
                self.provider.add_span_processor(
                    _QueuedProcessor(exporter, self.synchronous_export)
                )
                self._configuration[name] = {
                    "status": "pending",
                    "endpoint": endpoint,
                    "processor": "simple" if self.synchronous_export else "batch",
                    "queue_capacity": 0 if self.synchronous_export else 256,
                    "batch_capacity": 1 if self.synchronous_export else 64,
                }
            except Exception:
                self._configuration[name] = {"status": "misconfigured"}

    @contextmanager
    def span(
        self,
        name: str,
        attributes: Mapping[str, object] | None = None,
        root: bool = False,
        parent: Mapping[str, object] | None = None,
    ) -> Iterator[_SafeSpan]:
        parent_context: Context | None = None
        if parent is not None:
            if root:
                raise ValueError("A root span cannot also have a persisted parent")
            trace_id, span_id = parent.get("trace_id"), parent.get("span_id")
            if (
                not isinstance(trace_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", trace_id)
                or not isinstance(span_id, str)
                or not re.fullmatch(r"[0-9a-f]{16}", span_id)
            ):
                raise ValueError("Invalid persisted trace context")
            context = SpanContext(
                int(trace_id, 16),
                int(span_id, 16),
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            )
            if not context.is_valid:
                raise ValueError("Invalid persisted trace context")
            parent_context = trace.set_span_in_context(trace.NonRecordingSpan(context), Context())
        original = dict(attributes or {})
        scope = {} if root or parent is not None else dict(_SCOPE.get({}))
        if "generation_id" in original and "replay_generation_id" not in original:
            original["replay_generation_id"] = original["generation_id"]
        for identity in _SESSION_IDENTITIES:
            if identity in original:
                scope[identity] = _hash(original[identity])
        if "session_id" not in scope and scope:
            scope["session_id"] = _hash(json.dumps(scope, sort_keys=True))
        # Rebuild episode identity without inheriting another worker's active scope.
        if root and scope:
            scope["session_id"] = _hash(
                json.dumps(
                    {key: value for key, value in scope.items() if key != "session_id"},
                    sort_keys=True,
                )
            )
        token = _SCOPE.set(scope)
        safe: dict[str, Any] = {
            key: cleaned
            for key, value in original.items()
            if (cleaned := _safe(key, value, self.content_enabled)) is not None
        }
        for key, value in scope.items():
            safe[f"subsea.{key}"] = value
        if scope.get("session_id"):
            safe["langfuse.session.id"] = scope["session_id"]
        kind = name.split(".", 1)[0]
        observation_type = kind if kind in {"generation", "tool", "guardrail", "agent"} else "span"
        safe["langfuse.observation.type"] = observation_type
        if root:
            safe.setdefault("langfuse.trace.name", name[:100])
        links = []
        if original.get("linked_trace_id") and original.get("linked_span_id"):
            try:
                linked = SpanContext(
                    int(str(original["linked_trace_id"]), 16),
                    int(str(original["linked_span_id"]), 16),
                    is_remote=True,
                    trace_flags=TraceFlags(TraceFlags.SAMPLED),
                )
                if linked.is_valid:
                    links.append(Link(linked))
            except ValueError:
                pass
        try:
            with self.tracer.start_as_current_span(
                name[:100],
                attributes=safe,
                context=parent_context if parent is not None else (Context() if root else None),
                links=links,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                wrapped = _SafeSpan(span, self.content_enabled, safe)
                try:
                    yield wrapped
                except BaseException as exc:
                    wrapped.record_exception(exc)
                    raise
                finally:
                    context = span.get_span_context()
                    self._audit(
                        {
                            "name": name[:100],
                            "trace_id": f"{context.trace_id:032x}",
                            "span_id": f"{context.span_id:016x}",
                            "session_id": scope.get("session_id"),
                            "observation_type": observation_type,
                            "attributes": {
                                key: value
                                for key, value in wrapped._attributes.items()
                                if not _CONTENT.search(key)
                            },
                        }
                    )
        finally:
            _SCOPE.reset(token)

    def _audit(self, record: dict[str, object]) -> None:
        try:
            with self._audit_lock:
                self.runtime_dir.mkdir(parents=True, exist_ok=True)
                audit_path = self.runtime_dir / "telemetry-audit.jsonl"
                with audit_path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(record, separators=(",", ":")) + "\n")
                    self._audit_writes += 1
        except OSError:
            self._audit_failed = True

    def trace_metadata(self) -> dict[str, object]:
        context = trace.get_current_span().get_span_context()
        return {
            "trace_id": f"{context.trace_id:032x}" if context.is_valid else None,
            "span_id": f"{context.span_id:016x}" if context.is_valid else None,
            "session_id": _SCOPE.get({}).get("session_id"),
        }

    def trace_url(self, trace_id: str) -> str | None:
        if not re.fullmatch(r"[0-9a-f]{32}", trace_id) or not _loopback(self._langfuse_endpoint):
            return None
        parts = urlsplit(self._langfuse_endpoint)
        # The owned Compose stack initializes this project with a fixed ID.
        return f"{parts.scheme}://{parts.netloc}/project/subsea-copilot/traces/{trace_id}"

    def health(self) -> dict[str, object]:
        destinations = {}
        for name, configuration in self._configuration.items():
            destinations[name] = {
                **configuration,
                **(self._exporters[name].snapshot() if name in self._exporters else {}),
            }
        statuses = {value["status"] for value in destinations.values()}
        warning = (
            self._audit_failed
            or self._flush_failed
            or self._visibility_status in {"not_visible", "incomplete_tree"}
            or bool(statuses & {"misconfigured", "unavailable"})
        )
        pending = bool(statuses & {"pending", "queued"}) or (
            "langfuse" in self._exporters and self._visibility_status == "unverified"
        )
        return {
            "status": (
                "warning"
                if warning
                else ("disabled" if statuses == {"disabled"} else ("pending" if pending else "ok"))
            ),
            "destinations": destinations,
            "content_capture": self.content_enabled,
            "synchronous_export": self.synchronous_export,
            "local_audit": (
                "unavailable"
                if self._audit_failed
                else ("available" if self._audit_writes else "pending")
            ),
            "stored_trace_visibility": self._visibility_status,
            "storage_verification_api": "langfuse_observations_v2",
            "verified_trace_count": len(self._visible),
            "verified_observation_tree_count": len(self._verified_trees),
            "closed": self._closed,
            "flush_failed": self._flush_failed,
            "flush_diagnostic": dict(self._flush_diagnostic),
        }

    def verify_trace(
        self,
        trace_id: str,
        required_types: Sequence[str] | None = None,
    ) -> bool:
        """Query v4 stored observations, optionally checking connected episode tree."""
        if not re.fullmatch(r"[0-9a-f]{32}", trace_id) or "langfuse" not in self._exporters:
            return False
        parts = urlsplit(self._langfuse_endpoint)
        endpoint = (
            f"{parts.scheme}://{parts.netloc}/api/public/v2/observations"
            f"?traceId={trace_id}&fields=core,basic&limit=100"
        )
        auth = base64.b64encode(f"{self._public_key}:{self._secret_key}".encode()).decode()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:
                return None

        try:
            opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
            observations = []
            cursor = None
            seen_cursors: set[str] = set()
            for _ in range(5):
                url = endpoint + (f"&cursor={quote(cursor, safe='')}" if cursor else "")
                request = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
                with opener.open(request, timeout=3) as response:
                    raw = response.read(100001)
                if len(raw) > 100000:
                    raise ValueError("Stored trace page exceeds verification bound")
                value = json.loads(raw)
                page = value.get("data") if isinstance(value, dict) else None
                if (
                    not isinstance(page, list)
                    or len(page) > 100
                    or any(
                        not isinstance(item, dict) or item.get("traceId") != trace_id
                        for item in page
                    )
                ):
                    raise ValueError("Stored trace page is incorrectly scoped")
                observations.extend(page)
                meta = value.get("meta") or {}
                if not isinstance(meta, dict):
                    raise ValueError("Invalid stored trace pagination")
                cursor = meta.get("cursor")
                if not cursor:
                    break
                if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in seen_cursors:
                    raise ValueError("Invalid stored trace cursor")
                seen_cursors.add(cursor)
            else:
                raise ValueError("Stored trace pagination exceeds verification bound")
            if observations:
                self._visible.add(trace_id)
                self._visibility_status = "verified"
                if required_types:
                    if not _stored_tree_matches(observations, required_types):
                        self._visibility_status = "incomplete_tree"
                        return False
                    self._verified_trees.add(trace_id)
                return True
        except (OSError, ValueError, urllib.error.URLError):
            pass
        self._visibility_status = "not_visible"
        return False

    def flush(self) -> bool:
        error_type = None
        try:
            completed = self.provider.force_flush(timeout_millis=5000)
            if not completed:
                error_type = "provider_flush_failed"
        except Exception as exc:
            completed = False
            error_type = type(exc).__name__[:100]
        snapshots = [exporter.snapshot() for exporter in self._exporters.values()]
        if any(snapshot["pending_spans"] != 0 for snapshot in snapshots):
            error_type = error_type or "queue_incomplete"
        success = (
            completed
            and all(
                snapshot["status"] != "unavailable" and snapshot["pending_spans"] == 0
                for snapshot in snapshots
            )
            and not any(
                value["status"] == "misconfigured" for value in self._configuration.values()
            )
        )
        self._flush_failed = not success
        self._flush_diagnostic = {
            "status": "completed" if success else "failed",
            "error_type": error_type or (None if success else "exporter_unavailable"),
        }
        return success

    def force_flush(self) -> bool:
        return self.flush()

    def close(self) -> None:
        if not self._closed:
            self.flush()
            try:
                self.provider.shutdown()
            except Exception as exc:
                self._flush_failed = True
                self._flush_diagnostic = {
                    "status": "shutdown_failed",
                    "error_type": type(exc).__name__[:100],
                }
            self._closed = True
