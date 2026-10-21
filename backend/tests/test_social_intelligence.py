from app.services import social_intelligence as social


def test_equity_social_signal_is_not_applied():
    result = social.social_intelligence_snapshot("AAPL")
    assert result["applicable"] is False
    assert result["status"] == "not_applicable"
    assert result["score"] == 50


def test_weighted_consensus_requires_sample_and_win_rate(monkeypatch):
    monkeypatch.setattr(social.settings, "social_min_closed_trades", 20)
    monkeypatch.setattr(social.settings, "social_min_win_rate", 0.55)
    rows = [
        {"trader": "strong-long", "direction": "LONG", "win_rate": .72, "closed_trades": 80},
        {"trader": "good-long", "direction": "LONG", "win_rate": .64, "closed_trades": 45},
        {"trader": "weak-short", "direction": "SHORT", "win_rate": .51, "closed_trades": 100},
    ]
    result = social._aggregate("BTC", rows, ["invo"])
    assert result["qualified_traders"] == 2
    assert result["consensus"] == "BULLISH"
    assert result["score"] > 50


def test_social_adjustment_is_bounded(monkeypatch):
    monkeypatch.setattr(social.settings, "social_max_score_adjustment", 8)
    snapshot = {
        "applicable": True, "status": "verified", "qualified_traders": 5,
        "confidence": 100, "consensus": "BULLISH",
    }
    adjustment, _ = social.social_alignment_adjustment(snapshot, "CALL")
    assert adjustment == 8
    opposed, _ = social.social_alignment_adjustment(snapshot, "PUT")
    assert opposed == -8
