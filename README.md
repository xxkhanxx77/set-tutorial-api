# Settrade Bid/Ask 10-Level Collector

Python service for Railway that subscribes to Settrade Open API realtime bid/offer data and saves the full 10-level order book to PostgreSQL.

The service also exposes a small HTTP API so Railway has a healthcheck target and you can inspect the latest saved order book.

## Why Python

Settrade provides an official Python SDK v2 (`settrade-v2`), and its realtime MQTT helpers already include:

- `Investor(...).RealtimeDataConnection()`
- `subscribe_bid_offer(symbol, on_message=...)`
- `subscribe_price_info(symbol, on_message=...)`
- `Investor(...).MarketData().get_candlestick(...)`

Using Python keeps the collector close to the official SDK examples and avoids reimplementing Settrade MQTT auth.

Official references:

- Bid/offer realtime: <https://developer.settrade.com/open-api/api-reference/reference/sdkv2/python/market-mqtt-realtime-data/3_subscribeBidOffer>
- Price info realtime: <https://developer.settrade.com/open-api/api-reference/reference/sdkv2/python/market-mqtt-realtime-data/2_subscribePriceInfo>
- Realtime getting started: <https://developer.settrade.com/open-api/api-reference/reference/sdkv2/python/market-mqtt-realtime-data/1_gettingStart>
- Historical candlestick: <https://developer.settrade.com/open-api/api-reference/reference/sdkv2/python/market-historical-data/2_getCandlestick>

## What Gets Saved

On every bid/offer event, the app inserts:

- One row in `bidask_snapshots`
- Twenty rows in `bidask_levels`: bid levels 1-10 and ask levels 1-10
- The raw Settrade payload as JSONB for debugging and future fields

If `SUBSCRIBE_PRICE_INFO=true`, price info events are saved to `price_info_ticks`.

Optional candlestick backfills are saved to `candlesticks`.

## Project Structure

```text
.
├── Procfile
├── railway.toml
├── runtime.txt
├── pyproject.toml
├── src/set_bidask_service/
│   ├── main.py              # FastAPI app and Railway web process
│   ├── collector.py         # Settrade realtime subscriber
│   ├── repository.py        # PostgreSQL inserts and queries
│   ├── schema.py            # Database tables and indexes
│   ├── transforms.py        # Bid/ask and candle payload parsing
│   └── backfill_candles.py  # Optional historical candlestick loader
└── tests/
```

## 1. Configure Environment Variables

Copy the example file for local development:

```bash
cp .env.example .env
```

Fill in `.env` locally and Railway variables in production:

```bash
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
SETTRADE_APP_ID=your_app_id
SETTRADE_APP_SECRET=your_app_secret
SETTRADE_APP_CODE=ALGO
SETTRADE_BROKER_ID=your_broker_id
SETTRADE_ENV=prod
SETTRADE_SYMBOLS=AOT,PTT
ENABLE_COLLECTOR=true
SUBSCRIBE_PRICE_INFO=true
SNAPSHOT_MIN_INTERVAL_MS=0
LOG_LEVEL=INFO
```

Notes:

- Do not commit `.env`.
- Use `SETTRADE_ENV=uat`, `SETTRADE_APP_CODE=SANDBOX`, and `SETTRADE_BROKER_ID=SANDBOX` for sandbox credentials.
- `SETTRADE_SYMBOLS` is comma-separated. Use only symbols your Settrade account can access.
- `SNAPSHOT_MIN_INTERVAL_MS=0` saves every bid/offer event. Increase it, for example to `250`, if the database write volume is too high.

## 2. Run Locally

Install dependencies:

```bash
uv sync
```

Start the service:

```bash
uv run uvicorn set_bidask_service.main:app --reload --host 0.0.0.0 --port 8000
```

If your environment has not installed the package yet, run with the source app directory explicitly:

```bash
uv run uvicorn --app-dir src set_bidask_service.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- <http://localhost:8000/health>
- <http://localhost:8000/ready>
- <http://localhost:8000/latest/AOT>
- <http://localhost:8000/docs>

The app creates tables automatically on startup when `DATABASE_URL` is configured. `/health` is a liveness endpoint for Railway and should return HTTP 200 as long as the web server is running. `/ready` checks database and Settrade configuration and returns HTTP 503 until required variables are present.

## 3. Deploy To Railway

Create a Railway project and attach PostgreSQL, or use an existing PostgreSQL URL.

Add the variables from step 1 in Railway:

```bash
railway variables set DATABASE_URL="postgresql://..."
railway variables set SETTRADE_APP_ID="..."
railway variables set SETTRADE_APP_SECRET="..."
railway variables set SETTRADE_APP_CODE="ALGO"
railway variables set SETTRADE_BROKER_ID="..."
railway variables set SETTRADE_ENV="prod"
railway variables set SETTRADE_SYMBOLS="AOT,PTT"
railway variables set ENABLE_COLLECTOR="true"
railway variables set SUBSCRIBE_PRICE_INFO="true"
```

Deploy:

```bash
railway up
```

Railway will run:

```bash
uvicorn --app-dir src set_bidask_service.main:app --host 0.0.0.0 --port $PORT
```

After deploy, check:

```bash
curl https://YOUR-RAILWAY-DOMAIN/health
curl https://YOUR-RAILWAY-DOMAIN/latest/AOT
```

Run only one Railway replica for the collector. Multiple replicas will subscribe and insert duplicate realtime rows.

## 4. Query PostgreSQL

Latest saved snapshot:

```sql
SELECT id, symbol, received_at, bid_flag, ask_flag
FROM bidask_snapshots
WHERE symbol = 'AOT'
ORDER BY received_at DESC
LIMIT 5;
```

Levels for one snapshot:

```sql
SELECT side, level, price, volume
FROM bidask_levels
WHERE snapshot_id = 123
ORDER BY side, level;
```

Best bid/ask over time:

```sql
SELECT
    s.symbol,
    s.received_at,
    MAX(CASE WHEN l.side = 'bid' AND l.level = 1 THEN l.price END) AS best_bid,
    MAX(CASE WHEN l.side = 'ask' AND l.level = 1 THEN l.price END) AS best_ask
FROM bidask_snapshots s
JOIN bidask_levels l ON l.snapshot_id = s.id
WHERE s.symbol = 'AOT'
GROUP BY s.id, s.symbol, s.received_at
ORDER BY s.received_at DESC
LIMIT 100;
```

## 5. Optional Candlestick Backfill

Fetch historical candles through Settrade SDK and save them to the `candlesticks` table:

```bash
uv run python -m set_bidask_service.backfill_candles \
  --symbol AOT \
  --interval 1m \
  --limit 500
```

With a date range:

```bash
uv run python -m set_bidask_service.backfill_candles \
  --symbol AOT \
  --interval 1m \
  --start "2026-06-01T00:00:00+07:00" \
  --end "2026-06-11T23:59:59+07:00"
```

## 6. Local Checks

```bash
uv run pytest
uv run ruff check .
```
