from datetime import timedelta

from app.models.schemas import AnalyzeRequest, OptionContract, Quote
from app.services import ai_engine


def _quote():
    return Quote(symbol="AAPL", price=327.14, change=2.18, change_percent=0.67, volume=22_000_000, market_status="OPEN", data_source="yahoo_chart_delayed", as_of=ai_engine.now_et().isoformat())


def _technical():
    return {
        "symbol":"AAPL","data_source":"yahoo_chart_delayed","history_bars":253,"history_period":"1y",
        "trend":"bullish","rsi":58,"macd":{"state":"bullish","macd":2.0,"signal":1.0,"histogram":1.0},
        "vwap_relation":"above","vwap":324,"volume_ratio":1.4,"bollinger_position":0.60,"atr":5.0,
    }


def _market():
    return {"data_source":"yahoo_chart_delayed","market_breadth":"positive","score":82,"spy_trend":"bullish","qqq_trend":"bullish"}


def test_far_otm_short_dte_call_is_blocked(monkeypatch):
    contract = OptionContract(
        symbol="AAPL260918C00345000", contract_type="CALL", strike=345, bid=1.40, ask=1.49,
        volume=1000, open_interest=5000, implied_volatility=0.24, delta=0.26, gamma=0, theta=0, vega=0,
        spread_percent=6.2, expiration=(ai_engine.now_et().date() + timedelta(days=15)).isoformat(), days_to_expiration=15, data_source="yfinance_delayed_options",
    )
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: _technical())
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: _market())
    monkeypatch.setattr(ai_engine, "get_option_chain", lambda symbol: [contract])
    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="AAPL", asset_mode="options", option_structure="single", account_value=10_000, max_risk_percent=2, min_confidence=70))
    assert result.recommendation == "NO_TRADE"
    failures = " ".join(result.raw_data.get("blocking_failures", []))
    assert "out of the money" in failures.lower() or "delta" in failures.lower() or "expected move" in failures.lower()


def test_qualified_order_exposes_probability_metrics(monkeypatch):
    contract = OptionContract(
        symbol="AAPL261016C00330000", contract_type="CALL", strike=330, bid=8.0, ask=8.2,
        volume=2000, open_interest=9000, implied_volatility=0.28, delta=0.48, gamma=0, theta=-0.12, vega=0,
        spread_percent=2.5, expiration=(ai_engine.now_et().date() + timedelta(days=43)).isoformat(), days_to_expiration=43, data_source="yfinance_delayed_options",
    )
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: _technical())
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: _market())
    monkeypatch.setattr(ai_engine, "get_option_chain", lambda symbol: [contract])
    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="AAPL", asset_mode="options", option_structure="single", account_value=50_000, max_risk_percent=2, min_confidence=70))
    assert result.suggested_order is not None
    order = result.suggested_order
    assert order.required_move_percent is not None
    assert order.expected_move_percent is not None
    assert order.directional_delta == 0.48
    assert order.theta_per_day == -0.12
    assert "not" in order.delta_interpretation.lower()
    assert result.raw_data["confidence_interpretation"].lower().startswith("evidence-alignment")
