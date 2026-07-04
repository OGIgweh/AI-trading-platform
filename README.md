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
