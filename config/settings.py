"""Typed configuration loaded from .env via pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All runtime configuration for tradebot.

    Required keys without defaults must be present in .env or the environment
    before any module instantiates this class.
    """

    # Interactive Brokers
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1
    ibkr_readonly_key: str = ""
    ibkr_trading_key: str = ""

    # Alpaca (data-only in prototype phase)
    alpaca_api_key: str = Field(..., min_length=1)
    alpaca_secret_key: str = Field(..., min_length=1)
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    # Finnhub
    finnhub_api_key: str = Field(..., min_length=1)

    # Telegram alerting
    telegram_bot_token: str = Field(..., min_length=1)
    telegram_chat_id: str = Field(..., min_length=1)

    # Healthchecks.io
    healthchecks_url: str = ""

    # Paths (Docker-internal defaults)
    data_path: str = "/data"
    model_path: str = "/data/models"

    # Risk parameters
    max_positions: int = 10
    max_position_pct: float = 0.08
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    holding_days: int = 5

    # Regime gate
    vix_bear_threshold: float = 25.0

    model_config = {"env_file": ".env", "case_sensitive": False}


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()  # type: ignore[call-arg]
