from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "AI Trading Platform"
    app_env: str = "development"
    live_trading_enabled: bool = False
    cors_origins: str = "*"

    # Market data configuration
    # "yfinance" = free delayed market data best-effort provider.
    # "sample" = deterministic demo data.
    # "auto" = Tradier (if configured), direct Yahoo chart, Stooq, then yfinance; never substitute sample values for live analysis.
    market_data_provider: str = "auto"
    market_data_cache_seconds: int = 60
    market_data_retries: int = 2
    market_data_timeout_seconds: float = 12.0

    # Optional production-grade provider. Tradier supplies stock/ETF quotes,
    # historical prices, and option chains. Sandbox tokens return delayed data.
    tradier_api_token: str = ""
    tradier_sandbox: bool = True
    tradier_base_url: str = ""

    # Independent keyless fallback for completed daily US stock/ETF prices.
    # This prevents a Yahoo/Render rate limit from turning every valid quote into $0.
    stooq_fallback_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
