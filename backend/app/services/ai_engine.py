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
)
from app.services.indicators import market_context_snapshot, technical_snapshot
from app.services.market_data import get_option_chain, get_quote, normalize_symbol
from app.services.risk import (
    bid_ask_spread_pct,
    planned_loss_per_contract,
    position_contracts,
    spread_contracts,
)
from app.services.scoring_engine import score_market, score_options, score_risk, score_technical


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
            if raw_data.get("quote", {}).get("data_source") == "yfinance_delayed"
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


def analyze_trade(req: AnalyzeRequest) -> Recommendation:
    symbol = normalize_symbol(req.symbol)
    threshold = req.min_confidence
    quote = get_quote(symbol)
    if quote.data_source != "yfinance_delayed" or quote.price <= 0:
        return _data_quality_no_trade(req, symbol, quote)

    tech = technical_snapshot(symbol)
    market = market_context_snapshot()
    chain = get_option_chain(symbol)
    raw_data = {
        "quote": quote.model_dump(),
        "technical": tech,
        "market_context": market,
        "options_contract_count": len(chain),
        "analysis_settings": {
            "account_value": req.account_value,
            "max_risk_percent": req.max_risk_percent,
            "confidence_threshold": threshold,
            "risk_budget_dollars": round(req.account_value * req.max_risk_percent / 100, 2),
        },
    }

    all_evidence: list[EvidenceItem] = []
    hard_failures: list[str] = []
    warnings: list[str] = []

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
        technical_verified = tech.get("data_source") == "yfinance_delayed"
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
        strategy_name = "Long Call" if direction == "CALL" else "Long Put"
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
        strategy_name = "Bull Call Debit Spread" if direction == "CALL" else "Bear Put Debit Spread"
        selected_contract_raw = {
            "strategy": strategy_name,
            "long": long_contract.model_dump(),
            "short": short_contract.model_dump(),
            "net_debit": entry_price,
            "width": spread["width"],
        }
        all_evidence.append(EvidenceItem(
            category="Options",
            name="Defined-risk spread fallback",
            value={"net_debit": entry_price, "width": spread["width"], "quantity": quantity},
            signal="pass",
            score=20,
            weight=0.20,
            passed=True,
            explanation="A debit spread was selected because a single long option did not fit the configured risk budget. Maximum loss is limited to the net debit.",
            data_source="yfinance_delayed_options",
        ))

    all_evidence.extend(options_evidence)
    hard_failures.extend(options_failures)
    warnings.extend(options_warnings)

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
        (technical_score * 0.40)
        + (options_score * 0.30)
        + (market_score * 0.20)
        + (risk_score * 0.10)
    )
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
        hard_failures.append(f"Confidence {confidence}% is below the configured {threshold}% threshold.")

    raw_data.update({
        "selected_strategy": selected_strategy,
        "selected_contract": selected_contract_raw,
        "planned_risk_dollars": planned_risk,
        "absolute_max_loss_dollars": absolute_max_loss,
        "blocking_failures": list(dict.fromkeys(hard_failures)),
        "warnings": list(dict.fromkeys(warnings)),
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
            "This is decision support, not a guarantee of profit."
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
        data_quality="verified_live_delayed",
    )


def generate_recommendations(req: RecommendationsRequest):
    results = []
    unique_symbols = list(dict.fromkeys(normalize_symbol(symbol) for symbol in req.symbols if symbol.strip()))[:20]
    for symbol in unique_symbols:
        recommendation = analyze_trade(AnalyzeRequest(
            symbol=symbol,
            account_value=req.account_value,
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
        "message": "Recommendations use delayed provider data, defined risk controls, and debit-spread fallback when a single option is too expensive. Missing critical evidence produces NO_TRADE.",
        "recommendations": results,
    }
