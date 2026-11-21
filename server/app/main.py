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

from app.api.routers import (
    alarming,
    auth,
    control_centers,
    fleet,
    imports,
    interfaces,
    master_data,
    operations,
    proposals,
    system,
    users,
    ws,
)
from app.core.config import APP_VERSION, Settings, get_settings
from app.core.crypto import SecretBox
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, request_id_var
from app.db.session import Database
from app.plugins.registry import load_entry_points
from app.proposal.travel import OsrmProvider
from app.realtime.bus import create_bus
from app.realtime.hub import ConnectionHub
from app.services.alarm_delivery import recover_interrupted_deliveries
from app.services.reference_data import ensure_reference_data
from app.services.role_service import sync_catalogue
from app.services.uow import UnitOfWork
from app.simulation.runner import SimulationRunner

logger = logging.getLogger("app")

API_PREFIX = "/api/v1"


async def _synchronise_catalogues(app: FastAPI) -> None:
    """Permission catalogue + reference data are kept in sync on every start (idempotent,
    serialised via advisory locks), so updates never require a manual bootstrap."""
    async with app.state.db.sessionmaker() as session:
        uow = UnitOfWork(session, app.state.bus)
        await sync_catalogue(uow)
        await ensure_reference_data(uow)
        await recover_interrupted_deliveries(uow)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.secret_box = SecretBox.from_config(settings.encryption_keys)
        app.state.db = Database(settings)
        app.state.routing = (
            OsrmProvider(settings.osrm_url, settings.osrm_timeout_seconds) if settings.osrm_url else None
        )
        load_entry_points()
        app.state.hub = ConnectionHub()
        app.state.bus = create_bus(settings.redis_url)
        await app.state.bus.start(app.state.hub.handle)
        await _synchronise_catalogues(app)
        app.state.simulation = None
        if settings.simulation_tick_seconds > 0:
            app.state.simulation = SimulationRunner(app.state, settings.simulation_tick_seconds)
            await app.state.simulation.start()
        logger.info(
            "Server gestartet",
            extra={"ctx": {"version": APP_VERSION, "env": settings.environment, "bus": app.state.bus.name}},
        )
        try:
            yield
        finally:
            if app.state.simulation is not None:
                await app.state.simulation.stop()
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
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
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
    api.include_router(master_data.router)
    api.include_router(imports.router)
    api.include_router(operations.router)
    api.include_router(alarming.router)
    api.include_router(interfaces.router)
    api.include_router(proposals.router)
    api.include_router(fleet.router)
    api.include_router(system.router)
    api.include_router(ws.router)
    app.include_router(api)
    return app


app = create_app()
