# Market Data Provider Fallback Fix

## Problem fixed

The deployed Render service could be rate-limited or blocked by Yahoo Finance. The previous implementation converted that provider failure into a `$0.00` quote for every ticker, even though the ticker itself was valid.

## New provider order

When `MARKET_DATA_PROVIDER=auto`, the backend now uses:

1. **Tradier**, when `TRADIER_API_TOKEN` is configured.
2. **Stooq completed daily data** for a keyless independent stock/ETF quote and history fallback.
3. **Yahoo Finance** as a best-effort secondary provider and options fallback.

The Stooq fallback is deliberately labeled `stooq_eod`. It is the latest completed daily bar, not an intraday executable quote.

## Recommendations when options are unavailable

The platform never fabricates an option chain. If verified stock history and market context qualify but no verified option chain is available, the engine can produce a defined-risk **BUY** or **SHORT** stock setup with:

- share quantity,
- limit price,
- stop loss,
- two profit targets,
- estimated notional amount,
- planned dollar risk.

An options recommendation still requires a verified option chain. Configure Tradier for reliable stock and options data.

## Render environment variables

```text
MARKET_DATA_PROVIDER=auto
MARKET_DATA_CACHE_SECONDS=60
MARKET_DATA_RETRIES=2
MARKET_DATA_TIMEOUT_SECONDS=12
STOOQ_FALLBACK_ENABLED=true

# Optional but recommended for quotes, history, and option chains
TRADIER_API_TOKEN=
TRADIER_SANDBOX=true
TRADIER_BASE_URL=
```

Use `TRADIER_SANDBOX=true` with the paper/sandbox token for delayed testing data. Use a production token and set `TRADIER_SANDBOX=false` only when you are entitled to production data. Live order submission remains disabled in this project.

## Diagnostics

```text
GET /api/market/providers
```

This reports the configured provider mode, whether Tradier is configured, whether the independent fallback is enabled, and the provider priority.
