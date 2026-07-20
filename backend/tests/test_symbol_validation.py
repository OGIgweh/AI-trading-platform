from app.services import market_data


def test_symbol_normalization_preserves_exchange_suffixes():
    assert market_data.normalize_symbol("$aapl") == "AAPL"
    assert market_data.normalize_symbol("BRK.B") == "BRK-B"
    assert market_data.normalize_symbol("BRK/B") == "BRK-B"
    assert market_data.normalize_symbol("7203.T") == "7203.T"
    assert market_data.normalize_symbol("SHOP.TO") == "SHOP.TO"


def test_direct_ticker_is_offered_when_autocomplete_provider_is_down(monkeypatch):
    monkeypatch.setattr(
        market_data,
        "_yf_search_cached",
        lambda query, limit, bucket: ([], "provider_unavailable"),
    )
    results, status = market_data.search_instruments_with_status("PLTR", 8)
    assert status == "provider_unavailable"
    assert results[0].symbol == "PLTR"
    assert results[0].data_source == "direct_ticker_entry"


def test_invalid_format_is_distinct_from_not_found():
    result = market_data.get_quote_lookup("BAD TICKER !!")
    assert result.status == "invalid_format"
    assert result.quote.data_source == "invalid_symbol"


def test_company_name_search_does_not_insert_fake_exact_ticker(monkeypatch):
    from app.models.schemas import InstrumentSearchResult

    monkeypatch.setattr(
        market_data,
        "_yf_search_cached",
        lambda query, limit, bucket: ([
            InstrumentSearchResult(
                symbol="TSLA",
                name="Tesla, Inc.",
                exchange="NASDAQ",
                quote_type="EQUITY",
            )
        ], "ok"),
    )
    results, status = market_data.search_instruments_with_status("Tesla", 8)
    assert status == "ok"
    assert [item.symbol for item in results] == ["TSLA"]
