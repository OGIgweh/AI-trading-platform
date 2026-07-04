from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "AI Trading Platform"
    app_env: str = "development"
    live_trading_enabled: bool = False
    cors_origins: str = "*"

    # Market data configuration
    # "yfinance" = free delayed market data best-effort provider.
    # "sample" = deterministic demo data.
    # "auto" = try yfinance, then fall back to sample.
    market_data_provider: str = "auto"
    market_data_cache_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
