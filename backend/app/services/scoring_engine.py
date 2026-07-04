from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from app.models.schemas import EvidenceItem, OptionContract, Quote, ScoreBreakdown
from app.services.risk import bid_ask_spread_pct

MAX_SPREAD = 8.0
MIN_OPTION_VOLUME = 500
MIN_OPEN_INTEREST = 1000
MIN_PRICE_VOLUME = 1_000_000


@dataclass
class ScoreResult:
    direction: str
    confidence: int
    breakdown: ScoreBreakdown
    evidence: List[EvidenceItem]
    hard_failures: List[str]
    warnings: List[str]


def ev(category: str, name: str, value: Any, signal: str, score: int, weight: float, passed: bool, explanation: str, data_source: str) -> EvidenceItem:
    return EvidenceItem(category=category, name=name, value=value, signal=signal, score=max(-100, min(100, int(score))), weight=weight, passed=passed, explanation=explanation, data_source=data_source)


def score_technical(tech: dict) -> tuple[int, str, list[EvidenceItem], list[str]]:
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    ds = tech.get("data_source", "unknown")
    if ds != "yfinance_delayed":
        failures.append("Verified historical price data is unavailable.")
        return 0, "NO_TRADE", [ev("Technical", "Price history", ds, "fail", -100, 1, False, "Historical OHLCV data is required before any recommendation is allowed.", ds)], failures

    bull = 0
    bear = 0
    trend = tech.get("trend")
    if trend == "bullish":
        bull += 22
        evidence.append(ev("Technical", "Trend", trend, "bullish", 22, 0.22, True, "EMA alignment and price location indicate an upward trend.", ds))
    elif trend == "bearish":
        bear += 22
        evidence.append(ev("Technical", "Trend", trend, "bearish", 22, 0.22, True, "EMA alignment and price location indicate a downward trend.", ds))
    else:
        evidence.append(ev("Technical", "Trend", trend, "neutral", 0, 0.22, False, "Trend is mixed, reducing confidence.", ds))

    rsi = tech.get("rsi")
    if rsi is None:
        failures.append("RSI could not be calculated.")
        evidence.append(ev("Technical", "RSI", None, "fail", -10, 0.12, False, "RSI is required for momentum confirmation.", ds))
    elif 45 <= rsi <= 68:
        bull += 12
        evidence.append(ev("Technical", "RSI", rsi, "bullish", 12, 0.12, True, "RSI is in a constructive bullish range without being overbought.", ds))
    elif 32 <= rsi < 45:
        bear += 8
        evidence.append(ev("Technical", "RSI", rsi, "bearish", 8, 0.12, True, "RSI shows weak momentum.", ds))
    elif rsi >= 75 or rsi <= 25:
        evidence.append(ev("Technical", "RSI", rsi, "warning", -12, 0.12, False, "RSI is extreme; chase risk is high.", ds))
    else:
        evidence.append(ev("Technical", "RSI", rsi, "neutral", 0, 0.12, False, "RSI is not confirming strongly.", ds))

    macd_state = (tech.get("macd") or {}).get("state", "unknown")
    if macd_state == "bullish":
        bull += 14
        evidence.append(ev("Technical", "MACD", tech.get("macd"), "bullish", 14, 0.14, True, "MACD line is above signal with improving histogram.", ds))
    elif macd_state == "bearish":
        bear += 14
        evidence.append(ev("Technical", "MACD", tech.get("macd"), "bearish", 14, 0.14, True, "MACD line is below signal with weakening histogram.", ds))
    else:
        evidence.append(ev("Technical", "MACD", tech.get("macd"), "neutral", 0, 0.14, False, "MACD is mixed.", ds))

    if tech.get("vwap_relation") == "above":
        bull += 10
        evidence.append(ev("Technical", "VWAP", f"Price above 20-day VWAP {tech.get('vwap')}", "bullish", 10, 0.10, True, "Price is trading above VWAP, supporting long-call bias.", ds))
    elif tech.get("vwap_relation") == "below":
        bear += 10
        evidence.append(ev("Technical", "VWAP", f"Price below 20-day VWAP {tech.get('vwap')}", "bearish", 10, 0.10, True, "Price is below VWAP, supporting long-put bias.", ds))

    volume_ratio = tech.get("volume_ratio", 0)
    if volume_ratio >= 1.2:
        bull += 8 if bull >= bear else 0
        bear += 8 if bear > bull else 0
        evidence.append(ev("Technical", "Volume", f"{volume_ratio}x 20-day average", "pass", 8, 0.08, True, "Volume is above average, confirming participation.", ds))
    else:
        evidence.append(ev("Technical", "Volume", f"{volume_ratio}x 20-day average", "warning", -6, 0.08, False, "Volume is not confirming the setup.", ds))

    bb_pos = tech.get("bollinger_position")
    if bb_pos is not None:
        if 0.15 <= bb_pos <= 0.85:
            evidence.append(ev("Technical", "Bollinger Bands", bb_pos, "pass", 6, 0.06, True, "Price is not stretched outside the bands.", ds))
            bull += 3 if bull >= bear else 0
            bear += 3 if bear > bull else 0
        else:
            evidence.append(ev("Technical", "Bollinger Bands", bb_pos, "warning", -6, 0.06, False, "Price is stretched near/outside a band, increasing reversal risk.", ds))

    atr = tech.get("atr")
    evidence.append(ev("Technical", "ATR", atr, "info", 0, 0.04, True, "ATR is used to frame stops and holding-period risk.", ds))
    direction = "CALL" if bull > bear else "PUT" if bear > bull else "NO_TRADE"
    score = max(bull, bear)
    # Normalize directional evidence into a 0-100 technical score.
    tech_score = int(max(0, min(100, 40 + score - min(bull, bear) * 0.5))) if direction != "NO_TRADE" else 35
    return tech_score, direction, evidence, failures


def score_options(contract: OptionContract | None, direction: str) -> tuple[int, list[EvidenceItem], list[str], list[str]]:
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    warnings: list[str] = []
    ds = "yfinance_delayed_options"
    if contract is None:
        failures.append(f"No usable {direction} option contract was found.")
        evidence.append(ev("Options", "Contract availability", None, "fail", -100, 1, False, "A liquid options contract is required before a recommendation can qualify.", ds))
        return 0, evidence, failures, warnings

    score = 0
    spread = bid_ask_spread_pct(contract.bid, contract.ask)
    if spread <= MAX_SPREAD:
        score += 30
        evidence.append(ev("Options", "Bid/ask spread", f"{spread}%", "pass", 30, 0.30, True, "Spread is tight enough for safer entry/exit.", ds))
    else:
        failures.append(f"Bid/ask spread {spread}% exceeds {MAX_SPREAD}% maximum.")
        evidence.append(ev("Options", "Bid/ask spread", f"{spread}%", "fail", -30, 0.30, False, "Wide spreads create slippage and poor fills.", ds))

    if contract.volume >= MIN_OPTION_VOLUME:
        score += 22
        evidence.append(ev("Options", "Volume", contract.volume, "pass", 22, 0.22, True, "Contract volume meets liquidity minimum.", ds))
    else:
        failures.append(f"Option volume {contract.volume} is below {MIN_OPTION_VOLUME} minimum.")
        evidence.append(ev("Options", "Volume", contract.volume, "fail", -22, 0.22, False, "Low volume makes entries/exits less reliable.", ds))

    if contract.open_interest >= MIN_OPEN_INTEREST:
        score += 22
        evidence.append(ev("Options", "Open interest", contract.open_interest, "pass", 22, 0.22, True, "Open interest meets liquidity minimum.", ds))
    else:
        failures.append(f"Open interest {contract.open_interest} is below {MIN_OPEN_INTEREST} minimum.")
        evidence.append(ev("Options", "Open interest", contract.open_interest, "fail", -22, 0.22, False, "Low open interest can increase execution risk.", ds))

    iv = contract.implied_volatility
    if 0.10 <= iv <= 0.80:
        score += 14
        evidence.append(ev("Options", "Implied volatility", f"{round(iv * 100, 1)}%", "pass", 14, 0.14, True, "IV is within the allowed range for this basic long-options strategy.", ds))
    else:
        warnings.append("Implied volatility is outside preferred range.")
        evidence.append(ev("Options", "Implied volatility", f"{round(iv * 100, 1)}%", "warning", -8, 0.14, False, "Extreme IV can make long options expensive or unreliable.", ds))

    abs_delta = abs(contract.delta)
    if 0.25 <= abs_delta <= 0.65:
        score += 12
        evidence.append(ev("Options", "Delta", contract.delta, "pass", 12, 0.12, True, "Delta is in a usable range for directional exposure.", ds))
    else:
        warnings.append("Delta is outside preferred directional range.")
        evidence.append(ev("Options", "Delta", contract.delta, "warning", -6, 0.12, False, "Delta is not in the preferred range.", ds))

    return int(max(0, min(100, score))), evidence, failures, warnings


def score_market(market: dict, direction: str) -> tuple[int, list[EvidenceItem], list[str]]:
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    ds = market.get("data_source", "unknown")
    if ds != "yfinance_delayed":
        failures.append("Verified SPY/QQQ market context is unavailable.")
        evidence.append(ev("Market", "Market context", ds, "fail", -100, 1, False, "SPY/QQQ context is required before trade qualification.", ds))
        return 0, evidence, failures
    breadth = market.get("market_breadth")
    score = int(market.get("score", 0))
    if direction == "CALL" and breadth == "positive":
        evidence.append(ev("Market", "Market breadth", breadth, "pass", score, 0.60, True, "SPY/QQQ context supports bullish trades.", ds))
    elif direction == "PUT" and breadth == "weak":
        evidence.append(ev("Market", "Market breadth", breadth, "pass", score, 0.60, True, "Weak market context supports bearish trades.", ds))
    elif breadth == "mixed":
        evidence.append(ev("Market", "Market breadth", breadth, "warning", 45, 0.60, False, "Market context is mixed; confidence is reduced.", ds))
    else:
        evidence.append(ev("Market", "Market breadth", breadth, "warning", 35, 0.60, False, "Market context does not strongly support the trade direction.", ds))
    evidence.append(ev("Market", "SPY trend", market.get("spy_trend"), "info", 0, 0.20, True, "SPY trend is used as broad-market confirmation.", ds))
    evidence.append(ev("Market", "QQQ trend", market.get("qqq_trend"), "info", 0, 0.20, True, "QQQ trend is used as growth/tech confirmation.", ds))
    return max(0, min(100, score)), evidence, failures


def score_risk(quote: Quote, contract: OptionContract | None, account_value: float, max_risk_percent: float, contracts: int) -> tuple[int, list[EvidenceItem], list[str]]:
    evidence: list[EvidenceItem] = []
    failures: list[str] = []
    ds = quote.data_source
    if quote.data_source != "yfinance_delayed":
        failures.append("Verified quote is unavailable.")
        evidence.append(ev("Risk", "Quote quality", quote.data_source, "fail", -100, 0.30, False, "Current quote must be verified before a recommendation is allowed.", ds))
    else:
        evidence.append(ev("Risk", "Quote quality", quote.data_source, "pass", 20, 0.30, True, "Quote is from delayed live provider.", ds))

    if quote.volume >= MIN_PRICE_VOLUME:
        evidence.append(ev("Risk", "Underlying volume", quote.volume, "pass", 20, 0.20, True, "Underlying volume meets minimum liquidity requirement.", ds))
    else:
        failures.append(f"Underlying volume {quote.volume} is below {MIN_PRICE_VOLUME} minimum.")
        evidence.append(ev("Risk", "Underlying volume", quote.volume, "fail", -20, 0.20, False, "Underlying liquidity is too low.", ds))

    if contract is None or contracts < 1:
        failures.append("Position size is zero under configured risk limits.")
        evidence.append(ev("Risk", "Position sizing", contracts, "fail", -30, 0.30, False, "Configured account/risk limits do not allow even one contract.", ds))
    else:
        evidence.append(ev("Risk", "Position sizing", contracts, "pass", 30, 0.30, True, f"Position size respects {max_risk_percent}% max-risk setting.", ds))
    score = 100 if not failures else max(0, 50 - 15 * len(failures))
    return score, evidence, failures
