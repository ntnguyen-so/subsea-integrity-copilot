"""PostgreSQL persistence with scoped transactions, immutable evidence and fenced work.

Business state lives in ``subsea``; graph checkpoints belong exclusively to
``subsea_checkpoint``. Events are append-only and retained, so reconnect cursors
remain usable for the lifetime of a generation. No SQL transaction spans inference.
CLI-only qualification permits nine cohort manual roots and one separately identified
single-agent baseline per generation, instead of the interactive three-per-minute
throttle; all other budgets remain unchanged.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import JsonValue

from .contracts import (
    AgentTask,
    CanonicalObservation,
    ConsoleEvent,
    Contract,
    MonitoringEpisode,
    ReplaySession,
    WindowSnapshot,
    content_hash,
    utc_now,
)

T = TypeVar("T", bound=Contract)
TERMINAL = frozenset({"SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"})


def history_search_query(query: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", query)
    return " OR ".join(
        dict.fromkeys(word for word in words if word.upper() not in {"AND", "OR", "NOT"})
    )


class StoreError(RuntimeError):
    code = "store_error"

    def __init__(self, code: str | None = None, message: str | None = None) -> None:
        if code:
            self.code = code
        super().__init__(message or self.code)


class NotFound(StoreError):
    code = "not_found"

    def __init__(self, message: str = "Not found in active scope") -> None:
        super().__init__(self.code, message)


class ScopeError(StoreError):
    code = "forbidden"

    def __init__(self, message: str = "Forbidden scope") -> None:
        super().__init__(self.code, message)


class Conflict(StoreError):
    code = "conflict"

    def __init__(self, reason: str = "conflict") -> None:
        self.reason = reason
        super().__init__(self.code, reason)


class BudgetExceeded(Conflict):
    def __init__(self, message: str = "Persisted work budget exhausted") -> None:
        StoreError.__init__(self, "budget_blocked", message)


class QueueFull(Conflict):
    def __init__(self, message: str = "Root queue is full") -> None:
        StoreError.__init__(self, "queue_full", message)


def migrate(
    admin_dsn: str, app_password: str, tools_password: str, checkpoint_password: str
) -> None:
    """Install/reapply the PostgreSQL 16 schema; passwords never enter logs or SQL files."""
    if not all((app_password, tools_password, checkpoint_password)):
        raise ValueError("All database role passwords are required")
    with psycopg.connect(admin_dsn, autocommit=False) as conn:
        if conn.info.server_version < 160000:
            raise StoreError("database_version", "PostgreSQL 16 or newer is required")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('subsea:migrate',0))")
        for role, password in (
            ("subsea_app", app_password),
            ("subsea_tools_ro", tools_password),
            ("subsea_checkpoint", checkpoint_password),
        ):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
            conn.execute(
                sql.SQL(
                    "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            # Remove inherited authority if an existing installation was misconfigured.
            memberships = conn.execute(
                "SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid "
                "JOIN pg_roles member ON member.oid=m.member WHERE member.rolname=%s",
                (role,),
            ).fetchall()
            for membership in memberships:
                conn.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(membership[0]), sql.Identifier(role)
                    )
                )
            path = (
                "subsea_checkpoint, pg_catalog"
                if role == "subsea_checkpoint"
                else ("pg_catalog, subsea")
            )
            conn.execute(
                sql.SQL("ALTER ROLE {} SET search_path TO {}").format(
                    sql.Identifier(role), sql.SQL(path)
                )
            )
        for migration in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
            conn.execute(migration.read_text(encoding="utf-8"))


class Store:
    def __init__(
        self,
        dsn: str,
        tenant_id: str = "demo",
        site_id: str = "northsea",
        tools_dsn: str | None = None,
        *,
        qualification: bool = False,
    ) -> None:
        if not tenant_id or not site_id or max(len(tenant_id), len(site_id)) > 200:
            raise ScopeError("A bounded tenant and site are required")
        self.tenant_id = tenant_id
        self.site_id = site_id
        self.qualification = qualification
        self._pool: ConnectionPool[psycopg.Connection[dict[str, Any]]] = ConnectionPool(
            dsn,
            min_size=1,
            max_size=8,
            open=True,
            kwargs={"row_factory": dict_row, "autocommit": False},
        )
        self._tools_pool: ConnectionPool[psycopg.Connection[dict[str, Any]]] | None = (
            ConnectionPool(
                tools_dsn,
                min_size=1,
                max_size=4,
                open=True,
                kwargs={"row_factory": dict_row, "autocommit": False},
            )
            if tools_dsn
            else None
        )

    def close(self) -> None:
        self._pool.close()
        if self._tools_pool:
            self._tools_pool.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @contextmanager
    def _tx(
        self,
        *,
        read: bool = False,
        token: str | None = None,
        action: str = "",
        repeatable: bool = False,
    ) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        pool = self._tools_pool if read and self._tools_pool else self._pool
        try:
            with pool.connection() as conn, conn.transaction():
                if repeatable:
                    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                if read:
                    conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SET LOCAL search_path = pg_catalog, subsea")
                conn.execute("SET LOCAL lock_timeout = '5s'")
                conn.execute("SET LOCAL statement_timeout = '15s'")
                conn.execute(
                    "SELECT set_config('subsea.tenant_id',%s,true),"
                    "set_config('subsea.site_id',%s,true),"
                    "set_config('subsea.lease_token',%s,true),"
                    "set_config('subsea.action',%s,true),"
                    "set_config('subsea.qualification',%s,true)",
                    (
                        self.tenant_id,
                        self.site_id,
                        token or "",
                        action,
                        "true" if self.qualification else "false",
                    ),
                )
                yield conn
        except psycopg.errors.RaiseException as exc:
            code = exc.diag.message_primary or "conflict"
            if code == "scope_error":
                raise ScopeError(code) from exc
            if code == "budget_blocked":
                raise BudgetExceeded() from exc
            if code == "queue_full":
                raise QueueFull() from exc
            raise Conflict(code) from exc
        except psycopg.errors.UniqueViolation as exc:
            raise Conflict("identity_conflict") from exc
        except (psycopg.errors.ForeignKeyViolation, psycopg.errors.InsufficientPrivilege) as exc:
            raise ScopeError("scope_error") from exc

    def _scope(self, value: Contract) -> None:
        if (getattr(value, "tenant_id", None), getattr(value, "site_id", None)) != (
            self.tenant_id,
            self.site_id,
        ):
            raise ScopeError("scope_error")

    def _get(
        self,
        conn: psycopg.Connection[dict[str, Any]],
        table: str,
        id: str,
        cls: type[T],
        *,
        lock: bool = False,
    ) -> T:
        row = conn.execute(
            sql.SQL("SELECT payload FROM subsea.{} WHERE id=%s {}").format(
                sql.Identifier(table), sql.SQL("FOR UPDATE" if lock else "")
            ),
            (id,),
        ).fetchone()
        if not row:
            raise NotFound(f"{table}: not found in active scope")
        return cls.model_validate(row["payload"])

    def _generation(
        self, conn: psycopg.Connection[dict[str, Any]], generation_id: str
    ) -> ReplaySession:
        # Serialize all generation writes, including event identity allocation, for
        # commit-ordered cursors (sequence allocation alone is not commit ordered).
        return self._get(conn, "replays", generation_id, ReplaySession, lock=True)

    def _event(
        self,
        conn: psycopg.Connection[dict[str, Any]],
        generation_id: str,
        type: str,
        payload: dict[str, JsonValue],
        snapshot_id: str | None = None,
        task_id: str | None = None,
        simulated_seconds: float | None = None,
    ) -> ConsoleEvent:
        if snapshot_id:
            window = self._get(conn, "windows", snapshot_id, WindowSnapshot)
            if window.generation_id != generation_id:
                raise ScopeError("scope_error")
        if task_id:
            task = self._get(conn, "tasks", task_id, AgentTask)
            if task.generation_id != generation_id:
                raise ScopeError("scope_error")
        row = conn.execute(
            "INSERT INTO subsea.events "
            "(tenant_id,site_id,generation_id,type,payload,snapshot_id,task_id,simulated_seconds)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                self.tenant_id,
                self.site_id,
                generation_id,
                type,
                Jsonb(payload),
                snapshot_id,
                task_id,
                simulated_seconds,
            ),
        ).fetchone()
        assert row
        return ConsoleEvent.model_validate(row)

    def create_replay(self, session: ReplaySession) -> ReplaySession:
        self._scope(session)
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO subsea.replays (tenant_id,site_id,id,payload,version)"
                " VALUES (%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    self.site_id,
                    session.id,
                    Jsonb(session.model_dump(mode="json")),
                    session.version,
                ),
            )
            self._event(conn, session.id, "replay.state", session.model_dump(mode="json"))
        return session

    def get_replay(self, id: str) -> ReplaySession:
        with self._tx(read=True) as conn:
            return self._get(conn, "replays", id, ReplaySession)

    def list_replays(self) -> list[ReplaySession]:
        with self._tx(read=True) as conn:
            return [
                ReplaySession.model_validate(row["payload"])
                for row in conn.execute("SELECT payload FROM subsea.replays ORDER BY id")
            ]

    def save_replay(
        self, session: ReplaySession, expected_version: int | None = None
    ) -> ReplaySession:
        self._scope(session)
        with self._tx() as conn:
            previous = self._generation(conn, session.id)
            if previous.version != (
                session.version if expected_version is None else expected_version
            ):
                raise Conflict("version_conflict")
            if (
                previous.scenario,
                previous.seed,
                previous.epoch,
                previous.created_at,
                previous.duration_seconds,
                previous.mode,
            ) != (
                session.scenario,
                session.seed,
                session.epoch,
                session.created_at,
                session.duration_seconds,
                session.mode,
            ):
                raise Conflict("generation_identity_conflict")
            if session.latest_window_id:
                window = self._get(conn, "windows", session.latest_window_id, WindowSnapshot)
                if window.generation_id != session.id:
                    raise ScopeError("scope_error")
            saved = session.model_copy(
                update={"version": previous.version + 1, "updated_at": utc_now()}
            )
            conn.execute(
                "UPDATE subsea.replays SET payload=%s,version=%s WHERE id=%s",
                (Jsonb(saved.model_dump(mode="json")), saved.version, saved.id),
            )
            self._event(conn, saved.id, "replay.state", saved.model_dump(mode="json"))
        return saved

    def save_controlled_replay(
        self,
        session: ReplaySession,
        idempotency_key: str,
        action_hash: str,
        expected_version: int,
    ) -> ReplaySession:
        self._scope(session)
        if not idempotency_key or not action_hash or len(idempotency_key) > 200:
            raise ValueError("Bounded control identity and action hash are required")
        with self._tx() as conn:
            previous = self._generation(conn, session.id)
            existing = conn.execute(
                "SELECT action_hash,payload FROM subsea.control_requests "
                "WHERE generation_id=%s AND idempotency_key=%s",
                (session.id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["action_hash"] != action_hash:
                    raise Conflict("idempotency_conflict")
                return ReplaySession.model_validate(existing["payload"])
            if previous.version != expected_version:
                raise Conflict("version_conflict")
            for field in ("scenario", "seed", "epoch", "created_at", "duration_seconds", "mode"):
                if getattr(previous, field) != getattr(session, field):
                    raise Conflict("generation_identity_conflict")
            if session.latest_window_id:
                window = self._get(conn, "windows", session.latest_window_id, WindowSnapshot)
                if window.generation_id != session.id:
                    raise ScopeError("scope_error")
            saved = session.model_copy(
                update={
                    "version": previous.version + 1,
                    "updated_at": utc_now(),
                }
            )
            conn.execute(
                "UPDATE subsea.replays SET payload=%s,version=%s WHERE id=%s",
                (Jsonb(saved.model_dump(mode="json")), saved.version, saved.id),
            )
            conn.execute(
                "INSERT INTO subsea.control_requests "
                "(tenant_id,site_id,generation_id,idempotency_key,action_hash,payload) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    self.site_id,
                    session.id,
                    idempotency_key,
                    action_hash,
                    Jsonb(saved.model_dump(mode="json")),
                ),
            )
            self._event(conn, saved.id, "replay.state", saved.model_dump(mode="json"))
            return saved

    def save_observations(
        self, generation_id: str, records: Sequence[CanonicalObservation]
    ) -> None:
        """Append bounded committed chunks; an interrupted call is safe to retry."""
        rows: list[dict[str, JsonValue]] = []
        for record in records:
            payload = record.model_dump(mode="json")
            rows.append(
                {
                    "identity": record.identity,
                    "raw_hash": content_hash(record.original.model_dump(mode="json")),
                    "payload_hash": content_hash(payload),
                    "observed_at": payload["observed_at"],
                    "payload": payload,
                }
            )
        # A catch-up batch can contain an entire replay. Preparation must not hold
        # the generation fence, and ingestion must not add a round trip per record.
        if not rows:
            with self._tx() as conn:
                self._generation(conn, generation_id)
            return
        for offset in range(0, len(rows), 512):
            encoded = json.dumps(
                rows[offset : offset + 512],
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            with self._tx() as conn:
                self._generation(conn, generation_id)
                conn.execute(
                    "INSERT INTO subsea.observations "
                    "(tenant_id,site_id,generation_id,identity,raw_hash,payload_hash,"
                    "observed_at,payload) SELECT %s,%s,%s,identity,raw_hash,payload_hash,"
                    "observed_at,payload FROM jsonb_to_recordset(%s::jsonb) AS incoming("
                    "identity text,raw_hash text,payload_hash text,observed_at timestamptz,"
                    "payload jsonb)"
                    " ON CONFLICT DO NOTHING",
                    (self.tenant_id, self.site_id, generation_id, encoded),
                )

    def observations(
        self, generation_id: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[CanonicalObservation]:
        with self._tx(read=True) as conn:
            self._get(conn, "replays", generation_id, ReplaySession)
            rows = conn.execute(
                "WITH originals AS ("
                " SELECT DISTINCT ON (identity,raw_hash) identity,raw_hash,payload,observed_at "
                " FROM subsea.observations WHERE generation_id=%s "
                " ORDER BY identity,raw_hash,ordinal DESC"
                "), marked AS (SELECT *,count(*) OVER (PARTITION BY identity) AS variants "
                " FROM originals) SELECT * FROM marked "
                "WHERE (%s::timestamptz IS NULL OR observed_at >= %s) "
                "AND (%s::timestamptz IS NULL OR observed_at < %s)",
                (generation_id, start, start, end, end),
            ).fetchall()
            result = []
            for row in rows:
                record = CanonicalObservation.model_validate(row["payload"])
                if row["variants"] > 1:
                    record = record.model_copy(update={"validity": "conflicted", "value": None})
                result.append(record)
            return sorted(result, key=lambda item: (item.observed_at, item.identity, item.id))

    def install_history(self, documents: list[dict[str, Any]]) -> str:
        ordered = sorted(documents, key=lambda row: row["id"])
        encoded_documents: list[JsonValue] = list(ordered)
        version = content_hash(encoded_documents)
        with self._tx() as conn:
            for document in documents:
                conn.execute(
                    "INSERT INTO subsea.history_documents "
                    "(tenant_id,site_id,corpus_version,id,available_at,authored_at,"
                    "effective_from,asset_ids,scenarios,payload) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        self.tenant_id,
                        self.site_id,
                        version,
                        document["id"],
                        document["available_at"],
                        document["authored_at"],
                        document["effective_from"],
                        document["asset_ids"],
                        document["scenarios"],
                        Jsonb(document),
                    ),
                )
                retained = conn.execute(
                    "SELECT payload FROM subsea.history_documents "
                    "WHERE corpus_version=%s AND id=%s",
                    (version, document["id"]),
                ).fetchone()
                if retained is None or retained["payload"] != document:
                    raise Conflict("immutable_history")
        return version

    def history_documents(
        self,
        generation_id: str,
        version: str,
        as_of: datetime,
        *,
        query: str | None = None,
        assets: list[str] | None = None,
        ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query = history_search_query(query) if query is not None else None
        with self._tx(read=True) as conn:
            replay = self._get(conn, "replays", generation_id, ReplaySession)
            rows = conn.execute(
                "SELECT payload FROM subsea.history_documents "
                "WHERE corpus_version=%s AND available_at<=%s AND authored_at<=%s "
                "AND effective_from<=%s AND (cardinality(scenarios)=0 OR %s=ANY(scenarios)) "
                "AND (%s::text[] IS NULL OR asset_ids && %s::text[]) "
                "AND (%s::text[] IS NULL OR id=ANY(%s::text[])) "
                "AND (%s::text IS NULL OR search_vector @@ websearch_to_tsquery('english',%s)) "
                "ORDER BY (payload->>'status'='approved') DESC, "
                "ts_rank(search_vector,websearch_to_tsquery('english',coalesce(%s,''))) DESC, "
                "effective_from DESC,id LIMIT 6",
                (
                    version,
                    as_of,
                    as_of,
                    as_of,
                    replay.scenario,
                    assets,
                    assets,
                    ids,
                    ids,
                    query,
                    query,
                    query,
                ),
            ).fetchall()
            return [row["payload"] for row in rows]

    def save_window(self, snapshot: WindowSnapshot) -> WindowSnapshot:
        self._scope(snapshot)
        with self._tx() as conn:
            self._generation(conn, snapshot.generation_id)
            old = conn.execute(
                "SELECT payload FROM subsea.windows WHERE id=%s", (snapshot.id,)
            ).fetchone()
            if old:
                if old["payload"] != snapshot.model_dump(mode="json"):
                    raise Conflict("immutable_evidence")
                return WindowSnapshot.model_validate(old["payload"])
            if snapshot.predecessor_id:
                prior = self._get(conn, "windows", snapshot.predecessor_id, WindowSnapshot)
                if (
                    prior.generation_id,
                    prior.end_seconds,
                    prior.revision + 1,
                    prior.window_start,
                    prior.window_end,
                ) != (
                    snapshot.generation_id,
                    snapshot.end_seconds,
                    snapshot.revision,
                    snapshot.window_start,
                    snapshot.window_end,
                ):
                    raise Conflict("revision_conflict")
            elif snapshot.revision != 1:
                raise Conflict("revision_conflict")
            conn.execute(
                "INSERT INTO subsea.windows "
                "(tenant_id,site_id,id,generation_id,end_seconds,revision,predecessor_id,payload)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    self.site_id,
                    snapshot.id,
                    snapshot.generation_id,
                    snapshot.end_seconds,
                    snapshot.revision,
                    snapshot.predecessor_id,
                    Jsonb(snapshot.model_dump(mode="json")),
                ),
            )
            self._event(
                conn,
                snapshot.generation_id,
                "window.revised" if snapshot.predecessor_id else "window.completed",
                {"window_id": snapshot.id, "revision": snapshot.revision},
                snapshot_id=snapshot.id,
                simulated_seconds=snapshot.clock_seconds,
            )
        return snapshot

    def get_window(self, id: str) -> WindowSnapshot:
        with self._tx(read=True) as conn:
            return self._get(conn, "windows", id, WindowSnapshot)

    def list_windows(self, generation_id: str, limit: int = 120) -> list[WindowSnapshot]:
        with self._tx(read=True) as conn:
            self._get(conn, "replays", generation_id, ReplaySession)
            return [
                WindowSnapshot.model_validate(row["payload"])
                for row in conn.execute(
                    "SELECT DISTINCT ON (end_seconds) payload FROM subsea.windows "
                    "WHERE generation_id=%s ORDER BY end_seconds DESC,revision DESC LIMIT %s",
                    (generation_id, max(0, min(limit, 1000))),
                )
            ]

    def save_episode(self, episode: MonitoringEpisode) -> MonitoringEpisode:
        self._scope(episode)
        with self._tx() as conn:
            self._generation(conn, episode.generation_id)
            for id in (
                episode.basis_window_id,
                episode.current_window_id,
                episode.pending_window_id,
            ):
                if id and self._get(conn, "windows", id, WindowSnapshot).generation_id != (
                    episode.generation_id
                ):
                    raise ScopeError("scope_error")
            previous = conn.execute(
                "SELECT payload FROM subsea.episodes WHERE id=%s", (episode.id,)
            ).fetchone()
            if previous and previous["payload"]["generation_id"] != episode.generation_id:
                raise ScopeError("scope_error")
            if previous and previous["payload"]["basis_window_id"] != episode.basis_window_id:
                raise Conflict("episode_basis_conflict")
            count = conn.execute(
                "SELECT count(*) AS n FROM subsea.tasks WHERE episode_id=%s "
                "AND parent_id IS NULL AND automatic",
                (episode.id,),
            ).fetchone()
            assert count
            episode = episode.model_copy(update={"auto_roots": int(count["n"])})
            conn.execute(
                "INSERT INTO subsea.episodes (tenant_id,site_id,id,generation_id,payload)"
                " VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,site_id,id)"
                " DO UPDATE SET payload=excluded.payload",
                (
                    self.tenant_id,
                    self.site_id,
                    episode.id,
                    episode.generation_id,
                    Jsonb(episode.model_dump(mode="json")),
                ),
            )
            self._event(
                conn,
                episode.generation_id,
                "episode.changed",
                episode.model_dump(mode="json"),
                snapshot_id=episode.current_window_id,
            )
        return episode

    def list_episodes(self, generation_id: str) -> list[MonitoringEpisode]:
        with self._tx(read=True) as conn:
            self._get(conn, "replays", generation_id, ReplaySession)
            return [
                MonitoringEpisode.model_validate(row["payload"])
                for row in conn.execute(
                    "SELECT payload FROM subsea.episodes WHERE generation_id=%s ORDER BY id",
                    (generation_id,),
                )
            ]

    def events(self, generation_id: str, after: int = 0, limit: int = 100) -> list[ConsoleEvent]:
        with self._tx(read=True) as conn:
            self._get(conn, "replays", generation_id, ReplaySession)
            return [
                ConsoleEvent.model_validate(row)
                for row in conn.execute(
                    "SELECT * FROM subsea.events WHERE generation_id=%s AND id>%s "
                    "ORDER BY id LIMIT %s",
                    (generation_id, after, max(0, min(limit, 1000))),
                )
            ]

    def publish_event(
        self,
        generation_id: str,
        type: str,
        payload: dict[str, JsonValue],
        snapshot_id: str | None = None,
        task_id: str | None = None,
        simulated_seconds: float | None = None,
    ) -> ConsoleEvent:
        with self._tx() as conn:
            self._generation(conn, generation_id)
            return self._event(
                conn, generation_id, type, payload, snapshot_id, task_id, simulated_seconds
            )

    def newest_event_id(self, generation_id: str) -> int:
        with self._tx(read=True) as conn:
            self._get(conn, "replays", generation_id, ReplaySession)
            row = conn.execute(
                "SELECT coalesce(max(id),0) AS id FROM subsea.events WHERE generation_id=%s",
                (generation_id,),
            ).fetchone()
            assert row
            return int(row["id"])

    def get_projection(self, generation_id: str) -> dict[str, JsonValue]:
        with self._tx(read=True, repeatable=True) as conn:
            replay = self._get(conn, "replays", generation_id, ReplaySession)
            latest = (
                self._get(conn, "windows", replay.latest_window_id, WindowSnapshot)
                if replay.latest_window_id
                else None
            )
            episodes = conn.execute(
                "SELECT payload FROM subsea.episodes WHERE generation_id=%s ORDER BY id",
                (generation_id,),
            ).fetchall()
            tasks = conn.execute(
                "SELECT payload FROM subsea.tasks WHERE generation_id=%s ORDER BY created_at,id",
                (generation_id,),
            ).fetchall()
            cursor = conn.execute(
                "SELECT coalesce(max(id),0) AS id FROM subsea.events WHERE generation_id=%s",
                (generation_id,),
            ).fetchone()
            assert cursor
            return {
                "replay": replay.model_dump(mode="json"),
                "latest_window": latest.model_dump(mode="json") if latest else None,
                "episodes": [row["payload"] for row in episodes],
                "tasks": [row["payload"] for row in tasks],
                "cursor": int(cursor["id"]),
            }

    def acquire_monitor_lease(self, generation_id: str, owner: str, ttl_seconds: int = 10) -> bool:
        if not owner or ttl_seconds <= 0:
            raise ValueError("A lease owner and positive TTL are required")
        with self._tx() as conn:
            self._generation(conn, generation_id)
            return (
                conn.execute(
                    "INSERT INTO subsea.monitor_leases "
                    "(tenant_id,site_id,generation_id,owner,expires_at)"
                    " VALUES (%s,%s,%s,%s,clock_timestamp()+%s*interval '1 second')"
                    " ON CONFLICT (tenant_id,site_id,generation_id) DO UPDATE "
                    "SET owner=excluded.owner,expires_at=excluded.expires_at "
                    "WHERE monitor_leases.owner=excluded.owner "
                    "OR monitor_leases.expires_at<=clock_timestamp() RETURNING owner",
                    (self.tenant_id, self.site_id, generation_id, owner, ttl_seconds),
                ).fetchone()
                is not None
            )

    def release_monitor_lease(self, generation_id: str, owner: str) -> None:
        with self._tx() as conn:
            self._generation(conn, generation_id)
            conn.execute(
                "DELETE FROM subsea.monitor_leases WHERE generation_id=%s AND owner=%s",
                (generation_id, owner),
            )

    def _insert_task(
        self,
        conn: psycopg.Connection[dict[str, Any]],
        task: AgentTask,
        *,
        operator_id: str = "local",
        step_index: int | None = None,
        plan_revision: int | None = None,
    ) -> AgentTask:
        data = task.model_dump(mode="json")
        conn.execute(
            "INSERT INTO subsea.tasks "
            "(tenant_id,site_id,id,generation_id,root_id,parent_id,snapshot_id,episode_id,"
            "role,state,version,lease_token,lease_expires_at,deadline,model_calls,tool_calls,"
            "automatic,operator_id,idempotency_key,step_index,plan_revision,initial_payload,payload)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.tenant_id,
                self.site_id,
                task.id,
                task.generation_id,
                task.root_id,
                task.parent_id,
                task.snapshot_id,
                task.episode_id,
                task.role,
                task.state,
                task.version,
                task.lease_token,
                task.lease_expires_at,
                task.deadline,
                task.model_calls,
                task.tool_calls,
                task.automatic,
                operator_id,
                task.idempotency_key,
                step_index,
                plan_revision,
                Jsonb(data),
                Jsonb(data),
            ),
        )
        self._event(
            conn,
            task.generation_id,
            "task.queued",
            data,
            task_id=task.id,
            snapshot_id=task.snapshot_id,
        )
        return task

    @staticmethod
    def _compatible(existing: dict[str, Any], proposed: AgentTask) -> bool:
        # Retry identity may use a fresh generated ID/timestamps; all execution inputs
        # (including question, role, mode and pinned evidence) must remain identical.
        ignored = {"id", "root_id", "created_at", "updated_at", "deadline"}
        current = proposed.model_dump(mode="json", exclude=ignored)
        previous = {key: value for key, value in existing.items() if key not in ignored}
        return previous == current

    def create_task(self, task: AgentTask, *, operator_id: str = "local") -> AgentTask:
        self._scope(task)
        if task.parent_id is not None:
            raise Conflict("use_create_child")
        if not operator_id or len(operator_id) > 200:
            raise ValueError("A bounded operator identity is required")
        with self._tx() as conn:
            self._generation(conn, task.generation_id)
            existing = conn.execute(
                "SELECT initial_payload,payload FROM subsea.tasks "
                "WHERE generation_id=%s AND (id=%s OR "
                "(idempotency_key IS NOT NULL AND idempotency_key=%s))",
                (task.generation_id, task.id, task.idempotency_key),
            ).fetchone()
            if existing:
                if not self._compatible(existing["initial_payload"], task):
                    raise Conflict("idempotency_conflict")
                return AgentTask.model_validate(existing["payload"])
            saved = self._insert_task(conn, task, operator_id=operator_id)
            if task.automatic and task.episode_id:
                episode = self._get(conn, "episodes", task.episode_id, MonitoringEpisode)
                episode = episode.model_copy(update={"auto_roots": episode.auto_roots + 1})
                conn.execute(
                    "UPDATE subsea.episodes SET payload=%s WHERE id=%s",
                    (Jsonb(episode.model_dump(mode="json")), episode.id),
                )
                self._event(
                    conn,
                    task.generation_id,
                    "episode.changed",
                    episode.model_dump(mode="json"),
                    snapshot_id=task.snapshot_id,
                )
            return saved

    def get_task(self, id: str) -> AgentTask:
        with self._tx(read=True) as conn:
            return self._get(conn, "tasks", id, AgentTask)

    def list_tasks(self, generation_id: str) -> list[AgentTask]:
        with self._tx(read=True) as conn:
            self._get(conn, "replays", generation_id, ReplaySession)
            rows = conn.execute(
                "SELECT payload FROM subsea.tasks WHERE generation_id=%s ORDER BY created_at,id",
                (generation_id,),
            )
            return [AgentTask.model_validate(row["payload"]) for row in rows]

    def _update_task(self, conn: psycopg.Connection[dict[str, Any]], task: AgentTask) -> AgentTask:
        saved = task.model_copy(update={"version": task.version + 1, "updated_at": utc_now()})
        conn.execute(
            "UPDATE subsea.tasks SET payload=%s,state=%s,version=%s,lease_token=%s,"
            "lease_expires_at=%s,model_calls=%s,tool_calls=%s WHERE id=%s",
            (
                Jsonb(saved.model_dump(mode="json")),
                saved.state,
                saved.version,
                saved.lease_token,
                saved.lease_expires_at,
                saved.model_calls,
                saved.tool_calls,
                saved.id,
            ),
        )
        return saved

    def _live_task(
        self,
        conn: psycopg.Connection[dict[str, Any]],
        task_id: str,
        token: str | None,
        *,
        allow_waiting: bool = False,
    ) -> AgentTask:
        task = self._get(conn, "tasks", task_id, AgentTask, lock=True)
        now = conn.execute("SELECT clock_timestamp() AS now").fetchone()
        assert now
        allowed_states = {"RUNNING", "WAITING_ON_CHILD"} if allow_waiting else {"RUNNING"}
        if (
            not token
            or token != task.lease_token
            or task.state not in allowed_states
            or not task.lease_expires_at
            or task.lease_expires_at <= now["now"]
            or task.deadline <= now["now"]
        ):
            raise Conflict("stale_lease")
        return task

    def save_task(
        self,
        task: AgentTask,
        expected_version: int | None = None,
        lease_token: str | None = None,
    ) -> AgentTask:
        self._scope(task)
        with self._tx(token=lease_token or task.lease_token) as conn:
            self._generation(conn, task.generation_id)
            old = self._get(conn, "tasks", task.id, AgentTask, lock=True)
            if old.version != (task.version if expected_version is None else expected_version):
                raise Conflict("version_conflict")
            for field in (
                "root_id",
                "parent_id",
                "generation_id",
                "snapshot_id",
                "episode_id",
                "role",
                "mode",
                "question",
                "purpose",
                "deadline",
                "created_at",
                "automatic",
                "idempotency_key",
                "history_version",
                "response_protocol",
                "model_calls",
                "tool_calls",
                "lease_token",
                "lease_expires_at",
            ):
                if getattr(old, field) != getattr(task, field):
                    raise Conflict("task_identity_conflict")
            saved = self._update_task(conn, task.model_copy(update={"version": old.version}))
            if saved.state == "WAITING_ON_CHILD":
                children = conn.execute(
                    "SELECT state FROM subsea.tasks WHERE parent_id=%s", (saved.id,)
                ).fetchall()
                if not children:
                    raise Conflict("child_required")
                if all(child["state"] in TERMINAL for child in children):
                    conn.execute("SELECT set_config('subsea.action','resume',true)")
                    saved = self._update_task(
                        conn,
                        saved.model_copy(
                            update={
                                "state": "QUEUED",
                                "lease_token": None,
                                "lease_expires_at": None,
                            }
                        ),
                    )
                self._event(
                    conn,
                    task.generation_id,
                    "task.queued" if saved.state == "QUEUED" else "task.waiting",
                    saved.model_dump(mode="json"),
                    task_id=task.id,
                    snapshot_id=task.snapshot_id,
                )
            if saved.state in TERMINAL:
                self._event(
                    conn,
                    task.generation_id,
                    "task.finished",
                    saved.model_dump(mode="json"),
                    task_id=task.id,
                    snapshot_id=task.snapshot_id,
                )
                if task.parent_id:
                    parent = self._get(conn, "tasks", task.parent_id, AgentTask, lock=True)
                    unfinished = conn.execute(
                        "SELECT 1 FROM subsea.tasks WHERE parent_id=%s "
                        "AND state NOT IN ('SUCCEEDED','ABSTAINED','FAILED','CANCELLED') LIMIT 1",
                        (parent.id,),
                    ).fetchone()
                    if parent.state == "WAITING_ON_CHILD" and not unfinished:
                        conn.execute("SELECT set_config('subsea.action','resume',true)")
                        self._update_task(
                            conn,
                            parent.model_copy(
                                update={
                                    "state": "QUEUED",
                                    "lease_token": None,
                                    "lease_expires_at": None,
                                }
                            ),
                        )
            return saved

    def claim_task(
        self, owner: str, ttl_seconds: int = 360, *, task_id: str | None = None
    ) -> AgentTask | None:
        if not owner or ttl_seconds <= 0:
            raise ValueError("A lease owner and positive TTL are required")
        with self._tx(action="claim") as conn:
            if task_id is not None:
                self._get(conn, "tasks", task_id, AgentTask)
            # Acquire generation locks before task locks, matching every writer.
            generations = conn.execute(
                "SELECT DISTINCT generation_id FROM subsea.tasks "
                "WHERE state IN ('QUEUED','RUNNING','WAITING_ON_CHILD') "
                "AND (%s::text IS NULL OR id=%s) ORDER BY generation_id",
                (task_id, task_id),
            ).fetchall()
            for generation in generations:
                self._generation(conn, generation["generation_id"])
            expired = conn.execute(
                "SELECT payload FROM subsea.tasks "
                "WHERE state IN ('QUEUED','RUNNING','WAITING_ON_CHILD') "
                "AND deadline <= clock_timestamp() AND (%s::text IS NULL OR id=%s) FOR UPDATE",
                (task_id, task_id),
            ).fetchall()
            for row in expired:
                task = AgentTask.model_validate(row["payload"])
                failed = self._update_task(
                    conn,
                    task.model_copy(
                        update={
                            "state": "FAILED",
                            "error_code": "deadline_exceeded",
                            "error_message": "Root workflow deadline exceeded",
                            "lease_token": None,
                            "lease_expires_at": None,
                        }
                    ),
                )
                self._event(
                    conn,
                    task.generation_id,
                    "task.finished",
                    failed.model_dump(mode="json"),
                    task_id=task.id,
                )
            selected = conn.execute(
                "SELECT payload FROM subsea.tasks WHERE deadline > clock_timestamp() "
                "AND (state='QUEUED' OR (state='RUNNING' AND lease_expires_at<=clock_timestamp())) "
                "AND (%s::text IS NULL OR id=%s) "
                "ORDER BY (parent_id IS NOT NULL) DESC,created_at,id "
                "FOR UPDATE SKIP LOCKED LIMIT 1",
                (task_id, task_id),
            ).fetchone()
            if not selected:
                return None
            task = AgentTask.model_validate(selected["payload"])
            now = conn.execute("SELECT clock_timestamp() AS now").fetchone()
            assert now
            token = str(uuid.uuid4())
            saved = self._update_task(
                conn,
                task.model_copy(
                    update={
                        "state": "RUNNING",
                        "lease_token": token,
                        "lease_expires_at": min(
                            task.deadline, now["now"] + timedelta(seconds=ttl_seconds)
                        ),
                    }
                ),
            )
            conn.execute(
                "INSERT INTO subsea.attempts (tenant_id,site_id,task_id,id,owner,lease_token)"
                " VALUES (%s,%s,%s,%s,%s,%s)",
                (self.tenant_id, self.site_id, task.id, str(uuid.uuid4()), owner, token),
            )
            self._event(
                conn,
                task.generation_id,
                "task.started",
                saved.model_dump(mode="json"),
                task_id=task.id,
                snapshot_id=task.snapshot_id,
            )
            return saved

    def create_child(
        self,
        child: AgentTask,
        step_index: int,
        plan_revision: int = 1,
        *,
        lease_token: str | None = None,
    ) -> AgentTask:
        self._scope(child)
        if not child.parent_id:
            raise Conflict("parent_required")
        with self._tx(token=lease_token) as conn:
            self._generation(conn, child.generation_id)
            existing = conn.execute(
                "SELECT initial_payload,payload FROM subsea.tasks "
                "WHERE parent_id=%s AND plan_revision=%s AND step_index=%s",
                (child.parent_id, plan_revision, step_index),
            ).fetchone()
            if existing:
                if not self._compatible(existing["initial_payload"], child):
                    raise Conflict("idempotency_conflict")
                parent = self._get(conn, "tasks", child.parent_id, AgentTask, lock=True)
                token = lease_token or child.lease_token
                if existing["payload"]["state"] not in TERMINAL:
                    conn.execute("SELECT set_config('subsea.lease_token',%s,true)", (token,))
                    self._live_task(conn, parent.id, token, allow_waiting=True)
                    if parent.state == "RUNNING":
                        self._wait_for_children(conn, parent)
                return AgentTask.model_validate(existing["payload"])
            parent = self._get(conn, "tasks", child.parent_id, AgentTask, lock=True)
            # Frozen three-argument API can carry ownership through the child's token.
            token = lease_token or child.lease_token
            if not token:
                raise Conflict("stale_lease")
            conn.execute("SELECT set_config('subsea.lease_token',%s,true)", (token,))
            if parent.lease_token != token:
                raise Conflict("stale_lease")
            self._live_task(conn, parent.id, token, allow_waiting=True)
            clean = child.model_copy(update={"lease_token": None, "lease_expires_at": None})
            saved = self._insert_task(
                conn, clean, step_index=step_index, plan_revision=plan_revision
            )
            self._wait_for_children(conn, parent)
            return saved

    def _wait_for_children(
        self, conn: psycopg.Connection[dict[str, Any]], parent: AgentTask
    ) -> AgentTask:
        if parent.state != "WAITING_ON_CHILD":
            parent = self._update_task(
                conn,
                parent.model_copy(
                    update={
                        "state": "WAITING_ON_CHILD",
                    }
                ),
            )
        unfinished = conn.execute(
            "SELECT 1 FROM subsea.tasks WHERE parent_id=%s "
            "AND state NOT IN ('SUCCEEDED','ABSTAINED','FAILED','CANCELLED') LIMIT 1",
            (parent.id,),
        ).fetchone()
        if not unfinished:
            conn.execute("SELECT set_config('subsea.action','resume',true)")
            parent = self._update_task(
                conn,
                parent.model_copy(
                    update={
                        "state": "QUEUED",
                        "lease_token": None,
                        "lease_expires_at": None,
                    }
                ),
            )
        self._event(
            conn,
            parent.generation_id,
            "task.queued" if parent.state == "QUEUED" else "task.waiting",
            parent.model_dump(mode="json"),
            task_id=parent.id,
            snapshot_id=parent.snapshot_id,
        )
        return parent

    def get_provider_failure(self) -> str | None:
        with self._tx(read=True) as conn:
            row = conn.execute("SELECT subsea.get_provider_failure() AS code").fetchone()
            assert row
            return str(row["code"]) if row["code"] is not None else None

    def record_provider_failure(self, task_id: str, lease_token: str, code: str) -> None:
        if code not in {"proxy_auth", "proxy_quota"}:
            raise Conflict("invalid_provider_failure")
        with self._tx(token=lease_token) as conn:
            task = self._get(conn, "tasks", task_id, AgentTask)
            self._generation(conn, task.generation_id)
            self._live_task(conn, task_id, lease_token)
            conn.execute(
                "SELECT subsea.mark_provider_failure(%s,%s,%s)",
                (task_id, lease_token, code),
            )

    def clear_provider_failure(self) -> None:
        """Administrative action only after an explicit successful provider check."""
        with self._tx() as conn:
            conn.execute("SELECT subsea.clear_provider_failure()")

    def authorize_reuse(
        self, parent_id: str, task_ids: list[str], lease_token: str
    ) -> list[AgentTask]:
        if not 1 <= len(task_ids) <= 2 or len(set(task_ids)) != len(task_ids):
            raise Conflict("invalid_reuse_set")
        with self._tx(token=lease_token) as conn:
            initial = self._get(conn, "tasks", parent_id, AgentTask)
            self._generation(conn, initial.generation_id)
            parent = self._live_task(conn, parent_id, lease_token)
            if parent.role != "operator_response" or parent.plan != ["reuse", "answer"]:
                raise Conflict("reuse_not_planned")
            existing = conn.execute(
                "SELECT task_id FROM subsea.reuse_bindings WHERE parent_id=%s ORDER BY task_id",
                (parent_id,),
            ).fetchall()
            if existing and {row["task_id"] for row in existing} != set(task_ids):
                raise Conflict("idempotency_conflict")
            tasks = [self._get(conn, "tasks", id, AgentTask) for id in task_ids]
            quality = [task for task in tasks if task.role == "sensor_quality"]
            diagnosis = [task for task in tasks if task.role == "event_diagnosis"]
            if len(quality) != 1 or len(diagnosis) != len(tasks) - 1:
                raise Conflict("invalid_reuse_set")
            for task in tasks:
                if (task.generation_id, task.snapshot_id, task.mode) != (
                    parent.generation_id,
                    parent.snapshot_id,
                    parent.mode,
                ):
                    raise ScopeError("scope_error")
                expected_purpose = (
                    "assess_sensor_health"
                    if task.role == "sensor_quality"
                    else "assess_event_and_location"
                )
                if task.purpose != expected_purpose or task.parent_id != task.root_id:
                    raise Conflict("reuse_ancestry_conflict")
                if task.state not in {"SUCCEEDED", "ABSTAINED"} or task.result is None:
                    raise Conflict("reuse_result_not_accepted")
            if diagnosis and diagnosis[0].root_id != quality[0].root_id:
                raise Conflict("reuse_ancestry_conflict")
            if (
                diagnosis
                and not conn.execute(
                    "SELECT 1 FROM subsea.tool_receipts WHERE task_id=%s "
                    "AND payload->>'name'='task.result' "
                    "AND payload->'arguments'->>'task_id'=%s "
                    "AND payload->>'error' IS NULL AND payload->'result' <> 'null'::jsonb LIMIT 1",
                    (diagnosis[0].id, quality[0].id),
                ).fetchone()
            ):
                raise Conflict("reuse_dependency_not_consumed")
            if not existing:
                for task in sorted(tasks, key=lambda item: item.role != "sensor_quality"):
                    conn.execute(
                        "INSERT INTO subsea.reuse_bindings (tenant_id,site_id,parent_id,task_id)"
                        " VALUES (%s,%s,%s,%s)",
                        (self.tenant_id, self.site_id, parent_id, task.id),
                    )
                self._event(
                    conn,
                    parent.generation_id,
                    "task.dependencies",
                    {"task_ids": [task.id for task in tasks]},
                    task_id=parent_id,
                    snapshot_id=parent.snapshot_id,
                )
            return tasks

    def reuse_task_ids(self, parent_id: str) -> list[str]:
        with self._tx(read=True) as conn:
            self._get(conn, "tasks", parent_id, AgentTask)
            return [
                str(row["task_id"])
                for row in conn.execute(
                    "SELECT task_id FROM subsea.reuse_bindings WHERE parent_id=%s ORDER BY task_id",
                    (parent_id,),
                )
            ]

    def latest_task_trace(self, task_id: str) -> dict[str, JsonValue] | None:
        with self._tx(read=True) as conn:
            self._get(conn, "tasks", task_id, AgentTask)
            row = conn.execute(
                "SELECT payload FROM subsea.events WHERE task_id=%s AND type='task.started' "
                "AND coalesce(payload->'trace_metadata'->>'trace_id',payload->>'trace_id') "
                "IS NOT NULL ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if not row:
                return None
            payload = row["payload"]
            metadata = payload.get("trace_metadata")
            if not isinstance(metadata, dict):
                metadata = payload
            return {
                key: metadata.get(key, payload.get(key))
                for key in ("trace_id", "span_id", "attempt_id", "session_id")
                if metadata.get(key, payload.get(key)) is not None
            }

    def _reserve(self, task_id: str, lease_token: str, role_limit: int, field: str) -> AgentTask:
        with self._tx(token=lease_token) as conn:
            initial = self._get(conn, "tasks", task_id, AgentTask)
            self._generation(conn, initial.generation_id)
            task = self._live_task(conn, task_id, lease_token)
            if getattr(task, field) >= role_limit:
                raise BudgetExceeded()
            return self._update_task(
                conn,
                task.model_copy(
                    update={
                        field: getattr(task, field) + 1,
                    }
                ),
            )

    def reserve_model_call(self, task_id: str, lease_token: str, role_limit: int) -> AgentTask:
        return self._reserve(task_id, lease_token, role_limit, "model_calls")

    def reserve_tool_call(self, task_id: str, lease_token: str, role_limit: int) -> AgentTask:
        return self._reserve(task_id, lease_token, role_limit, "tool_calls")

    def begin_attempt(self, task_id: str, lease_token: str) -> str:
        with self._tx(read=True) as conn:
            self._live_task_read(conn, task_id, lease_token)
            row = conn.execute(
                "SELECT id FROM subsea.attempts WHERE task_id=%s AND lease_token=%s",
                (task_id, lease_token),
            ).fetchone()
            if not row:
                raise NotFound("attempt: not found in active scope")
            return str(row["id"])

    def _live_task_read(
        self, conn: psycopg.Connection[dict[str, Any]], task_id: str, token: str
    ) -> AgentTask:
        task = self._get(conn, "tasks", task_id, AgentTask)
        now = conn.execute("SELECT clock_timestamp() AS now").fetchone()
        assert now
        if (
            task.lease_token != token
            or task.state != "RUNNING"
            or not task.lease_expires_at
            or task.lease_expires_at <= now["now"]
            or task.deadline <= now["now"]
        ):
            raise Conflict("stale_lease")
        return task

    def _receipt(
        self,
        task_id: str,
        call_id: str,
        data: dict[str, JsonValue],
        lease_token: str | None,
        table: str,
        event_type: str,
    ) -> None:
        if not call_id or len(call_id) > 200:
            raise ValueError("A bounded call identity is required")
        with self._tx(token=lease_token) as conn:
            task = self._get(conn, "tasks", task_id, AgentTask)
            self._generation(conn, task.generation_id)
            task = self._live_task(conn, task_id, lease_token)
            existing = conn.execute(
                sql.SQL("SELECT payload FROM subsea.{} WHERE task_id=%s AND call_id=%s").format(
                    sql.Identifier(table)
                ),
                (task_id, call_id),
            ).fetchone()
            if existing:
                if existing["payload"] != data:
                    raise Conflict("idempotency_conflict")
                return
            count = conn.execute(
                sql.SQL("SELECT count(*) AS n FROM subsea.{} WHERE task_id=%s").format(
                    sql.Identifier(table)
                ),
                (task_id,),
            ).fetchone()
            assert count
            budget = task.tool_calls if table == "tool_receipts" else task.model_calls
            if int(count["n"]) >= budget:
                raise Conflict("call_not_reserved")
            conn.execute(
                sql.SQL(
                    "INSERT INTO subsea.{} "
                    "(tenant_id,site_id,task_id,call_id,lease_token,payload) "
                    "VALUES (%s,%s,%s,%s,%s,%s)"
                ).format(sql.Identifier(table)),
                (self.tenant_id, self.site_id, task_id, call_id, lease_token, Jsonb(data)),
            )
            self._event(
                conn,
                task.generation_id,
                event_type,
                {"call_id": call_id, "task_id": task_id, "error": data.get("error")},
                task_id=task_id,
                snapshot_id=task.snapshot_id,
            )
            if table == "model_receipts":
                code = data.get("error_code") or data.get("error")
                if isinstance(code, str) and code in {"proxy_auth", "proxy_quota"}:
                    conn.execute(
                        "SELECT subsea.mark_provider_failure(%s,%s,%s)",
                        (task_id, lease_token, code),
                    )

    def record_tool_call(
        self,
        task_id: str,
        call_id: str,
        name: str,
        arguments: dict[str, JsonValue],
        result: dict[str, JsonValue] | None,
        error: str | None = None,
        *,
        lease_token: str | None = None,
    ) -> None:
        if result is not None and len(json.dumps(result).encode("utf-8")) > 12 * 1024:
            raise Conflict("tool_payload_too_large")
        self._receipt(
            task_id,
            call_id,
            {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "result": result,
                "error": error,
            },
            lease_token,
            "tool_receipts",
            "tool.completed",
        )

    def tool_receipts(self, task_id: str) -> list[dict[str, JsonValue]]:
        with self._tx(read=True) as conn:
            self._get(conn, "tasks", task_id, AgentTask)
            return [
                row["payload"]
                for row in conn.execute(
                    "SELECT payload FROM subsea.tool_receipts WHERE task_id=%s ORDER BY call_id",
                    (task_id,),
                )
            ]

    def record_model_call(
        self, task_id: str, lease_token: str, call_id: str, metadata: dict[str, JsonValue]
    ) -> None:
        self._receipt(task_id, call_id, metadata, lease_token, "model_receipts", "model.completed")

    def list_model_calls(self, task_id: str) -> list[dict[str, JsonValue]]:
        with self._tx(read=True) as conn:
            self._get(conn, "tasks", task_id, AgentTask)
            return [
                row["payload"]
                for row in conn.execute(
                    "SELECT payload FROM subsea.model_receipts WHERE task_id=%s ORDER BY call_id",
                    (task_id,),
                )
            ]
