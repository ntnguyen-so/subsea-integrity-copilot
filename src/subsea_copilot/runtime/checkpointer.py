"""Checkpoint ownership is separate from application and gateway database roles."""

import re
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row


class CheckpointError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@contextmanager
def postgres_checkpointer(
    connection_string: str,
    schema: str = "subsea_checkpoint",
    *,
    setup: bool = False,
) -> Iterator[PostgresSaver]:
    """Bootstrap explicitly with setup=True; default startup verifies readiness immediately."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Invalid checkpoint schema.")
    with psycopg.connect(
        connection_string, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as connection:
        connection.execute("SELECT set_config('search_path', %s, false)", (schema,))
        saver = PostgresSaver(connection)
        if setup:
            saver.setup()
        else:
            try:
                row = connection.execute(
                    "SELECT v FROM checkpoint_migrations ORDER BY v DESC LIMIT 1"
                ).fetchone()
                if row is None or row["v"] != len(saver.MIGRATIONS) - 1:
                    raise CheckpointError(
                        "checkpoint_uninitialized",
                        "Run checkpoint bootstrap with setup=True before starting the worker.",
                    )
            except psycopg.errors.UndefinedTable as exc:
                raise CheckpointError(
                    "checkpoint_uninitialized",
                    "Run checkpoint bootstrap with setup=True before starting the worker.",
                ) from exc
            except psycopg.errors.InsufficientPrivilege as exc:
                raise CheckpointError(
                    "checkpoint_permission", "Checkpoint role cannot read its owned schema."
                ) from exc
        yield saver
