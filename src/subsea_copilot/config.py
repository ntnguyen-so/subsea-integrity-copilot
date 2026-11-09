"""Environment-only credentials and independently owned local resources."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required; run tools\\bootstrap.ps1 and load its environment")
    return value


def database_url(user: str, password: str) -> str:
    port = os.environ.get("SUBSEA_DB_PORT", "15433")
    return f"postgresql://{user}:{quote(password, safe='')}@127.0.0.1:{port}/subsea"


@dataclass(frozen=True)
class Settings:
    """Separate application, tool-read and checkpoint authorities; hide secrets from repr."""

    database_dsn: str = field(repr=False)
    tools_dsn: str = field(repr=False)
    checkpoint_dsn: str = field(repr=False)
    admin_dsn: str = field(repr=False)
    app_password: str = field(repr=False)
    tools_password: str = field(repr=False)
    checkpoint_password: str = field(repr=False)
    operator_password: str = field(repr=False)
    runtime_dir: Path
    host: str = "127.0.0.1"
    port: int = 8086
    tenant_id: str = "demo"
    site_id: str = "northsea"

    @classmethod
    def from_env(cls) -> Settings:
        """Require externally bootstrapped credentials rather than committing usable defaults."""
        app = required("SUBSEA_DB_APP_PASSWORD")
        tools = required("SUBSEA_DB_TOOL_PASSWORD")
        checkpoint = required("SUBSEA_DB_CHECKPOINT_PASSWORD")
        return cls(
            database_dsn=database_url("subsea_app", app),
            tools_dsn=database_url("subsea_tools_ro", tools),
            checkpoint_dsn=database_url("subsea_checkpoint", checkpoint),
            admin_dsn=database_url("subsea_admin", required("SUBSEA_DB_ADMIN_PASSWORD")),
            app_password=app,
            tools_password=tools,
            checkpoint_password=checkpoint,
            operator_password=required("SUBSEA_OPERATOR_PASSWORD"),
            runtime_dir=Path(
                os.environ.get(
                    "SUBSEA_RUNTIME_DIR",
                    str(Path(os.environ["LOCALAPPDATA"]) / "SubseaCopilot"),
                )
            ),
            port=int(os.environ.get("SUBSEA_PORT", "8086")),
        )
