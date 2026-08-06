from app.services import provider_adapters


def _payload():
    return {
        "chart": {
            "result": [{
                "meta": {"currency": "USD", "exchangeTimezoneName": "America/New_York"},
                "timestamp": [1785715200, 1785801600],
                "indicators": {
                    "quote": [{
                        "open": [200.0, 202.0],
                        "high": [204.0, 206.0],
                        "low": [199.0, 201.0],
                        "close": [203.0, 205.0],
                        "volume": [1000000, 1200000],
                    }],
                    "adjclose": [{"adjclose": [203.0, 205.0]}],
                },
            }],
            "error": None,
        }
    }


def test_yahoo_chart_payload_is_normalized():
    frame = provider_adapters._yahoo_chart_payload_to_frame(_payload())
    assert frame is not None
    assert len(frame) == 2
    assert float(frame.iloc[-1]["Close"]) == 205.0
    assert frame.attrs["data_source"] == "yahoo_chart_delayed"


def test_yahoo_chart_error_returns_none():
    frame = provider_adapters._yahoo_chart_payload_to_frame({"chart": {"result": None, "error": {"code": "Not Found"}}})
    assert frame is None
