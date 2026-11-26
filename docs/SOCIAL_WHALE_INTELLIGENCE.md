# Social / Whale Intelligence

The platform now includes a supplemental crypto social-intelligence provider layer.

## Invo

Invo publicly describes verified track records, green/red trades, total return, open positions, live P&L, entry price, leverage, take-profit/stop-loss, and mimic functionality. The platform **does not scrape undocumented Invo endpoints**. Instead it supports an authorized/export JSON endpoint configured with:

- `INVO_SOCIAL_API_URL`
- `INVO_API_TOKEN` (optional bearer token)

The adapter accepts a normalized list under `traders`, `results`, `data`, or a top-level array. Useful fields include handle/username, win rate, green/red/closed trades, ROI, asset, direction, entry price, P&L, leverage, position size, and wallet.

## Hyperliquid public fallback

Because Invo states that its futures product is Hyperliquid-powered, the project can independently analyze public Hyperliquid wallets that the user explicitly chooses to track. Configure comma-separated addresses in `SOCIAL_HYPERLIQUID_WALLETS`.

The service calls Hyperliquid's public `/info` endpoint for `clearinghouseState` and `userFills` and derives:

- active LONG/SHORT direction for the requested asset
- sample win rate from closed P&L fills
- number of closed trades in the sample
- current unrealized P&L and leverage when available

No wallet is added automatically and no private keys are ever used.

## Scoring

Only traders meeting both configured gates are weighted:

- minimum closed trades (default 20)
- minimum win rate (default 55%)

Consensus is weighted by sample size and win rate. The result contains a 0-100 directional score, consensus label, coverage/confidence, and top qualifying traders.

This signal is deliberately **supplemental**. It never creates a trade by itself. Crypto social data is not applied to equity or equity-option confidence scores. The helper for a bounded confidence adjustment (default maximum ±8 points) activates only for an asset-matched crypto signal with enough verified coverage.
