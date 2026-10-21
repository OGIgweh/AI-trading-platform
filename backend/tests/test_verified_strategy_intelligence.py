from app.services import verified_strategy_intelligence as vsi


def _strategy(**overrides):
    row = {
        "strategy_name": "Test Strategy",
        "provider": "Test Provider",
        "alpha_score": 82,
        "sharpe_ratio": 1.4,
        "max_drawdown_percent": 12,
        "performance_days": 240,
        "ownership_validated": True,
        "audit_status": "active",
        "positions": [{"symbol": "AAPL", "direction": "LONG", "weight": 1.0}],
    }
    row.update(overrides)
    normalized = vsi._normalize_strategy(row)
    quality, qualified, blockers = vsi._quality_score(normalized)
    normalized.update({"quality_score": quality, "qualified": qualified, "qualification_blockers": blockers})
    return normalized


def test_not_configured_does_not_adjust(monkeypatch):
    monkeypatch.setattr(vsi.settings, "alphaledger_api_url", "")
    result = vsi.verified_strategy_intelligence_snapshot("AAPL")
    assert result["status"] == "not_configured"
    adjustment, _ = vsi.verified_strategy_alignment_adjustment(result, "CALL")
    assert adjustment == 0


def test_quality_requires_verified_track_record(monkeypatch):
    monkeypatch.setattr(vsi.settings, "alphaledger_min_alpha_score", 60.0)
    monkeypatch.setattr(vsi.settings, "alphaledger_min_sharpe", 0.5)
    monkeypatch.setattr(vsi.settings, "alphaledger_max_drawdown_percent", 40.0)
    monkeypatch.setattr(vsi.settings, "alphaledger_min_track_record_days", 60)
    row = _strategy(ownership_validated=False)
    assert row["qualified"] is False
    assert any("Ownership" in blocker for blocker in row["qualification_blockers"])


def test_only_matching_exposure_drives_direction(monkeypatch):
    monkeypatch.setattr(vsi.settings, "alphaledger_min_relevant_strategies", 2)
    rows = [
        _strategy(strategy_name="A", positions=[{"symbol": "AAPL", "direction": "LONG", "weight": 1.0}]),
        _strategy(strategy_name="B", positions=[{"symbol": "AAPL", "direction": "LONG", "weight": 0.8}]),
        _strategy(strategy_name="C", positions=[{"symbol": "MSFT", "direction": "SHORT", "weight": 1.0}]),
    ]
    result = vsi._aggregate("AAPL", rows)
    assert result["status"] == "verified"
    assert result["consensus"] == "BULLISH"
    assert result["matched_strategies"] == 2


def test_metrics_only_never_adjusts_confidence(monkeypatch):
    monkeypatch.setattr(vsi.settings, "alphaledger_min_relevant_strategies", 2)
    rows = [_strategy(positions=[]), _strategy(strategy_name="B", positions=[])]
    result = vsi._aggregate("AAPL", rows)
    assert result["status"] == "metrics_only"
    adjustment, _ = vsi.verified_strategy_alignment_adjustment(result, "CALL")
    assert adjustment == 0


def test_verified_adjustment_is_bounded(monkeypatch):
    monkeypatch.setattr(vsi.settings, "alphaledger_max_score_adjustment", 6)
    monkeypatch.setattr(vsi.settings, "alphaledger_min_relevant_strategies", 2)
    snapshot = {
        "applicable": True,
        "status": "verified",
        "matched_strategies": 3,
        "confidence": 100,
        "consensus": "BULLISH",
    }
    aligned, _ = vsi.verified_strategy_alignment_adjustment(snapshot, "CALL")
    opposed, _ = vsi.verified_strategy_alignment_adjustment(snapshot, "PUT")
    assert aligned == 6
    assert opposed == -6
