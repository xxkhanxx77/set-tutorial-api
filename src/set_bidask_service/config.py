from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")

    settrade_app_id: str = Field(alias="SETTRADE_APP_ID")
    settrade_app_secret: str = Field(alias="SETTRADE_APP_SECRET")
    settrade_app_code: str = Field(alias="SETTRADE_APP_CODE")
    settrade_broker_id: str = Field(alias="SETTRADE_BROKER_ID")
    settrade_env: Literal["prod", "uat"] = Field(default="prod", alias="SETTRADE_ENV")

    settrade_symbols: str = Field(default="", alias="SETTRADE_SYMBOLS")
    settrade_symbol: str | None = Field(default=None, alias="SETTRADE_SYMBOL")

    enable_collector: bool = Field(default=True, alias="ENABLE_COLLECTOR")
    subscribe_price_info: bool = Field(default=True, alias="SUBSCRIBE_PRICE_INFO")
    snapshot_min_interval_ms: int = Field(default=0, alias="SNAPSHOT_MIN_INTERVAL_MS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("snapshot_min_interval_ms")
    @classmethod
    def validate_snapshot_interval(cls, value: int) -> int:
        if value < 0:
            raise ValueError("SNAPSHOT_MIN_INTERVAL_MS must be zero or greater")
        return value

    @property
    def symbols(self) -> list[str]:
        raw = self.settrade_symbols or self.settrade_symbol or ""
        symbols = [symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()]
        if not symbols:
            raise ValueError("Set SETTRADE_SYMBOLS to at least one symbol")
        return list(dict.fromkeys(symbols))


@lru_cache
def get_settings() -> Settings:
    return Settings()

