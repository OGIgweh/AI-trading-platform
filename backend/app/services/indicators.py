def technical_snapshot(symbol: str):
    # Demo snapshots. Replace with provider-backed OHLCV calculations before live use.
    snapshots = {
        "AAPL": {"trend": "bullish", "ema_alignment": True, "rsi": 58, "macd": "bullish", "vwap_relation": "above", "atr": 3.1, "support": 211.0, "resistance": 221.0, "score": 82},
        "MSFT": {"trend": "mixed", "ema_alignment": False, "rsi": 47, "macd": "bearish", "vwap_relation": "below", "atr": 6.4, "support": 490.0, "resistance": 506.0, "score": 48},
        "NVDA": {"trend": "bullish", "ema_alignment": True, "rsi": 64, "macd": "bullish", "vwap_relation": "above", "atr": 7.9, "support": 158.0, "resistance": 172.0, "score": 86},
        "SPY": {"trend": "bullish", "ema_alignment": True, "rsi": 61, "macd": "bullish", "vwap_relation": "above", "atr": 5.2, "support": 618.0, "resistance": 631.0, "score": 76},
        "QQQ": {"trend": "bullish", "ema_alignment": True, "rsi": 60, "macd": "bullish", "vwap_relation": "above", "atr": 5.7, "support": 549.0, "resistance": 563.0, "score": 78},
    }
    return snapshots.get(symbol.upper(), {"score": 0, "trend": "unknown", "ema_alignment": False, "rsi": None, "macd": "unknown", "vwap_relation": "unknown"})


def market_context_snapshot():
    return {
        "spy_trend": "bullish",
        "qqq_trend": "bullish",
        "vix_state": "normal",
        "market_breadth": "moderately_positive",
        "sector_rotation": "growth_led",
        "score": 76,
        "data_source": "sample"
    }
