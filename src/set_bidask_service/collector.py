from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from settrade_v2 import Investor
from settrade_v2.config import config as settrade_config

from set_bidask_service.config import Settings
from set_bidask_service.repository import MarketRepository

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class CollectorState:
    running: bool = False
    connected: bool = False
    started_at: str | None = None
    last_message_at: str | None = None
    last_saved_at: str | None = None
    last_error: str | None = None
    message_count: int = 0
    saved_bidask_count: int = 0
    saved_price_info_count: int = 0
    error_count: int = 0
    reconnect_count: int = 0
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
                "connected": self.connected,
                "started_at": self.started_at,
                "last_message_at": self.last_message_at,
                "last_saved_at": self.last_saved_at,
                "last_error": self.last_error,
                "message_count": self.message_count,
                "saved_bidask_count": self.saved_bidask_count,
                "saved_price_info_count": self.saved_price_info_count,
                "error_count": self.error_count,
                "reconnect_count": self.reconnect_count,
            }


class RealtimeCollector:
    def __init__(self, settings: Settings, repository: MarketRepository):
        self.settings = settings
        self.repository = repository
        self.state = CollectorState()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._reconnect_event = threading.Event()
        self._last_saved_monotonic: dict[str, float] = {}
        self._save_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="settrade-realtime", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        self.state.update(running=True, started_at=utc_now_iso(), last_error=None)
        retry_seconds = 5

        while not self._stop_event.is_set():
            self._reconnect_event.clear()
            realtime = None
            subscribers = []
            try:
                settrade_config["environment"] = self.settings.settrade_env
                investor = Investor(
                    app_id=self.settings.settrade_app_id,
                    app_secret=self.settings.settrade_app_secret,
                    app_code=self.settings.settrade_app_code,
                    broker_id=self.settings.settrade_broker_id,
                    is_auto_queue=True,
                )
                realtime = investor.RealtimeDataConnection()

                for symbol in self.settings.symbols:
                    subscribers.append(
                        realtime.subscribe_bid_offer(
                            symbol,
                            on_message=self._on_bid_offer,
                            args=(symbol,),
                        )
                    )
                    if self.settings.subscribe_price_info:
                        subscribers.append(
                            realtime.subscribe_price_info(
                                symbol,
                                on_message=self._on_price_info,
                                args=(symbol,),
                            )
                        )

                for subscriber in subscribers:
                    subscriber.start()

                logger.info("Settrade realtime collector started for %s", self.settings.symbols)
                self.state.update(connected=True, last_error=None)

                while not self._stop_event.wait(1.0):
                    if self._reconnect_event.is_set():
                        logger.info("Reconnecting Settrade realtime collector")
                        break
            except Exception as exc:
                logger.exception("Settrade realtime collector failed")
                self.state.increment("error_count")
                self.state.update(connected=False, last_error=str(exc))
                if self._stop_event.wait(retry_seconds):
                    break
            finally:
                for subscriber in subscribers:
                    try:
                        subscriber.stop()
                    except Exception:
                        logger.debug("Failed to stop subscriber", exc_info=True)
                if realtime is not None:
                    try:
                        realtime._stop()
                    except Exception:
                        logger.debug("Failed to stop realtime connection", exc_info=True)
                self.state.update(connected=False)

        self.state.update(running=False)

    def _should_save(self, symbol: str) -> bool:
        interval_ms = self.settings.snapshot_min_interval_ms
        if interval_ms <= 0:
            return True

        now = time.monotonic() * 1000
        with self._save_lock:
            last = self._last_saved_monotonic.get(symbol, 0)
            if now - last < interval_ms:
                return False
            self._last_saved_monotonic[symbol] = now
            return True

    def _on_bid_offer(self, result: dict[str, Any], symbol: str) -> None:
        self.state.increment("message_count")
        self.state.update(last_message_at=utc_now_iso())

        if not result.get("is_success"):
            message = result.get("message") or result.get("data") or "unknown realtime error"
            self._handle_realtime_error("Bid/offer", symbol, message)
            return

        data = dict(result["data"])
        data["symbol"] = str(data.get("symbol") or symbol).upper()
        if not self._should_save(data["symbol"]):
            return

        try:
            self.repository.save_bid_offer(data)
            self.state.increment("saved_bidask_count")
            self.state.update(last_saved_at=utc_now_iso(), last_error=None)
        except Exception as exc:
            logger.exception("Failed to save bid/offer payload for %s", symbol)
            self.state.increment("error_count")
            self.state.update(last_error=str(exc))

    def _on_price_info(self, result: dict[str, Any], symbol: str) -> None:
        self.state.increment("message_count")
        self.state.update(last_message_at=utc_now_iso())

        if not result.get("is_success"):
            message = result.get("message") or result.get("data") or "unknown realtime error"
            self._handle_realtime_error("Price info", symbol, message)
            return

        data = dict(result["data"])
        data["symbol"] = str(data.get("symbol") or symbol).upper()

        try:
            self.repository.save_price_info(data)
            self.state.increment("saved_price_info_count")
            self.state.update(last_saved_at=utc_now_iso(), last_error=None)
        except Exception as exc:
            logger.exception("Failed to save price info payload for %s", symbol)
            self.state.increment("error_count")
            self.state.update(last_error=str(exc))

    def _handle_realtime_error(self, feed_name: str, symbol: str, message: Any) -> None:
        message_text = str(message)
        logger.warning("%s subscription error for %s: %s", feed_name, symbol, message_text)
        self.state.increment("error_count")
        self.state.update(last_error=message_text)

        if "disconnected" in message_text.lower():
            self.state.increment("reconnect_count")
            self.state.update(connected=False)
            self._reconnect_event.set()
