"""Tenant-isolated playback of recorded evidence, with workers and mutations disabled."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import replace

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .config import Settings


def create_recorded_console(settings: Settings, tenant_id: str) -> FastAPI:
    from .api import create_app

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", tenant_id):
        raise ValueError("Invalid recorded-console tenant identifier")
    app = create_app(replace(settings, tenant_id=tenant_id), start_workers=False)

    @app.middleware("http")
    async def recorded_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path not in {
            "/api/login", "/api/logout",
        }:
            return JSONResponse(
                status_code=405,
                content={"detail": "recorded_only: inspection is read-only; new work is disabled"},
            )
        return await call_next(request)

    @app.get("/api/recorded-mode")
    def mode() -> dict[str, object]:
        return {
            "recorded_only": True, "tenant_id": tenant_id, "site_id": settings.site_id,
            "monitor_workers": False, "agent_workers": False, "new_inference": False,
        }

    return app
