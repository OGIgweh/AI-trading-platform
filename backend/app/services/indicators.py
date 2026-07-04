from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

from app.core.config import settings


def _provider_enabled() -> bool:
    return settings.market_data_provider.lower() in {"auto", "yfinance"}


def _sample_technical_snapshot(symbol: str):
    snapshots = {
        "AAPL": {"trend": "bullish", "ema_alignment": True, "rsi": 58, "macd": "bullish", "vwap_relation": "above", "atr": 3.1, "support": 211.0, "resistance": 221.0, "score": 82, "data_source": "sample"},
        "MSFT": {"trend": "mixed", "ema_alignment": False, "rsi": 47, "macd": "bearish", "vwap_relation": "below", "atr": 6.4, "support": 490.0, "resistance": 506.0, "score": 48, "data_source": "sample"},
        "NVDA": {"trend": "bullish", "ema_alignment": True, "rsi": 64, "macd": "bullish", "vwap_relation": "above", "atr": 7.9, "support": 158.0, "resistance": 172.0, "score": 86, "data_source": "sample"},
        "SPY": {"trend": "bullish", "ema_alignment": True, "rsi": 61, "macd": "bullish", "vwap_relation": "above", "atr": 5.2, "support": 618.0, "resistance": 631.0, "score": 76, "data_source": "sample"},
        "QQQ": {"trend": "bullish", "ema_alignment": True, "rsi": 60, "macd": "bullish", "vwap_relation": "above", "atr": 5.7, "support": 549.0, "resistance": 563.0, "score": 78, "data_source": "sample"},
    }
    return snapshots.get(symbol.upper(), {"score": 0, "trend": "unknown", "ema_alignment": False, "rsi": None, "macd": "unknown", "vwap_relation": "unknown", "data_source": "sample"})


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except Exception:
        return default


def _rsi(close, period: int = 14) -> float | None:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    value = rsi = 100 - (100 / (1 + rs))
    if value.empty or value.iloc[-1] != value.iloc[-1]:
        return None
    return round(float(value.iloc[-1]), 2)


def _atr(df, period: int = 14) -> float | None:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = high_low.to_frame("hl").join(high_close.to_frame("hc")).join(low_close.to_frame("lc")).max(axis=1)
    value = tr.rolling(period).mean().iloc[-1]
    if value != value:
        return None
    return round(float(value), 2)


def _macd_signal(close) -> str:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-1] > macd.iloc[-3]:
        return "bullish"
    if macd.iloc[-1] < signal.iloc[-1] and macd.iloc[-1] < macd.iloc[-3]:
        return "bearish"
    return "mixed"


@lru_cache(maxsize=256)
def _yf_technical_cached(symbol: str, cache_bucket: int):
    del cache_bucket
    try:
        import yfinance as yf

        df = yf.Ticker(symbol).history(period="6mo", interval="1d", auto_adjust=False)
        if df is None or df.empty or len(df) < 60:
            return None
        close = df["Close"].dropna()
        if len(close) < 60:
            return None
        last = float(close.iloc[-1])
        ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close) >= 200 else ema50
        rsi = _rsi(close)
        macd = _macd_signal(close)
        atr = _atr(df)
        support = round(float(close.tail(20).min()), 2)
        resistance = round(float(close.tail(20).max()), 2)
        vwap_relation = "above" if last >= float((df["Close"] * df["Volume"]).tail(20).sum() / max(df["Volume"].tail(20).sum(), 1)) else "below"
        ema_alignment = ema9 > ema21 > ema50
        down_alignment = ema9 < ema21 < ema50
        trend = "bullish" if ema_alignment and last > ema50 else "bearish" if down_alignment and last < ema50 else "mixed"

        score = 50
        score += 18 if trend == "bullish" else -18 if trend == "bearish" else 0
        score += 10 if ema_alignment else -10 if down_alignment else 0
        if rsi is not None:
            score += 10 if 45 <= rsi <= 68 else -10 if rsi >= 75 or rsi <= 30 else 0
        score += 10 if macd == "bullish" else -10 if macd == "bearish" else 0
        score += 7 if vwap_relation == "above" else -7
        score = int(max(0, min(100, score)))

        return {
            "trend": trend,
            "ema_alignment": ema_alignment,
            "rsi": rsi,
            "macd": macd,
            "vwap_relation": vwap_relation,
            "atr": atr,
            "support": support,
            "resistance": resistance,
            "ema9": round(ema9, 2),
            "ema21": round(ema21, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
            "score": score,
            "data_source": "yfinance_delayed",
        }
    except Exception:
        return None


def technical_snapshot(symbol: str):
    symbol = symbol.upper().strip()
    if _provider_enabled():
        bucket = int(datetime.now().timestamp() // max(60, settings.market_data_cache_seconds * 5))
        live = _yf_technical_cached(symbol, bucket)
        if live:
            return live
    return _sample_technical_snapshot(symbol)


def market_context_snapshot():
    if _provider_enabled():
        spy = technical_snapshot("SPY")
        qqq = technical_snapshot("QQQ")
        vix = technical_snapshot("^VIX")
        live = spy.get("data_source") != "sample" or qqq.get("data_source") != "sample"
        score = round((spy.get("score", 50) * 0.45) + (qqq.get("score", 50) * 0.45) + ((100 - vix.get("score", 50)) * 0.10))
        return {
            "spy_trend": spy.get("trend"),
            "qqq_trend": qqq.get("trend"),
            "vix_state": "elevated" if vix.get("score", 50) >= 65 else "normal",
            "market_breadth": "positive" if score >= 65 else "weak" if score <= 45 else "mixed",
            "sector_rotation": "not_available_yet",
            "score": int(max(0, min(100, score))),
            "data_source": "yfinance_delayed" if live else "sample"
        }
    return {
        "spy_trend": "bullish",
        "qqq_trend": "bullish",
        "vix_state": "normal",
        "market_breadth": "moderately_positive",
        "sector_rotation": "growth_led",
        "score": 76,
        "data_source": "sample"
    }
