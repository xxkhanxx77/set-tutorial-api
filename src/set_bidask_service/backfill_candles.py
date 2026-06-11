from __future__ import annotations

import argparse
import logging

from settrade_v2 import Investor
from settrade_v2.config import config as settrade_config

from set_bidask_service.config import get_settings
from set_bidask_service.db import create_pool, init_schema
from set_bidask_service.repository import MarketRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Settrade candlesticks into PostgreSQL.")
    parser.add_argument("--symbol", required=True, help="Symbol, for example AOT or USDM26.")
    parser.add_argument(
        "--interval",
        default="1m",
        help="Candlestick interval: 1m, 3m, 5m, 10m, 15m, 30m, 60m, 120m, 240m, 1d, 1w, 1M.",
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--start",
        default=None,
        help="Optional start datetime accepted by Settrade.",
    )
    parser.add_argument("--end", default=None, help="Optional end datetime accepted by Settrade.")
    parser.add_argument("--normalized", action="store_true")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required for candlestick backfill")
    if settings.missing_settrade_vars:
        missing = ", ".join(settings.missing_settrade_vars)
        raise SystemExit(f"Missing Settrade configuration: {missing}")

    settrade_config["environment"] = settings.settrade_env

    pool = create_pool(settings.database_url)
    pool.open()
    try:
        init_schema(pool)
        investor = Investor(
            app_id=settings.settrade_app_id,
            app_secret=settings.settrade_app_secret,
            app_code=settings.settrade_app_code,
            broker_id=settings.settrade_broker_id,
            is_auto_queue=True,
        )
        payload = investor.MarketData().get_candlestick(
            symbol=args.symbol.upper(),
            interval=args.interval,
            limit=args.limit,
            start=args.start,
            end=args.end,
            normalized=args.normalized or None,
        )
        saved = MarketRepository(pool).save_candlesticks(payload, args.symbol, args.interval)
        logging.info("Saved %s candlesticks for %s %s", saved, args.symbol.upper(), args.interval)
    finally:
        pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
