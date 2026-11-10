"""Server-owned replay and numerical monitoring, independent of hosted inference."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from .budgets import AUTOMATIC_COOLDOWN_SECONDS
from .contracts import (
    CanonicalObservation,
    Mode,
    MonitoringEpisode,
    RawRecord,
    ReplaySession,
    SitePack,
    WindowSnapshot,
    Workflow,
    content_hash,
    utc_now,
)
from .diagnostics import analyze_window
from .ingest import CanonicalBuffer, normalize_records
from .ontology import load_pack
from .replay_sources import load_frozen_replay_source
from .store import BudgetExceeded, Conflict, QueueFull, Store
from .synthetic import SOURCE_VERSION, ReplayDataset, generate_scenario
from .validation import ValidationError as AgentValidationError

if TYPE_CHECKING:
    from .runtime.workflow import AgentService
    from .telemetry import Telemetry

logger = logging.getLogger(__name__)

AUTO_QUESTION = (
    "Is this a possible leak or an instrumentation issue? Which pipeline section "
    "should an integrity engineer inspect first, and which sensors are unreliable?"
)
UNAVAILABLE_DISPATCH = frozenset(
    {"agent_unavailable", "knowledge_unavailable", "budget_blocked", "no_pressure_anomaly"}
)


def _pressure_alert_keys(snapshot: WindowSnapshot) -> list[str]:
    return sorted(
        {
            f"{finding.sensor_id}:pressure"
            for finding in snapshot.quality.findings
            if finding.anomaly_count > 0
        }
    )


def pressure_context_ready(
    snapshot: WindowSnapshot, pack: SitePack, first_alert_seconds: int, context_seconds: int = 15,
) -> bool:
    return (
        snapshot.quality.status != "WARMING_UP"
        and bool(_pressure_alert_keys(snapshot))
        and snapshot.end_seconds - first_alert_seconds >= context_seconds
    )


def instrument_signals(snapshot: WindowSnapshot, pack: SitePack) -> set[tuple[str, str]]:
    signals: set[tuple[str, str]] = set()
    for finding in snapshot.quality.findings:
        for kind, present in (
            ("invalid", finding.hard_excluded > 0),
            ("missing", finding.missing > finding.expected * 0.1),
            ("anomaly", finding.anomaly_count > 0),
        ):
            if present:
                signals.add((finding.sensor_id, kind))
    return signals


@dataclass
class SourceState:
    """Per-generation arrival cursor/cache; PostgreSQL retains durable replay truth."""

    dataset: ReplayDataset
    baseline: list[CanonicalObservation]
    received_seconds: list[float]
    buffer: CanonicalBuffer
    released: int = 0
    canonical: list[CanonicalObservation] = field(default_factory=list)
    dirty: bool = False
    anchor: float = field(default_factory=time.monotonic)
    version: int = 0
    pending_seconds: float = 0


class Monitor:
    """Advance source time and publish numerical windows independently of model calls.

    A short monitor lease coordinates processes; the local lock protects caches.
    Agent admission uses pinned window IDs rather than a moving latest-data query.
    """

    def __init__(self, store: Store, agents: AgentService, telemetry: Telemetry) -> None:
        self.store = store
        self.agents = agents
        self.telemetry = telemetry
        self.owner = "monitor-" + uuid.uuid4().hex
        self._sources: dict[str, SourceState] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._dispatch_attempts: dict[str, float] = {}
        self.error: str | None = None
        self.last_compute_seconds: float | None = None

    def _source(self, session: ReplaySession) -> SourceState:
        """Restore exact frozen inputs or regenerate a seeded source, never reinterpret archives."""
        if session.source_version != SOURCE_VERSION:
            raise Conflict(
                "Archived replay: create a new brief-aligned pressure scenario. "
                "Historical snapshots and receipts are retained, not reinterpreted."
            )
        cached = self._sources.get(session.id)
        if cached is not None:
            return cached
        dataset = load_frozen_replay_source(session)
        if dataset is None:
            dataset = generate_scenario(
                session.scenario, session.seed, session.duration_seconds, session.site_id
            )
        arrival = [
            (
                datetime.fromisoformat(row.received_at.replace("Z", "+00:00")) - dataset.epoch
            ).total_seconds()
            for row in dataset.records
        ]
        if arrival != sorted(arrival):
            raise ValueError("Synthetic source must be sorted by arrival time")
        cached = SourceState(
            dataset=dataset,
            baseline=normalize_records(dataset.baseline, dataset.pack),
            received_seconds=arrival,
            buffer=CanonicalBuffer(dataset.pack),
            version=session.version,
        )
        self._sources[session.id] = cached
        return cached

    def pack_for(self, generation_id: str) -> SitePack:
        with self._lock:
            return self._source(self.store.get_replay(generation_id)).dataset.pack

    def create(
        self,
        scenario: str,
        seed: int,
        mode: Mode,
        idempotency_key: str,
        *,
        workflow: Workflow = "agent_assisted",
        pause_on_anomaly: bool = False,
    ) -> ReplaySession:
        with self._lock:
            generation_id = (
                "replay-"
                + content_hash({"tenant": self.store.tenant_id, "key": idempotency_key})[:24]
            )
            dataset = generate_scenario(scenario, seed, 360, self.store.site_id)
            return self.store.create_replay(
                ReplaySession(
                    id=generation_id,
                    tenant_id=self.store.tenant_id,
                    site_id=self.store.site_id,
                    scenario=scenario,
                    source_version=SOURCE_VERSION,
                    seed=seed,
                    mode=mode,
                    speed=5,
                    workflow=workflow,
                    pause_on_anomaly=pause_on_anomaly,
                    investigation_context_seconds=15
                    if pause_on_anomaly and workflow == "agent_assisted" else 0,
                    investigation_context_policy="early-pressure-context-v3",
                    epoch=dataset.epoch,
                )
            )

    def control(
        self,
        generation_id: str,
        action: Literal["play", "pause", "step", "speed"],
        speed: Literal[1, 2, 5, 10, 20, 30] | None,
        idempotency_key: str,
        *,
        step_seconds: Literal[1, 2, 5, 10, 20, 30] | None = None,
    ) -> ReplaySession:
        with self._lock:
            session = self.store.get_replay(generation_id)
            source = self._source(session)
            action_hash = content_hash({"action": action, "speed": speed})
            if step_seconds is not None:
                if action != "step":
                    raise ValueError("Step seconds are only valid for a step control")
                action_hash = content_hash({
                    "action": action, "speed": speed, "step_seconds": step_seconds,
                })
            if self.store.replay_control_applied(generation_id, idempotency_key, action_hash):
                return session
            self._advance(session, source)
            session = self.store.get_replay(generation_id)
            if session.investigation_window_id and action in ("play", "step"):
                reports = [
                    task
                    for task in self.store.list_tasks(session.id)
                    if task.parent_id is None
                    and task.snapshot_id == session.investigation_window_id
                ]
                unavailable = [
                    episode
                    for episode in self.store.list_episodes(session.id)
                    if episode.current_window_id == session.investigation_window_id
                    and episode.dispatch_status in UNAVAILABLE_DISPATCH
                ]
                if (not reports and not unavailable) or any(
                    task.state not in ("SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED")
                    for task in reports
                ):
                    raise Conflict("investigation_pending: wait for the agent checks to finish")
                for episode in unavailable:
                    episode.pending_window_id = None
                    episode.dispatch_status = "continued_without_report"
                    self.store.save_episode(episode)
            if session.state in ("COMPLETED", "FAILED"):
                raise Conflict("Replay is terminal; select a scenario to create a new generation")
            if action == "step" and session.state != "PAUSED":
                raise Conflict("Pause the replay before stepping")
            if action == "speed" and speed is None:
                raise ValueError("Speed is required for speed control")
            changes: dict[str, object] = {"updated_at": utc_now()}
            target_clock: float | None = None
            if action == "play":
                changes["state"] = "PLAYING"
            elif action == "pause":
                changes["state"] = "PAUSED"
            elif action == "speed":
                changes["speed"] = speed
            else:
                target_clock = min(
                    max(
                        session.duration_seconds + source.dataset.pack.lateness_seconds,
                        source.received_seconds[-1] if source.received_seconds else 0,
                    ),
                    session.clock_seconds + (
                        step_seconds if step_seconds is not None
                        else source.dataset.pack.hop_seconds
                    ),
                )
                changes["clock_seconds"] = min(
                    target_clock, session.clock_seconds + source.dataset.pack.hop_seconds,
                )
            if action in ("play", "step"):
                changes["investigation_window_id"] = None
            updated = session.model_copy(update=changes)
            result = self.store.save_controlled_replay(
                updated,
                idempotency_key=idempotency_key,
                action_hash=action_hash,
                expected_version=session.version,
            )
            source.anchor = time.monotonic()
            source.version = result.version
            if action != "speed":
                source.pending_seconds = 0
            result = self._process(result, source)
            while (
                target_clock is not None and result.clock_seconds < target_clock
                and not result.investigation_window_id
            ):
                result = self.store.save_replay(
                    result.model_copy(update={
                        "clock_seconds": min(
                            target_clock, result.clock_seconds + source.dataset.pack.hop_seconds,
                        ),
                    }),
                    expected_version=result.version,
                )
                source.version = result.version
                result = self._process(result, source)
            return self.store.get_replay(generation_id)

    def _advance(self, session: ReplaySession, source: SourceState) -> None:
        """Convert monotonic wall-time credit to source seconds, stopping at investigation holds."""
        now = time.monotonic()
        if source.version != session.version:
            source.anchor = now
            source.version = session.version
            source.pending_seconds = 0
        elapsed = now - source.anchor
        source.anchor = now
        if session.investigation_window_id:
            source.pending_seconds = 0
            return
        if session.state == "PLAYING":
            end = max(
                session.duration_seconds + source.dataset.pack.lateness_seconds,
                source.received_seconds[-1] if source.received_seconds else 0,
            )
            source.pending_seconds += elapsed * session.speed
            for _ in range(2):
                clock = min(end, session.clock_seconds + source.pending_seconds)
                check_alarm = (
                    session.pause_on_anomaly
                    and session.workflow == "agent_assisted"
                    and session.last_endpoint < session.duration_seconds
                )
                if check_alarm:
                    clock = min(
                        clock,
                        session.last_endpoint
                        + source.dataset.pack.hop_seconds
                        + source.dataset.pack.lateness_seconds,
                    )
                # Check each hop before releasing more data; retain unused wall-time credit.
                source.pending_seconds -= clock - session.clock_seconds
                updated = session.model_copy(
                    update={
                        "clock_seconds": clock,
                        "state": "COMPLETED" if clock >= end else "PLAYING",
                        "updated_at": utc_now(),
                    }
                )
                saved = self.store.save_replay(updated, expected_version=session.version)
                source.version = saved.version
                session = self._process(saved, source)
                if session.state != "PLAYING":
                    source.pending_seconds = 0
                    break
                if not check_alarm or source.pending_seconds <= 0:
                    break
        elif session.state in ("PAUSED", "COMPLETED"):
            source.pending_seconds = 0
            self._process(session, source)

    def _release(self, session: ReplaySession, source: SourceState) -> list[CanonicalObservation]:
        """Release only arrived records and persist new rows/conflict masks incrementally."""
        previous = source.released
        while (
            source.released < len(source.received_seconds)
            and source.received_seconds[source.released] <= session.clock_seconds
        ):
            source.released += 1
        if previous == source.released:
            return []
        released: list[RawRecord] = source.dataset.records[previous : source.released]
        changed = source.buffer.ingest(released)
        source.dirty = source.dirty or bool(changed)
        self.store.save_observations(session.id, changed)
        return changed

    def _snapshot(
        self,
        session: ReplaySession,
        source: SourceState,
        endpoint: int,
        previous: WindowSnapshot | None = None,
    ) -> WindowSnapshot:
        started = time.monotonic()
        if source.dirty:
            source.canonical = source.buffer.observations()
            source.dirty = False
        with self.telemetry.span(
            "subsea.monitor.window",
            attributes={
                "tenant_id": session.tenant_id,
                "site_id": session.site_id,
                "replay_generation_id": session.id,
                "subsea.window_end_seconds": endpoint,
            },
        ):
            result = analyze_window(
                source.dataset.pack,
                source.baseline,
                source.canonical,
                generation_id=session.id,
                end_seconds=endpoint,
                clock_seconds=session.clock_seconds,
                epoch=session.epoch,
                tenant_id=session.tenant_id,
                revision=previous.revision + 1 if previous else 1,
                predecessor_id=previous.id if previous else None,
                # Models receive measured alerts, not a preselected deterministic
                # cause/inspection answer to repeat back as their own diagnosis.
                screening_only=session.workflow == "agent_assisted",
            )
        self.last_compute_seconds = time.monotonic() - started
        return result

    def _process(self, session: ReplaySession, source: SourceState) -> ReplaySession:
        """Revise affected recent windows, then complete new endpoints behind the watermark."""
        if session.investigation_window_id:
            return session
        changed = self._release(session, source)
        pack = source.dataset.pack
        # A watermark is a declared arrival allowance, not a guarantee all data
        # arrived. Later data can still create append-only revisions for 120s.
        watermark = session.clock_seconds - pack.lateness_seconds
        latest_id = session.latest_window_id
        endpoint = session.last_endpoint
        if changed and endpoint > 0:
            times = [
                (row.observed_at - session.epoch).total_seconds()
                for row in changed
                if (row.observed_at - session.epoch).total_seconds() < endpoint
            ]
            revisions = self.store.list_windows(session.id, limit=120) if times else []
            for old in reversed(revisions):
                if old.end_seconds < watermark - pack.revision_seconds:
                    continue
                if not any(
                    old.end_seconds - pack.window_seconds <= t < old.end_seconds for t in times
                ):
                    continue
                revised = self._snapshot(session, source, old.end_seconds, previous=old)
                if revised.input_hash == old.input_hash:
                    continue
                self.store.save_window(revised)
                if old.id == latest_id:
                    latest_id = revised.id
                    self._episode(session, revised)
        next_endpoint = max(pack.hop_seconds, endpoint + pack.hop_seconds)
        processed = 0
        # Bound lock hold time so accelerated catch-up cannot starve pause/control.
        while next_endpoint <= min(watermark, session.duration_seconds) and processed < 2:
            snapshot = self._snapshot(session, source, next_endpoint)
            self.store.save_window(snapshot)
            latest_id = snapshot.id
            endpoint = next_endpoint
            held = self._pause_for_investigation(session, snapshot)
            if session.workflow == "agent_assisted" and (held or not session.pause_on_anomaly):
                current = self.store.get_replay(session.id)
                self._episode(current, snapshot)
            if held:
                break
            next_endpoint += pack.hop_seconds
            processed += 1
        if latest_id != session.latest_window_id or endpoint != session.last_endpoint:
            current = self.store.get_replay(session.id)
            saved = self.store.save_replay(
                current.model_copy(
                    update={"latest_window_id": latest_id, "last_endpoint": endpoint}
                ),
                expected_version=current.version,
            )
            source.version = saved.version
            return saved
        return session

    def _pause_for_investigation(self, session: ReplaySession, snapshot: WindowSnapshot) -> bool:
        """Acquire configured post-alert context before freezing one fresh investigation window."""
        if (
            not session.pause_on_anomaly
            or session.workflow == "sensor_alerts"
            or snapshot.quality.status == "WARMING_UP"
        ):
            return False
        keys = _pressure_alert_keys(snapshot)
        current = self.store.get_replay(session.id)
        raised = set(keys) - set(current.detected_alert_keys)
        pending = current.pending_pressure_alert_seconds
        if raised and pending is None:
            pending = snapshot.end_seconds
        if not raised:
            pending = None
        ready = bool(raised) and pending is not None and (
            snapshot.end_seconds - pending >= current.investigation_context_seconds
        )
        changes: dict[str, object] = {
            "pending_pressure_alert_seconds": None if ready else pending,
        }
        if ready or not raised:
            changes["detected_alert_keys"] = keys
        if ready:
            changes.update(
                state="PAUSED",
                investigation_window_id=snapshot.id,
                latest_window_id=snapshot.id,
                last_endpoint=snapshot.end_seconds,
            )
        saved = self.store.save_replay(
            current.model_copy(update=changes), expected_version=current.version
        )
        if ready:
            self.store.publish_event(
                session.id,
                "replay.investigation_paused",
                {
                    "new_alert_count": len(raised),
                    "clock_seconds": saved.clock_seconds,
                    "reason": "New pressure anomalies with acquired context; simulation waits "
                    "for fresh agent checks",
                },
                snapshot_id=snapshot.id,
            )
        return ready

    def _episode(self, session: ReplaySession, snapshot: WindowSnapshot) -> None:
        """Group alerts and admit bounded automatic work without blocking numerical warnings."""
        if session.workflow == "sensor_alerts":
            return
        if snapshot.quality.status == "WARMING_UP":
            return
        held = session.investigation_window_id == snapshot.id
        if session.pause_on_anomaly and not held:
            return
        existing = [
            row
            for row in self.store.list_episodes(session.id)
            if row.state not in ("QUIET", "SUPERSEDED_BY_REVISION")
        ]
        episode = existing[0] if existing else None
        if episode is None and not held and not _pressure_alert_keys(snapshot):
            return
        if held:
            matching = [
                task
                for task in self.store.list_tasks(session.id)
                if task.parent_id is None and task.snapshot_id == snapshot.id
            ]
            if matching:
                if episode and episode.pending_window_id == snapshot.id:
                    episode.pending_window_id = None
                    episode.dispatch_status = "queued"
                    self.store.save_episode(episode)
                return
            if episode and episode.current_window_id == snapshot.id:
                if episode.dispatch_status in UNAVAILABLE_DISPATCH:
                    return
        material = False
        if episode is None:
            if not _pressure_alert_keys(snapshot) and not held:
                return
            episode = MonitoringEpisode(
                id="episode-" + uuid.uuid4().hex,
                tenant_id=session.tenant_id,
                site_id=session.site_id,
                generation_id=session.id,
                state="COVERAGE_LOST" if snapshot.quality.status == "COVERAGE_LOST" else "ACTIVE",
                hypothesis="insufficient_evidence",
                basis_window_id=snapshot.id,
                current_window_id=snapshot.id,
                segment_ids=[],
                first_seen_seconds=snapshot.end_seconds,
                last_qualified_seconds=snapshot.end_seconds,
            )
            material = True
        else:
            old = self.store.get_window(episode.current_window_id)
            pack = load_pack(session.site_id)
            material = (
                _pressure_alert_keys(old) != _pressure_alert_keys(snapshot)
                or instrument_signals(old, pack) != instrument_signals(snapshot, pack)
                or (
                    old.quality.status != snapshot.quality.status
                    and "COVERAGE_LOST" in (old.quality.status, snapshot.quality.status)
                )
                or (held and old.id != snapshot.id)
            )
            episode = episode.model_copy(update={"current_window_id": snapshot.id})
            if snapshot.quality.status == "COVERAGE_LOST":
                episode.state = "COVERAGE_LOST"
            elif _pressure_alert_keys(snapshot) or held:
                episode.state = "ACTIVE"
                episode.last_qualified_seconds = snapshot.end_seconds
                episode.hypothesis = "insufficient_evidence"
                episode.segment_ids = []
            elif (
                snapshot.end_seconds - episode.last_qualified_seconds
                >= pack.quiet_seconds
            ):
                episode.state = "QUIET"
            if material:
                episode.material_revision += 1
        active_roots = [
            task
            for task in self.store.list_tasks(session.id)
            if task.parent_id is None
            and task.episode_id == episode.id
            and task.state in ("QUEUED", "RUNNING", "WAITING_ON_CHILD")
        ]
        if material or held:
            episode.pending_window_id = snapshot.id
        episode = self.store.save_episode(episode)
        if episode.auto_roots == 0 and episode.pending_window_id and not active_roots:
            if (
                not held
                and episode.dispatch_status == "gathering_context"
                and not _pressure_alert_keys(snapshot)
            ):
                episode.pending_window_id = None
                episode.dispatch_status = "resolved_before_dispatch"
                self.store.save_episode(episode)
                return
            if episode.dispatch_status == "gathering_context":
                episode.pending_window_id = snapshot.id
                episode = self.store.save_episode(episode)
        if episode.pending_window_id is None or active_roots or episode.state == "QUIET":
            return
        basis = self.store.get_window(episode.pending_window_id)
        if not _pressure_alert_keys(basis):
            episode.pending_window_id = None
            episode.dispatch_status = "no_pressure_anomaly"
            self.store.save_episode(episode)
            return
        failed_provider = any(
            task.mode == "live" and task.error_code in ("proxy_auth", "proxy_quota")
            for task in self.store.list_tasks(session.id)
        )
        if session.mode == "live" and (
            failed_provider or self.agents.health().get("available") is False
        ):
            episode.dispatch_status = "agent_unavailable"
            self.store.save_episode(episode)
            return
        last_attempt = self._dispatch_attempts.get(episode.id)
        if (
            last_attempt is not None
            and time.monotonic() - last_attempt < AUTOMATIC_COOLDOWN_SECONDS
        ):
            return
        self._dispatch_attempts[episode.id] = time.monotonic()
        try:
            self.agents.submit_question(
                session,
                basis,
                AUTO_QUESTION,
                idempotency_key=f"automatic:{episode.id}:{episode.material_revision}",
                automatic=True,
                episode_id=episode.id,
            )
        except (BudgetExceeded, QueueFull) as exc:
            episode.dispatch_status = exc.code
            self.store.save_episode(episode)
        except AgentValidationError as exc:
            if exc.code == "knowledge_unavailable":
                logger.warning("Agent admission withheld: knowledge_unavailable")
                episode.dispatch_status = "knowledge_unavailable"
                self.store.save_episode(episode)
                return
            if exc.code not in ("proxy_auth", "proxy_quota"):
                raise
            episode.dispatch_status = "agent_unavailable"
            self.store.save_episode(episode)
        else:
            refreshed = next(
                row for row in self.store.list_episodes(session.id) if row.id == episode.id
            )
            refreshed.pending_window_id = None
            refreshed.dispatch_status = "queued"
            self.store.save_episode(refreshed)

    def tick(self) -> None:
        """Process only generations needing work under a renewable cross-process monitor lease."""
        with self._lock:
            pack = load_pack(self.store.site_id)
            for session in self.store.list_monitor_replays(
                SOURCE_VERSION, pack.hop_seconds, pack.lateness_seconds,
                sorted(UNAVAILABLE_DISPATCH),
            ):
                if session.investigation_window_id:
                    if self.store.acquire_monitor_lease(session.id, self.owner, ttl_seconds=10):
                        self._episode(
                            session, self.store.get_window(session.investigation_window_id)
                        )
                    continue
                caught_up = False
                if session.state != "PLAYING":
                    target = min(
                        session.duration_seconds,
                        max(
                            0,
                            int(
                                (session.clock_seconds - pack.lateness_seconds) // pack.hop_seconds
                            ),
                        )
                        * pack.hop_seconds,
                    )
                    caught_up = session.last_endpoint >= target
                if self.store.acquire_monitor_lease(session.id, self.owner, ttl_seconds=10):
                    if not caught_up:
                        self._advance(session, self._source(session))
                    if session.workflow == "agent_assisted" and not session.pause_on_anomaly:
                        pending = any(
                            row.pending_window_id is not None
                            for row in self.store.list_episodes(session.id)
                        )
                        if pending:
                            current = self.store.get_replay(session.id)
                            if current.latest_window_id:
                                self._episode(
                                    current, self.store.get_window(current.latest_window_id),
                                )

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=self.owner, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                self.tick()
                self._stop.wait(max(0.01, 0.1 - (time.monotonic() - started)))
        except Exception:
            logger.exception("Monitoring worker stopped after an unhandled failure")
            self.error = "monitor_worker_failed"

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        for generation_id in self._sources:
            self.store.release_monitor_lease(generation_id, self.owner)
