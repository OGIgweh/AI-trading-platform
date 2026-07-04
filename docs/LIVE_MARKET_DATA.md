# Live Market Data Setup

This version tries to use `yfinance` for delayed stock quotes, options chains, and OHLCV history. If Yahoo/yfinance fails or the symbol has missing data, the app falls back to sample data and clearly marks the result as `sample_or_partial`.

## Render environment variable

Set this on the backend Web Service:

```text
MARKET_DATA_PROVIDER=auto
```

Options:

```text
auto      Try yfinance first, fallback to sample if unavailable.
yfinance  Require yfinance best-effort data path, but still fallback for UI safety.
sample    Force demo/sample mode.
```

## Important limitations

`yfinance` is useful for prototyping, but it is not a professional trading data feed. Before real trading, replace it with a provider such as Polygon, Tradier, Alpaca, ORATS, ThetaData, or Interactive Brokers and verify exchange permissions, latency, options Greeks, corporate actions, and data entitlements.

## How to test

After redeploying the backend, open:

```text
/api/market/quote/AAPL
/api/market/options/AAPL
/api/ai/analyze
/api/ai/recommendations
```

Look for:

```json
"data_source": "yfinance_delayed"
```

If you see `sample` or `sample_or_partial`, the provider did not return enough usable data for that request.
