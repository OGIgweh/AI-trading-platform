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

    # Supplemental social/whale intelligence. Invo is only used through an
    # explicitly configured authorized/export JSON endpoint; the application
    # does not scrape undocumented Invo APIs. Hyperliquid uses its public info
    # API for wallet addresses the user explicitly chooses to track.
    social_intelligence_enabled: bool = True
    invo_social_api_url: str = ""
    invo_api_token: str = ""
    hyperliquid_api_url: str = "https://api.hyperliquid.xyz/info"
    social_hyperliquid_wallets: str = ""
    social_min_closed_trades: int = 20
    social_min_win_rate: float = 0.55
    social_max_traders: int = 25
    social_fill_lookback: int = 300
    social_max_score_adjustment: int = 8
    social_data_cache_seconds: int = 300
    social_data_timeout_seconds: float = 8.0

    # Verified Strategy Intelligence (AlphaLedger). Only an explicitly configured
    # authorized/export JSON endpoint is used; undocumented endpoints are not scraped.
    verified_strategy_intelligence_enabled: bool = True
    alphaledger_api_url: str = ""
    alphaledger_api_token: str = ""
    alphaledger_min_alpha_score: float = 60.0
    alphaledger_min_sharpe: float = 0.50
    alphaledger_max_drawdown_percent: float = 40.0
    alphaledger_min_track_record_days: int = 60
    alphaledger_min_relevant_strategies: int = 2
    alphaledger_max_score_adjustment: int = 6
    alphaledger_data_cache_seconds: int = 300
    alphaledger_timeout_seconds: float = 8.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
