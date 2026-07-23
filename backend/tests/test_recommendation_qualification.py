from app.models.schemas import AnalyzeRequest, OptionContract, Quote
from app.services import ai_engine


def _quote():
    return Quote(
        symbol="QQQ",
        price=700.0,
        change=5.0,
        change_percent=0.72,
        volume=20_000_000,
        market_status="OPEN",
        data_source="yfinance_delayed",
    )


def _technical(direction="bullish"):
    bullish = direction == "bullish"
    return {
        "symbol": "QQQ",
        "data_source": "yfinance_delayed",
        "history_bars": 252,
        "history_period": "1y",
        "trend": direction,
        "rsi": 58 if bullish else 39,
        "macd": {"state": direction, "macd": 2.0, "signal": 1.0, "histogram": 1.0},
        "vwap_relation": "above" if bullish else "below",
        "vwap": 695,
        "volume_ratio": 1.3,
        "bollinger_position": 0.60 if bullish else 0.35,
        "atr": 8.5,
    }


def _market(direction="CALL"):
    return {
        "data_source": "yfinance_delayed",
        "market_breadth": "positive" if direction == "CALL" else "weak",
        "score": 80 if direction == "CALL" else 30,
        "spy_trend": "bullish" if direction == "CALL" else "bearish",
        "qqq_trend": "bullish" if direction == "CALL" else "bearish",
    }


def _contract(symbol, strike, bid, ask, delta, volume=1000, oi=5000):
    return OptionContract(
        symbol=symbol,
        contract_type="CALL",
        strike=strike,
        bid=bid,
        ask=ask,
        volume=volume,
        open_interest=oi,
        implied_volatility=0.30,
        delta=delta,
        gamma=0.0,
        theta=0.0,
        vega=0.0,
        spread_percent=1.0,
        expiration="2026-08-21",
        days_to_expiration=29,
    )


def test_expensive_single_uses_defined_risk_spread(monkeypatch):
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: _technical("bullish"))
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: _market("CALL"))
    monkeypatch.setattr(
        ai_engine,
        "get_option_chain",
        lambda symbol: [
            _contract("QQQ260821C00700000", 700, 10.0, 10.2, 0.45),
            _contract("QQQ260821C00701000", 701, 9.4, 9.6, 0.40),
            _contract("QQQ260821C00705000", 705, 7.0, 7.2, 0.30),
        ],
    )

    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="QQQ", account_value=10_000, max_risk_percent=1, min_confidence=75, strategy="auto"))

    assert result.recommendation == "CALL"
    assert result.suggested_order is not None
    assert result.suggested_order.leg_count == 2
    assert result.suggested_order.strategy == "Bull Call Debit Spread"
    assert result.suggested_order.estimated_max_loss <= 100
    assert result.confidence >= 75


def test_affordable_single_option_can_qualify(monkeypatch):
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: _technical("bullish"))
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: _market("CALL"))
    monkeypatch.setattr(
        ai_engine,
        "get_option_chain",
        lambda symbol: [_contract("QQQ260821C00720000", 720, 2.9, 3.1, 0.35)],
    )

    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="QQQ", account_value=10_000, max_risk_percent=1, min_confidence=75, strategy="auto"))

    assert result.recommendation == "CALL"
    assert result.suggested_order is not None
    assert result.suggested_order.leg_count == 1
    assert result.position_size >= 1
    assert result.confidence >= 75


def test_mixed_technical_setup_remains_no_trade(monkeypatch):
    mixed = _technical("bullish")
    mixed.update({
        "trend": "mixed",
        "rsi": 52,
        "macd": {"state": "mixed", "macd": 0.1, "signal": 0.1, "histogram": 0.0},
        "vwap_relation": "below",
        "volume_ratio": 0.8,
    })
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: mixed)
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: _market("CALL"))
    monkeypatch.setattr(ai_engine, "get_option_chain", lambda symbol: [])

    result = ai_engine.analyze_trade(AnalyzeRequest(symbol="QQQ", strategy="auto"))

    assert result.recommendation == "NO_TRADE"
    assert "mixed" in result.explanation.lower() or "balanced" in result.explanation.lower()
