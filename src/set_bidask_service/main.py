from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from psycopg_pool import ConnectionPool
from settrade_v2 import __version__ as settrade_sdk_version

from set_bidask_service import __version__
from set_bidask_service.collector import RealtimeCollector
from set_bidask_service.config import Settings, get_settings
from set_bidask_service.db import check_database, create_pool, init_schema
from set_bidask_service.repository import MarketRepository


class AppState:
    settings: Settings | None = None
    pool: ConnectionPool | None = None
    repository: MarketRepository | None = None
    collector: RealtimeCollector | None = None
    startup_errors: list[str]

    def __init__(self) -> None:
        self.startup_errors = []


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    state.settings = settings
    state.pool = None
    state.repository = None
    state.collector = None
    state.startup_errors = []

    if settings.database_url:
        pool = None
        try:
            pool = create_pool(settings.database_url)
            pool.open()
            init_schema(pool)
            state.pool = pool
            state.repository = MarketRepository(pool)
            app.state.pool = pool
        except Exception as exc:
            state.startup_errors.append(f"database startup failed: {exc}")
            if pool:
                pool.close()
            state.pool = None
            state.repository = None
    else:
        state.startup_errors.append("DATABASE_URL is not configured")

    if settings.enable_collector and state.repository and settings.can_start_collector:
        state.collector = RealtimeCollector(settings, state.repository)
        state.collector.start()
    elif settings.enable_collector:
        missing = ", ".join(settings.missing_settrade_vars)
        reason = missing or "database is not ready"
        state.startup_errors.append(f"collector not started: {reason}")

    try:
        yield
    finally:
        if state.collector:
            state.collector.stop()
        if state.pool:
            state.pool.close()


app = FastAPI(
    title="Settrade Bid/Ask Collector",
    version=__version__,
    lifespan=lifespan,
)


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "settrade-bidask-railway",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    settings = state.settings
    collector_state = state.collector.state.snapshot() if state.collector else None
    return {
        "status": "ok",
        "service": "settrade-bidask-railway",
        "version": __version__,
        "collector_enabled": settings.enable_collector if settings else False,
        "collector": collector_state,
        "symbols": settings.symbols if settings else [],
        "ready": "/ready",
    }


@app.get("/ready")
def ready(response: Response) -> dict[str, Any]:
    settings = state.settings
    db_ok = False
    db_error = None
    if state.pool:
        try:
            db_ok = check_database(state.pool)
        except Exception as exc:
            db_error = str(exc)
    elif settings and not settings.database_url:
        db_error = "DATABASE_URL is not configured"
    else:
        db_error = "database pool is not available"

    missing_settrade_vars = settings.missing_settrade_vars if settings else []
    collector_state = state.collector.state.snapshot() if state.collector else None
    is_ready = db_ok and not missing_settrade_vars

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if is_ready else "degraded",
        "database": "ok" if db_ok else "error",
        "database_error": db_error,
        "missing_settrade_vars": missing_settrade_vars,
        "collector_enabled": settings.enable_collector if settings else False,
        "collector": collector_state,
        "symbols": settings.symbols if settings else [],
        "settrade_sdk_version": settrade_sdk_version,
        "startup_errors": state.startup_errors,
    }


@app.get("/symbols")
def symbols() -> dict[str, list[str]]:
    if state.settings is None:
        raise HTTPException(status_code=503, detail="Application settings are not loaded")
    return {"symbols": state.settings.symbols}


@app.get("/latest/{symbol}")
def latest(symbol: str) -> dict[str, Any]:
    if state.repository is None:
        raise HTTPException(status_code=503, detail="Database is not configured or not available")
    snapshot = state.repository.latest_bid_offer(symbol)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No bid/offer snapshot for {symbol.upper()}")
    return jsonable_encoder(snapshot)


@app.get("/recent/{symbol}")
def recent(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    if state.repository is None:
        raise HTTPException(status_code=503, detail="Database is not configured or not available")
    return jsonable_encoder(state.repository.recent_snapshots(symbol, limit=limit))
