from datetime import UTC
from decimal import Decimal

from set_bidask_service.transforms import (
    extract_candles,
    normalize_time,
    parse_bidask_levels,
    to_decimal,
    to_int,
)


def test_parse_bidask_levels_keeps_10_bid_and_10_ask_rows():
    payload = {
        "symbol": "AOT",
        "bid_price1": 10.25,
        "bid_volume1": "100",
        "ask_price1": "10.30",
        "ask_volume1": 200,
    }

    rows = parse_bidask_levels(payload)

    assert len(rows) == 20
    assert rows[0] == {
        "side": "bid",
        "level": 1,
        "price": Decimal("10.25"),
        "volume": 100,
    }
    assert rows[1] == {
        "side": "ask",
        "level": 1,
        "price": Decimal("10.30"),
        "volume": 200,
    }
    assert rows[-1]["side"] == "ask"
    assert rows[-1]["level"] == 10


def test_number_helpers_return_none_for_empty_values():
    assert to_decimal("") is None
    assert to_decimal(None) is None
    assert to_decimal("1.2345") == Decimal("1.2345")
    assert to_int("") is None
    assert to_int(None) is None
    assert to_int("123") == 123


def test_normalize_time_accepts_iso_and_epoch_ms():
    from_iso = normalize_time("2026-06-11T10:00:00Z")
    from_ms = normalize_time(1_786_400_000_000)

    assert from_iso is not None
    assert from_iso.tzinfo == UTC
    assert from_ms is not None
    assert from_ms.tzinfo == UTC


def test_extract_candles_accepts_common_response_keys():
    assert extract_candles({"candlesticks": [{"open": 1}]}) == [{"open": 1}]
    assert extract_candles({"data": [{"open": 2}]}) == [{"open": 2}]
    assert extract_candles([{"open": 3}]) == [{"open": 3}]
    assert extract_candles({"data": "bad"}) == []
