from app.services import market_data


def test_short_chart_ranges_reuse_one_year_history(monkeypatch):
    calls = []

    class Frame:
        empty = False

    monkeypatch.setattr(
        market_data,
        "get_price_history",
        lambda symbol, period, interval: (calls.append((symbol, period, interval)) or (Frame(), symbol, "ok")),
    )

    # Stop after the retrieval decision; this test targets provider-period use.
    class Stop(Exception):
        pass

    monkeypatch.setattr(Frame, "dropna", lambda self, **kwargs: (_ for _ in ()).throw(Stop()), raising=False)
    try:
        market_data.get_chart_history("AAPL", "1mo")
    except Stop:
        pass

    assert calls[0] == ("AAPL", "1y", "1d")
