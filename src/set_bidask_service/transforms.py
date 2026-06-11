from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        # Settrade REST often uses milliseconds, while some SDK objects use seconds.
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def parse_bidask_levels(data: dict[str, Any], depth: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for level in range(1, depth + 1):
        rows.append(
            {
                "side": "bid",
                "level": level,
                "price": to_decimal(data.get(f"bid_price{level}")),
                "volume": to_int(data.get(f"bid_volume{level}")) or 0,
            }
        )
        rows.append(
            {
                "side": "ask",
                "level": level,
                "price": to_decimal(data.get(f"ask_price{level}")),
                "volume": to_int(data.get(f"ask_volume{level}")) or 0,
            }
        )
    return rows


def extract_candles(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("candlesticks", "candles", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []
