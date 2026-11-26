from datetime import datetime

import numpy as np
import pandas as pd

from app.models.schemas import AnalyzeRequest, Quote
from app.services import ai_engine, market_data


def _history(source: str = "stooq_eod", rows: int = 252):
    index = pd.date_range(end="2026-08-03", periods=rows, freq="B")
    close = np.linspace(100, 160, rows) + np.sin(np.linspace(0, 10, rows))
    frame = pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_500_000, rows),
        },
        index=index,
    )
    frame.attrs["data_source"] = source
    return frame


def test_quote_falls_back_to_stooq_instead_of_zero(monkeypatch):
    market_data._lookup_quote_cached.cache_clear()
    monkeypatch.setattr(market_data, "tradier_enabled", lambda: False)
    monkeypatch.setattr(market_data, "fetch_yahoo_chart_history", lambda *args: None)
    monkeypatch.setattr(market_data, "fetch_stooq_history", lambda symbol, period: _history())
    monkeypatch.setattr(
        market_data,
        "_lookup_yfinance_quote_cached",
        lambda symbol, bucket: market_data.QuoteLookup(
            Quote(
                symbol=symbol,
                price=0,
                change=0,
                change_percent=0,
                volume=0,
                market_status="OPEN",
                data_source="provider_unavailable",
            ),
            "provider_unavailable",
            symbol,
            symbol,
            "Yahoo unavailable",
        ),
    )

    result = market_data.get_quote_lookup("AAPL")

    assert result.status == "ok"
    assert result.quote.price > 0
    assert result.quote.data_source == "stooq_eod"
    assert result.quote.as_of is not None


def test_equity_recommendation_when_options_provider_is_unavailable(monkeypatch):
    quote = Quote(
        symbol="AAPL",
        price=160,
        change=2,
        change_percent=1.27,
        volume=1_500_000,
        market_status="OPEN",
        data_source="stooq_eod",
        as_of=ai_engine.latest_completed_session(ai_engine.now_et()).isoformat(),
        previous_close=158,
        day_low=157,
        day_high=161,
    )
    technical = {
        "symbol": "AAPL",
        "data_source": "stooq_eod",
        "history_bars": 252,
        "history_period": "1y",
        "trend": "bullish",
        "rsi": 58,
        "macd": {"state": "bullish", "macd": 2.0, "signal": 1.0, "histogram": 1.0},
        "vwap_relation": "above",
        "vwap": 155,
        "volume_ratio": 1.3,
        "bollinger_position": 0.60,
        "atr": 3.0,
    }
    market = {
        "data_source": "stooq_eod",
        "market_breadth": "positive",
        "score": 80,
        "spy_trend": "bullish",
        "qqq_trend": "bullish",
    }
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: quote)
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: technical)
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: market)
    monkeypatch.setattr(ai_engine, "get_option_chain", lambda symbol: [])

    result = ai_engine.analyze_trade(
        AnalyzeRequest(
            symbol="AAPL",
            account_value=10_000,
            asset_mode="auto",
            max_risk_percent=1,
            min_confidence=75,
            strategy="auto",
        )
    )

    assert result.recommendation == "BUY"
    assert result.suggested_equity_order is not None
    assert result.suggested_order is None
    assert result.position_size >= 1
    assert result.confidence >= 75


def test_stooq_csv_is_parsed_as_verified_daily_history(monkeypatch):
    from app.services import provider_adapters

    csv = """Date,Open,High,Low,Close,Volume\n2026-07-31,150,153,149,152,1000000\n2026-08-03,152,161,151,160,1500000\n"""

    class Response:
        status_code = 200
        text = csv

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(provider_adapters.httpx, "Client", Client)
    frame = provider_adapters.fetch_stooq_history("AAPL", "1y")

    assert frame is not None
    assert len(frame) == 2
    assert float(frame.iloc[-1]["Close"]) == 160
    assert frame.attrs["data_source"] == "stooq_eod"


def test_quote_uses_direct_yahoo_chart_before_library_and_zero(monkeypatch):
    market_data._lookup_quote_cached.cache_clear()
    monkeypatch.setattr(market_data, "tradier_enabled", lambda: False)
    direct = _history("yahoo_chart_delayed")
    monkeypatch.setattr(market_data, "fetch_yahoo_chart_history", lambda symbol, period, interval="1d": direct)
    monkeypatch.setattr(market_data, "fetch_stooq_history", lambda symbol, period: None)
    monkeypatch.setattr(
        market_data,
        "_lookup_yfinance_quote_cached",
        lambda symbol, bucket: market_data.QuoteLookup(
            Quote(symbol=symbol, price=0, change=0, change_percent=0, volume=0, market_status="OPEN", data_source="provider_unavailable"),
            "provider_unavailable", symbol, symbol, "library unavailable"
        ),
    )
    result = market_data.get_quote_lookup("AAPL")
    assert result.status == "ok"
    assert result.quote.price > 0
    assert result.quote.data_source == "yahoo_chart_delayed"
