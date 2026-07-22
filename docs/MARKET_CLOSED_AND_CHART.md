# Market Closed Data and Selected-Ticker Chart

This update keeps the selected ticker useful outside regular market hours.

## Behavior

- The UI states when the regular market is closed.
- The latest completed market price, change, volume, day range, previous close, and timestamp remain visible.
- The selected ticker has a chart with 1-month, 3-month, 6-month, 1-year, and 5-year views.
- The chart uses completed daily bars and identifies the last data timestamp.
- Period low/high and 52-week low/high are displayed.
- Missing provider data is shown as unavailable and does not create a trade recommendation.

## API

`GET /api/market/history/{symbol}?period=1y`

Supported periods: `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, `max`.
