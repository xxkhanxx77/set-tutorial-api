from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import requests

from set_bidask_service.config import Settings
from set_bidask_service.repository import MarketRepository

logger = logging.getLogger(__name__)

BYBIT_TRADFI_SOURCE = "bybit_tradfi"

REQUEST_HEADERS = {
    "accept": "application/json,text/plain,*/*",
    "origin": "https://www.bybit.com",
    "referer": "https://www.bybit.com/trade/tradfi/USDTHB+",
    "user-agent": "settrade-bidask-railway/0.1",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class PollingCollectorState:
    running: bool = False
    started_at: str | None = None
    last_message_at: str | None = None
    last_saved_at: str | None = None
    last_candle_saved_at: str | None = None
    last_error: str | None = None
    request_count: int = 0
    saved_count: int = 0
    quote_saved_count: int = 0
    candle_saved_count: int = 0
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
                "last_candle_saved_at": self.last_candle_saved_at,
                "last_error": self.last_error,
                "request_count": self.request_count,
                "saved_count": self.saved_count,
                "quote_saved_count": self.quote_saved_count,
                "candle_saved_count": self.candle_saved_count,
                "error_count": self.error_count,
            }


def find_tradfi_symbol_items(
    payload: dict[str, Any],
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    wanted = {symbol.upper() for symbol in symbols}
    found: dict[str, dict[str, Any]] = {}
    result = payload.get("result")
    groups = result.get("list", {}) if isinstance(result, dict) else {}
    if not isinstance(groups, dict):
        return found

    for group in groups.values():
        values = group.get("value") if isinstance(group, dict) else None
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper()
            if symbol in wanted:
                found[symbol] = item
    return found


def tradfi_kline_payload_to_candles(
    payload: dict[str, Any],
    *,
    symbol: str,
    interval: str,
) -> list[dict[str, Any]]:
    result = payload.get("result")
    rows = result.get("list", []) if isinstance(result, dict) else []
    if not isinstance(rows, list):
        return []

    candles: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            continue
        try:
            candle_time = int(row[0])
        except (TypeError, ValueError):
            continue
        candles.append(
            {
                "symbol": symbol,
                "interval": interval,
                "time": candle_time,
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5] if len(row) > 5 else None,
                "raw": row,
            }
        )
    return candles


class BybitTradfiCollector:
    def __init__(self, settings: Settings, repository: MarketRepository):
        self.settings = settings
        self.repository = repository
        self.state = PollingCollectorState()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._session = requests.Session()
        self._session.headers.update(REQUEST_HEADERS)
        self._last_candle_poll_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="bybit-tradfi", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._session.close()

    @property
    def _base_url(self) -> str:
        return self.settings.bybit_tradfi_base_url.rstrip("/")

    def _run(self) -> None:
        self.state.update(running=True, started_at=utc_now_iso(), last_error=None)
        try:
            while not self._stop_event.is_set():
                self._fetch_quotes()

                now = time.monotonic()
                if (
                    now - self._last_candle_poll_at
                    >= self.settings.bybit_tradfi_candle_poll_interval_seconds
                ):
                    self._last_candle_poll_at = now
                    for symbol in self.settings.bybit_tradfi_symbol_list:
                        if self._stop_event.is_set():
                            break
                        self._fetch_candles(symbol)

                self._stop_event.wait(self.settings.bybit_tradfi_poll_interval_seconds)
        finally:
            self.state.update(running=False)

    def _fetch_quotes(self) -> None:
        try:
            response = self._session.get(
                f"{self._base_url}/fapi/copymt5/public/v1/gdfx/symbol/list-for-guest",
                timeout=15,
            )
            self.state.increment("request_count")
            response.raise_for_status()
            payload = response.json()
            if payload.get("retCode") != 0:
                raise RuntimeError(f"Bybit TradFi retCode={payload.get('retCode')}")

            self.state.update(last_message_at=utc_now_iso())
            symbols = self.settings.bybit_tradfi_symbol_list
            items = find_tradfi_symbol_items(payload, symbols)
            missing = [symbol for symbol in symbols if symbol not in items]

            for symbol, item in items.items():
                raw = {"provider": BYBIT_TRADFI_SOURCE, "quote_only": True, **item}
                self.repository.save_quote_tick(
                    symbol=symbol,
                    source=BYBIT_TRADFI_SOURCE,
                    bid=item.get("bid"),
                    ask=item.get("ask"),
                    last=item.get("lastPrice"),
                    open_price=item.get("openPrice"),
                    high=item.get("highPrice"),
                    low=item.get("lowPrice"),
                    close=item.get("closePrice"),
                    change=item.get("change"),
                    spread=item.get("spread"),
                    raw=raw,
                )
                self.state.increment("quote_saved_count")

                self.repository.save_order_book(
                    symbol=symbol,
                    source=BYBIT_TRADFI_SOURCE,
                    bids=[(item.get("bid"), 0)],
                    asks=[(item.get("ask"), 0)],
                    raw=raw,
                    bid_flag="QUOTE_ONLY",
                    ask_flag="QUOTE_ONLY",
                )
                self.state.increment("saved_count")
                self.state.update(last_saved_at=utc_now_iso(), last_error=None)

            if missing:
                self.state.update(
                    last_error=f"Bybit TradFi symbols not found: {', '.join(missing)}"
                )
        except Exception as exc:
            logger.exception("Failed to collect Bybit TradFi quotes")
            self.state.increment("error_count")
            self.state.update(last_error=str(exc))

    def _fetch_candles(self, symbol: str) -> None:
        try:
            response = self._session.get(
                f"{self._base_url}/fapi/copymt5/kline",
                params={
                    "symbol": symbol,
                    "interval": self.settings.bybit_tradfi_candle_interval,
                    "limit": self.settings.bybit_tradfi_candle_limit,
                },
                timeout=15,
            )
            self.state.increment("request_count")
            response.raise_for_status()
            payload = response.json()
            if payload.get("ret_code") != 0:
                raise RuntimeError(f"Bybit TradFi kline ret_code={payload.get('ret_code')}")

            candles = tradfi_kline_payload_to_candles(
                payload,
                symbol=symbol,
                interval=self.settings.bybit_tradfi_candle_interval,
            )
            saved = self.repository.save_candlesticks(
                candles,
                fallback_symbol=symbol,
                interval=self.settings.bybit_tradfi_candle_interval,
            )
            if saved:
                self.state.increment("candle_saved_count", saved)
                self.state.update(last_candle_saved_at=utc_now_iso(), last_error=None)
        except Exception as exc:
            logger.exception("Failed to collect Bybit TradFi candles for %s", symbol)
            self.state.increment("error_count")
            self.state.update(last_error=str(exc))
