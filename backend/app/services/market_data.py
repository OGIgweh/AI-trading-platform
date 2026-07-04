from app.models.schemas import Quote, OptionContract

SAMPLE_QUOTES = {
    "AAPL": {"price": 214.35, "change": 1.26, "change_percent": 0.59, "volume": 58234000},
    "MSFT": {"price": 498.12, "change": -2.15, "change_percent": -0.43, "volume": 25420000},
    "NVDA": {"price": 164.85, "change": 3.41, "change_percent": 2.11, "volume": 189543000},
    "SPY": {"price": 624.91, "change": 0.84, "change_percent": 0.13, "volume": 74523000},
    "QQQ": {"price": 556.40, "change": 1.10, "change_percent": 0.20, "volume": 39120000},
}

def get_quote(symbol: str) -> Quote:
    symbol = symbol.upper().strip()
    raw = SAMPLE_QUOTES.get(symbol, {"price": 100.0, "change": 0.0, "change_percent": 0.0, "volume": 1000000})
    return Quote(symbol=symbol, market_status="CLOSED", data_source="sample", **raw)

def _premium(price: float, strike: float, contract_type: str, i: int):
    if contract_type == "CALL":
        intrinsic = max(price - strike, 0)
        distance = max(strike - price, 0)
    else:
        intrinsic = max(strike - price, 0)
        distance = max(price - strike, 0)
    # Demo option pricing: closer contracts cost more; far OTM contracts can fit small paper accounts.
    time_value = max(0.55, 2.2 - distance * 0.13)
    mid = intrinsic + time_value + (0.04 * i)
    bid = round(max(0.25, mid - 0.04), 2)
    ask = round(bid + max(0.05, bid * 0.045), 2)
    return bid, ask

def get_option_chain(symbol: str) -> list[OptionContract]:
    q = get_quote(symbol)
    base = round(q.price / 5) * 5
    rows = []
    strikes = [base - 10, base - 5, base, base + 5, base + 10]
    for i, strike in enumerate(strikes):
        for t in ["CALL", "PUT"]:
            bid, ask = _premium(q.price, strike, t, i)
            spread_pct = round(((ask - bid) / ask) * 100, 2)
            rows.append(OptionContract(
                symbol=f"{q.symbol}-{t}-{strike}", contract_type=t, strike=float(strike), bid=bid, ask=ask,
                volume=900 + i * 250, open_interest=2200 + i * 700, implied_volatility=0.24 + i * 0.015,
                delta=round((0.55 - i * 0.04) if t == "CALL" else (-0.45 + i * 0.04), 2),
                gamma=0.02, theta=-0.04, vega=0.12, spread_percent=spread_pct
            ))
    return rows
