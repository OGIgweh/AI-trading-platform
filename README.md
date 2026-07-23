# AI Trading Platform Starter

A working full-stack starter for a risk-first AI trading assistant.

## Includes

- FastAPI backend deployed under `/api`
- React web dashboard
- Expo React Native mobile app
- AI decision engine that defaults to `NO_TRADE`
- Sample market data and options chain data
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
npm install
npm run dev
```

## Safety

This project is a starter decision-support application. Live trading is blocked by design. Do not use it for real trading without broker integration, data validation, security review, paper-trading validation, and compliance review.

## AI Recommendations Added

This build includes backend-powered recommendation endpoints:

- `POST /api/ai/analyze` - analyzes one ticker and returns CALL, PUT, or NO_TRADE.
- `GET /api/ai/recommendations` - returns default watchlist recommendations.
- `POST /api/ai/recommendations` - analyzes a custom watchlist.

The web dashboard now displays a Recent AI Recommendations panel, confidence scores, entry/stop/targets when a setup qualifies, risk notes, and the evidence payload used to generate the decision.

Important: this build still uses sample market data until you connect a real market data provider. Live trading remains disabled.

## Broker-Entry Options Ticket

Qualified CALL/PUT recommendations now include a structured `suggested_order` object and a mobile-friendly broker-entry ticket in the AI Trading Assistant. It displays Action, Quantity, Expiration, Strike, Call/Put, Bid/Mid/Ask, Order Type, Limit Price, Timing, Special Instructions, estimated amount, contract symbol, and the suggested exit plan. NO TRADE decisions never generate an order ticket.

- Search and analyze any provider-supported stock or ETF by ticker or company name.

## Resilient Universal Ticker Search

The current build treats autocomplete as optional. Exact ticker entries are independently verified through multiple delayed Yahoo Finance data paths with retries. Temporary provider failures return a provider-unavailable/NO-TRADE state instead of falsely claiming that a valid ticker does not exist. Common class-share and international ticker formats are supported, including `BRK.B`, `BRK-B`, `7203.T`, and `SHOP.TO`.

## Recommendation qualification update

The recommendation engine now supports user-configurable account/risk settings and defined-risk debit-spread fallback when a single long option cannot fit the configured risk budget. See `docs/RECOMMENDATION_QUALIFICATION_FIX.md`.
