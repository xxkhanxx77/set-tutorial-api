from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    settrade_app_id: str | None = Field(default=None, alias="SETTRADE_APP_ID")
    settrade_app_secret: str | None = Field(default=None, alias="SETTRADE_APP_SECRET")
    settrade_app_code: str | None = Field(default=None, alias="SETTRADE_APP_CODE")
    settrade_broker_id: str | None = Field(default=None, alias="SETTRADE_BROKER_ID")
    settrade_env: Literal["prod", "uat"] = Field(default="prod", alias="SETTRADE_ENV")

    settrade_symbols: str = Field(default="", alias="SETTRADE_SYMBOLS")
    settrade_symbol: str | None = Field(default=None, alias="SETTRADE_SYMBOL")

    enable_collector: bool = Field(default=True, alias="ENABLE_COLLECTOR")
    subscribe_price_info: bool = Field(default=True, alias="SUBSCRIBE_PRICE_INFO")
    snapshot_min_interval_ms: int = Field(default=0, alias="SNAPSHOT_MIN_INTERVAL_MS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    enable_binance_th_collector: bool = Field(default=False, alias="ENABLE_BINANCE_TH_COLLECTOR")
    binance_th_symbols: str = Field(default="", alias="BINANCE_TH_SYMBOLS")
    binance_th_depth_limit: int = Field(default=10, alias="BINANCE_TH_DEPTH_LIMIT")
    binance_th_poll_interval_seconds: float = Field(
        default=1.0,
        alias="BINANCE_TH_POLL_INTERVAL_SECONDS",
    )

    @field_validator(
        "database_url",
        "settrade_app_id",
        "settrade_app_secret",
        "settrade_app_code",
        "settrade_broker_id",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: str | None) -> str | None:
        if value == "":
            return None
        return value

    @field_validator("snapshot_min_interval_ms")
    @classmethod
    def validate_snapshot_interval(cls, value: int) -> int:
        if value < 0:
            raise ValueError("SNAPSHOT_MIN_INTERVAL_MS must be zero or greater")
        return value

    @field_validator("binance_th_depth_limit")
    @classmethod
    def validate_binance_th_depth_limit(cls, value: int) -> int:
        if value < 1 or value > 10:
            raise ValueError("BINANCE_TH_DEPTH_LIMIT must be between 1 and 10")
        return value

    @field_validator("binance_th_poll_interval_seconds")
    @classmethod
    def validate_binance_th_poll_interval(cls, value: float) -> float:
        if value < 0.25:
            raise ValueError("BINANCE_TH_POLL_INTERVAL_SECONDS must be at least 0.25")
        return value

    @property
    def symbols(self) -> list[str]:
        raw = self.settrade_symbols or self.settrade_symbol or ""
        symbols = [symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()]
        return list(dict.fromkeys(symbols))

    @property
    def binance_symbols(self) -> list[str]:
        symbols = [
            symbol.strip().upper()
            for symbol in self.binance_th_symbols.split(",")
            if symbol.strip()
        ]
        return list(dict.fromkeys(symbols))

    @property
    def missing_settrade_vars(self) -> list[str]:
        missing = []
        if not self.settrade_app_id:
            missing.append("SETTRADE_APP_ID")
        if not self.settrade_app_secret:
            missing.append("SETTRADE_APP_SECRET")
        if not self.settrade_app_code:
            missing.append("SETTRADE_APP_CODE")
        if not self.settrade_broker_id:
            missing.append("SETTRADE_BROKER_ID")
        if not self.symbols:
            missing.append("SETTRADE_SYMBOLS")
        return missing

    @property
    def can_start_collector(self) -> bool:
        return bool(self.database_url) and not self.missing_settrade_vars


@lru_cache
def get_settings() -> Settings:
    return Settings()
