"""Local authenticated console API and durable server-sent monitoring events."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .casefile import InvestigationCase, build_casefile
from .config import Settings
from .contracts import AgentRole, Contract, Mode, WindowSnapshot, Workflow, utc_now
from .ingest import normalize_records
from .llm.copilot_cli import CopilotCLIChatModel
from .monitoring import Monitor
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
from .store import Store, StoreError
from .synthetic import CUSTOMER_QUESTIONS, SCENARIOS
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
    speed: Literal[1, 2, 5, 10] | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)


class QuestionForm(Contract):
    question: str = Field(min_length=3, max_length=2000)
    snapshot_id: str = Field(min_length=1, max_length=200)
    mode: Mode
    idempotency_key: str = Field(min_length=1, max_length=200)


class AgentWorker:
    def __init__(self, service: AgentService) -> None:
        self.service = service
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.error: str | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name="subsea-agent-worker", daemon=True)
        self.thread.start()

    def run(self) -> None:
        try:
            while not self._stop.is_set():
                if not self.service.run_once():
                    self._stop.wait(0.25)
        except Exception:
            logger.exception("Agent worker stopped after an unhandled failure")
            self.error = "agent_worker_failed"

    def close(self) -> None:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=330)
            if self.thread.is_alive():
                logger.error("Agent worker exceeded its root deadline during shutdown")


def create_app(settings: Settings, *, start_workers: bool = True) -> FastAPI:
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
            worker = AgentWorker(service)
            resources.update({"service": service, "monitor": monitor, "worker": worker})
            if start_workers:
                monitor.start()
                worker.start()
            try:
                yield
            finally:
                monitor.close()
                worker.close()
                telemetry.close()
                store.close()

    app = FastAPI(title="Subsea Integrity Copilot", lifespan=lifespan)
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

    def health() -> dict[str, object]:
        worker = resources.get("worker")
        monitor = resources.get("monitor")
        service = resources.get("service")
        provider = service.health() if isinstance(service, AgentService) else {}
        agent_status = worker.error or "running" if isinstance(worker, AgentWorker) else "starting"
        if provider.get("available") is False:
            agent_status = str(provider.get("error_code") or "agent_unavailable")
        return {
            "monitor": monitor.error or "running" if isinstance(monitor, Monitor) else "starting",
            "agent": agent_status,
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
                generation_id, form.action, form.speed, form.idempotency_key
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
                    sensor_alerts_only=True,
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

    @app.get("/api/windows/{snapshot_id}")
    def window(snapshot_id: str, request: Request) -> object:
        principal(request)
        return store.get_window(snapshot_id)

    @app.get("/api/windows/{snapshot_id}/sensors/{sensor_id}")
    def sensor_details(snapshot_id: str, sensor_id: str, request: Request) -> dict[str, object]:
        principal(request)
        snapshot = store.get_window(snapshot_id)
        pack = monitor_service().pack_for(snapshot.generation_id)
        sensor = next((row for row in pack.sensors if row.id == sensor_id), None)
        if sensor is None:
            raise HTTPException(status_code=404, detail="Sensor not found in this site")
        replay = store.get_replay(snapshot.generation_id)
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

    def task_detail(task_id: str) -> dict[str, object]:
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
        if (
            task.role == "operator_response"
            and task.response_protocol in {"engineer-v1", "engineer-v2"}
            and task.state in {"SUCCEEDED", "ABSTAINED"}
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
        return {
            "task": task,
            "children": children,
            "receipts": store.tool_receipts(task_id),
            "investigation_receipts": history_receipts,
            "casefile": casefile,
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
        metadata = store.latest_task_trace(task_id) or {}
        visible: bool | None = None
        trace_id = metadata.get("trace_id")
        if task.state in ("SUCCEEDED", "ABSTAINED") and isinstance(trace_id, str):
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
            "langfuse_url": "http://127.0.0.1:3001",
            "content_capture": False,
            "stored_trace_visible": visible,
            **metadata,
        }

    @app.get("/api/replays/{generation_id}/events")
    async def events(generation_id: str, request: Request, after: int = 0) -> StreamingResponse:
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
        return FileResponse(web / "index.html")

    @app.get("/assets/styles.css", include_in_schema=False)
    def stylesheet() -> FileResponse:
        return FileResponse(web / "styles.css", media_type="text/css")

    @app.get("/assets/console.js", include_in_schema=False)
    def javascript() -> FileResponse:
        asset = web / "dist" / "console.js"
        if not asset.exists():
            raise HTTPException(status_code=503, detail="Console not built; run npm run build")
        return FileResponse(asset, media_type="application/javascript")

    return app
