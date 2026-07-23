# Price Chart Provider Fix

The chart is not disabled when the market is closed. Daily OHLCV history is valid after hours and on weekends.

This update fixes two causes of an empty chart:

1. The AI indicator engine and chart endpoint were downloading the same Yahoo history independently, which could trigger a second-request rate limit.
2. Optional yfinance keyword arguments can differ across versions and could cause chart-only requests to fail.

The backend now caches verified history, reuses the one-year indicator dataset for 1/3/6-month charts, slices those ranges locally, and falls back through version-compatible history/download calls.
