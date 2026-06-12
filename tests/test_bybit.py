from set_bidask_service.bybit import find_tradfi_symbol_items, tradfi_kline_payload_to_candles
from set_bidask_service.config import Settings


def test_find_tradfi_symbol_items_keeps_plus_symbol():
    payload = {
        "result": {
            "list": {
                "Forex": {
                    "value": [
                        {"symbol": "USDTHB", "bid": "32.79"},
                        {"symbol": "USDTHB+", "bid": "32.80", "ask": "32.81"},
                    ]
                }
            }
        }
    }

    found = find_tradfi_symbol_items(payload, ["USDTHB+"])

    assert found["USDTHB+"]["bid"] == "32.80"
    assert "USDTHB" not in found


def test_tradfi_kline_payload_to_candles_maps_bybit_rows():
    payload = {
        "result": {
            "list": [
                ["1781240400000", "32.8", "32.82", "32.791", "32.805"],
            ]
        }
    }

    candles = tradfi_kline_payload_to_candles(payload, symbol="USDTHB+", interval="30")

    assert candles == [
        {
            "symbol": "USDTHB+",
            "interval": "30",
            "time": 1781240400000,
            "open": "32.8",
            "high": "32.82",
            "low": "32.791",
            "close": "32.805",
            "volume": None,
            "raw": ["1781240400000", "32.8", "32.82", "32.791", "32.805"],
        }
    ]


def test_bybit_settings_parse_symbols_and_default_depth():
    settings = Settings(
        ENABLE_COLLECTOR=False,
        BYBIT_TRADFI_SYMBOLS="USDTHB+,xauusd+",
        BYBIT_V5_SYMBOLS="BTCUSDT, ethusdt",
    )

    assert settings.bybit_tradfi_symbol_list == ["USDTHB+", "XAUUSD+"]
    assert settings.bybit_v5_symbol_list == ["BTCUSDT", "ETHUSDT"]
    assert settings.bybit_v5_depth_limit == 5
