from datetime import datetime

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.services import ai_engine, indicators
from app.services.market_clock import NY_TZ, latest_completed_session
from test_recommendation_qualification import _contract, _market, _quote, _technical


def test_stale_quote_blocks_ticket_through_api(monkeypatch):
    now = datetime(2026, 11, 27, 12, tzinfo=NY_TZ)
    monkeypatch.setattr(ai_engine, "now_et", lambda: now)
    quote = _quote().model_copy(update={"as_of": "2026-11-24T16:00:00-05:00"})
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: quote)

    response = TestClient(app).post("/api/ai/analyze", json={"symbol": "QQQ"})

    assert response.status_code == 200
    result = response.json()
    assert result["recommendation"] == "NO_TRADE"
    assert "predates" in result["explanation"]
    assert result["suggested_order"] is None


def test_last_completed_session_handles_holiday_and_early_close():
    assert latest_completed_session(datetime(2026, 11, 27, 12, tzinfo=NY_TZ)).day == 25
    assert latest_completed_session(datetime(2026, 11, 27, 13, tzinfo=NY_TZ)).day == 27


def test_forced_put_cannot_use_bullish_technical_score(monkeypatch):
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: _technical())
    monkeypatch.setattr(ai_engine, "market_context_snapshot", lambda: _market("PUT"))

    result = ai_engine.analyze_trade(ai_engine.AnalyzeRequest(
        symbol="QQQ", asset_mode="stock", strategy="put", min_confidence=1
    ))

    assert result.recommendation == "NO_TRADE"
    assert result.suggested_equity_order is None
    assert any("does not confirm" in issue for issue in result.raw_data["blocking_failures"])


def test_expired_option_is_excluded_even_if_cached_dte_is_positive(monkeypatch):
    monkeypatch.setattr(ai_engine, "get_quote", lambda symbol: _quote())
    monkeypatch.setattr(ai_engine, "technical_snapshot", lambda symbol: _technical())
    monkeypatch.setattr(ai_engine, "market_context_snapshot", _market)
    expired = _contract("expired", 700, 1.00, 1.02, 0.45).model_copy(
        update={"expiration": "2025-01-17"}
    )
    monkeypatch.setattr(ai_engine, "get_option_chain", lambda symbol: [expired])

    result = ai_engine.analyze_trade(ai_engine.AnalyzeRequest(symbol="QQQ"))

    assert result.recommendation == "NO_TRADE"
    assert result.raw_data["options_contract_count"] == 0


def test_flat_prices_have_neutral_rsi():
    assert indicators._rsi(pd.Series([25.0] * 30)) == 50
