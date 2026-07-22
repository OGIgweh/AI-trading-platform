from app.services import market_data


def test_invalid_nine_month_period_falls_back_to_supported_one_year_period():
    assert market_data.normalize_history_period("9mo") == "1y"


def test_supported_period_is_preserved():
    assert market_data.normalize_history_period("6mo") == "6mo"
    assert market_data.normalize_history_period("1y") == "1y"
