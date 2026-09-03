from app.models.schemas import AnalyzeRequest, OptionContract, Quote
from app.services import ai_engine


def _quote():
    return Quote(symbol="QQQ", price=700.0, change=5.0, change_percent=0.72, volume=20_000_000, market_status="OPEN", data_source="yfinance_delayed")


def _technical():
    return {
        "symbol": "QQQ", "data_source": "yfinance_delayed", "history_bars": 252, "history_period": "1y",
        "trend": "bullish", "rsi": 58,
        "macd": {"state": "bullish", "macd": 2.0, "signal": 1.0, "histogram": 1.0},
        "vwap_relation": "above", "vwap": 695, "volume_ratio": 1.3, "bollinger_position": 0.60, "atr": 8.5,
    }


def _market():
    return {"data_source": "yfinance_delayed", "market_breadth": "positive", "score": 80, "spy_trend": "bullish", "qqq_trend": "bullish"}


def _call(symbol, strike, bid, ask, delta):
    return OptionContract(
        symbol=symbol, contract_type="CALL", strike=strike, bid=bid, ask=ask, volume=1500, open_interest=6000,
        implied_volatility=0.30, delta=delta, gamma=0.0, theta=0.0, vega=0.0, spread_percent=1.0,
        expiration="2026-09-18", days_to_expiration=35, data_source="yfinance_delayed_options",
    )


def _patch(monkeypatch, chain):
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: _technical())
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: _market())
    monkeypatch.setattr(ai_engine, "get_option_chain", lambda symbol: chain)


def test_single_leg_is_strict_even_when_vertical_could_fit(monkeypatch):
    chain = [
        _call("QQQ260918C00700000", 700, 10.0, 10.2, 0.45),
        _call("QQQ260918C00705000", 705, 7.0, 7.2, 0.30),
    ]
    _patch(monkeypatch, chain)
    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="QQQ", asset_mode="options", option_structure="single", account_value=10_000, max_risk_percent=1, min_confidence=70))
    assert result.recommendation == "NO_TRADE"
    assert result.suggested_order is None
    assert result.raw_data["selected_strategy"] == "single"
    assert result.raw_data["analysis_settings"]["option_structure"] == "single"


def test_multi_leg_forces_vertical_even_when_single_is_affordable(monkeypatch):
    chain = [
        _call("QQQ260918C00720000", 720, 2.9, 3.1, 0.35),
        _call("QQQ260918C00725000", 725, 2.2, 2.4, 0.30),
    ]
    _patch(monkeypatch, chain)
    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="QQQ", asset_mode="options", option_structure="multi", account_value=10_000, max_risk_percent=1, min_confidence=70))
    assert result.recommendation == "CALL"
    assert result.suggested_order is not None
    assert result.suggested_order.strategy == "Vertical Call"
    assert result.suggested_order.leg_count == 2
    assert len(result.suggested_order.legs) == 2
    assert result.raw_data["option_structure"] == "multi"


def test_best_fit_keeps_affordable_single(monkeypatch):
    chain = [_call("QQQ260918C00720000", 720, 2.9, 3.1, 0.35)]
    _patch(monkeypatch, chain)
    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="QQQ", asset_mode="options", option_structure="auto", account_value=10_000, max_risk_percent=1, min_confidence=70))
    assert result.recommendation == "CALL"
    assert result.suggested_order is not None
    assert result.suggested_order.strategy == "Call"
    assert result.suggested_order.leg_count == 1
