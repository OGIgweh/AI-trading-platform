# Any Symbol Search

The AI Trading Assistant now supports provider-backed search by ticker symbol or company name.

## Behavior

- Type a ticker such as `TSLA`, `AMD`, `PLTR`, `BRK-B`, or an exchange-suffixed symbol supported by Yahoo Finance.
- Type a company name and choose the correct exchange-listed result from the search menu.
- The selected symbol is added to the saved/recent symbol list in browser storage.
- The same technical, options, market-context, liquidity, and risk rules are applied to every searched symbol.
- Stocks without a usable options chain return `NO_TRADE`; the system does not fabricate a contract.
- Invalid or unavailable symbols return a clear error or `NO_TRADE`; the system does not substitute a fake $100 quote.

## API

```text
GET /api/market/search?q=Tesla&limit=8
GET /api/market/quote/TSLA
GET /api/market/options/TSLA
POST /api/ai/analyze
```
