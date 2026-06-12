SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bidask_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'settrade',
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    bid_flag TEXT,
    ask_flag TEXT,
    raw JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bidask_snapshots_symbol_received_at
    ON bidask_snapshots (symbol, received_at DESC);

DROP VIEW IF EXISTS latest_bidask_10_levels;
DROP VIEW IF EXISTS latest_bidask_snapshots;
DROP VIEW IF EXISTS latest_quote_ticks;

CREATE TABLE IF NOT EXISTS bidask_levels (
    snapshot_id BIGINT NOT NULL REFERENCES bidask_snapshots(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK (side IN ('bid', 'ask')),
    level SMALLINT NOT NULL CHECK (level BETWEEN 1 AND 10),
    price NUMERIC(20, 8),
    volume NUMERIC(28, 8) NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, side, level)
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'bidask_levels'
          AND column_name = 'volume'
          AND data_type <> 'numeric'
    ) THEN
        ALTER TABLE bidask_levels
            ALTER COLUMN volume TYPE NUMERIC(28, 8)
            USING volume::NUMERIC(28, 8);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bidask_levels_snapshot_side_level
    ON bidask_levels (snapshot_id, side, level);

CREATE TABLE IF NOT EXISTS price_info_ticks (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'settrade',
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    projected_open_price NUMERIC(20, 8),
    projected_open_volume BIGINT,
    high NUMERIC(20, 8),
    low NUMERIC(20, 8),
    last NUMERIC(20, 8),
    change NUMERIC(20, 8),
    total_volume BIGINT,
    total_value NUMERIC(24, 8),
    market_status TEXT,
    raw JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_info_ticks_symbol_received_at
    ON price_info_ticks (symbol, received_at DESC);

CREATE TABLE IF NOT EXISTS quote_ticks (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    source TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    bid NUMERIC(20, 8),
    ask NUMERIC(20, 8),
    last NUMERIC(20, 8),
    open NUMERIC(20, 8),
    high NUMERIC(20, 8),
    low NUMERIC(20, 8),
    close NUMERIC(20, 8),
    change NUMERIC(20, 8),
    spread NUMERIC(20, 8),
    raw JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quote_ticks_source_symbol_received_at
    ON quote_ticks (source, symbol, received_at DESC);

CREATE TABLE IF NOT EXISTS candlesticks (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    candle_time TIMESTAMPTZ NOT NULL,
    open NUMERIC(20, 8),
    high NUMERIC(20, 8),
    low NUMERIC(20, 8),
    close NUMERIC(20, 8),
    volume BIGINT,
    value NUMERIC(24, 8),
    last_sequence BIGINT,
    raw JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, interval, candle_time)
);

CREATE INDEX IF NOT EXISTS idx_candlesticks_symbol_interval_time
    ON candlesticks (symbol, interval, candle_time DESC);

CREATE OR REPLACE VIEW latest_quote_ticks AS
SELECT DISTINCT ON (source, symbol)
    id,
    symbol,
    source,
    received_at,
    bid,
    ask,
    last,
    open,
    high,
    low,
    close,
    change,
    spread,
    raw
FROM quote_ticks
ORDER BY source, symbol, received_at DESC;

CREATE OR REPLACE VIEW latest_bidask_snapshots AS
WITH latest AS (
    SELECT DISTINCT ON (source, symbol)
        id,
        symbol,
        source,
        received_at,
        bid_flag,
        ask_flag
    FROM bidask_snapshots
    ORDER BY source, symbol, received_at DESC
)
SELECT
    latest.id AS snapshot_id,
    latest.symbol,
    latest.source,
    latest.received_at,
    latest.bid_flag,
    latest.ask_flag,
    MAX(levels.price) FILTER (WHERE levels.side = 'bid' AND levels.level = 1) AS best_bid,
    MAX(levels.volume) FILTER (WHERE levels.side = 'bid' AND levels.level = 1) AS best_bid_volume,
    MAX(levels.price) FILTER (WHERE levels.side = 'ask' AND levels.level = 1) AS best_ask,
    MAX(levels.volume) FILTER (WHERE levels.side = 'ask' AND levels.level = 1) AS best_ask_volume
FROM latest
LEFT JOIN bidask_levels levels ON levels.snapshot_id = latest.id
GROUP BY
    latest.id,
    latest.symbol,
    latest.source,
    latest.received_at,
    latest.bid_flag,
    latest.ask_flag;

CREATE OR REPLACE VIEW latest_bidask_10_levels AS
WITH latest AS (
    SELECT DISTINCT ON (source, symbol)
        id,
        symbol,
        source,
        received_at,
        bid_flag,
        ask_flag
    FROM bidask_snapshots
    ORDER BY source, symbol, received_at DESC
),
levels AS (
    SELECT generate_series(1, 10)::SMALLINT AS level
)
SELECT
    latest.id AS snapshot_id,
    latest.symbol,
    latest.source,
    latest.received_at,
    latest.bid_flag,
    latest.ask_flag,
    levels.level,
    bid.price AS bid_price,
    bid.volume AS bid_volume,
    ask.price AS ask_price,
    ask.volume AS ask_volume
FROM latest
CROSS JOIN levels
LEFT JOIN bidask_levels bid
    ON bid.snapshot_id = latest.id
    AND bid.side = 'bid'
    AND bid.level = levels.level
LEFT JOIN bidask_levels ask
    ON ask.snapshot_id = latest.id
    AND ask.side = 'ask'
    AND ask.level = levels.level
ORDER BY latest.source, latest.symbol, levels.level;
"""
