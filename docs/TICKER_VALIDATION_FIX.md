# Resilient Ticker Search and Validation

This build separates **autocomplete** from **ticker verification**.

## Behavior

- Exact ticker entry is always sent to the analysis endpoint, even if autocomplete is empty.
- Common broker formats are normalized (`BRK.B` and `BRK/B` become `BRK-B`).
- International Yahoo symbols such as `7203.T` and `SHOP.TO` remain intact.
- Quote verification tries multiple yfinance data paths with configurable retries.
- Temporary provider, network, and rate-limit failures are reported as provider unavailability—not as a nonexistent ticker.
- A ticker receives a `not_found` result only after the provider returns no usable quote and no exact search confirmation.
- The web app analyzes one selected ticker at a time instead of automatically hammering the provider with every saved symbol.

## Render environment

```text
MARKET_DATA_PROVIDER=auto
MARKET_DATA_CACHE_SECONDS=60
MARKET_DATA_RETRIES=2
```

Autocomplete is a convenience only. It is not an authorization list and never blocks direct ticker analysis.
