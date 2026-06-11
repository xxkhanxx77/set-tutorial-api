from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

from set_bidask_service.config import Settings
from set_bidask_service.repository import MarketRepository

logger = logging.getLogger(__name__)

BINANCE_TH_REST_BASE_URL = "https://api.binance.th"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class BinanceThCollectorState:
    running: bool = False
    started_at: str | None = None
    last_message_at: str | None = None
    last_saved_at: str | None = None
    last_error: str | None = None
    request_count: int = 0
    saved_count: int = 0
    error_count: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **changes: Any) -> None:
        with self.lock:
            for key, value in changes.items():
                setattr(self, key, value)

    def increment(self, key: str, amount: int = 1) -> None:
        with self.lock:
            setattr(self, key, getattr(self, key) + amount)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "running": self.running,
                "started_at": self.started_at,
                "last_message_at": self.last_message_at,
                "last_saved_at": self.last_saved_at,
                "last_error": self.last_error,
                "request_count": self.request_count,
                "saved_count": self.saved_count,
                "error_count": self.error_count,
            }


class BinanceThDepthCollector:
    def __init__(self, settings: Settings, repository: MarketRepository):
        self.settings = settings
        self.repository = repository
        self.state = BinanceThCollectorState()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._session = requests.Session()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="binance-th-depth", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._session.close()

    def _run(self) -> None:
        self.state.update(running=True, started_at=utc_now_iso(), last_error=None)
        try:
            while not self._stop_event.is_set():
                for symbol in self.settings.binance_symbols:
                    if self._stop_event.is_set():
                        break
                    self._fetch_and_save(symbol)
                self._stop_event.wait(self.settings.binance_th_poll_interval_seconds)
        finally:
            self.state.update(running=False)

    def _fetch_and_save(self, symbol: str) -> None:
        try:
            response = self._session.get(
                f"{BINANCE_TH_REST_BASE_URL}/api/v1/depth",
                params={"symbol": symbol, "limit": self.settings.binance_th_depth_limit},
                timeout=10,
            )
            self.state.increment("request_count")
            response.raise_for_status()
            payload = response.json()
            self.state.update(last_message_at=utc_now_iso())

            self.repository.save_order_book(
                symbol=symbol,
                source="binance_th",
                bids=payload.get("bids", []),
                asks=payload.get("asks", []),
                raw={
                    "provider": "binance_th",
                    "symbol": symbol,
                    "depth_limit": self.settings.binance_th_depth_limit,
                    **payload,
                },
            )
            self.state.increment("saved_count")
            self.state.update(last_saved_at=utc_now_iso(), last_error=None)
        except Exception as exc:
            logger.exception("Failed to collect Binance TH depth for %s", symbol)
            self.state.increment("error_count")
            self.state.update(last_error=str(exc))
