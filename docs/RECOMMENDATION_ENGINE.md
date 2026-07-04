# Recommendation Engine

This build replaces placeholder recommendations with a modular evidence-based scoring engine.

## What the backend now does

For each symbol, `/api/ai/analyze` and `/api/ai/recommendations` now:

1. Pull delayed live market data through `yfinance` when available.
2. Pull delayed quote data, OHLCV price history, and option-chain data.
3. Calculate technical indicators from real OHLCV data:
   - EMA 9, EMA 21, EMA 50, EMA 200
   - RSI
   - MACD line, signal, and histogram
   - VWAP relationship
   - ATR
   - Bollinger Bands
   - 20-day support/resistance
   - volume ratio versus 20-day average
4. Evaluate rules through a modular scoring system:
   - Technical score
   - Options-liquidity score
   - Market-context score
   - Risk score
5. Build structured evidence objects.
6. Return `NO_TRADE` when required evidence is missing, risk rules fail, or confidence is below the user threshold.
7. Display the evidence and score breakdown in the web UI.

## Important limitations

Yahoo/yfinance can be delayed, incomplete, throttled, or missing Greeks. Because of that:

- The engine treats missing live data as a hard failure.
- The engine returns `NO_TRADE` if required data cannot be verified.
- Yahoo options data does not provide complete Greeks, so delta is approximated from moneyness and clearly marked as part of options evidence.
- This is still decision-support software, not financial advice.

## Main files

- `backend/app/services/scoring_engine.py` — modular evidence scoring rules.
- `backend/app/services/ai_engine.py` — recommendation orchestration and strict NO_TRADE logic.
- `backend/app/services/indicators.py` — real OHLCV technical indicator calculations.
- `backend/app/models/schemas.py` — structured evidence and score-breakdown response models.
- `web/src/App.jsx` — displays score breakdown and evidence cards.

## Test endpoints

Backend:

```text
/api/health
/api/market/quote/AAPL
/api/market/options/AAPL
/api/ai/recommendations
```

Use POST `/api/ai/analyze` with:

```json
{
  "symbol": "AAPL",
  "account_value": 10000,
  "strategy": "auto",
  "min_confidence": 75,
  "max_risk_percent": 1
}
```
