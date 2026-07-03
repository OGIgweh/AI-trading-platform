from app.models.schemas import AnalyzeRequest, Recommendation
from app.services.market_data import get_quote, get_option_chain

def analyze_trade(req: AnalyzeRequest) -> Recommendation:
    symbol = req.symbol.upper().strip()
    quote = get_quote(symbol)
    chain = get_option_chain(symbol)
    liquid_contracts = [c for c in chain if c.volume >= 1000 and c.open_interest >= 1000 and c.spread_percent <= 8]

    technical_score = 22 if quote.change_percent > 0.5 else 12
    options_score = 20 if len(liquid_contracts) >= 4 else 8
    market_score = 8  # conservative because sample market is closed
    risk_score = 8
    confidence = min(100, technical_score + options_score + market_score + risk_score)

    risks = []
    if quote.market_status != "OPEN": risks.append("Market is currently closed; real-time confirmation is unavailable.")
    if len(liquid_contracts) < 4: risks.append("Options evidence is incomplete or liquidity is not strong enough.")
    if confidence < req.min_confidence: risks.append("Confidence is below the configured threshold.")

    evidence = {
        "technical": {"change_percent": quote.change_percent, "trend_note": "Positive momentum" if quote.change_percent > 0 else "Weak or neutral momentum"},
        "options": {"liquid_contracts": len(liquid_contracts), "max_spread_percent_allowed": 8},
        "market_context": {"market_status": quote.market_status, "data_source": quote.data_source},
        "risk": {"account_value": req.account_value, "max_risk_per_trade_percent": 1},
    }

    if confidence >= req.min_confidence and quote.market_status == "OPEN":
        entry = quote.price
        return Recommendation(
            symbol=symbol, recommendation="TRADE", confidence=confidence, threshold=req.min_confidence,
            trade_type=req.strategy, entry_price=entry, stop_loss=round(entry * 0.98, 2),
            profit_targets=[round(entry * 1.03, 2), round(entry * 1.06, 2)], position_size=1,
            explanation="Multiple evidence categories align and risk controls passed.", risks=risks, evidence=evidence
        )

    return Recommendation(
        symbol=symbol, recommendation="NO_TRADE", confidence=confidence, threshold=req.min_confidence,
        explanation="NO TRADE RECOMMENDED because the platform does not have enough aligned, verified evidence to justify risk. Capital preservation takes priority over trade frequency.",
        risks=risks or ["Evidence is not strong enough to justify a recommendation."], evidence=evidence
    )
