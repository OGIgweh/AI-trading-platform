# AI Trading Platform Starter

A full-stack, risk-first trading decision-support platform with resilient market-data fallbacks.

## Includes

- FastAPI backend deployed under `/api`
- React web dashboard
- Expo React Native mobile app
- AI decision engine that defaults to `NO_TRADE`
- Multi-provider stock/ETF quotes and history
- Options chains from Tradier when configured, with Yahoo best-effort fallback
- Order preview with live trading blocked by default
- Render deployment helpers
- EAS mobile build configuration

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Test:

```text
http://localhost:8000/api/health
http://localhost:8000/docs
```

## Mobile

```bash
cd mobile
npm install
npm install -g eas-cli
eas login
eas build:configure
eas build --profile preview --platform ios
```

For Android:

```bash
eas build --profile preview --platform android
```

The mobile backend URL is in `mobile/app.json`:

```json
"extra": { "apiUrl": "https://ai-trading-platform-vdm6.onrender.com/api" }
```

## Web

```bash
cd web
npm ci
npm run dev
```

Start the backend on port 8000 first. Vite proxies `/api` to it. For a
separately hosted backend, set `VITE_API_URL` to its full API URL including
`/api` before starting or building the web app. For mobile, set
`EXPO_PUBLIC_API_URL` or update `extra.apiUrl` in `mobile/app.json`.

The evidence score is a heuristic on a 0–100 scale. Recommendations require
timestamped quotes and the latest completed regular session of daily history.
Stock sizing uses a planned stop, and realized losses can exceed that amount.

## Safety

This project is a starter decision-support application. Live trading is blocked by design. Do not use it for real trading without broker integration, data validation, security review, paper-trading validation, and compliance review.

## AI Recommendations Added

This build includes backend-powered recommendation endpoints:

- `POST /api/ai/analyze` - analyzes one ticker and returns CALL, PUT, or NO_TRADE.
- `GET /api/ai/recommendations` - returns default watchlist recommendations.
- `POST /api/ai/recommendations` - analyzes a custom watchlist.

The web dashboard now displays a Recent AI Recommendations panel, confidence scores, entry/stop/targets when a setup qualifies, risk notes, and the evidence payload used to generate the decision.

The default `auto` mode uses an independent completed-daily fallback so valid tickers do not become `$0.00` when Yahoo rate-limits the Render service. Configure a Tradier token for reliable delayed/real-time quotes and option chains. Live trading remains disabled.

## Broker-Entry Options Ticket

Qualified CALL/PUT recommendations now include a structured `suggested_order` object and a mobile-friendly broker-entry ticket in the AI Trading Assistant. It displays Action, Quantity, Expiration, Strike, Call/Put, Bid/Mid/Ask, Order Type, Limit Price, Timing, Special Instructions, estimated amount, contract symbol, and the suggested exit plan. NO TRADE decisions never generate an order ticket.

- Search and analyze any provider-supported stock or ETF by ticker or company name.

## Resilient Universal Ticker Search

The current build treats autocomplete as optional. Exact ticker entries are independently verified through multiple delayed Yahoo Finance data paths with retries. Temporary provider failures return a provider-unavailable/NO-TRADE state instead of falsely claiming that a valid ticker does not exist. Common class-share and international ticker formats are supported, including `BRK.B`, `BRK-B`, `7203.T`, and `SHOP.TO`.

## Recommendation qualification update

The recommendation engine now supports user-configurable account/risk settings and defined-risk debit-spread fallback when a single long option cannot fit the configured risk budget. See `docs/RECOMMENDATION_QUALIFICATION_FIX.md`.


## Market-data reliability update

The backend no longer treats Yahoo Finance as a single point of failure. In `auto` mode it prefers Tradier when configured, uses Stooq completed daily data as an independent keyless fallback, and keeps Yahoo as a best-effort secondary source. The UI clearly identifies end-of-day fallback data. If options are unavailable but verified stock data qualifies, the engine may produce a defined-risk stock ticket instead of inventing an options contract. See `docs/MARKET_DATA_PROVIDER_FALLBACK_FIX.md`.

## Quote Provider and Schwab Naming Update

- Uses Tradier when configured, then Yahoo public chart data, Stooq completed daily data, and yfinance as a final fallback.
- Provider failures display **Unavailable**, never a fabricated `$0.00` quote.
- Options tickets use Schwab labels: **Call**, **Put**, **Vertical Call**, and **Vertical Put**.
- Unsupported Schwab strategies are not fabricated or displayed as available recommendations.


## Recommendation Type Selector

The web and mobile clients now expose **Options**, **Stock**, and **Auto** modes:

- **Options:** options-only. Missing verified option-chain data returns `NO_TRADE`; stock is never substituted.
- **Stock:** shares-only. The backend does not request or use an option chain.
- **Auto:** evaluates options first and may use a defined-risk stock setup only when verified options data is unavailable.


## Option Trade Structure
Options and Auto modes include a strict **Single Leg / Multi Leg / Best Fit** selector. Single Leg permits Call/Put only; Multi Leg currently permits verified Vertical Call/Vertical Put debit spreads only; Best Fit can choose either.

## Probability-sensitive option qualification
The options engine now checks moneyness, DTE, IV-implied expected move, break-even distance, directional delta, and time-decay exposure before producing a broker ticket. The displayed AI confidence is evidence alignment, not probability of profit. See `docs/PROBABILITY_SENSITIVE_OPTION_QUALIFICATION.md`.

## Social / Whale Intelligence

This build adds a supplemental crypto social-intelligence layer. It can ingest an authorized Invo/export JSON endpoint when configured and can independently evaluate explicitly configured Hyperliquid public wallets through Hyperliquid's public info API.

The dashboard exposes BTC, ETH, SOL, HYPE, and ARB consensus with weighted win-rate/sample-size qualification. The signal is deliberately isolated from equity/equity-option confidence: crypto trader activity does not inflate AAPL/SPY/etc. recommendations.

Configuration is documented in `docs/SOCIAL_WHALE_INTELLIGENCE.md` and `backend/.env.example`.

## Verified Strategy Intelligence

The platform includes an AlphaLedger-ready verified strategy adapter. It scores authorized strategy records using Alpha Score, Sharpe ratio, maximum drawdown, track-record duration, ownership validation, and audit status. Historical performance alone is informational; recommendation confidence can change only when an authorized feed explicitly reports qualified current exposure to the same analyzed ticker. See `docs/VERIFIED_STRATEGY_INTELLIGENCE.md`.
