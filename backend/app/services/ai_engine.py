from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.models.schemas import (
    AnalyzeRequest,
    EvidenceItem,
    Recommendation,
    RecommendationsRequest,
    ScoreBreakdown,
    SuggestedOptionsLeg,
    SuggestedOptionsOrder,
    SuggestedEquityOrder,
)
from app.services.indicators import market_context_snapshot, technical_snapshot
from app.services.market_data import (
    get_option_chain,
    get_quote,
    normalize_symbol,
    is_verified_quote_source,
    is_verified_history_source,
)
from app.services.risk import (
    bid_ask_spread_pct,
    planned_loss_per_contract,
    position_contracts,
    spread_contracts,
)
from app.services.scoring_engine import score_market, score_options, score_risk, score_technical
from app.services.social_intelligence import social_intelligence_snapshot
from app.services.verified_strategy_intelligence import verified_strategy_intelligence_snapshot, verified_strategy_alignment_adjustment


PLANNED_STOP_FRACTION = 0.25
MAX_SINGLE_PREMIUM_EXPOSURE_PERCENT = 10.0


def _mid(contract) -> float:
    return round((float(contract.bid) + float(contract.ask)) / 2, 2)


def _liquidity_rank(contract) -> float:
    spread = bid_ask_spread_pct(contract.bid, contract.ask)
    return (
        max(0.0, 30.0 - spread * 1.5)
        + min(25.0, float(contract.volume or 0) / 20.0)
        + min(25.0, float(contract.open_interest or 0) / 80.0)
    )


def _best_single_contract(
    chain,
    direction: str,
    account_value: float,
    max_risk_percent: float,
):
    matching = [
        contract
        for contract in chain
        if contract.contract_type.upper() == direction.upper()
        and contract.bid > 0
        and contract.ask > 0
        and contract.strike > 0
        and 0.22 <= abs(float(contract.delta or 0)) <= 0.65
    ]
    if not matching:
        return None

    def rank(contract):
        premium = _mid(contract)
        quantity = position_contracts(
            account_value,
            premium,
            max_risk_percent,
            stop_loss_fraction=PLANNED_STOP_FRACTION,
            max_premium_exposure_pct=MAX_SINGLE_PREMIUM_EXPOSURE_PERCENT,
        )
        delta_score = max(0.0, 35.0 - abs(abs(float(contract.delta or 0)) - 0.40) * 110)
        affordability = 45.0 if quantity >= 1 else -25.0
        dte_score = 10.0 if 14 <= int(contract.days_to_expiration or 0) <= 45 else 2.0
        return affordability + delta_score + _liquidity_rank(contract) + dte_score

    return max(matching, key=rank)


def _spread_quote(long_contract, short_contract) -> tuple[float, float, float]:
    # Conservative market for a debit spread: pay long ask, receive short bid.
    natural_ask = max(0.01, float(long_contract.ask) - float(short_contract.bid))
    natural_bid = max(0.0, float(long_contract.bid) - float(short_contract.ask))
    midpoint = round(max(0.01, (natural_bid + natural_ask) / 2), 2)
    return round(natural_bid, 2), midpoint, round(natural_ask, 2)


def _best_debit_spread(
    chain,
    direction: str,
    account_value: float,
    max_risk_percent: float,
):
    matching = [
        contract
        for contract in chain
        if contract.contract_type.upper() == direction.upper()
        and contract.bid > 0
        and contract.ask > 0
        and contract.strike > 0
        and contract.expiration
    ]
    if len(matching) < 2:
        return None

    by_expiration = defaultdict(list)
    for contract in matching:
        by_expiration[contract.expiration].append(contract)

    candidates: list[dict] = []
    for expiration, contracts in by_expiration.items():
        contracts = sorted(contracts, key=lambda item: item.strike)
        for long_contract in contracts:
            long_delta = abs(float(long_contract.delta or 0))
            if not 0.22 <= long_delta <= 0.65:
                continue

            for short_contract in contracts:
                if direction == "CALL" and short_contract.strike <= long_contract.strike:
                    continue
                if direction == "PUT" and short_contract.strike >= long_contract.strike:
                    continue

                width = abs(float(short_contract.strike) - float(long_contract.strike))
                if width <= 0 or width > 20:
                    continue

                spread_bid, net_debit, spread_ask = _spread_quote(long_contract, short_contract)
                if net_debit <= 0 or net_debit >= width:
                    continue

                quantity = spread_contracts(account_value, net_debit, max_risk_percent)
                if quantity < 1:
                    continue

                long_spread = bid_ask_spread_pct(long_contract.bid, long_contract.ask)
                short_spread = bid_ask_spread_pct(short_contract.bid, short_contract.ask)
                if long_spread > 25 or short_spread > 25:
                    continue
                if (
                    long_contract.volume < 5
                    and long_contract.open_interest < 50
                ) or (
                    short_contract.volume < 5
                    and short_contract.open_interest < 50
                ):
                    continue

                debit_ratio = net_debit / width
                value_score = max(0.0, 30.0 - abs(debit_ratio - 0.45) * 45)
                delta_score = max(0.0, 25.0 - abs(long_delta - 0.40) * 80)
                width_score = 15.0 if width <= 5 else 8.0
                liquidity = (_liquidity_rank(long_contract) + _liquidity_rank(short_contract)) / 2
                candidates.append({
                    "long": long_contract,
                    "short": short_contract,
                    "expiration": expiration,
                    "spread_bid": spread_bid,
                    "net_debit": net_debit,
                    "spread_ask": spread_ask,
                    "width": round(width, 2),
                    "quantity": quantity,
                    "rank": value_score + delta_score + width_score + liquidity,
                })

    return max(candidates, key=lambda item: item["rank"]) if candidates else None


def _option_expiration_metrics(quote, contract, entry_price: float, direction: str) -> dict:
    """Return probability-sensitive expiration metrics without pretending delta is a win probability."""
    price = float(quote.price or 0)
    strike = float(contract.strike or 0)
    dte = max(1, int(contract.days_to_expiration or 0))
    iv = max(0.0, float(contract.implied_volatility or 0))
    delta = float(contract.delta or 0)

    if direction == "CALL":
        moneyness_pct = max(0.0, (strike - price) / price * 100) if price else 0.0
        break_even = strike + entry_price
        required_move_pct = max(0.0, (break_even - price) / price * 100) if price else 0.0
    else:
        moneyness_pct = max(0.0, (price - strike) / price * 100) if price else 0.0
        break_even = strike - entry_price
        required_move_pct = max(0.0, (price - break_even) / price * 100) if price else 0.0

    expected_move_dollars = price * iv * ((dte / 365.0) ** 0.5) if price and iv else 0.0
    expected_move_pct = (expected_move_dollars / price * 100) if price and expected_move_dollars else 0.0
    expected_move_multiple = (required_move_pct / expected_move_pct) if expected_move_pct > 0 else None

    theta = float(contract.theta or 0)
    if theta != 0:
        theta_per_day = round(theta, 4)
        theta_interpretation = "Provider-reported theta; option value can change by approximately this amount per share per day from time decay, all else equal."
    else:
        theta_per_day = None
        theta_interpretation = "Exact theta is unavailable from this provider; time-decay risk is classified from days to expiration instead of inventing a Greek."

    if dte <= 10:
        decay_risk = "VERY HIGH"
    elif dte <= 21:
        decay_risk = "HIGH"
    elif dte <= 45:
        decay_risk = "MODERATE"
    else:
        decay_risk = "LOWER"

    return {
        "break_even": round(break_even, 2),
        "moneyness_percent": round(moneyness_pct, 2),
        "required_move_percent": round(required_move_pct, 2),
        "expected_move_dollars": round(expected_move_dollars, 2),
        "expected_move_percent": round(expected_move_pct, 2),
        "break_even_expected_move_multiple": round(expected_move_multiple, 2) if expected_move_multiple is not None else None,
        "directional_delta": round(delta, 2),
        "delta_interpretation": "Directional delta exposure only; it is not the model's probability of profit and may be a provider proxy.",
        "theta_per_day": theta_per_day,
        "theta_interpretation": theta_interpretation,
        "time_decay_risk": decay_risk,
        "dte": dte,
    }


def _score_expiration_quality(quote, contract, entry_price: float, direction: str) -> tuple[int, list[EvidenceItem], list[str], list[str], dict]:
    metrics = _option_expiration_metrics(quote, contract, entry_price, direction)
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    warnings: list[str] = []
    ds = getattr(contract, "data_source", "options")
    dte = metrics["dte"]
    otm = metrics["moneyness_percent"]
    required = metrics["required_move_percent"]
    multiple = metrics["break_even_expected_move_multiple"]
    abs_delta = abs(metrics["directional_delta"] or 0)

    quality = 100
    if dte <= 21 and otm > 4.0:
        failures.append(f"The selected option is {otm:.1f}% out of the money with only {dte} DTE; short-dated far-OTM contracts are blocked.")
        quality -= 45
    elif otm > 3.0:
        warnings.append(f"The selected option starts {otm:.1f}% out of the money.")
        quality -= 15

    if multiple is not None and multiple > 1.35:
        failures.append(f"Break-even requires about {multiple:.2f}× the IV-implied expected move by expiration, which exceeds the configured probability-sensitive limit.")
        quality -= 45
    elif multiple is not None and multiple > 1.0:
        warnings.append(f"Break-even requires about {multiple:.2f}× the IV-implied expected move by expiration.")
        quality -= 15

    if dte <= 21 and abs_delta < 0.30:
        failures.append(f"Directional delta {abs_delta:.2f} is too low for a {dte}-DTE single-leg directional trade.")
        quality -= 35
    elif abs_delta < 0.35:
        warnings.append(f"Directional delta {abs_delta:.2f} provides relatively weak price sensitivity.")
        quality -= 10

    evidence.append(EvidenceItem(
        category="Expiration / Probability", name="Required move to break-even",
        value={"required_move_percent": required, "expected_move_percent": metrics["expected_move_percent"], "expected_move_multiple": multiple},
        signal="fail" if any("expected move" in x for x in failures) else "warning" if multiple and multiple > 1 else "pass",
        score=max(-100, min(100, quality)), weight=0.18, passed=not any("expected move" in x for x in failures),
        explanation="Compares the expiration break-even move with an IV-based one-standard-deviation expected-move estimate. This is an estimate, not a guaranteed range.", data_source=ds))
    evidence.append(EvidenceItem(
        category="Expiration / Probability", name="Moneyness and DTE",
        value={"out_of_money_percent": otm, "days_to_expiration": dte},
        signal="fail" if dte <= 21 and otm > 4 else "warning" if otm > 3 else "pass",
        score=20 if otm <= 3 else -25, weight=0.12, passed=not (dte <= 21 and otm > 4),
        explanation="Short-dated contracts that require a large underlying move are penalized or blocked before a high-confidence recommendation can qualify.", data_source=ds))
    evidence.append(EvidenceItem(
        category="Expiration / Probability", name="Directional delta", value=metrics["directional_delta"],
        signal="fail" if dte <= 21 and abs_delta < .30 else "warning" if abs_delta < .35 else "pass",
        score=int(abs_delta * 100), weight=0.10, passed=not (dte <= 21 and abs_delta < .30),
        explanation=metrics["delta_interpretation"], data_source=ds))
    evidence.append(EvidenceItem(
        category="Expiration / Probability", name="Time-decay exposure",
        value={"theta_per_day": metrics["theta_per_day"], "time_decay_risk": metrics["time_decay_risk"], "dte": dte},
        signal="warning" if dte <= 21 else "info", score=0, weight=0.08, passed=dte > 10,
        explanation=metrics["theta_interpretation"], data_source=ds))
    return max(0, min(100, quality)), evidence, failures, warnings, metrics


def _prefix_evidence(items: Iterable[EvidenceItem], prefix: str) -> list[EvidenceItem]:
    return [item.model_copy(update={"name": f"{prefix} — {item.name}"}) for item in items]


def _no_trade(
    symbol: str,
    threshold: int,
    explanation: str,
    risks: list[str],
    evidence: list,
    raw_data: dict,
    breakdown: ScoreBreakdown | None = None,
) -> Recommendation:
    return Recommendation(
        symbol=symbol,
        recommendation="NO_TRADE",
        confidence=breakdown.final_confidence if breakdown else 0,
        threshold=threshold,
        trade_type=None,
        direction=None,
        explanation=explanation,
        risks=risks,
        invalidation_conditions=["Missing, conflicting, or risk-limit evidence must be resolved before reconsidering the trade."],
        evidence=evidence,
        score_breakdown=breakdown or ScoreBreakdown(threshold=threshold),
        raw_data=raw_data,
        data_quality=(
            "verified_live_delayed"
            if is_verified_quote_source(raw_data.get("quote", {}).get("data_source"))
            else "insufficient_verified_data"
        ),
    )


def _data_quality_no_trade(req: AnalyzeRequest, symbol: str, quote) -> Recommendation:
    threshold = req.min_confidence
    provider_issue = quote.data_source == "provider_unavailable"
    invalid_format = quote.data_source == "invalid_symbol"
    if provider_issue:
        explanation = (
            f"The market-data provider could not return a verified quote for {symbol}. "
            "This is a temporary provider or rate-limit condition and does not mean the ticker is nonexistent."
        )
        risk = "Retry after the provider recovers; do not place a trade using stale or missing data."
    elif invalid_format:
        explanation = f"{symbol or req.symbol} is not in a supported ticker format."
        risk = "Enter a ticker such as AAPL, BRK-B, or 7203.T."
    else:
        explanation = f"No supported stock or ETF could be verified for {symbol}."
        risk = "Confirm the exact exchange ticker before retrying."

    evidence = [EvidenceItem(
        category="Data Quality",
        name="Verified market quote",
        value=quote.data_source,
        signal="fail",
        score=-100,
        weight=1.0,
        passed=False,
        explanation=explanation,
        data_source=quote.data_source,
    )]
    return _no_trade(
        symbol,
        threshold,
        f"NO TRADE RECOMMENDED. {explanation}",
        [risk],
        evidence,
        {
            "quote": quote.model_dump(),
            "technical": {"data_source": quote.data_source},
            "market_context": {},
            "options_contract_count": 0,
        },
        ScoreBreakdown(threshold=threshold),
    )



def _equity_recommendation(
    req: AnalyzeRequest,
    symbol: str,
    quote,
    tech: dict,
    market: dict,
    direction: str,
    technical_score: int,
    all_evidence: list[EvidenceItem],
    hard_failures: list[str],
    raw_data: dict,
    *,
    auto_fallback: bool,
) -> Recommendation:
    """Produce a defined-risk stock setup only when Stock or Auto mode permits it."""
    market_score, market_evidence, market_failures = score_market(market, direction)
    all_evidence.extend(market_evidence)
    hard_failures.extend(market_failures)

    atr = float(tech.get("atr") or 0)
    entry = float(quote.price)
    stop_distance = max(atr * 1.5, entry * 0.02)
    risk_budget = req.account_value * req.max_risk_percent / 100
    max_notional = req.account_value * 0.25
    quantity_by_risk = int(risk_budget // stop_distance) if stop_distance > 0 else 0
    quantity_by_notional = int(max_notional // entry) if entry > 0 else 0
    quantity = max(0, min(quantity_by_risk, quantity_by_notional))
    planned_risk = round(quantity * stop_distance, 2)
    risk_score = 100 if quantity >= 1 else 0

    all_evidence.append(EvidenceItem(
        category="Analysis Mode",
        name="Stock-analysis authorization",
        value="Auto fallback" if auto_fallback else "Stock selected",
        signal="info" if auto_fallback else "pass",
        score=0 if auto_fallback else 100,
        weight=0,
        passed=not auto_fallback,
        explanation=(
            "Auto mode permitted a defined-risk stock setup because no verified option chain was available. "
            "No option contract was invented."
            if auto_fallback
            else "Stock mode was explicitly selected. The engine evaluated shares only and did not require or use an option chain."
        ),
        data_source="analysis_mode",
    ))
    all_evidence.append(EvidenceItem(
        category="Risk",
        name="Equity position sizing",
        value={
            "shares": quantity,
            "risk_budget": round(risk_budget, 2),
            "planned_risk": planned_risk,
            "max_notional": round(max_notional, 2),
        },
        signal="pass" if quantity >= 1 else "fail",
        score=100 if quantity >= 1 else -100,
        weight=0.15,
        passed=quantity >= 1,
        explanation="Share quantity is limited by both the configured risk budget and a 25% account-value notional cap.",
        data_source=quote.data_source,
    ))
    if quantity < 1:
        hard_failures.append("No stock position fits the configured risk and notional limits.")

    verified_strategy_adjustment = int(raw_data.get("verified_strategy_adjustment") or 0)
    confidence = round((technical_score * 0.60) + (market_score * 0.25) + (risk_score * 0.15))
    confidence = max(0, min(100, confidence + verified_strategy_adjustment))
    if quote.data_source == "stooq_eod":
        confidence = max(0, confidence - 4)
    breakdown = ScoreBreakdown(
        technical_score=technical_score,
        options_score=0,
        market_score=market_score,
        risk_score=risk_score,
        verified_strategy_score=int(raw_data.get("verified_strategy_intelligence", {}).get("quality_score") or 0),
        final_confidence=confidence,
        threshold=req.min_confidence,
    )
    if confidence < req.min_confidence:
        hard_failures.append(f"Confidence {confidence}% is below the configured {req.min_confidence}% threshold.")

    is_bullish = direction == "CALL"
    recommendation = "BUY" if is_bullish else "SHORT"
    stop_loss = round(entry - stop_distance, 2) if is_bullish else round(entry + stop_distance, 2)
    targets = (
        [round(entry + stop_distance * 1.5, 2), round(entry + stop_distance * 2.5, 2)]
        if is_bullish
        else [round(entry - stop_distance * 1.5, 2), round(entry - stop_distance * 2.5, 2)]
    )
    raw_data.update({
        "selected_strategy": "auto_equity_fallback" if auto_fallback else "stock_only",
        "planned_risk_dollars": planned_risk,
        "blocking_failures": list(dict.fromkeys(hard_failures)),
    })
    if hard_failures:
        return _no_trade(
            symbol,
            req.min_confidence,
            "NO TRADE RECOMMENDED because the verified stock setup did not pass every confidence, market-context, and risk gate.",
            list(dict.fromkeys(hard_failures)),
            all_evidence,
            raw_data,
            breakdown,
        )

    equity_order = SuggestedEquityOrder(
        strategy="Long Stock" if is_bullish else "Short Stock",
        symbol=symbol,
        action="BUY" if is_bullish else "SELL_SHORT",
        quantity=quantity,
        limit_price=round(entry, 2),
        stop_loss=stop_loss,
        profit_targets=targets,
        estimated_amount=round(quantity * entry, 2),
        planned_risk=planned_risk,
        price_basis=(
            "Latest completed daily price; verify a current quote before entry"
            if quote.data_source == "stooq_eod"
            else "Latest verified provider quote"
        ),
    )
    return Recommendation(
        symbol=symbol,
        recommendation=recommendation,
        confidence=confidence,
        threshold=req.min_confidence,
        trade_type="long_stock" if is_bullish else "short_stock",
        direction="BULLISH" if is_bullish else "BEARISH",
        entry_price=round(entry, 2),
        stop_loss=stop_loss,
        profit_targets=targets,
        position_size=quantity,
        max_risk_dollars=planned_risk,
        risk_level="Defined by stop and position size",
        expected_holding_period="2-15 trading days",
        explanation=(
            "A stock setup qualifies from verified technical, market-context, and risk evidence. "
            + (
                "Auto mode selected shares because no verified option chain was available; no option contract was invented."
                if auto_fallback
                else "Stock mode was explicitly selected, so the recommendation applies to shares rather than options."
            )
        ),
        risks=[
            "A stop order can fill below/above the intended price during gaps.",
            "Verify the latest quote before entry, especially when the source is end-of-day data.",
        ],
        invalidation_conditions=[
            "Price closes through the stop level.",
            "EMA/MACD alignment reverses against the setup.",
            "Broad-market context turns materially against the setup.",
        ],
        evidence=all_evidence,
        score_breakdown=breakdown,
        suggested_equity_order=equity_order,
        raw_data=raw_data,
        data_quality="verified_market_data",
    )


def _options_only_no_trade(
    req: AnalyzeRequest,
    symbol: str,
    quote,
    tech: dict,
    market: dict,
    direction: str,
    technical_score: int,
    all_evidence: list[EvidenceItem],
    hard_failures: list[str],
    raw_data: dict,
) -> Recommendation:
    """Block stock substitution when the user explicitly selected Options mode."""
    market_score, market_evidence, market_failures = score_market(market, direction)
    all_evidence.extend(market_evidence)
    hard_failures.extend(market_failures)
    blocker = (
        "Options mode requires a verified option chain, but no verified option contracts were available. "
        "The engine did not substitute a stock trade."
    )
    hard_failures.append(blocker)
    all_evidence.append(EvidenceItem(
        category="Analysis Mode",
        name="Options-only requirement",
        value={"selected_mode": "options", "verified_contracts": 0},
        signal="fail",
        score=-100,
        weight=1.0,
        passed=False,
        explanation=blocker,
        data_source="options_unavailable",
    ))
    breakdown = ScoreBreakdown(
        technical_score=technical_score,
        options_score=0,
        market_score=market_score,
        risk_score=0,
        final_confidence=0,
        threshold=req.min_confidence,
    )
    raw_data.update({
        "selected_strategy": "options_only_unavailable",
        "blocking_failures": list(dict.fromkeys(hard_failures)),
    })
    return _no_trade(
        symbol,
        req.min_confidence,
        "NO TRADE RECOMMENDED. Options mode is options-only, and a verified option chain was unavailable. The engine did not replace it with a stock recommendation.",
        list(dict.fromkeys(hard_failures)),
        all_evidence,
        raw_data,
        breakdown,
    )

def analyze_trade(req: AnalyzeRequest) -> Recommendation:
    symbol = normalize_symbol(req.symbol)
    threshold = req.min_confidence
    quote = get_quote(symbol)
    if not is_verified_quote_source(quote.data_source) or quote.price <= 0:
        return _data_quality_no_trade(req, symbol, quote)

    asset_mode = req.asset_mode.lower()
    option_structure = req.option_structure.lower()
    tech = technical_snapshot(symbol)
    market = market_context_snapshot()
    # Stock mode never requests an option chain. Options and Auto request it once.
    chain = get_option_chain(symbol) if asset_mode in {"options", "auto"} else []
    social = social_intelligence_snapshot(symbol)
    verified_strategy = verified_strategy_intelligence_snapshot(symbol)
    raw_data = {
        "quote": quote.model_dump(),
        "technical": tech,
        "market_context": market,
        "social_intelligence": social,
        "verified_strategy_intelligence": verified_strategy,
        "options_contract_count": len(chain),
        "analysis_settings": {
            "account_value": req.account_value,
            "max_risk_percent": req.max_risk_percent,
            "confidence_threshold": threshold,
            "risk_budget_dollars": round(req.account_value * req.max_risk_percent / 100, 2),
            "asset_mode": asset_mode,
            "option_structure": option_structure,
        },
    }

    all_evidence: list[EvidenceItem] = []
    hard_failures: list[str] = []
    warnings: list[str] = []

    # Social/whale intelligence is supplemental. It is asset-specific and does
    # not alter equity/equity-option confidence when the signal is crypto-only.
    if social.get("applicable"):
        consensus = social.get("consensus", "UNAVAILABLE")
        social_signal = "bullish" if consensus == "BULLISH" else "bearish" if consensus == "BEARISH" else "neutral"
        all_evidence.append(EvidenceItem(
            category="Social / Whale",
            name="Top-trader consensus",
            value={
                "consensus": consensus,
                "score": social.get("score"),
                "confidence": social.get("confidence"),
                "qualified_traders": social.get("qualified_traders"),
                "providers": social.get("providers_used", []),
            },
            signal=social_signal,
            score=int((social.get("score", 50) or 50) - 50),
            weight=0.0,
            passed=social.get("status") == "verified",
            explanation="Supplemental asset-matched social/whale consensus. It is not a standalone trade trigger and is not treated as probability of profit.",
            data_source="+".join(social.get("providers_used", [])) or "social_unavailable",
        ))
    else:
        all_evidence.append(EvidenceItem(
            category="Social / Whale",
            name="Crypto social intelligence applicability",
            value=social.get("status"),
            signal="info",
            score=0,
            weight=0.0,
            passed=True,
            explanation=social.get("message", "Crypto social intelligence is not applied to this equity recommendation."),
            data_source="not_applicable",
        ))

    all_evidence.append(EvidenceItem(
        category="Verified Strategy",
        name="AlphaLedger verified-strategy quality",
        value={
            "status": verified_strategy.get("status"),
            "quality_score": verified_strategy.get("quality_score"),
            "consensus": verified_strategy.get("consensus"),
            "matched_strategies": verified_strategy.get("matched_strategies"),
            "qualified_strategies": verified_strategy.get("qualified_strategies"),
        },
        signal=(
            "bullish" if verified_strategy.get("consensus") == "BULLISH"
            else "bearish" if verified_strategy.get("consensus") == "BEARISH"
            else "info"
        ),
        score=int((verified_strategy.get("score", 50) or 50) - 50),
        weight=0.0,
        passed=verified_strategy.get("status") in {"verified", "metrics_only"},
        explanation=verified_strategy.get("message", "Verified strategy intelligence is supplemental and never creates a trade by itself."),
        data_source="+".join(verified_strategy.get("providers_used", [])) or "alphaledger_unavailable",
    ))

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

    verified_strategy_adjustment, verified_strategy_note = verified_strategy_alignment_adjustment(verified_strategy, direction)
    raw_data["verified_strategy_adjustment"] = verified_strategy_adjustment
    raw_data["verified_strategy_adjustment_note"] = verified_strategy_note
    if direction != "NO_TRADE":
        all_evidence.append(EvidenceItem(
            category="Verified Strategy",
            name="Asset-matched AlphaLedger alignment",
            value={
                "consensus": verified_strategy.get("consensus"),
                "confidence": verified_strategy.get("confidence"),
                "matched_strategies": verified_strategy.get("matched_strategies"),
                "adjustment": verified_strategy_adjustment,
            },
            signal="bullish" if verified_strategy_adjustment > 0 else "bearish" if verified_strategy_adjustment < 0 else "neutral",
            score=max(-100, min(100, verified_strategy_adjustment * 10)),
            weight=0.0,
            passed=verified_strategy_adjustment != 0,
            explanation=verified_strategy_note,
            data_source="alphaledger" if verified_strategy.get("providers_used") else "alphaledger_unavailable",
        ))

    if direction == "NO_TRADE":
        technical_verified = is_verified_history_source(tech.get("data_source"))
        displayed_confidence = technical_score if technical_verified else 0
        breakdown = ScoreBreakdown(
            technical_score=technical_score,
            options_score=0,
            market_score=0,
            risk_score=0,
            final_confidence=displayed_confidence,
            threshold=threshold,
        )
        if technical_verified:
            explanation = (
                "NO TRADE RECOMMENDED because verified bullish and bearish technical evidence is too closely balanced. "
                "This is a genuine mixed setup rather than a missing-data failure."
            )
            reasons = hard_failures or ["The directional technical-score gap is below the minimum confirmation requirement."]
        else:
            explanation = (
                "NO TRADE RECOMMENDED because verified historical OHLCV data could not be loaded, "
                "so the indicator analysis could not be completed."
            )
            reasons = hard_failures or [tech.get("error", "Verified price history is unavailable.")]
        raw_data["blocking_failures"] = reasons
        return _no_trade(symbol, threshold, explanation, reasons, all_evidence, raw_data, breakdown)

    if asset_mode == "stock":
        return _equity_recommendation(
            req,
            symbol,
            quote,
            tech,
            market,
            direction,
            technical_score,
            all_evidence,
            hard_failures,
            raw_data,
            auto_fallback=False,
        )

    if not chain and asset_mode == "options":
        return _options_only_no_trade(
            req,
            symbol,
            quote,
            tech,
            market,
            direction,
            technical_score,
            all_evidence,
            hard_failures,
            raw_data,
        )

    if not chain:
        return _equity_recommendation(
            req,
            symbol,
            quote,
            tech,
            market,
            direction,
            technical_score,
            all_evidence,
            hard_failures,
            raw_data,
            auto_fallback=True,
        )

    single_contract = _best_single_contract(chain, direction, req.account_value, req.max_risk_percent)
    single_mid = _mid(single_contract) if single_contract else 0.0
    single_quantity = (
        position_contracts(
            req.account_value,
            single_mid,
            req.max_risk_percent,
            stop_loss_fraction=PLANNED_STOP_FRACTION,
            max_premium_exposure_pct=MAX_SINGLE_PREMIUM_EXPOSURE_PERCENT,
        )
        if single_contract
        else 0
    )

    spread = None
    selected_strategy = "single"

    if option_structure == "multi":
        # Multi-leg is strict: never substitute a single long option. The current
        # production engine supports defined-risk two-leg vertical debit spreads.
        spread = _best_debit_spread(chain, direction, req.account_value, req.max_risk_percent)
        if spread:
            selected_strategy = "debit_spread"
        else:
            market_score, market_evidence, market_failures = score_market(market, direction)
            all_evidence.extend(market_evidence)
            hard_failures.extend(market_failures)
            blocker = (
                "Multi Leg was selected, but no verified Vertical Call/Vertical Put spread fit the configured "
                "liquidity, expiration, pricing, and risk requirements. The engine did not substitute a single-leg option."
            )
            hard_failures.append(blocker)
            all_evidence.append(EvidenceItem(
                category="Options",
                name="Option structure requirement",
                value={"selected_structure": "multi", "supported_multi_leg": ["Vertical Call", "Vertical Put"]},
                signal="fail",
                score=-100,
                weight=1.0,
                passed=False,
                explanation=blocker,
                data_source="verified_options_chain",
            ))
            breakdown = ScoreBreakdown(
                technical_score=technical_score,
                options_score=0,
                market_score=market_score,
                risk_score=0,
                final_confidence=0,
                threshold=threshold,
            )
            raw_data.update({
                "selected_strategy": "multi_leg_unavailable",
                "option_structure": option_structure,
                "blocking_failures": list(dict.fromkeys(hard_failures)),
            })
            return _no_trade(
                symbol,
                threshold,
                "NO TRADE RECOMMENDED. Multi Leg was selected, but no qualifying defined-risk vertical spread was available. A single-leg option was not substituted.",
                list(dict.fromkeys(hard_failures)),
                all_evidence,
                raw_data,
                breakdown,
            )
    elif option_structure == "single":
        # Single-leg is strict: keep the selected long call/put even when a
        # vertical spread could fit the account better. Risk sizing can still
        # reject the trade, but the engine will not silently switch structures.
        selected_strategy = "single"
        all_evidence.append(EvidenceItem(
            category="Options",
            name="Option structure preference",
            value="Single Leg",
            signal="info",
            score=0,
            weight=0.0,
            passed=True,
            explanation="Single Leg was selected, so only a Call or Put may qualify; multi-leg spreads are not substituted.",
            data_source="user_setting",
        ))
    else:
        # Best Fit preserves the previous risk-first behavior: prefer a single
        # long option when it fits, otherwise attempt a defined-risk vertical.
        if single_quantity < 1:
            spread = _best_debit_spread(chain, direction, req.account_value, req.max_risk_percent)
            if spread:
                selected_strategy = "debit_spread"

    if selected_strategy == "single":
        contract = single_contract
        options_score, options_evidence, options_failures, options_warnings = score_options(contract, direction)
        quantity = single_quantity
        entry_price = single_mid
        planned_risk = round(quantity * planned_loss_per_contract(single_mid, PLANNED_STOP_FRACTION), 2)
        absolute_max_loss = round(quantity * single_mid * 100, 2)
        strategy_name = "Call" if direction == "CALL" else "Put"
        selected_contract_raw = contract.model_dump() if contract else None
    else:
        long_contract = spread["long"]
        short_contract = spread["short"]
        long_score, long_ev, long_fail, long_warn = score_options(long_contract, direction)
        short_score, short_ev, short_fail, short_warn = score_options(short_contract, direction)
        options_score = round((long_score * 0.60) + (short_score * 0.40))
        options_evidence = _prefix_evidence(long_ev, "Long leg") + _prefix_evidence(short_ev, "Short leg")
        options_failures = long_fail + short_fail
        options_warnings = long_warn + short_warn
        contract = long_contract
        quantity = int(spread["quantity"])
        entry_price = float(spread["net_debit"])
        planned_risk = round(quantity * entry_price * 100, 2)
        absolute_max_loss = planned_risk
        strategy_name = "Vertical Call" if direction == "CALL" else "Vertical Put"
        selected_contract_raw = {
            "strategy": strategy_name,
            "long": long_contract.model_dump(),
            "short": short_contract.model_dump(),
            "net_debit": entry_price,
            "width": spread["width"],
        }
        all_evidence.append(EvidenceItem(
            category="Options",
            name="Multi-leg vertical selection" if option_structure == "multi" else "Defined-risk spread fallback",
            value={"net_debit": entry_price, "width": spread["width"], "quantity": quantity, "option_structure": option_structure},
            signal="pass",
            score=20,
            weight=0.20,
            passed=True,
            explanation=(
                "A two-leg vertical debit spread was selected because Multi Leg was requested. Maximum loss is limited to the net debit."
                if option_structure == "multi"
                else "A debit spread was selected because a single long option did not fit the configured risk budget. Maximum loss is limited to the net debit."
            ),
            data_source="verified_options_chain",
        ))

    all_evidence.extend(options_evidence)
    hard_failures.extend(options_failures)
    warnings.extend(options_warnings)

    expiration_score, expiration_evidence, expiration_failures, expiration_warnings, expiration_metrics = _score_expiration_quality(
        quote, contract, entry_price, direction
    )
    all_evidence.extend(expiration_evidence)
    hard_failures.extend(expiration_failures)
    warnings.extend(expiration_warnings)

    market_score, market_evidence, market_failures = score_market(market, direction)
    all_evidence.extend(market_evidence)
    hard_failures.extend(market_failures)

    risk_score, risk_evidence, risk_failures = score_risk(
        quote,
        contract,
        req.account_value,
        req.max_risk_percent,
        quantity,
        planned_risk=planned_risk,
        absolute_max_loss=absolute_max_loss,
        strategy_name=strategy_name,
    )
    all_evidence.extend(risk_evidence)
    hard_failures.extend(risk_failures)

    # Setup confidence is predominantly evidence quality. Position affordability
    # is still a hard gate, but no longer suppresses every otherwise valid setup
    # into the low 60s simply because one long contract costs more than $100.
    confidence = round(
        (technical_score * 0.32)
        + (options_score * 0.23)
        + (expiration_score * 0.20)
        + (market_score * 0.15)
        + (risk_score * 0.10)
    )
    confidence = max(0, min(100, confidence + int(raw_data.get("verified_strategy_adjustment") or 0)))
    # Confidence is evidence-alignment, never a probability of profit.
    # Short-dated / weak-delta contracts cannot receive an extreme confidence label.
    if expiration_metrics["dte"] <= 21 or abs(expiration_metrics["directional_delta"] or 0) < 0.35:
        confidence = min(confidence, 84)
    breakdown = ScoreBreakdown(
        technical_score=technical_score,
        options_score=options_score,
        market_score=market_score,
        risk_score=risk_score,
        verified_strategy_score=int(raw_data.get("verified_strategy_intelligence", {}).get("quality_score") or 0),
        final_confidence=confidence,
        threshold=threshold,
    )

    if not is_verified_quote_source(quote.data_source) or not is_verified_history_source(tech.get("data_source")) or not (is_verified_history_source(market.get("data_source")) or market.get("data_source") == "mixed_verified_providers"):
        hard_failures.append("Verified market data was not available for every required evidence category.")
    if confidence < threshold:
        hard_failures.append(f"Confidence {confidence}% is below the configured {threshold}% threshold.")

    raw_data.update({
        "selected_strategy": selected_strategy,
        "option_structure": option_structure,
        "schwab_strategy_name": strategy_name,
        "strategy_structure": (
            "Buy lower-strike call and sell higher-strike call with the same expiration"
            if strategy_name == "Vertical Call"
            else "Buy higher-strike put and sell lower-strike put with the same expiration"
            if strategy_name == "Vertical Put"
            else "Single-leg long call"
            if strategy_name == "Call"
            else "Single-leg long put"
        ),
        "selected_contract": selected_contract_raw,
        "planned_risk_dollars": planned_risk,
        "absolute_max_loss_dollars": absolute_max_loss,
        "blocking_failures": list(dict.fromkeys(hard_failures)),
        "warnings": list(dict.fromkeys(warnings)),
        "expiration_metrics": expiration_metrics,
        "confidence_interpretation": "Evidence-alignment score only; not probability of profit or probability of reaching break-even.",
    })

    if hard_failures:
        return _no_trade(
            symbol,
            threshold,
            "NO TRADE RECOMMENDED because the setup did not pass every critical data, execution, confidence, and risk-control gate. The specific blockers are listed below.",
            list(dict.fromkeys(hard_failures + warnings)),
            all_evidence,
            raw_data,
            breakdown,
        )

    if selected_strategy == "single":
        stop_loss = round(entry_price * (1 - PLANNED_STOP_FRACTION), 2)
        targets = [round(entry_price * 1.25, 2), round(entry_price * 1.50, 2)]
        legs = [SuggestedOptionsLeg(
            action="BUY_TO_OPEN",
            quantity=quantity,
            expiration=contract.expiration or "Unavailable",
            days_to_expiration=contract.days_to_expiration,
            strike=contract.strike,
            option_type=direction,
            contract_symbol=contract.symbol,
            bid=contract.bid,
            mid=entry_price,
            ask=contract.ask,
        )]
        max_profit = None
        break_even = round(contract.strike + entry_price, 2) if direction == "CALL" else round(contract.strike - entry_price, 2)
        spread_width = None
        contract_symbol = contract.symbol
        trade_type = "long_call" if direction == "CALL" else "long_put"
        price_basis = "Midpoint of current bid/ask"
    else:
        long_contract = spread["long"]
        short_contract = spread["short"]
        width = float(spread["width"])
        max_profit = round(quantity * max(0, width - entry_price) * 100, 2)
        break_even = round(long_contract.strike + entry_price, 2) if direction == "CALL" else round(long_contract.strike - entry_price, 2)
        stop_loss = round(entry_price * 0.70, 2)
        max_value = width
        targets = [
            round(min(max_value * 0.90, entry_price + (max_value - entry_price) * 0.35), 2),
            round(min(max_value * 0.95, entry_price + (max_value - entry_price) * 0.60), 2),
        ]
        legs = [
            SuggestedOptionsLeg(
                action="BUY_TO_OPEN",
                quantity=quantity,
                expiration=long_contract.expiration or "Unavailable",
                days_to_expiration=long_contract.days_to_expiration,
                strike=long_contract.strike,
                option_type=direction,
                contract_symbol=long_contract.symbol,
                bid=long_contract.bid,
                mid=_mid(long_contract),
                ask=long_contract.ask,
            ),
            SuggestedOptionsLeg(
                action="SELL_TO_OPEN",
                quantity=quantity,
                expiration=short_contract.expiration or "Unavailable",
                days_to_expiration=short_contract.days_to_expiration,
                strike=short_contract.strike,
                option_type=direction,
                contract_symbol=short_contract.symbol,
                bid=short_contract.bid,
                mid=_mid(short_contract),
                ask=short_contract.ask,
            ),
        ]
        spread_width = width
        contract_symbol = f"{long_contract.symbol} / {short_contract.symbol}"
        trade_type = "bull_call_debit_spread" if direction == "CALL" else "bear_put_debit_spread"
        price_basis = "Net debit midpoint of both option legs"

    suggested_order = SuggestedOptionsOrder(
        strategy=strategy_name,
        underlying_symbol=symbol,
        underlying_price=quote.price,
        leg_count=len(legs),
        legs=legs,
        action="BUY_TO_OPEN",
        quantity=quantity,
        expiration=contract.expiration or "Unavailable",
        days_to_expiration=contract.days_to_expiration,
        strike=contract.strike,
        option_type=direction,
        contract_symbol=contract_symbol,
        bid=(spread["spread_bid"] if selected_strategy == "debit_spread" else contract.bid),
        mid=entry_price,
        ask=(spread["spread_ask"] if selected_strategy == "debit_spread" else contract.ask),
        limit_price=entry_price,
        estimated_amount=absolute_max_loss,
        estimated_max_loss=absolute_max_loss,
        planned_stop_loss=planned_risk,
        max_profit=max_profit,
        break_even=break_even,
        spread_width=spread_width,
        moneyness_percent=expiration_metrics["moneyness_percent"],
        required_move_percent=expiration_metrics["required_move_percent"],
        expected_move_dollars=expiration_metrics["expected_move_dollars"],
        expected_move_percent=expiration_metrics["expected_move_percent"],
        break_even_expected_move_multiple=expiration_metrics["break_even_expected_move_multiple"],
        directional_delta=expiration_metrics["directional_delta"],
        delta_interpretation=expiration_metrics["delta_interpretation"],
        theta_per_day=expiration_metrics["theta_per_day"],
        theta_interpretation=expiration_metrics["theta_interpretation"],
        time_decay_risk=expiration_metrics["time_decay_risk"],
        price_basis=price_basis,
    )

    return Recommendation(
        symbol=symbol,
        recommendation=direction,
        confidence=confidence,
        threshold=threshold,
        trade_type=trade_type,
        direction=direction,
        contract_symbol=contract_symbol,
        entry_price=entry_price,
        stop_loss=stop_loss,
        profit_targets=targets,
        position_size=quantity,
        max_risk_dollars=absolute_max_loss,
        risk_level="Defined" if selected_strategy == "debit_spread" else "Controlled with stop; full premium remains at risk",
        expected_holding_period="1-10 trading days",
        explanation=(
            f"{strategy_name} qualifies because verified technical, options-liquidity, market-alignment, and risk evidence passed the configured threshold. "
            "The displayed confidence is an evidence-alignment score, not a probability of profit. This is decision support, not a guarantee of profit."
        ),
        risks=list(dict.fromkeys(warnings)),
        invalidation_conditions=[
            "Price loses the relevant VWAP/trend structure and fails to recover.",
            "EMA and MACD alignment reverse against the proposed direction.",
            "Bid/ask spreads expand beyond the execution safety limit.",
            "SPY/QQQ context turns materially against the setup.",
            "Unexpected news, earnings, or volatility changes the setup.",
        ],
        evidence=all_evidence,
        score_breakdown=breakdown,
        suggested_order=suggested_order,
        raw_data=raw_data,
        data_quality="verified_market_data",
    )


def generate_recommendations(req: RecommendationsRequest):
    results = []
    unique_symbols = list(dict.fromkeys(normalize_symbol(symbol) for symbol in req.symbols if symbol.strip()))[:20]
    for symbol in unique_symbols:
        recommendation = analyze_trade(AnalyzeRequest(
            symbol=symbol,
            account_value=req.account_value,
            asset_mode=req.asset_mode,
            option_structure=req.option_structure,
            strategy="auto",
            min_confidence=req.min_confidence,
            max_risk_percent=req.max_risk_percent,
        ))
        if req.include_no_trade or recommendation.recommendation != "NO_TRADE":
            results.append(recommendation)
    results.sort(key=lambda item: item.confidence, reverse=True)
    return {
        "mode": "paper_decision_support",
        "live_trading_enabled": False,
        "message": f"Recommendations ran in {req.asset_mode.upper()} mode with {req.option_structure.upper()} option structure. Options mode never substitutes stock; Single Leg never substitutes a spread; Multi Leg currently uses qualified Vertical Call/Vertical Put structures only; Best Fit may choose either.",
        "recommendations": results,
    }
