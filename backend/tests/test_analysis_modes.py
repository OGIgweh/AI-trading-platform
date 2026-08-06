from app.models.schemas import AnalyzeRequest, Quote
from app.services import ai_engine


def _quote():
    return Quote(
        symbol="AAPL",
        price=200.0,
        change=1.0,
        change_percent=0.5,
        volume=10_000_000,
        market_status="OPEN",
        data_source="yfinance_delayed",
    )


def _technical():
    return {
        "symbol": "AAPL",
        "data_source": "yfinance_delayed",
        "history_bars": 252,
        "history_period": "1y",
        "trend": "bullish",
        "rsi": 58,
        "macd": {"state": "bullish", "macd": 2.0, "signal": 1.0, "histogram": 1.0},
        "vwap_relation": "above",
        "vwap": 198,
        "volume_ratio": 1.3,
        "bollinger_position": 0.60,
        "atr": 4.0,
    }


def _market():
    return {
        "data_source": "yfinance_delayed",
        "market_breadth": "positive",
        "score": 80,
        "spy_trend": "bullish",
        "qqq_trend": "bullish",
    }


def _patch_common(monkeypatch):
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: _technical())
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: _market())


def test_options_mode_never_substitutes_stock(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(ai_engine, "get_option_chain", lambda symbol: [])

    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="AAPL", asset_mode="options", min_confidence=65))

    assert result.recommendation == "NO_TRADE"
    assert result.suggested_equity_order is None
    assert result.raw_data["selected_strategy"] == "options_only_unavailable"
    assert "did not replace" in result.explanation.lower()


def test_stock_mode_does_not_request_option_chain(monkeypatch):
    _patch_common(monkeypatch)

    def should_not_run(symbol):
        raise AssertionError("Stock mode must not request options")

    monkeypatch.setattr(ai_engine, "get_option_chain", should_not_run)
    result = ai_engine.analyze_trade(AnalyzeRequest(
        symbol="AAPL",
        asset_mode="stock",
        account_value=10_000,
        max_risk_percent=2,
        min_confidence=65,
    ))

    assert result.recommendation == "BUY"
    assert result.suggested_equity_order is not None
    assert result.suggested_order is None
    assert result.raw_data["selected_strategy"] == "stock_only"


def test_auto_mode_can_fallback_to_stock(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(ai_engine, "get_option_chain", lambda symbol: [])

    result = ai_engine.analyze_trade(AnalyzeRequest(
        symbol="AAPL",
        asset_mode="auto",
        account_value=10_000,
        max_risk_percent=2,
        min_confidence=65,
    ))

    assert result.recommendation == "BUY"
    assert result.suggested_equity_order is not None
    assert result.raw_data["selected_strategy"] == "auto_equity_fallback"
