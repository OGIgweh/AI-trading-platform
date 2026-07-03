from app.core.config import settings

def bid_ask_spread_pct(bid: float, ask: float) -> float:
    if ask <= 0 or bid <= 0:
        return 100.0
    mid = (bid + ask) / 2
    return round(((ask - bid) / mid) * 100, 2)

def position_contracts(account_value: float, premium: float, max_risk_pct: float | None = None) -> int:
    limit = account_value * ((max_risk_pct or settings.max_risk_per_trade_pct) / 100)
    cost_per_contract = premium * 100
    if cost_per_contract <= 0:
        return 0
    return int(limit // cost_per_contract)
