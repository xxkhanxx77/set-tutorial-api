from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from settrade_v2 import __version__ as settrade_sdk_version

from set_bidask_service import __version__
from set_bidask_service.collector import RealtimeCollector
from set_bidask_service.config import Settings, get_settings
from set_bidask_service.db import check_database, create_pool, init_schema
from set_bidask_service.repository import MarketRepository


class AppState:
    settings: Settings
    repository: MarketRepository
    collector: RealtimeCollector | None = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    pool = create_pool(settings.database_url)
    pool.open()
    init_schema(pool)

    state.settings = settings
    state.repository = MarketRepository(pool)

    if settings.enable_collector:
        state.collector = RealtimeCollector(settings, state.repository)
        state.collector.start()

    app.state.pool = pool
    try:
        yield
    finally:
        if state.collector:
            state.collector.stop()
        pool.close()


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
    }


@app.get("/health")
def health() -> dict[str, Any]:
    db_ok = check_database(app.state.pool)
    collector_state = state.collector.state.snapshot() if state.collector else None
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "collector_enabled": state.settings.enable_collector,
        "collector": collector_state,
        "symbols": state.settings.symbols,
        "settrade_sdk_version": settrade_sdk_version,
    }


@app.get("/symbols")
def symbols() -> dict[str, list[str]]:
    return {"symbols": state.settings.symbols}


@app.get("/latest/{symbol}")
def latest(symbol: str) -> dict[str, Any]:
    snapshot = state.repository.latest_bid_offer(symbol)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No bid/offer snapshot for {symbol.upper()}")
    return jsonable_encoder(snapshot)


@app.get("/recent/{symbol}")
def recent(
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return jsonable_encoder(state.repository.recent_snapshots(symbol, limit=limit))

