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

CREATE TABLE IF NOT EXISTS bidask_levels (
    snapshot_id BIGINT NOT NULL REFERENCES bidask_snapshots(id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK (side IN ('bid', 'ask')),
    level SMALLINT NOT NULL CHECK (level BETWEEN 1 AND 10),
    price NUMERIC(20, 8),
    volume BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, side, level)
);

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
"""

