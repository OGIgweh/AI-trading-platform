# Architecture

This starter platform is split into three primary clients/services:

1. Backend FastAPI trading engine
2. React web dashboard
3. Expo React Native mobile app

Live trading is disabled by default. The `/api/orders/submit` endpoint returns HTTP 403 unless `ALLOW_LIVE_TRADING=true` is set. Before enabling live trading, add a broker adapter, signed order approval, account authorization, rate limits, and compliance review.

## Decision Engine Rule

The platform must return `NO_TRADE` when:

- Quote data is stale or missing
- Option chain / Greeks are unavailable
- Confidence is below threshold
- Bid/ask spread exceeds configured limit
- Liquidity is inadequate
- Risk controls fail
- Market context conflicts with setup

## Production Upgrades

Replace sample data with provider-backed services:

- Alpaca, Tradier, Polygon, ORATS, or Interactive Brokers
- Real OHLCV calculations
- Real options chain, Greeks, IV rank, IV percentile
- News provider and sentiment model
- Earnings calendar
- Economic calendar
- Portfolio/account sync from broker

Add:

- PostgreSQL + TimescaleDB
- Redis
- Kafka/Redpanda
- Vault/Secrets Manager
- OAuth/OIDC
- MFA
- Audit-log immutability
- SAST/DAST/security scanning
