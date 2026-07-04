from __future__ import annotations

from app.models.schemas import AnalyzeRequest, RecommendationsRequest, Recommendation, ScoreBreakdown
from app.services.market_data import get_quote, get_option_chain
from app.services.indicators import technical_snapshot, market_context_snapshot
from app.services.risk import position_contracts
from app.services.scoring_engine import score_technical, score_options, score_market, score_risk


def _best_contract(chain, direction: str, account_value: float = 10000, max_risk_percent: float = 1.0):
    matching = [c for c in chain if c.contract_type.upper() == direction.upper()]
    if not matching:
        return None

    def score(c):
        mid = (c.bid + c.ask) / 2
        if mid <= 0:
            return -999
        delta_score = max(0, 30 - abs(abs(c.delta) - 0.45) * 100)
        liquidity_score = min(30, c.volume / 100) + min(25, c.open_interest / 300)
        spread_score = max(0, 25 - c.spread_percent * 2)
        affordable = 20 if position_contracts(account_value, mid, max_risk_percent) >= 1 else -50
        return delta_score + liquidity_score + spread_score + affordable

    return sorted(matching, key=score, reverse=True)[0]


def _no_trade(symbol: str, threshold: int, explanation: str, risks: list[str], evidence: list, raw_data: dict, breakdown: ScoreBreakdown | None = None) -> Recommendation:
    return Recommendation(
        symbol=symbol,
        recommendation="NO_TRADE",
        confidence=breakdown.final_confidence if breakdown else 0,
        threshold=threshold,
        trade_type=None,
        direction=None,
        explanation=explanation,
        risks=risks,
        invalidation_conditions=["Missing or conflicting evidence must be resolved before reconsidering the trade."],
        evidence=evidence,
        score_breakdown=breakdown or ScoreBreakdown(threshold=threshold),
        raw_data=raw_data,
        data_quality="verified_live_delayed" if raw_data.get("quote", {}).get("data_source") == "yfinance_delayed" else "insufficient_verified_data",
    )


def analyze_trade(req: AnalyzeRequest) -> Recommendation:
    symbol = req.symbol.upper().strip()
    threshold = req.min_confidence
    quote = get_quote(symbol)
    tech = technical_snapshot(symbol)
    market = market_context_snapshot()
    chain = get_option_chain(symbol)

    raw_data = {"quote": quote.model_dump(), "technical": tech, "market_context": market, "options_contract_count": len(chain)}
    all_evidence = []
    hard_failures = []
    warnings = []

    technical_score, inferred_direction, tech_evidence, tech_failures = score_technical(tech)
    all_evidence.extend(tech_evidence)
    hard_failures.extend(tech_failures)

    strategy = req.strategy.lower()
    if strategy in {"long_call", "call", "calls"}:
        direction = "CALL"
    elif strategy in {"long_put", "put", "puts"}:
        direction = "PUT"
    else:
        direction = inferred_direction

    if direction == "NO_TRADE":
        breakdown = ScoreBreakdown(technical_score=technical_score, options_score=0, market_score=0, risk_score=0, final_confidence=0, threshold=threshold)
        return _no_trade(symbol, threshold, "NO TRADE RECOMMENDED because the technical engine could not infer a clear bullish or bearish direction from verified evidence.", hard_failures or ["Direction is unclear."], all_evidence, raw_data, breakdown)

    contract = _best_contract(chain, direction, req.account_value, req.max_risk_percent)
    options_score, options_evidence, options_failures, options_warnings = score_options(contract, direction)
    all_evidence.extend(options_evidence)
    hard_failures.extend(options_failures)
    warnings.extend(options_warnings)

    market_score, market_evidence, market_failures = score_market(market, direction)
    all_evidence.extend(market_evidence)
    hard_failures.extend(market_failures)

    mid = round((contract.bid + contract.ask) / 2, 2) if contract else 0
    contracts = position_contracts(req.account_value, mid, req.max_risk_percent) if contract else 0
    max_risk = round(contracts * mid * 100, 2) if contract else 0
    risk_score, risk_evidence, risk_failures = score_risk(quote, contract, req.account_value, req.max_risk_percent, contracts)
    all_evidence.extend(risk_evidence)
    hard_failures.extend(risk_failures)

    confidence = round((technical_score * 0.35) + (options_score * 0.25) + (market_score * 0.15) + (risk_score * 0.25))
    breakdown = ScoreBreakdown(
        technical_score=technical_score,
        options_score=options_score,
        market_score=market_score,
        risk_score=risk_score,
        final_confidence=confidence,
        threshold=threshold,
    )

    if quote.data_source != "yfinance_delayed" or tech.get("data_source") != "yfinance_delayed" or market.get("data_source") != "yfinance_delayed":
        hard_failures.append("Live delayed data was not available for every required evidence category.")

    if confidence < threshold:
        hard_failures.append(f"Confidence {confidence}% is below required threshold {threshold}%.")

    if hard_failures:
        return _no_trade(
            symbol,
            threshold,
            "NO TRADE RECOMMENDED because one or more required evidence, liquidity, market-context, or risk rules failed. Capital preservation takes priority over trade frequency.",
            hard_failures + warnings,
            all_evidence,
            raw_data | {"selected_contract": contract.model_dump() if contract else None},
            breakdown,
        )

    stop_loss = round(mid * 0.75, 2)
    targets = [round(mid * 1.25, 2), round(mid * 1.50, 2)]
    return Recommendation(
        symbol=symbol,
        recommendation=direction,
        confidence=confidence,
        threshold=threshold,
        trade_type="long_call" if direction == "CALL" else "long_put",
        direction=direction,
        contract_symbol=contract.symbol if contract else None,
        entry_price=mid,
        stop_loss=stop_loss,
        profit_targets=targets,
        position_size=contracts,
        max_risk_dollars=max_risk,
        risk_level="Controlled",
        expected_holding_period="1-5 trading days",
        explanation=f"{direction} setup qualifies because verified technical, options-liquidity, market-context, and risk evidence all passed the configured threshold. This is decision support only, not financial advice.",
        risks=warnings,
        invalidation_conditions=[
            "Price loses VWAP and fails to reclaim it.",
            "EMA alignment reverses against the trade direction.",
            "Bid/ask spread expands above the allowed threshold.",
            "SPY/QQQ market context turns against the setup.",
            "Unexpected news, earnings, or volatility event changes the setup.",
        ],
        evidence=all_evidence,
        score_breakdown=breakdown,
        raw_data=raw_data | {"selected_contract": contract.model_dump() if contract else None},
        data_quality="verified_live_delayed",
    )


def generate_recommendations(req: RecommendationsRequest):
    results = []
    for symbol in req.symbols:
        rec = analyze_trade(AnalyzeRequest(
            symbol=symbol,
            account_value=req.account_value,
            strategy="auto",
            min_confidence=req.min_confidence,
            max_risk_percent=req.max_risk_percent,
        ))
        if req.include_no_trade or rec.recommendation != "NO_TRADE":
            results.append(rec)
    results.sort(key=lambda r: r.confidence, reverse=True)
    return {
        "mode": "paper_decision_support",
        "live_trading_enabled": False,
        "message": "Recommendations use live delayed yfinance data when available. If required evidence is missing, the engine returns NO_TRADE. This is not financial advice.",
        "recommendations": results,
    }
