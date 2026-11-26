# Verified Strategy Intelligence (AlphaLedger adapter)

This build adds a separate **Verified Strategy Intelligence** layer beside Social / Whale Intelligence.

## Why it is separate

Invo/Hyperliquid data is used for active trader-position consensus, primarily for crypto. AlphaLedger-style data is evaluated as verified strategy quality: Alpha Score, Sharpe ratio, maximum drawdown, track-record length, ownership validation, audit status, and — only when supplied by an authorized data feed — current asset exposure.

A strong historical track record is **not** treated as a directional signal by itself.

## Data-access policy

The application does not scrape undocumented AlphaLedger endpoints. Configure an authorized/export JSON endpoint only:

```env
VERIFIED_STRATEGY_INTELLIGENCE_ENABLED=true
ALPHALEDGER_API_URL=
ALPHALEDGER_API_TOKEN=
```

The adapter sends a GET request to `ALPHALEDGER_API_URL` with `?symbol=AAPL` (or the selected symbol) and an optional bearer token.

## Supported JSON shape

The endpoint may return a list directly or an object containing `strategies`, `results`, `data`, `accounts`, or `leaderboard`.

Example:

```json
{
  "strategies": [
    {
      "strategy_name": "Example Strategy",
      "provider": "Example Manager",
      "alpha_score": 84,
      "total_return_percent": 21.4,
      "sharpe_ratio": 1.62,
      "max_drawdown_percent": 11.8,
      "calmar_ratio": 1.3,
      "performance_days": 420,
      "ownership_validated": true,
      "audit_status": "active",
      "positions": [
        {"symbol": "AAPL", "direction": "LONG", "weight": 0.35}
      ]
    }
  ]
}
```

## Quality gate

Defaults:

- Minimum Alpha Score: 60
- Minimum Sharpe ratio: 0.50
- Maximum drawdown: 40%
- Minimum track record: 60 days
- Ownership validation required
- Audit status adds quality weight but is not required

The quality score is deliberately risk-adjusted; high return alone does not qualify a strategy.

## Confidence adjustment

Historical metrics are always supplemental. The recommendation engine changes its evidence-alignment confidence only when:

1. the strategy passes the quality gate;
2. the authorized feed reports a current position/exposure for the **same ticker** being analyzed;
3. at least the configured number of relevant strategies are present; and
4. their directional consensus is strong enough.

The adjustment is capped by `ALPHALEDGER_MAX_SCORE_ADJUSTMENT` (default ±6 points). It can never create a trade by itself and does not override NO TRADE data-quality, liquidity, probability-sensitive options, or risk gates.

## API endpoints

```text
GET /api/verified-strategy/providers
GET /api/verified-strategy/intelligence/AAPL
```

## Render environment variables

```env
VERIFIED_STRATEGY_INTELLIGENCE_ENABLED=true
ALPHALEDGER_API_URL=
ALPHALEDGER_API_TOKEN=
ALPHALEDGER_MIN_ALPHA_SCORE=60
ALPHALEDGER_MIN_SHARPE=0.50
ALPHALEDGER_MAX_DRAWDOWN_PERCENT=40
ALPHALEDGER_MIN_TRACK_RECORD_DAYS=60
ALPHALEDGER_MIN_RELEVANT_STRATEGIES=2
ALPHALEDGER_MAX_SCORE_ADJUSTMENT=6
ALPHALEDGER_DATA_CACHE_SECONDS=300
```
