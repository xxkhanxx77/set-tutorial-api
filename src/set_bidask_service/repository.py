from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from set_bidask_service.transforms import (
    extract_candles,
    normalize_time,
    parse_bidask_levels,
    to_decimal,
    to_int,
)


class MarketRepository:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def save_order_book(
        self,
        *,
        symbol: str,
        source: str,
        bids: list[tuple[Any, Any]],
        asks: list[tuple[Any, Any]],
        raw: dict[str, Any],
        bid_flag: str = "",
        ask_flag: str = "",
    ) -> int:
        normalized_symbol = symbol.upper()
        levels: list[dict[str, Any]] = []
        for level in range(1, 11):
            bid = bids[level - 1] if level <= len(bids) else (None, 0)
            ask = asks[level - 1] if level <= len(asks) else (None, 0)
            levels.append(
                {
                    "side": "bid",
                    "level": level,
                    "price": to_decimal(bid[0]),
                    "volume": to_decimal(bid[1]) or 0,
                }
            )
            levels.append(
                {
                    "side": "ask",
                    "level": level,
                    "price": to_decimal(ask[0]),
                    "volume": to_decimal(ask[1]) or 0,
                }
            )

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bidask_snapshots (symbol, source, bid_flag, ask_flag, raw)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        normalized_symbol,
                        source,
                        bid_flag,
                        ask_flag,
                        Jsonb(raw),
                    ),
                )
                snapshot_id = cur.fetchone()[0]
                cur.executemany(
                    """
                    INSERT INTO bidask_levels (snapshot_id, side, level, price, volume)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            snapshot_id,
                            row["side"],
                            row["level"],
                            row["price"],
                            row["volume"],
                        )
                        for row in levels
                    ],
                )
            conn.commit()
        return int(snapshot_id)

    def save_bid_offer(self, data: dict[str, Any]) -> int:
        symbol = str(data.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("bid/offer payload is missing symbol")

        levels = parse_bidask_levels(data, depth=10)

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO bidask_snapshots (symbol, bid_flag, ask_flag, raw)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        symbol,
                        str(data.get("bid_flag") or ""),
                        str(data.get("ask_flag") or ""),
                        Jsonb(data),
                    ),
                )
                snapshot_id = cur.fetchone()[0]
                cur.executemany(
                    """
                    INSERT INTO bidask_levels (snapshot_id, side, level, price, volume)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            snapshot_id,
                            row["side"],
                            row["level"],
                            row["price"],
                            row["volume"],
                        )
                        for row in levels
                    ],
                )
            conn.commit()
        return int(snapshot_id)

    def save_price_info(self, data: dict[str, Any]) -> int:
        symbol = str(data.get("symbol") or "").upper()
        if not symbol:
            raise ValueError("price info payload is missing symbol")

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO price_info_ticks (
                        symbol, projected_open_price, projected_open_volume, high, low,
                        last, change, total_volume, total_value, market_status, raw
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        symbol,
                        to_decimal(data.get("projected_open_price")),
                        to_int(data.get("projected_open_volume")),
                        to_decimal(data.get("high")),
                        to_decimal(data.get("low")),
                        to_decimal(data.get("last")),
                        to_decimal(data.get("change")),
                        to_int(data.get("total_volume")),
                        to_decimal(data.get("total_value")),
                        str(data.get("market_status") or ""),
                        Jsonb(data),
                    ),
                )
                tick_id = cur.fetchone()[0]
            conn.commit()
        return int(tick_id)

    def save_quote_tick(
        self,
        *,
        symbol: str,
        source: str,
        raw: dict[str, Any],
        bid: Any = None,
        ask: Any = None,
        last: Any = None,
        open_price: Any = None,
        high: Any = None,
        low: Any = None,
        close: Any = None,
        change: Any = None,
        spread: Any = None,
    ) -> int:
        normalized_symbol = symbol.upper()
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO quote_ticks (
                        symbol, source, bid, ask, last, open, high, low,
                        close, change, spread, raw
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        normalized_symbol,
                        source,
                        to_decimal(bid),
                        to_decimal(ask),
                        to_decimal(last),
                        to_decimal(open_price),
                        to_decimal(high),
                        to_decimal(low),
                        to_decimal(close),
                        to_decimal(change),
                        to_decimal(spread),
                        Jsonb(raw),
                    ),
                )
                tick_id = cur.fetchone()[0]
            conn.commit()
        return int(tick_id)

    def save_candlesticks(self, payload: Any, fallback_symbol: str, interval: str) -> int:
        candles = extract_candles(payload)
        rows = []
        for candle in candles:
            candle_time = normalize_time(
                candle.get("time")
                or candle.get("datetime")
                or candle.get("dateTime")
                or candle.get("timestamp")
            )
            if candle_time is None:
                continue
            rows.append(
                (
                    str(candle.get("symbol") or fallback_symbol).upper(),
                    str(candle.get("interval") or interval),
                    candle_time,
                    to_decimal(candle.get("open")),
                    to_decimal(candle.get("high")),
                    to_decimal(candle.get("low")),
                    to_decimal(candle.get("close")),
                    to_int(candle.get("volume")),
                    to_decimal(candle.get("value")),
                    to_int(candle.get("last_sequence") or candle.get("lastSequence")),
                    Jsonb(candle),
                )
            )

        if not rows:
            return 0

        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO candlesticks (
                        symbol, interval, candle_time, open, high, low, close,
                        volume, value, last_sequence, raw
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, interval, candle_time) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        value = EXCLUDED.value,
                        last_sequence = EXCLUDED.last_sequence,
                        raw = EXCLUDED.raw,
                        received_at = now()
                    """,
                    rows,
                )
            conn.commit()
        return len(rows)

    def latest_bid_offer(self, symbol: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, symbol, source, received_at, bid_flag, ask_flag, raw
                    FROM bidask_snapshots
                    WHERE symbol = %s
                    ORDER BY received_at DESC
                    LIMIT 1
                    """,
                    (symbol.upper(),),
                )
                snapshot = cur.fetchone()
                if snapshot is None:
                    return None

                cur.execute(
                    """
                    SELECT side, level, price::TEXT AS price, volume
                    FROM bidask_levels
                    WHERE snapshot_id = %s
                    ORDER BY side, level
                    """,
                    (snapshot["id"],),
                )
                levels = cur.fetchall()

        bids = [row for row in levels if row["side"] == "bid"]
        asks = [row for row in levels if row["side"] == "ask"]
        return {**snapshot, "levels": {"bids": bids, "asks": asks}}

    def recent_snapshots(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        bounded_limit = min(max(limit, 1), 500)
        with self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, symbol, source, received_at, bid_flag, ask_flag
                    FROM bidask_snapshots
                    WHERE symbol = %s
                    ORDER BY received_at DESC
                    LIMIT %s
                    """,
                    (symbol.upper(), bounded_limit),
                )
                return list(cur.fetchall())
