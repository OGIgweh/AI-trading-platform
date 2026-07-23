from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from app.models.schemas import EvidenceItem, OptionContract, Quote, ScoreBreakdown
from app.services.risk import bid_ask_spread_pct

# Preferred liquidity thresholds. Missing one preferred threshold is a warning;
# critically illiquid contracts remain hard failures.
PREFERRED_SPREAD = 8.0
MAX_EXECUTABLE_SPREAD = 20.0
PREFERRED_OPTION_VOLUME = 250
PREFERRED_OPEN_INTEREST = 500
CRITICAL_OPTION_VOLUME = 10
CRITICAL_OPEN_INTEREST = 100
MIN_PRICE_VOLUME = 250_000


@dataclass
class ScoreResult:
    direction: str
    confidence: int
    breakdown: ScoreBreakdown
    evidence: List[EvidenceItem]
    hard_failures: List[str]
    warnings: List[str]


def ev(
    category: str,
    name: str,
    value: Any,
    signal: str,
    score: int,
    weight: float,
    passed: bool,
    explanation: str,
    data_source: str,
) -> EvidenceItem:
    return EvidenceItem(
        category=category,
        name=name,
        value=value,
        signal=signal,
        score=max(-100, min(100, int(score))),
        weight=weight,
        passed=passed,
        explanation=explanation,
        data_source=data_source,
    )


def score_technical(tech: dict) -> tuple[int, str, list[EvidenceItem], list[str]]:
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    ds = tech.get("data_source", "unknown")
    if ds != "yfinance_delayed":
        failures.append("Verified historical price data is unavailable.")
        return 0, "NO_TRADE", [
            ev(
                "Technical",
                "Price history",
                ds,
                "fail",
                -100,
                1,
                False,
                "Historical OHLCV data is required before any recommendation is allowed.",
                ds,
            )
        ], failures

    bull = 0
    bear = 0
    trend = tech.get("trend")
    if trend == "bullish":
        bull += 24
        evidence.append(ev("Technical", "Trend", trend, "bullish", 24, 0.24, True, "EMA alignment and price location indicate an upward trend.", ds))
    elif trend == "bearish":
        bear += 24
        evidence.append(ev("Technical", "Trend", trend, "bearish", 24, 0.24, True, "EMA alignment and price location indicate a downward trend.", ds))
    else:
        evidence.append(ev("Technical", "Trend", trend, "neutral", 0, 0.24, False, "Trend is mixed, reducing confidence.", ds))

    rsi = tech.get("rsi")
    if rsi is None:
        failures.append("RSI could not be calculated.")
        evidence.append(ev("Technical", "RSI", None, "fail", -10, 0.12, False, "RSI is required for momentum confirmation.", ds))
    elif 48 <= rsi <= 68:
        bull += 12
        evidence.append(ev("Technical", "RSI", rsi, "bullish", 12, 0.12, True, "RSI confirms constructive bullish momentum without being overbought.", ds))
    elif 32 <= rsi <= 48:
        bear += 10
        evidence.append(ev("Technical", "RSI", rsi, "bearish", 10, 0.12, True, "RSI confirms weak or bearish momentum.", ds))
    elif rsi >= 75 or rsi <= 25:
        evidence.append(ev("Technical", "RSI", rsi, "warning", -12, 0.12, False, "RSI is extreme; reversal and chase risk are elevated.", ds))
    else:
        evidence.append(ev("Technical", "RSI", rsi, "neutral", 0, 0.12, False, "RSI is not strongly directional.", ds))

    macd_state = (tech.get("macd") or {}).get("state", "unknown")
    if macd_state == "bullish":
        bull += 16
        evidence.append(ev("Technical", "MACD", tech.get("macd"), "bullish", 16, 0.16, True, "MACD is above signal with improving histogram.", ds))
    elif macd_state == "bearish":
        bear += 16
        evidence.append(ev("Technical", "MACD", tech.get("macd"), "bearish", 16, 0.16, True, "MACD is below signal with weakening histogram.", ds))
    else:
        evidence.append(ev("Technical", "MACD", tech.get("macd"), "neutral", 0, 0.16, False, "MACD is mixed.", ds))

    if tech.get("vwap_relation") == "above":
        bull += 12
        evidence.append(ev("Technical", "VWAP", f"Price above 20-day VWAP {tech.get('vwap')}", "bullish", 12, 0.12, True, "Price is above VWAP, supporting bullish bias.", ds))
    elif tech.get("vwap_relation") == "below":
        bear += 12
        evidence.append(ev("Technical", "VWAP", f"Price below 20-day VWAP {tech.get('vwap')}", "bearish", 12, 0.12, True, "Price is below VWAP, supporting bearish bias.", ds))

    volume_ratio = float(tech.get("volume_ratio", 0) or 0)
    leading = "bullish" if bull > bear else "bearish" if bear > bull else "neutral"
    if volume_ratio >= 1.15 and leading != "neutral":
        if leading == "bullish":
            bull += 10
        else:
            bear += 10
        evidence.append(ev("Technical", "Volume", f"{volume_ratio}x 20-day average", "pass", 10, 0.10, True, "Above-average volume confirms the leading direction.", ds))
    elif volume_ratio >= 0.75:
        evidence.append(ev("Technical", "Volume", f"{volume_ratio}x 20-day average", "info", 2, 0.10, True, "Volume is adequate but not an exceptional confirmation.", ds))
    else:
        evidence.append(ev("Technical", "Volume", f"{volume_ratio}x 20-day average", "warning", -6, 0.10, False, "Volume is below normal and reduces conviction.", ds))

    bb_pos = tech.get("bollinger_position")
    if bb_pos is not None:
        if 0.10 <= bb_pos <= 0.90:
            evidence.append(ev("Technical", "Bollinger Bands", bb_pos, "pass", 6, 0.06, True, "Price is not materially stretched beyond the bands.", ds))
            if bull >= bear:
                bull += 4
            else:
                bear += 4
        else:
            evidence.append(ev("Technical", "Bollinger Bands", bb_pos, "warning", -6, 0.06, False, "Price is stretched near or beyond a band.", ds))

    evidence.append(ev("Technical", "ATR", tech.get("atr"), "info", 0, 0.04, True, "ATR frames expected movement and stop distance.", ds))

    directional_gap = abs(bull - bear)
    direction = "CALL" if bull > bear else "PUT" if bear > bull else "NO_TRADE"
    if direction == "NO_TRADE" or directional_gap < 10:
        direction = "NO_TRADE"
        technical_score = max(35, min(64, 40 + directional_gap))
    else:
        dominant = max(bull, bear)
        opposing = min(bull, bear)
        technical_score = int(max(0, min(100, 45 + dominant - (opposing * 0.60))))

    return technical_score, direction, evidence, failures


def score_options(contract: OptionContract | None, direction: str) -> tuple[int, list[EvidenceItem], list[str], list[str]]:
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    warnings: list[str] = []
    ds = "yfinance_delayed_options"
    if contract is None:
        failures.append(f"No usable {direction} option contract was found.")
        evidence.append(ev("Options", "Contract availability", None, "fail", -100, 1, False, "A usable options contract is required before a recommendation can qualify.", ds))
        return 0, evidence, failures, warnings

    score = 0
    spread = bid_ask_spread_pct(contract.bid, contract.ask)
    if spread <= PREFERRED_SPREAD:
        score += 32
        evidence.append(ev("Options", "Bid/ask spread", f"{spread}%", "pass", 32, 0.32, True, "Spread is within the preferred execution range.", ds))
    elif spread <= MAX_EXECUTABLE_SPREAD:
        score += 16
        warnings.append(f"Bid/ask spread {spread}% is wider than the preferred {PREFERRED_SPREAD}% range.")
        evidence.append(ev("Options", "Bid/ask spread", f"{spread}%", "warning", 16, 0.32, False, "The contract remains executable but slippage risk is elevated.", ds))
    else:
        failures.append(f"Bid/ask spread {spread}% exceeds the {MAX_EXECUTABLE_SPREAD}% safety maximum.")
        evidence.append(ev("Options", "Bid/ask spread", f"{spread}%", "fail", -32, 0.32, False, "The spread is too wide for a disciplined entry.", ds))

    volume_ok = contract.volume >= PREFERRED_OPTION_VOLUME
    oi_ok = contract.open_interest >= PREFERRED_OPEN_INTEREST
    critically_illiquid = contract.volume < CRITICAL_OPTION_VOLUME and contract.open_interest < CRITICAL_OPEN_INTEREST

    if volume_ok:
        score += 22
        evidence.append(ev("Options", "Volume", contract.volume, "pass", 22, 0.22, True, "Contract volume meets the preferred liquidity level.", ds))
    elif contract.volume >= CRITICAL_OPTION_VOLUME:
        score += 10
        warnings.append(f"Option volume {contract.volume} is below the preferred {PREFERRED_OPTION_VOLUME} level.")
        evidence.append(ev("Options", "Volume", contract.volume, "warning", 10, 0.22, False, "Volume is usable but below the preferred level.", ds))
    else:
        evidence.append(ev("Options", "Volume", contract.volume, "warning", 0, 0.22, False, "Contract volume is very low.", ds))

    if oi_ok:
        score += 22
        evidence.append(ev("Options", "Open interest", contract.open_interest, "pass", 22, 0.22, True, "Open interest meets the preferred liquidity level.", ds))
    elif contract.open_interest >= CRITICAL_OPEN_INTEREST:
        score += 10
        warnings.append(f"Open interest {contract.open_interest} is below the preferred {PREFERRED_OPEN_INTEREST} level.")
        evidence.append(ev("Options", "Open interest", contract.open_interest, "warning", 10, 0.22, False, "Open interest is usable but below the preferred level.", ds))
    else:
        evidence.append(ev("Options", "Open interest", contract.open_interest, "warning", 0, 0.22, False, "Open interest is very low.", ds))

    if critically_illiquid:
        failures.append("Both option volume and open interest are below minimum executable levels.")

    iv = float(contract.implied_volatility or 0)
    if 0.08 <= iv <= 1.00:
        score += 14
        evidence.append(ev("Options", "Implied volatility", f"{round(iv * 100, 1)}%", "pass", 14, 0.14, True, "IV is within the permitted range for the proposed strategy.", ds))
    else:
        warnings.append("Implied volatility is outside the preferred range.")
        evidence.append(ev("Options", "Implied volatility", f"{round(iv * 100, 1)}%", "warning", 3, 0.14, False, "Extreme or missing IV reduces confidence.", ds))
        score += 3

    abs_delta = abs(float(contract.delta or 0))
    if 0.22 <= abs_delta <= 0.65:
        score += 10
        evidence.append(ev("Options", "Delta", contract.delta, "pass", 10, 0.10, True, "Delta provides usable directional exposure.", ds))
    else:
        warnings.append("Delta is outside the preferred directional range.")
        evidence.append(ev("Options", "Delta", contract.delta, "warning", 2, 0.10, False, "Delta is less efficient for this directional setup.", ds))
        score += 2

    return int(max(0, min(100, score))), evidence, failures, warnings


def score_market(market: dict, direction: str) -> tuple[int, list[EvidenceItem], list[str]]:
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    ds = market.get("data_source", "unknown")
    if ds != "yfinance_delayed":
        failures.append("Verified SPY/QQQ market context is unavailable.")
        evidence.append(ev("Market", "Market context", ds, "fail", -100, 1, False, "Broad-market context is required before qualification.", ds))
        return 0, evidence, failures

    breadth = market.get("market_breadth")
    raw_score = int(market.get("score", 0) or 0)
    aligned = (direction == "CALL" and breadth == "positive") or (direction == "PUT" and breadth == "weak")
    opposed = (direction == "CALL" and breadth == "weak") or (direction == "PUT" and breadth == "positive")

    if aligned:
        directional_score = max(75, raw_score if direction == "CALL" else 100 - raw_score)
        evidence.append(ev("Market", "Market alignment", f"{breadth} for {direction}", "pass", directional_score, 0.60, True, "Broad-market context supports the proposed direction.", ds))
    elif opposed:
        directional_score = 25
        evidence.append(ev("Market", "Market alignment", f"{breadth} against {direction}", "warning", 25, 0.60, False, "Broad-market context opposes the proposed direction.", ds))
    else:
        directional_score = 52
        evidence.append(ev("Market", "Market alignment", f"{breadth} for {direction}", "warning", 52, 0.60, False, "Broad-market context is mixed rather than strongly aligned.", ds))

    evidence.append(ev("Market", "SPY trend", market.get("spy_trend"), "info", 0, 0.20, True, "SPY trend provides broad-market context.", ds))
    evidence.append(ev("Market", "QQQ trend", market.get("qqq_trend"), "info", 0, 0.20, True, "QQQ trend provides growth/technology context.", ds))
    return max(0, min(100, int(directional_score))), evidence, failures


def score_risk(
    quote: Quote,
    contract: OptionContract | None,
    account_value: float,
    max_risk_percent: float,
    contracts: int,
    *,
    planned_risk: float = 0.0,
    absolute_max_loss: float = 0.0,
    strategy_name: str = "Long option",
) -> tuple[int, list[EvidenceItem], list[str]]:
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    ds = quote.data_source

    if quote.data_source != "yfinance_delayed":
        failures.append("Verified quote is unavailable.")
        evidence.append(ev("Risk", "Quote quality", quote.data_source, "fail", -100, 0.25, False, "A verified quote is required.", ds))
    else:
        evidence.append(ev("Risk", "Quote quality", quote.data_source, "pass", 25, 0.25, True, "Quote is from the delayed live provider.", ds))

    if quote.volume >= MIN_PRICE_VOLUME:
        evidence.append(ev("Risk", "Underlying volume", quote.volume, "pass", 20, 0.20, True, "Underlying volume meets the minimum liquidity requirement.", ds))
    else:
        failures.append(f"Underlying volume {quote.volume} is below {MIN_PRICE_VOLUME} minimum.")
        evidence.append(ev("Risk", "Underlying volume", quote.volume, "fail", -20, 0.20, False, "Underlying liquidity is too low.", ds))

    risk_budget = round(account_value * (max_risk_percent / 100), 2)
    if contract is None or contracts < 1:
        failures.append(
            f"No position fits the configured ${risk_budget:,.2f} risk budget. "
            "Increase account value/risk only if that accurately reflects your real limits, or use a lower-cost defined-risk spread."
        )
        evidence.append(ev("Risk", "Position sizing", contracts, "fail", -35, 0.35, False, "The selected strategy cannot be sized within the configured risk budget.", ds))
    else:
        evidence.append(ev(
            "Risk",
            "Position sizing",
            {
                "contracts": contracts,
                "planned_risk": round(planned_risk, 2),
                "absolute_max_loss": round(absolute_max_loss, 2),
                "risk_budget": risk_budget,
                "strategy": strategy_name,
            },
            "pass",
            35,
            0.35,
            True,
            "Quantity fits the configured risk budget; full-premium or spread max loss remains visible.",
            ds,
        ))

    score = 100 if not failures else max(0, 55 - 20 * len(failures))
    return score, evidence, failures
