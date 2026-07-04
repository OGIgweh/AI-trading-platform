from app.models.schemas import AnalyzeRequest, RecommendationsRequest, Recommendation
from app.services.market_data import get_quote, get_option_chain
from app.services.indicators import technical_snapshot, market_context_snapshot
from app.services.risk import bid_ask_spread_pct, position_contracts

MAX_SPREAD = 8.0
MIN_OPTION_VOLUME = 500
MIN_OPEN_INTEREST = 1000


def _best_contract(chain, direction: str, account_value: float = 10000, max_risk_percent: float = 1.0):
    matching = [c for c in chain if c.contract_type.upper() == direction.upper()]
    if not matching:
        return None
    # Favor liquid contracts near 0.35-0.60 absolute delta with tight spreads.
    def score(c):
        delta_score = max(0, 30 - abs(abs(c.delta) - 0.45) * 100)
        liquidity_score = min(30, c.volume / 100) + min(25, c.open_interest / 300)
        spread_score = max(0, 20 - c.spread_percent * 2)
        mid = (c.bid + c.ask) / 2
        affordable = 35 if position_contracts(account_value, mid, max_risk_percent) >= 1 else -40
        return delta_score + liquidity_score + spread_score + affordable
    return sorted(matching, key=score, reverse=True)[0]


def analyze_trade(req: AnalyzeRequest) -> Recommendation:
    symbol = req.symbol.upper().strip()
    threshold = req.min_confidence
    quote = get_quote(symbol)
    chain = get_option_chain(symbol)
    tech = technical_snapshot(symbol)
    market = market_context_snapshot()
    risks = []
    missing = []

    if quote.data_source == "sample":
        risks.append("Using sample market data. Connect a live data provider before relying on this for real trades.")
    if quote.price <= 0:
        missing.append("valid quote price")
    if not chain:
        missing.append("options chain")
    if tech.get("score", 0) == 0:
        missing.append("technical indicator snapshot")

    if missing:
        return Recommendation(
            symbol=symbol, recommendation="NO_TRADE", confidence=0, threshold=threshold,
            explanation="NO TRADE RECOMMENDED because required evidence is missing: " + ", ".join(missing) + ".",
            risks=["Incomplete evidence can cause unsafe recommendations."], evidence={"missing": missing}, data_quality=quote.data_source
        )

    strategy = req.strategy.lower()
    if strategy in {"long_put", "put", "puts"}:
        direction = "PUT"
    else:
        # Demo directional logic: bullish technicals -> CALL, weak technicals -> PUT.
        direction = "CALL" if tech.get("score", 0) >= 65 else "PUT"

    contract = _best_contract(chain, direction, req.account_value, req.max_risk_percent)
    if contract is None:
        return Recommendation(
            symbol=symbol, recommendation="NO_TRADE", confidence=0, threshold=threshold,
            explanation=f"NO TRADE RECOMMENDED because no {direction} contract was available for analysis.",
            risks=["Options chain incomplete."], evidence={"options_count": len(chain)}, data_quality=quote.data_source
        )

    spread = bid_ask_spread_pct(contract.bid, contract.ask)
    mid = round((contract.bid + contract.ask) / 2, 2)
    contracts = position_contracts(req.account_value, mid, req.max_risk_percent)
    max_risk = round(contracts * mid * 100, 2)

    if spread > MAX_SPREAD:
        risks.append(f"Bid/ask spread is too wide at {spread}%; max allowed is {MAX_SPREAD}%.")
    if contract.volume < MIN_OPTION_VOLUME:
        risks.append(f"Option volume is low at {contract.volume}; preferred minimum is {MIN_OPTION_VOLUME}.")
    if contract.open_interest < MIN_OPEN_INTEREST:
        risks.append(f"Open interest is low at {contract.open_interest}; preferred minimum is {MIN_OPEN_INTEREST}.")
    if contracts < 1:
        risks.append("Position size is 0 contracts under the configured max risk limit.")

    technical_score = tech.get("score", 0)
    options_score = 0
    options_score += 30 if spread <= MAX_SPREAD else 10
    options_score += 25 if contract.volume >= MIN_OPTION_VOLUME else 8
    options_score += 25 if contract.open_interest >= MIN_OPEN_INTEREST else 8
    options_score += 20 if 0.20 <= contract.implied_volatility <= 0.65 else 10
    market_score = market.get("score", 0)
    risk_score = 90 if len([r for r in risks if "sample market data" not in r]) == 0 else 50
    confidence = round((technical_score * 0.35) + (options_score * 0.30) + (market_score * 0.15) + (risk_score * 0.20))

    hard_risk_failures = [r for r in risks if "sample market data" not in r]
    qualifies = confidence >= threshold and not hard_risk_failures
    recommendation = direction if qualifies else "NO_TRADE"

    stop_loss = round(mid * 0.75, 2) if qualifies else None
    targets = [round(mid * 1.25, 2), round(mid * 1.50, 2)] if qualifies else []

    evidence = {
        "quote": quote.model_dump(),
        "technical": tech,
        "options": {
            "selected_contract": contract.model_dump(),
            "mid_price": mid,
            "bid_ask_spread_percent": spread,
            "liquidity_passed": contract.volume >= MIN_OPTION_VOLUME and contract.open_interest >= MIN_OPEN_INTEREST,
        },
        "market_context": market,
        "risk": {
            "account_value": req.account_value,
            "max_risk_percent": req.max_risk_percent,
            "contracts": contracts,
            "max_risk_dollars": max_risk,
        },
        "score_breakdown": {
            "technical_score": technical_score,
            "options_score": options_score,
            "market_score": market_score,
            "risk_score": risk_score,
        }
    }

    if qualifies:
        explanation = (
            f"{direction} setup qualifies in paper-mode analysis because trend, options liquidity, market context, "
            "and risk filters are aligned. Review manually before placing any real order."
        )
    else:
        explanation = (
            "NO TRADE RECOMMENDED because confidence is below threshold or one or more risk filters failed. "
            "Capital preservation takes priority over trade frequency."
        )

    return Recommendation(
        symbol=symbol,
        recommendation=recommendation,
        confidence=confidence,
        threshold=threshold,
        trade_type="long_call" if direction == "CALL" else "long_put",
        direction=direction,
        contract_symbol=contract.symbol,
        entry_price=mid if qualifies else None,
        stop_loss=stop_loss,
        profit_targets=targets,
        position_size=contracts if qualifies else 0,
        max_risk_dollars=max_risk if qualifies else 0,
        risk_level="Controlled" if qualifies else "Avoid",
        expected_holding_period="1-5 trading days",
        explanation=explanation,
        risks=risks,
        invalidation_conditions=[
            "Price loses VWAP and fails to reclaim it.",
            "Bid/ask spread expands above allowed threshold.",
            "Market breadth or SPY/QQQ trend turns against the setup.",
            "Unexpected news or earnings risk appears."
        ],
        evidence=evidence,
        data_quality=quote.data_source,
    )


def generate_recommendations(req: RecommendationsRequest):
    results = []
    for symbol in req.symbols:
        rec = analyze_trade(AnalyzeRequest(
            symbol=symbol,
            account_value=req.account_value,
            min_confidence=req.min_confidence,
            max_risk_percent=req.max_risk_percent,
        ))
        if req.include_no_trade or rec.recommendation != "NO_TRADE":
            results.append(rec)
    results.sort(key=lambda r: r.confidence, reverse=True)
    return {
        "mode": "paper_decision_support",
        "live_trading_enabled": False,
        "message": "Recommendations are evidence-based decision support. They are not financial advice and do not place trades.",
        "recommendations": results,
    }
