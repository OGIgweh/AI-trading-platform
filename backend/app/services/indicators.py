from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.services.market_data import get_price_history, normalize_symbol


def _provider_enabled() -> bool:
    return settings.market_data_provider.lower() in {"auto", "yfinance"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except Exception:
        return default


def _rsi(close, period: int = 14) -> float | None:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    value = 100 - (100 / (1 + rs))
    if value.empty or value.iloc[-1] != value.iloc[-1]:
        return None
    return round(float(value.iloc[-1]), 2)


def _atr(df, period: int = 14) -> float | None:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = (
        high_low.to_frame("hl")
        .join(high_close.to_frame("hc"))
        .join(low_close.to_frame("lc"))
        .max(axis=1)
    )
    value = true_range.rolling(period).mean().iloc[-1]
    if value != value:
        return None
    return round(float(value), 2)


def _macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    if len(histogram) < 3:
        state = "mixed"
    elif macd_line.iloc[-1] > signal_line.iloc[-1] and histogram.iloc[-1] > histogram.iloc[-2]:
        state = "bullish"
    elif macd_line.iloc[-1] < signal_line.iloc[-1] and histogram.iloc[-1] < histogram.iloc[-2]:
        state = "bearish"
    else:
        state = "mixed"
    return {
        "state": state,
        "macd": round(float(macd_line.iloc[-1]), 4),
        "signal": round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
    }


@lru_cache(maxsize=512)
def _technical_cached(symbol: str, cache_bucket: int):
    del cache_bucket
    frame, canonical_symbol, status = get_price_history(symbol, period="9mo", interval="1d")
    if status != "ok" or frame is None or frame.empty:
        return {
            "symbol": normalize_symbol(symbol),
            "data_source": status,
            "error": (
                "Market-data provider is temporarily unavailable."
                if status == "provider_unavailable"
                else "No verified price history was found."
            ),
        }

    frame = frame.dropna(subset=["Close", "High", "Low", "Volume"])
    close = frame["Close"]
    if len(close) < 60:
        return {
            "symbol": canonical_symbol,
            "data_source": "insufficient_history",
            "error": "At least 60 daily price bars are required for indicator analysis.",
        }

    last = float(close.iloc[-1])
    ema9_series = close.ewm(span=9, adjust=False).mean()
    ema21_series = close.ewm(span=21, adjust=False).mean()
    ema50_series = close.ewm(span=50, adjust=False).mean()
    ema200_series = close.ewm(span=200, adjust=False).mean() if len(close) >= 200 else ema50_series
    ema9 = float(ema9_series.iloc[-1])
    ema21 = float(ema21_series.iloc[-1])
    ema50 = float(ema50_series.iloc[-1])
    ema200 = float(ema200_series.iloc[-1])
    rsi = _rsi(close)
    macd = _macd(close)
    atr = _atr(frame)
    volume = int(frame["Volume"].iloc[-1])
    average_volume_20 = float(frame["Volume"].tail(20).mean())
    volume_ratio = round(volume / average_volume_20, 2) if average_volume_20 else 0
    typical_price = (frame["High"] + frame["Low"] + frame["Close"]) / 3
    vwap_20 = float((typical_price * frame["Volume"]).tail(20).sum() / max(frame["Volume"].tail(20).sum(), 1))
    vwap_relation = "above" if last >= vwap_20 else "below"
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bollinger_upper = float((sma20 + 2 * std20).iloc[-1])
    bollinger_lower = float((sma20 - 2 * std20).iloc[-1])
    bollinger_position = round((last - bollinger_lower) / max(bollinger_upper - bollinger_lower, 0.01), 2)
    support = round(float(close.tail(20).min()), 2)
    resistance = round(float(close.tail(20).max()), 2)
    bullish_alignment = ema9 > ema21 > ema50
    bearish_alignment = ema9 < ema21 < ema50
    trend = "bullish" if bullish_alignment and last > ema50 else "bearish" if bearish_alignment and last < ema50 else "mixed"
    momentum = (
        "bullish"
        if (rsi is not None and 45 <= rsi <= 70 and macd["state"] == "bullish")
        else "bearish"
        if (rsi is not None and (rsi < 40 or macd["state"] == "bearish"))
        else "mixed"
    )

    return {
        "symbol": canonical_symbol,
        "last_price": round(last, 2),
        "trend": trend,
        "momentum": momentum,
        "ema_alignment": bullish_alignment,
        "bearish_ema_alignment": bearish_alignment,
        "rsi": rsi,
        "macd": macd,
        "vwap": round(vwap_20, 2),
        "vwap_relation": vwap_relation,
        "atr": atr,
        "support": support,
        "resistance": resistance,
        "ema9": round(ema9, 2),
        "ema21": round(ema21, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "bollinger_upper": round(bollinger_upper, 2),
        "bollinger_lower": round(bollinger_lower, 2),
        "bollinger_position": bollinger_position,
        "volume": volume,
        "avg_volume_20": round(average_volume_20),
        "volume_ratio": volume_ratio,
        "data_source": "yfinance_delayed",
    }


def technical_snapshot(symbol: str):
    normalized = normalize_symbol(symbol)
    if _provider_enabled():
        bucket = int(datetime.now().timestamp() // max(60, settings.market_data_cache_seconds * 5))
        return _technical_cached(normalized, bucket)
    return {
        "symbol": normalized,
        "data_source": "provider_unavailable",
        "error": "No verified price-history provider is enabled.",
    }


def market_context_snapshot():
    if not _provider_enabled():
        return {"data_source": "provider_unavailable", "score": 0, "market_breadth": "unknown"}

    spy = technical_snapshot("SPY")
    qqq = technical_snapshot("QQQ")
    vix = technical_snapshot("^VIX")
    live = spy.get("data_source") == "yfinance_delayed" and qqq.get("data_source") == "yfinance_delayed"
    if not live:
        unavailable_status = (
            "provider_unavailable"
            if "provider_unavailable" in {spy.get("data_source"), qqq.get("data_source")}
            else "unavailable"
        )
        return {
            "data_source": unavailable_status,
            "score": 0,
            "market_breadth": "unknown",
            "error": "SPY/QQQ market context is unavailable.",
        }

    spy_component = 80 if spy.get("trend") == "bullish" else 30 if spy.get("trend") == "bearish" else 50
    qqq_component = 80 if qqq.get("trend") == "bullish" else 30 if qqq.get("trend") == "bearish" else 50
    vix_penalty = 10 if vix.get("trend") == "bullish" else 0
    score = max(0, min(100, round((spy_component * 0.45) + (qqq_component * 0.45) + 10 - vix_penalty)))
    return {
        "spy_trend": spy.get("trend"),
        "qqq_trend": qqq.get("trend"),
        "vix_state": "elevated" if vix.get("trend") == "bullish" else "normal_or_unavailable",
        "market_breadth": "positive" if score >= 65 else "weak" if score <= 45 else "mixed",
        "score": int(score),
        "data_source": "yfinance_delayed",
    }
