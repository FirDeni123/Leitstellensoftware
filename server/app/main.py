"""Application factory.

Run in development::

    uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routers import auth, control_centers, system, users, ws
from app.core.config import APP_VERSION, Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, request_id_var
from app.db.session import Database
from app.realtime.bus import create_bus
from app.realtime.hub import ConnectionHub

logger = logging.getLogger("app")

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.db = Database(settings)
        app.state.hub = ConnectionHub()
        app.state.bus = create_bus(settings.redis_url)
        await app.state.bus.start(app.state.hub.handle)
        logger.info(
            "Server gestartet",
            extra={"ctx": {"version": APP_VERSION, "env": settings.environment, "bus": app.state.bus.name}},
        )
        try:
            yield
        finally:
            await app.state.hub.close_all()
            await app.state.bus.stop()
            await app.state.db.dispose()

    app = FastAPI(
        title="ILS-Sim API",
        version=APP_VERSION,
        description="Zentrale API der Leitstellen-Simulation. Alle Endpunkte unter /api/v1.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    register_exception_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid[:64])
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        duration = (time.perf_counter() - start) * 1000
        if request.url.path != "/health":
            logger.info(
                "%s %s -> %s (%.1f ms)",
                request.method,
                request.url.path,
                response.status_code,
                duration,
                extra={"ctx": {"request_id": rid}},
            )
        return response

    @app.get("/health", tags=["System"], summary="Liveness/Readiness (ohne Anmeldung)")
    async def health(request: Request) -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with request.app.state.db.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
        bus = request.app.state.bus
        if hasattr(bus, "ping"):
            checks["redis"] = "ok" if await bus.ping() else "error"
        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ok" if healthy else "degraded", "version": APP_VERSION, "checks": checks},
        )

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(control_centers.router)
    api.include_router(system.router)
    api.include_router(ws.router)
    app.include_router(api)
    return app


app = create_app()
