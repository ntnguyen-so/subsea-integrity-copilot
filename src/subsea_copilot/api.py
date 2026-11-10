"""Composition root for the local FastAPI console, monitoring and agent workers.

Routes expose scoped PostgreSQL evidence, not direct model/database capabilities.
Numerical monitoring runs independently of hosted inference; durable event cursors
let the browser reconnect. Recorded views reconstruct measurements or replay saved
reports, while explicit investigation endpoints admit fresh hosted work.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from bisect import bisect_right
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .budgets import ROOT_WATCHDOG_SECONDS
from .casefile import InvestigationCase, build_casefile
from .config import Settings
from .contracts import (
    AgentRole,
    AgentTask,
    CanonicalObservation,
    Contract,
    Mode,
    ReplaySession,
    SitePack,
    WindowSnapshot,
    Workflow,
    utc_now,
)
from .diagnostics import analyze_window
from .ingest import normalize_records, parse_timestamp
from .llm.copilot_cli import CopilotCLIChatModel
from .monitoring import Monitor
from .playback import Recording
from .report_mapping import load_report_mapping, prepare_report_mapping
from .runtime.checkpointer import postgres_checkpointer
from .runtime.gateway import ToolGateway
from .runtime.scripted import ScriptedChatModel
from .runtime.workflow import AgentService
from .security import (
    COOKIE_NAME,
    SESSION_SECONDS,
    AuthenticationError,
    Principal,
    SessionManager,
)
from .store import TERMINAL, Store, StoreError
from .synthetic import CUSTOMER_QUESTIONS, SCENARIOS, generate_pack
from .telemetry import Telemetry
from .validation import ValidationError as AgentValidationError
from .validation import validate_result
from .warning import monitoring_warning

logger = logging.getLogger(__name__)

QUESTIONS = CUSTOMER_QUESTIONS


class LoginForm(Contract):
    username: str = Field(max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class ReplayCreate(Contract):
    scenario: Literal["S1", "S2", "S3", "S4", "S5", "S6", "S7"]
    seed: int = Field(default=2026, ge=0, le=2**32 - 1)
    mode: Mode = "scripted"
    workflow: Workflow = "agent_assisted"
    pause_on_anomaly: bool = True
    idempotency_key: str = Field(min_length=1, max_length=200)


class ReplayControl(Contract):
    action: Literal["play", "pause", "step", "speed"]
    speed: Literal[1, 2, 5, 10, 20, 30] | None = None
    step_seconds: Literal[1, 2, 5, 10, 20, 30] | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)


class QuestionForm(Contract):
    question: str = Field(min_length=3, max_length=2000)
    snapshot_id: str = Field(min_length=1, max_length=200)
    mode: Mode
    idempotency_key: str = Field(min_length=1, max_length=200)


class PlaybackInvestigation(Contract):
    source_seconds: int = Field(ge=60, le=360)
    idempotency_key: str = Field(min_length=1, max_length=200)


class AgentWorker:
    """Dispatch independent roots, each with its own graph-checkpoint connection.

    Report-to-map extraction happens after investigation completion and reports
    its own errors; visualization failure must not erase the accepted report.
    """

    def __init__(
        self, service: AgentService, map_report: Callable[[AgentTask], None] | None = None,
        *, service_factory: Callable[[str], AbstractContextManager[AgentService]],
    ) -> None:
        self.service = service
        self.service_factory = service_factory
        self.map_report = map_report
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self._workers: dict[str, threading.Thread] = {}
        self._failed_roots: set[str] = set()
        self._mapping_roots: set[str] = set()
        self.error: str | None = None
        self.mapping_error: str | None = None

    @property
    def active_workers(self) -> int:
        with self._lock:
            return sum(thread.is_alive() for thread in self._workers.values()) - len(
                self._mapping_roots
            )

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self.run, name="subsea-investigation-dispatcher", daemon=True,
        )
        self.thread.start()

    def _map_one(self, task: AgentTask) -> None:
        if self.map_report is None:
            return
        with self._lock:
            self._mapping_roots.add(task.root_id)
        try:
            self.map_report(task)
        except Exception:
            logger.exception("Background report mapping failed; investigations remain available")
            self.mapping_error = "mapping_worker_failed"
            self.service.store.publish_event(
                task.generation_id, "mapping.completed",
                {"status": "failed", "error_code": "mapping_worker_failed"},
                task_id=task.id, snapshot_id=task.snapshot_id,
            )
        else:
            self.mapping_error = None
        finally:
            with self._lock:
                self._mapping_roots.discard(task.root_id)

    def _investigate(self, root_id: str) -> None:
        try:
            with self.service_factory(root_id) as service:
                while not self._stop.is_set():
                    if self.service.store.get_task(root_id).state in TERMINAL:
                        return
                    progressed = service.run_once()
                    root = self.service.store.get_task(root_id)
                    if root.state in TERMINAL:
                        self._map_one(root)
                        return
                    if not progressed:
                        self._stop.wait(0.25)
        except Exception:
            logger.exception("Investigation worker failed root_id=%s", root_id)
            self.error = "agent_worker_failed"
            with self._lock:
                self._failed_roots.add(root_id)
            root = self.service.store.get_task(root_id)
            self.service.store.publish_event(
                root.generation_id, "agent.worker_failed",
                {"error_code": "agent_worker_failed"},
                task_id=root.id, snapshot_id=root.snapshot_id,
            )

    def run(self) -> None:
        try:
            while not self._stop.is_set():
                roots = self.service.store.pending_root_ids()
                with self._lock:
                    self._workers = {
                        root_id: thread for root_id, thread in self._workers.items()
                        if thread.is_alive()
                    }
                    for root_id in roots:
                        if root_id in self._workers or root_id in self._failed_roots:
                            continue
                        thread = threading.Thread(
                            target=self._investigate, args=(root_id,),
                            name=f"subsea-investigation-{root_id}", daemon=True,
                        )
                        self._workers[root_id] = thread
                        thread.start()
                self._stop.wait(0.25)
        except Exception:
            logger.exception("Investigation dispatcher stopped after an unhandled failure")
            self.error = "agent_worker_failed"

    def close(self) -> None:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=10)
        with self._lock:
            threads = list(self._workers.values())
        for thread in threads:
            thread.join(timeout=ROOT_WATCHDOG_SECONDS)
            if thread.is_alive():
                logger.error("Agent worker exceeded its root deadline during shutdown")


def create_app(settings: Settings, *, start_workers: bool = True) -> FastAPI:
    """Wire scoped storage, authentication, optional workers and lifecycle cleanup."""
    store = Store(
        settings.database_dsn,
        tenant_id=settings.tenant_id,
        site_id=settings.site_id,
        tools_dsn=settings.tools_dsn,
    )
    sessions = SessionManager(settings.operator_password)
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    checkpointer_context = postgres_checkpointer(settings.checkpoint_dsn)
    resources: dict[str, object] = {}
    failures: dict[str, deque[float]] = defaultdict(deque)
    login_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        with checkpointer_context as checkpointer:

            def model_factory(
                role: AgentRole, mode: Mode
            ) -> CopilotCLIChatModel | ScriptedChatModel:
                if mode == "scripted":
                    return ScriptedChatModel(role=role)
                return CopilotCLIChatModel(runtime_dir=settings.runtime_dir, model_id="gpt-6.1-sol")

            service = AgentService(store, model_factory, checkpointer, telemetry)
            monitor = Monitor(store, service, telemetry)

            def map_report(task: AgentTask) -> None:
                if (
                    task.mode != "live" or task.state != "SUCCEEDED"
                    or task.role != "operator_response"
                    or task.parent_id is not None or task.result is None
                    or task.result.interpretation is None
                ):
                    return
                extraction = prepare_report_mapping(
                    settings.runtime_dir, task, monitor.pack_for(task.generation_id),
                    model_factory("operator_response", "live"), telemetry,
                )
                store.publish_event(
                    task.generation_id, "mapping.completed",
                    {"status": extraction["status"]},
                    task_id=task.id, snapshot_id=task.snapshot_id,
                )

            @contextmanager
            def investigation_service(root_id: str) -> Iterator[AgentService]:
                with postgres_checkpointer(settings.checkpoint_dsn) as own_checkpointer:
                    yield AgentService(
                        store, model_factory, own_checkpointer, telemetry, root_id=root_id,
                    )

            worker = AgentWorker(service, map_report, service_factory=investigation_service)
            resources.update({"service": service, "monitor": monitor, "worker": worker})
            if start_workers:
                monitor.start()
                worker.start()
            try:
                yield
            finally:
                monitor.close()
                worker.close()
                from .llm.copilot_sdk import close_hosts

                try:
                    close_hosts()
                finally:
                    telemetry.close()
                    store.close()

    app = FastAPI(title="Subsea Lens", lifespan=lifespan)
    app.state.store = store
    app.state.resources = resources

    @app.exception_handler(StoreError)
    async def store_error(_request: Request, exc: StoreError) -> JSONResponse:
        status = {
            "not_found": 404,
            "forbidden": 403,
            "conflict": 409,
            "budget_blocked": 429,
            "queue_full": 429,
        }.get(exc.code, 409)
        return JSONResponse(status_code=status, content={"detail": str(exc), "code": exc.code})

    @app.exception_handler(AgentValidationError)
    async def agent_error(_request: Request, exc: AgentValidationError) -> JSONResponse:
        status = {
            "scope": 403,
            "question": 422,
            "proxy_auth": 503,
            "proxy_quota": 503,
        }.get(exc.code, 409)
        return JSONResponse(status_code=status, content={"detail": str(exc), "code": exc.code})

    def principal(request: Request, *, write: bool = False) -> Principal:
        """Authenticate every protected route and require CSRF/same-origin checks for writes."""
        try:
            result = sessions.authenticate(request.cookies.get(COOKIE_NAME))
            if write:
                sessions.check_csrf(result, request.headers.get("X-CSRF-Token"))
                origin = request.headers.get("origin")
                if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                    raise AuthenticationError("Cross-origin writes are forbidden")
            return result
        except AuthenticationError as exc:
            raise HTTPException(status_code=403 if write else 401, detail=str(exc)) from exc

    def monitor_service() -> Monitor:
        instance = resources.get("monitor")
        if not isinstance(instance, Monitor):
            raise HTTPException(status_code=503, detail="Monitoring service is not initialized")
        if instance.error:
            raise HTTPException(status_code=503, detail=instance.error)
        return instance

    def agent_service() -> AgentService:
        instance = resources.get("service")
        if not isinstance(instance, AgentService):
            raise HTTPException(status_code=503, detail="Agent service is not initialized")
        return instance

    def report_labels(task: AgentTask, pack: SitePack) -> object:
        try:
            return load_report_mapping(settings.runtime_dir, task, pack)
        except (OSError, ValueError):
            logger.exception("Map extraction evidence unavailable task_id=%s", task.id)
            return {
                "status": "failed", "mapping": None, "error_code": "mapping_evidence_invalid",
            }

    def health() -> dict[str, object]:
        worker = resources.get("worker")
        monitor = resources.get("monitor")
        service = resources.get("service")
        provider = service.health() if isinstance(service, AgentService) else {}
        agent_status = (
            worker.error or ("running" if start_workers else "disabled")
            if isinstance(worker, AgentWorker)
            else "starting"
        )
        if provider.get("available") is False:
            agent_status = str(provider.get("error_code") or "agent_unavailable")
        return {
            "monitor": (
                monitor.error or ("running" if start_workers else "disabled")
                if isinstance(monitor, Monitor)
                else "starting"
            ),
            "agent": agent_status,
            "investigation_workers": worker.active_workers
            if isinstance(worker, AgentWorker) else 0,
            "investigation_worker_limit": None,
            "map_worker": (
                worker.mapping_error or ("ready" if start_workers else "disabled")
                if isinstance(worker, AgentWorker) else "starting"
            ),
            "observability": telemetry.health(),
            "provider": provider,
            "source": "synthetic",
            "authority": "read-only",
            "server_time": utc_now().isoformat(),
        }

    @app.get("/api/health")
    def get_health() -> dict[str, object]:
        return health()

    @app.get("/api/session")
    def session_info(request: Request) -> dict[str, object]:
        try:
            current = sessions.authenticate(request.cookies.get(COOKIE_NAME))
        except AuthenticationError:
            return {"authenticated": False, "csrf_token": None, "username": None}
        return {
            "authenticated": True,
            "csrf_token": current.csrf_token,
            "username": current.username,
        }

    @app.post("/api/login")
    def login(form: LoginForm, request: Request, response: Response) -> dict[str, object]:
        identity = request.client.host if request.client else "local"
        with login_lock:
            queue = failures[identity]
            while queue and time.monotonic() - queue[0] > 60:
                queue.popleft()
            if len(queue) >= 5:
                raise HTTPException(
                    status_code=429, detail="Too many login attempts; wait one minute"
                )
        try:
            cookie, current = sessions.login(form.username, form.password)
        except AuthenticationError as exc:
            with login_lock:
                failures[identity].append(time.monotonic())
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        response.set_cookie(
            COOKIE_NAME,
            cookie,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=SESSION_SECONDS,
            path="/",
        )
        return {
            "authenticated": True,
            "csrf_token": current.csrf_token,
            "username": current.username,
        }

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        principal(request, write=True)
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"authenticated": False}

    @app.get("/api/scenarios")
    def scenarios(request: Request) -> dict[str, object]:
        principal(request)
        return {
            "scenarios": [{"id": key, "name": value} for key, value in SCENARIOS.items()],
            "questions": QUESTIONS,
        }

    @app.get("/api/replays")
    def replays(request: Request) -> dict[str, object]:
        principal(request)
        return {"replays": store.list_replays()}

    @app.post("/api/replays")
    def create_replay(form: ReplayCreate, request: Request) -> object:
        principal(request, write=True)
        return monitor_service().create(
            form.scenario,
            form.seed,
            form.mode,
            form.idempotency_key,
            workflow=form.workflow,
            pause_on_anomaly=form.pause_on_anomaly,
        )

    @app.post("/api/replays/{generation_id}/control")
    def control(generation_id: str, form: ReplayControl, request: Request) -> object:
        principal(request, write=True)
        try:
            return monitor_service().control(
                generation_id, form.action, form.speed, form.idempotency_key,
                step_seconds=form.step_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/replays/{generation_id}/projection")
    def projection(generation_id: str, request: Request) -> dict[str, object]:
        principal(request)
        view: dict[str, object] = dict(store.get_projection(generation_id))
        latest = view["latest_window"]
        view.update(
            {
                "warning": monitoring_warning(
                    WindowSnapshot.model_validate(latest) if latest is not None else None,
                    workflow=ReplaySession.model_validate(view["replay"]).workflow,
                ),
                "pack": monitor_service().pack_for(generation_id),
                "health": health(),
                "server_time": utc_now().isoformat(),
            }
        )
        return view

    @app.get("/api/replays/{generation_id}/windows")
    def windows(generation_id: str, request: Request) -> dict[str, object]:
        principal(request)
        store.get_replay(generation_id)
        return {"windows": store.list_windows(generation_id, limit=120)}

    playback_hashes: dict[str, str] = {}
    timeline_frames: dict[str, WindowSnapshot] = {}
    timeline_lock = threading.RLock()

    def timeline_observations(
        replay: ReplaySession, end_seconds: int, clock_seconds: float,
        sensor_id: str | None = None,
    ) -> list[CanonicalObservation]:
        """Reconstruct only measurements available at the requested source clock."""
        source = monitor_service()._source(replay)
        end = replay.epoch + timedelta(seconds=end_seconds)
        start = end - timedelta(seconds=source.dataset.pack.window_seconds)
        released = bisect_right(source.received_seconds, clock_seconds)
        return normalize_records([
            row for row in source.dataset.records[:released]
            if (sensor_id is None or row.sensor_id == sensor_id)
            and start <= parse_timestamp(row.observed_at) < end
        ], source.dataset.pack)

    def timeline_frame(replay: ReplaySession, source_seconds: int) -> WindowSnapshot | None:
        source = monitor_service()._source(replay)
        pack = source.dataset.pack
        if not 0 <= source_seconds <= replay.duration_seconds or source_seconds % pack.hop_seconds:
            raise HTTPException(status_code=422, detail="Choose a source-window endpoint")
        if source_seconds == 0:
            return None
        with timeline_lock:
            cached = next((
                frame for frame in timeline_frames.values()
                if frame.generation_id == replay.id and frame.end_seconds == source_seconds
            ), None)
        if cached is None:
            clock = source_seconds + pack.lateness_seconds
            cached = analyze_window(
                pack, source.baseline,
                timeline_observations(replay, source_seconds, clock),
                generation_id=replay.id, end_seconds=source_seconds,
                clock_seconds=clock, epoch=replay.epoch, tenant_id=replay.tenant_id,
                screening_only=True,
            )
            with timeline_lock:
                timeline_frames[cached.id] = cached
                if len(timeline_frames) > 128:
                    del timeline_frames[next(iter(timeline_frames))]
        return cached

    def display_window(
        snapshot_id: str, generation_id: str | None = None, source_seconds: int | None = None,
    ) -> tuple[WindowSnapshot, bool]:
        if generation_id is not None or source_seconds is not None:
            if generation_id is None or source_seconds is None:
                raise HTTPException(
                    status_code=422, detail="Provide replay and source endpoint together",
                )
            reconstructed = timeline_frame(store.get_replay(generation_id), source_seconds)
            if reconstructed is None or reconstructed.id != snapshot_id:
                raise HTTPException(
                    status_code=409, detail="Timeline source does not match this snapshot",
                )
            return reconstructed, True
        with timeline_lock:
            cached = timeline_frames.get(snapshot_id)
        if cached is not None:
            store.get_replay(cached.generation_id)
            return cached, True
        return store.get_window(snapshot_id), False

    @app.get("/api/replays/{generation_id}/timeline-window")
    def timeline_window(
        generation_id: str, source_seconds: int, request: Request,
    ) -> dict[str, object]:
        """Build a bounded measurement-only display frame without creating agent work."""
        principal(request)
        replay = store.get_replay(generation_id)
        cached = timeline_frame(replay, source_seconds)
        return {
            "snapshot": cached,
            "warning": monitoring_warning(cached, workflow=replay.workflow),
        }

    def recording_dataset_hash(generation_id: str) -> str:
        from .playback import dataset_hash

        replay = store.get_replay(generation_id)
        if generation_id not in playback_hashes:
            playback_hashes[generation_id] = dataset_hash(monitor_service()._source(replay).dataset)
        return playback_hashes[generation_id]

    def compatible_recordings(generation_id: str) -> list[Recording]:
        """Match scenario, seed, raw-data hash and geometry before presenting a saved report."""
        from .playback import load_library

        replay = store.get_replay(generation_id)
        digest = recording_dataset_hash(generation_id)
        pack = monitor_service().pack_for(generation_id)
        try:
            library = load_library(settings.runtime_dir / "agent-playback.json")
        except (OSError, ValueError) as exc:
            logger.error("Recording library unavailable: %s", type(exc).__name__)
            raise HTTPException(
                status_code=503, detail="Recording library unavailable; no results substituted.",
            ) from exc
        return [
            row for row in library.recordings
            if row.scenario == replay.scenario and row.seed == replay.seed
            and row.dataset_sha256 == digest and row.pack.version == pack.version
        ]

    @app.get("/api/replays/{generation_id}/recordings")
    def recordings(generation_id: str, request: Request) -> dict[str, object]:
        principal(request)
        replay = store.get_replay(generation_id)
        rows = [
            {"origin": "library", **row.summary()}
            for row in compatible_recordings(generation_id)
        ]
        pack = monitor_service().pack_for(generation_id)
        rows.extend(store.recorded_investigations(replay, pack.version))
        unique = {str(row["task_id"]): row for row in rows}
        return {"base_playback_speed": 5, "recordings": sorted(unique.values(), key=lambda row: (
            int(str(row["source_seconds"])), str(row["created_at"]),
        ))}

    @app.get("/api/replays/{generation_id}/recordings/{task_id}")
    def recording_detail(generation_id: str, task_id: str, request: Request) -> dict[str, object]:
        principal(request)
        for row in compatible_recordings(generation_id):
            if row.task.id == task_id:
                payload = row.public_detail()
                detail = payload["detail"]
                assert isinstance(detail, dict)
                detail["output_mapping"] = report_labels(row.task, row.pack)
                return payload
        task, snapshot, pack = stored_recording(generation_id, task_id)
        return {
            "pack": pack, "snapshot": snapshot,
            "detail": task_detail(task.id, accepted_casefile_only=True),
        }

    def stored_recording(
        generation_id: str, task_id: str,
    ) -> tuple[AgentTask, WindowSnapshot, SitePack]:
        replay = store.get_replay(generation_id)
        task = store.get_task(task_id)
        original = store.get_replay(task.generation_id)
        snapshot = store.get_window(task.snapshot_id)
        pack = monitor_service().pack_for(generation_id)
        if (
            task.parent_id is not None
            or task.state not in {"SUCCEEDED", "ABSTAINED", "FAILED"}
            or original.scenario != replay.scenario or original.seed != replay.seed
            or original.source_version != replay.source_version
            or snapshot.pack_version != pack.version
            or recording_dataset_hash(original.id) != recording_dataset_hash(generation_id)
        ):
            raise HTTPException(status_code=404, detail="No compatible recorded investigation")
        return task, snapshot, pack

    @app.get("/api/replays/{generation_id}/recordings/{task_id}/trace")
    def recorded_trace(generation_id: str, task_id: str, request: Request) -> dict[str, object]:
        principal(request)
        for row in compatible_recordings(generation_id):
            if row.task.id == task_id:
                metadata = (
                    row.trace_metadata.model_dump(exclude_none=True) if row.trace_metadata else {}
                )
                return trace_payload(row.task, metadata)
        task, _, _ = stored_recording(generation_id, task_id)
        return trace_payload(task, store.latest_task_trace(task.id) or {})

    @app.post("/api/replays/{generation_id}/investigate-here")
    def investigate_here(
        generation_id: str, form: PlaybackInvestigation, request: Request,
    ) -> dict[str, object]:
        """Create a separate live generation at a selected endpoint; never mutate the recording."""
        principal(request, write=True)
        with monitor_service()._lock:
            return prepare_live_investigation(generation_id, form)

    def prepare_live_investigation(
        generation_id: str, form: PlaybackInvestigation,
    ) -> dict[str, object]:
        from .contracts import content_hash
        from .monitoring import AUTO_QUESTION

        original = store.get_replay(generation_id)
        monitor = monitor_service()
        pack = monitor.pack_for(generation_id)
        if form.source_seconds % pack.hop_seconds:
            raise HTTPException(status_code=422, detail="Choose a monitoring-window endpoint")
        creation_key = "playback:" + form.idempotency_key
        prepared_id = "replay-" + content_hash({
            "tenant": store.tenant_id, "key": creation_key,
        })[:24]
        try:
            replay = store.get_replay(prepared_id)
        except StoreError as exc:
            if exc.code != "not_found":
                raise
            replay = monitor.create(
                original.scenario, original.seed, "live", creation_key,
                workflow="agent_assisted", pause_on_anomaly=True,
            )
        if (
            replay.scenario != original.scenario or replay.seed != original.seed
            or replay.mode != "live" or replay.workflow != "agent_assisted"
            or not replay.pause_on_anomaly
        ):
            raise HTTPException(status_code=409, detail="Retry key belongs to another source")
        existing = [task for task in store.list_tasks(replay.id) if task.parent_id is None]
        if existing:
            snapshot = store.get_window(existing[0].snapshot_id)
            if snapshot.end_seconds != form.source_seconds:
                raise HTTPException(status_code=409, detail="Retry key belongs to another endpoint")
            return {"replay": replay, "task": existing[0]}
        source = monitor._source(replay)
        if replay.investigation_window_id:
            held = store.get_window(replay.investigation_window_id)
            if held.end_seconds != form.source_seconds:
                raise HTTPException(status_code=409, detail="Retry key belongs to another endpoint")
        if replay.last_endpoint > form.source_seconds:
            raise HTTPException(status_code=409, detail="Retry key belongs to another endpoint")
        prepared_snapshot = (
            store.get_window(replay.latest_window_id) if replay.latest_window_id else None
        )
        for endpoint in range(
            replay.last_endpoint + pack.hop_seconds,
            form.source_seconds + 1, pack.hop_seconds,
        ):
            replay = store.save_replay(replay.model_copy(update={
                "clock_seconds": endpoint + pack.lateness_seconds,
            }), expected_version=replay.version)
            monitor._release(replay, source)
            prepared_snapshot = store.save_window(monitor._snapshot(replay, source, endpoint))
            replay = store.save_replay(replay.model_copy(update={
                "latest_window_id": prepared_snapshot.id, "last_endpoint": endpoint,
            }), expected_version=replay.version)
        if prepared_snapshot is None:
            raise HTTPException(status_code=409, detail="Live source window was not prepared")
        replay = store.save_replay(replay.model_copy(update={
            "investigation_window_id": prepared_snapshot.id,
        }), expected_version=replay.version)
        task = agent_service().submit_question(
            replay, prepared_snapshot, AUTO_QUESTION, "playback-live:" + form.idempotency_key,
        )
        return {"replay": replay, "task": task}

    @app.get("/api/evaluation")
    def evaluation_report(request: Request) -> object:
        principal(request)
        from .qualification import MODEL_METADATA_KEYS
        from .reference_evaluation import read_evaluation

        try:
            archive_id = request.query_params.get("archive_id")
            if archive_id:
                from .evaluation_history import load_archive

                try:
                    report = load_archive(archive_id)
                except LookupError as exc:
                    raise HTTPException(
                        status_code=404, detail="Archived evaluation not found",
                    ) from exc
            else:
                report = read_evaluation()
            for recording in [report, *report.get("additional_evaluations", [])]:
                for case in recording.get("cases", []):
                    case["model_receipts"] = [
                        {key: receipt.get(key) for key in ("task_id", *MODEL_METADATA_KEYS)}
                        for receipt in case.get("model_receipts", [])
                    ]
            return report
        except (OSError, ValueError, TypeError) as exc:
            logger.error("Reference evaluation artifact is unreadable: %s", type(exc).__name__)
            raise HTTPException(
                status_code=503, detail="Recorded evaluation unavailable; no score is verified."
            ) from exc

    @app.get("/api/windows/{snapshot_id}")
    def window(
        snapshot_id: str, request: Request,
        generation_id: str | None = None, source_seconds: int | None = None,
    ) -> object:
        principal(request)
        return display_window(snapshot_id, generation_id, source_seconds)[0]

    @app.get("/api/windows/{snapshot_id}/sensors/{sensor_id}")
    def sensor_details(
        snapshot_id: str, sensor_id: str, request: Request,
        generation_id: str | None = None, source_seconds: int | None = None,
    ) -> dict[str, object]:
        principal(request)
        snapshot, reconstructed = display_window(snapshot_id, generation_id, source_seconds)
        pack = monitor_service().pack_for(snapshot.generation_id)
        sensor = next((row for row in pack.sensors if row.id == sensor_id), None)
        if sensor is None:
            raise HTTPException(status_code=404, detail="Sensor not found in this site")
        replay = store.get_replay(snapshot.generation_id)
        if reconstructed:
            return {"sensor": sensor, "observations": timeline_observations(
                replay, snapshot.end_seconds, snapshot.clock_seconds, sensor_id,
            )}
        originals = [
            row.original
            for row in store.observations(snapshot.generation_id)
            if (row.received_at - replay.epoch).total_seconds() <= snapshot.clock_seconds
        ]
        rows = [
            row
            for row in normalize_records(originals, pack)
            if row.sensor_id == sensor_id
            and snapshot.window_start <= row.observed_at < snapshot.window_end
        ]
        return {"sensor": sensor, "observations": rows}

    def submit(generation_id: str, form: QuestionForm, episode_id: str | None = None) -> object:
        replay = store.get_replay(generation_id)
        snapshot = store.get_window(form.snapshot_id)
        if snapshot.generation_id != generation_id:
            raise HTTPException(status_code=403, detail="Snapshot belongs to another replay")
        if form.mode != replay.mode:
            raise HTTPException(status_code=409, detail="Question mode must match the replay mode")
        return agent_service().submit_question(
            replay, snapshot, form.question, form.idempotency_key, episode_id=episode_id
        )

    @app.post("/api/replays/{generation_id}/questions")
    def question(generation_id: str, form: QuestionForm, request: Request) -> object:
        principal(request, write=True)
        return submit(generation_id, form)

    @app.post("/api/incidents/{episode_id}/questions")
    def incident_question(episode_id: str, form: QuestionForm, request: Request) -> object:
        principal(request, write=True)
        snapshot = store.get_window(form.snapshot_id)
        if not any(row.id == episode_id for row in store.list_episodes(snapshot.generation_id)):
            raise HTTPException(status_code=404, detail="Episode not found in this replay")
        return submit(snapshot.generation_id, form, episode_id)

    def task_detail(
        task_id: str, *, accepted_casefile_only: bool = False,
    ) -> dict[str, object]:
        """Revalidate accepted results against executed receipts before constructing a handoff."""
        from .execution_usage import summarize_usage

        task = store.get_task(task_id)
        children = [row for row in store.list_tasks(task.generation_id) if row.parent_id == task.id]
        sources = [row for row in children if row.role == "event_diagnosis"]
        if task.role == "event_diagnosis":
            sources = [task]
        for identifier in store.reuse_task_ids(task.id):
            source = store.get_task(identifier)
            if source.role == "event_diagnosis" and source.generation_id == task.generation_id:
                sources.append(source)
        history_receipts = [
            {"task_id": source.id, **receipt}
            for source in sources
            for receipt in store.tool_receipts(source.id)
            if str(receipt["name"]).startswith("history.")
        ]
        casefile: InvestigationCase | None = None
        output_mapping: object = None
        if (
            task.role == "operator_response"
            and task.response_protocol in {"engineer-v1", "engineer-v2"}
            and task.state in {"SUCCEEDED", "ABSTAINED"}
            and (
                not accepted_casefile_only or task.state == "SUCCEEDED"
                or task.interpretation_review is not None
                and task.interpretation_review.rounds[-1].assessment.decision == "accept"
            )
        ):
            if task.result is None:
                raise AgentValidationError("casefile_unavailable", "Accepted task has no result.")
            snapshot = store.get_window(task.snapshot_id)
            gateway = ToolGateway(store, task, snapshot, telemetry)
            dependencies = gateway.dependencies()
            for dependency in dependencies:
                if dependency.result is None:
                    raise AgentValidationError("casefile_sources", "Specialist has no result.")
                validate_result(
                    dependency.result,
                    dependency,
                    snapshot,
                    store.tool_receipts(dependency.id),
                    ToolGateway(store, dependency, snapshot, telemetry).dependencies(),
                )
            validate_result(
                task.result,
                task,
                snapshot,
                store.tool_receipts(task.id),
                dependencies,
            )
            casefile = build_casefile(task, snapshot, dependencies, history_receipts)
            if task.state == "SUCCEEDED" and casefile.interpretation is not None:
                output_mapping = report_labels(
                    task, generate_pack(snapshot.site_id, version=snapshot.pack_version),
                )
        return {
            "task": task,
            "children": children,
            "receipts": store.tool_receipts(task_id),
            "harness_events": store.task_harness_events(task_id),
            "investigation_receipts": history_receipts,
            "casefile": casefile,
            "output_mapping": output_mapping,
            "activity": store.public_agent_activity(task.id),
            "execution_usage": summarize_usage(
                [task, *children],
                [receipt for member in [task, *children]
                 for receipt in store.list_model_calls(member.id)],
            ),
        }

    @app.get("/api/tasks/{task_id}")
    def task_view(task_id: str, request: Request) -> dict[str, object]:
        principal(request)
        return task_detail(task_id)

    @app.get("/api/tasks/{task_id}/casefile")
    def casefile_download(task_id: str, request: Request, response: Response) -> InvestigationCase:
        principal(request)
        casefile = task_detail(task_id)["casefile"]
        if not isinstance(casefile, InvestigationCase):
            raise HTTPException(
                status_code=409, detail="No completed operator handoff for this task"
            )
        response.headers["Content-Disposition"] = (
            f'attachment; filename="investigation-{casefile.task_id}.json"'
        )
        return casefile

    @app.get("/api/tasks/{task_id}/trace")
    def trace_view(task_id: str, request: Request) -> dict[str, object]:
        principal(request)
        task = store.get_task(task_id)
        return trace_payload(task, store.latest_task_trace(task_id) or {})

    def trace_payload(task: AgentTask, metadata: Mapping[str, object]) -> dict[str, object]:
        visible: bool | None = None
        trace_id = metadata.get("trace_id")
        if task.state in ("SUCCEEDED", "ABSTAINED", "FAILED") and isinstance(trace_id, str):
            telemetry.flush()
            visible = telemetry.verify_trace(
                trace_id, required_types=["agent", "generation", "tool", "guardrail"]
            )
        return {
            "task_id": task.id,
            "root_id": task.root_id,
            "snapshot_id": task.snapshot_id,
            "mode": task.mode,
            "observability": telemetry.health(),
            "langfuse_url": telemetry.trace_url(trace_id) if isinstance(trace_id, str) else None,
            "content_capture": telemetry.content_enabled,
            "stored_trace_visible": visible,
            **metadata,
        }

    @app.get("/api/replays/{generation_id}/events")
    async def events(generation_id: str, request: Request, after: int = 0) -> StreamingResponse:
        """Stream committed events after a durable cursor; heartbeats contain no synthetic data."""
        principal(request)
        await run_in_threadpool(store.get_replay, generation_id)
        supplied = request.headers.get("Last-Event-ID")
        try:
            cursor = int(supplied) if supplied else after
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid event cursor") from exc
        if cursor < 0:
            raise HTTPException(status_code=422, detail="Event cursor must be nonnegative")

        async def stream() -> AsyncIterator[str]:
            nonlocal cursor
            newest = await run_in_threadpool(store.newest_event_id, generation_id)
            if cursor > newest:
                yield 'event: resync_required\ndata: {"reason":"cursor_unavailable"}\n\n'
                return
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                rows = await run_in_threadpool(store.events, generation_id, cursor, 100)
                for row in rows:
                    cursor = row.id
                    data = json.dumps(row.model_dump(mode="json"), separators=(",", ":"))
                    yield f"id: {row.id}\nevent: {row.type}\ndata: {data}\n\n"
                if time.monotonic() - heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    web = Path(__file__).resolve().parents[2] / "web"

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/assets/styles.css", include_in_schema=False)
    def stylesheet() -> FileResponse:
        return FileResponse(
            web / "styles.css", media_type="text/css", headers={"Cache-Control": "no-store"},
        )

    @app.get("/assets/console.js", include_in_schema=False)
    def javascript() -> FileResponse:
        asset = web / "dist" / "console.js"
        if not asset.exists():
            raise HTTPException(status_code=503, detail="Console not built; run npm run build")
        return FileResponse(
            asset, media_type="application/javascript", headers={"Cache-Control": "no-store"},
        )

    return app
