from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

from app.core.config import settings
from app.models.schemas import InstrumentSearchResult, OptionContract, Quote
from app.services.market_clock import market_status
from app.services.risk import bid_ask_spread_pct

SAMPLE_QUOTES = {
    "AAPL": {"price": 214.35, "change": 1.26, "change_percent": 0.59, "volume": 58_234_000},
    "MSFT": {"price": 498.12, "change": -2.15, "change_percent": -0.43, "volume": 25_420_000},
    "NVDA": {"price": 164.85, "change": 3.41, "change_percent": 2.11, "volume": 189_543_000},
    "SPY": {"price": 624.91, "change": 0.84, "change_percent": 0.13, "volume": 74_523_000},
    "QQQ": {"price": 556.40, "change": 1.10, "change_percent": 0.20, "volume": 39_120_000},
}

_ALLOWED_SEARCH_TYPES = {"EQUITY", "ETF"}
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.^=\-]{0,23}$")
_VALID_HISTORY_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}


def normalize_history_period(period: str) -> str:
    """Return a yfinance-supported history period.

    The provider does not support arbitrary values such as ``9mo``. Invalid
    values are deliberately mapped to one year so the indicator engine has
    enough daily bars for EMA, RSI, MACD, ATR, and Bollinger calculations.
    """

    clean = str(period or "").strip().lower()
    return clean if clean in _VALID_HISTORY_PERIODS else "1y"


_TRANSIENT_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "temporarily unavailable",
    "too many requests",
    "rate limit",
    "429",
    "502",
    "503",
    "504",
    "curl",
    "could not resolve",
    "connection reset",
    "unauthorized",
    "invalid crumb",
)


@dataclass(frozen=True)
class QuoteLookup:
    quote: Quote
    status: Literal["ok", "invalid_format", "not_found", "provider_unavailable"]
    requested_symbol: str
    canonical_symbol: str
    message: str


def normalize_symbol(symbol: str) -> str:
    """Normalize common broker/user ticker formats without breaking exchange suffixes.

    Examples:
    - ``$aapl`` -> ``AAPL``
    - ``BRK.B`` or ``BRK/B`` -> ``BRK-B``
    - ``7203.T`` remains ``7203.T``
    """

    clean = str(symbol or "").strip().upper().replace(" ", "")
    if clean.startswith("$"):
        clean = clean[1:]
    clean = clean.replace("/", "-")

    # Yahoo represents US share classes with a hyphen (BRK-B, BF-B), while
    # many brokers/users enter a dot. Preserve longer international suffixes.
    if clean.count(".") == 1:
        root, suffix = clean.rsplit(".", 1)
        if root.isalpha() and suffix in {"A", "B", "C"}:
            clean = f"{root}-{suffix}"
    return clean


def symbol_candidates(symbol: str) -> list[str]:
    clean = normalize_symbol(symbol)
    candidates = [clean] if clean else []

    # Try the alternate US share-class notation as a provider fallback.
    if "-" in clean:
        root, suffix = clean.rsplit("-", 1)
        if root.isalpha() and suffix in {"A", "B", "C"}:
            candidates.append(f"{root}.{suffix}")
    elif "." in clean:
        root, suffix = clean.rsplit(".", 1)
        if root.isalpha() and suffix in {"A", "B", "C"}:
            candidates.append(f"{root}-{suffix}")

    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def is_valid_symbol_format(symbol: str) -> bool:
    return bool(_SYMBOL_PATTERN.fullmatch(normalize_symbol(symbol)))


def _provider_enabled() -> bool:
    return settings.market_data_provider.lower() in {"auto", "yfinance"}


def _market_status() -> str:
    return market_status()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value != value:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value != value:
            return default
        return int(value)
    except Exception:
        return default


def _is_transient_error(exc: BaseException | str) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_ERROR_MARKERS)


def _configure_yfinance(yf: Any) -> None:
    """Apply resilient network defaults supported by current yfinance."""

    try:
        yf.config.network.retries = max(2, int(getattr(settings, "market_data_retries", 2)))
    except Exception:
        pass
    try:
        yf.config.debug.hide_exceptions = False
    except Exception:
        pass


def _extract_history_frame(raw: Any, symbol: str):
    """Flatten a yfinance download frame when a single ticker uses MultiIndex columns."""

    if raw is None or getattr(raw, "empty", True):
        return raw
    try:
        import pandas as pd

        if isinstance(raw.columns, pd.MultiIndex):
            level_values = [str(value).upper() for value in raw.columns.get_level_values(-1)]
            if symbol.upper() in level_values:
                raw = raw.xs(symbol.upper(), axis=1, level=-1)
            elif len(set(level_values)) == 1:
                raw.columns = raw.columns.get_level_values(0)
    except Exception:
        pass
    return raw


def _history_to_quote(symbol: str, hist: Any) -> Quote | None:
    if hist is None or getattr(hist, "empty", True):
        return None
    try:
        hist = hist.dropna(subset=["Close"])
        if hist.empty:
            return None
        last = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else last
        price = _safe_float(last.get("Close"))
        prev_close = _safe_float(prev.get("Close"), price)
        if price <= 0:
            return None
        change = price - prev_close
        change_percent = (change / prev_close * 100) if prev_close else 0
        as_of_value = hist.index[-1]
        as_of = as_of_value.isoformat() if hasattr(as_of_value, "isoformat") else str(as_of_value)
        return Quote(
            symbol=symbol,
            price=round(price, 2),
            change=round(change, 2),
            change_percent=round(change_percent, 2),
            volume=_safe_int(last.get("Volume"), 0),
            market_status=_market_status(),
            data_source="yfinance_delayed",
            as_of=as_of,
            previous_close=round(prev_close, 2),
            day_low=round(_safe_float(last.get("Low"), price), 2),
            day_high=round(_safe_float(last.get("High"), price), 2),
        )
    except Exception:
        return None

def _fast_info_to_quote(symbol: str, ticker: Any) -> Quote | None:
    try:
        info = ticker.fast_info
        getter = info.get if hasattr(info, "get") else lambda key, default=None: info[key]
        price = _safe_float(getter("last_price"))
        if price <= 0:
            return None
        previous = _safe_float(getter("previous_close"), price)
        volume = _safe_int(getter("last_volume"), 0)
        change = price - previous
        return Quote(
            symbol=symbol,
            price=round(price, 2),
            change=round(change, 2),
            change_percent=round((change / previous * 100) if previous else 0, 2),
            volume=volume,
            market_status=_market_status(),
            data_source="yfinance_delayed",
            as_of=datetime.now().astimezone().isoformat(),
            previous_close=round(previous, 2),
            day_low=round(_safe_float(getter("day_low"), price), 2),
            day_high=round(_safe_float(getter("day_high"), price), 2),
            fifty_two_week_low=round(_safe_float(getter("year_low"), 0), 2) or None,
            fifty_two_week_high=round(_safe_float(getter("year_high"), 0), 2) or None,
        )
    except Exception:
        return None

def _info_to_quote(symbol: str, ticker: Any) -> Quote | None:
    try:
        info = ticker.get_info() or {}
        price = _safe_float(info.get("regularMarketPrice") or info.get("currentPrice"))
        if price <= 0:
            return None
        previous = _safe_float(info.get("regularMarketPreviousClose") or info.get("previousClose"), price)
        volume = _safe_int(info.get("regularMarketVolume") or info.get("volume"), 0)
        change = price - previous
        timestamp = info.get("regularMarketTime")
        as_of = datetime.fromtimestamp(timestamp).astimezone().isoformat() if timestamp else datetime.now().astimezone().isoformat()
        return Quote(
            symbol=symbol,
            price=round(price, 2),
            change=round(change, 2),
            change_percent=round((change / previous * 100) if previous else 0, 2),
            volume=volume,
            market_status=_market_status(),
            data_source="yfinance_delayed",
            as_of=as_of,
            previous_close=round(previous, 2),
            day_low=round(_safe_float(info.get("regularMarketDayLow") or info.get("dayLow"), price), 2),
            day_high=round(_safe_float(info.get("regularMarketDayHigh") or info.get("dayHigh"), price), 2),
            fifty_two_week_low=round(_safe_float(info.get("fiftyTwoWeekLow"), 0), 2) or None,
            fifty_two_week_high=round(_safe_float(info.get("fiftyTwoWeekHigh"), 0), 2) or None,
        )
    except Exception:
        return None

def _exact_search_state(yf: Any, symbol: str) -> bool | None:
    """Return True if search confirms the exact ticker, False if not, None on provider failure."""

    try:
        search = yf.Search(
            symbol,
            max_results=12,
            news_count=0,
            lists_count=0,
            timeout=12,
            raise_errors=False,
        )
        quotes = list(search.quotes or [])
        exact = {normalize_symbol(str(item.get("symbol", ""))) for item in quotes}
        return normalize_symbol(symbol) in exact
    except Exception:
        return None


@lru_cache(maxsize=512)
def _lookup_quote_cached(requested_symbol: str, cache_bucket: int) -> QuoteLookup:
    del cache_bucket
    normalized = normalize_symbol(requested_symbol)
    unavailable = Quote(
        symbol=normalized or str(requested_symbol).upper().strip(),
        price=0.0,
        change=0.0,
        change_percent=0.0,
        volume=0,
        market_status=_market_status(),
        data_source="invalid_symbol" if not is_valid_symbol_format(normalized) else "provider_unavailable",
    )

    if not normalized or not is_valid_symbol_format(normalized):
        return QuoteLookup(
            quote=unavailable,
            status="invalid_format",
            requested_symbol=str(requested_symbol),
            canonical_symbol=normalized,
            message="Ticker format is invalid. Enter a symbol such as AAPL, BRK-B, or 7203.T.",
        )

    try:
        import yfinance as yf

        _configure_yfinance(yf)
    except Exception as exc:
        unavailable.data_source = "provider_unavailable"
        return QuoteLookup(
            quote=unavailable,
            status="provider_unavailable",
            requested_symbol=str(requested_symbol),
            canonical_symbol=normalized,
            message=f"The market-data library is unavailable: {exc}",
        )

    errors: list[str] = []
    any_transient = False

    for candidate in symbol_candidates(normalized):
        ticker = yf.Ticker(candidate)

        # Method 1: history() with explicit exceptions. This is the strongest
        # validity signal because it distinguishes missing prices from many
        # transient network failures.
        try:
            hist = ticker.history(
                period="5d",
                interval="1d",
                auto_adjust=False,
                repair=True,
                timeout=15,
                raise_errors=True,
            )
            quote = _history_to_quote(candidate, hist)
            if quote:
                return QuoteLookup(quote, "ok", str(requested_symbol), candidate, "Verified quote retrieved.")
        except Exception as exc:
            errors.append(str(exc))
            any_transient = any_transient or _is_transient_error(exc)

        # Method 2: fast_info uses a separate Yahoo quote path and can succeed
        # when historical chart data is temporarily empty.
        quote = _fast_info_to_quote(candidate, ticker)
        if quote:
            return QuoteLookup(quote, "ok", str(requested_symbol), candidate, "Verified quote retrieved.")

        # Method 3: the general quote-summary endpoint.
        quote = _info_to_quote(candidate, ticker)
        if quote:
            return QuoteLookup(quote, "ok", str(requested_symbol), candidate, "Verified quote retrieved.")

        # Method 4: download() provides another chart request path and handles
        # single-ticker responses differently from Ticker.history().
        try:
            downloaded = yf.download(
                candidate,
                period="5d",
                interval="1d",
                auto_adjust=False,
                repair=True,
                progress=False,
                threads=False,
                timeout=15,
                multi_level_index=False,
            )
            downloaded = _extract_history_frame(downloaded, candidate)
            quote = _history_to_quote(candidate, downloaded)
            if quote:
                return QuoteLookup(quote, "ok", str(requested_symbol), candidate, "Verified quote retrieved.")
        except Exception as exc:
            errors.append(str(exc))
            any_transient = any_transient or _is_transient_error(exc)

        exact_state = _exact_search_state(yf, candidate)
        if exact_state is True:
            unavailable.symbol = candidate
            unavailable.data_source = "provider_unavailable"
            return QuoteLookup(
                quote=unavailable,
                status="provider_unavailable",
                requested_symbol=str(requested_symbol),
                canonical_symbol=candidate,
                message="The ticker exists, but Yahoo Finance did not return a usable quote. Retry shortly.",
            )
        if exact_state is None:
            any_transient = True

    unavailable.symbol = normalized
    if any_transient:
        unavailable.data_source = "provider_unavailable"
        return QuoteLookup(
            quote=unavailable,
            status="provider_unavailable",
            requested_symbol=str(requested_symbol),
            canonical_symbol=normalized,
            message="The market-data provider could not verify the ticker because of a temporary network, rate-limit, or upstream-data error. The ticker was not rejected as nonexistent.",
        )

    unavailable.data_source = "not_found"
    detail = errors[-1] if errors else "No quote or exact search result was returned."
    return QuoteLookup(
        quote=unavailable,
        status="not_found",
        requested_symbol=str(requested_symbol),
        canonical_symbol=normalized,
        message=f"No supported stock or ETF could be verified for {normalized}. Provider detail: {detail}",
    )


def get_quote_lookup(symbol: str) -> QuoteLookup:
    normalized = normalize_symbol(symbol)
    bucket = int(datetime.now().timestamp() // max(15, settings.market_data_cache_seconds))
    return _lookup_quote_cached(normalized, bucket)


def get_quote(symbol: str) -> Quote:
    normalized = normalize_symbol(symbol)
    if settings.market_data_provider.lower() == "sample":
        return _sample_quote(normalized)
    if not _provider_enabled():
        return Quote(
            symbol=normalized,
            price=0.0,
            change=0.0,
            change_percent=0.0,
            volume=0,
            market_status=_market_status(),
            data_source="provider_unavailable",
        )
    return get_quote_lookup(normalized).quote


@lru_cache(maxsize=256)
def _yf_search_cached(query: str, limit: int, cache_bucket: int) -> tuple[list[InstrumentSearchResult], str]:
    del cache_bucket
    try:
        import yfinance as yf

        _configure_yfinance(yf)
        search = yf.Search(
            query,
            max_results=max(1, min(limit, 12)),
            news_count=0,
            lists_count=0,
            enable_fuzzy_query=True,
            timeout=12,
            raise_errors=False,
        )
        raw_quotes = list(search.quotes or [])
        results: list[InstrumentSearchResult] = []
        seen: set[str] = set()
        for item in raw_quotes:
            symbol = normalize_symbol(str(item.get("symbol", "")))
            quote_type = str(item.get("quoteType") or item.get("typeDisp") or "").upper()
            if not symbol or symbol in seen or quote_type not in _ALLOWED_SEARCH_TYPES:
                continue
            results.append(
                InstrumentSearchResult(
                    symbol=symbol,
                    name=str(item.get("longname") or item.get("shortname") or item.get("name") or symbol),
                    exchange=str(item.get("exchDisp") or item.get("exchange") or item.get("fullExchangeName") or "Unknown"),
                    quote_type=quote_type,
                    currency=item.get("currency"),
                    market_state=item.get("marketState"),
                    has_options=item.get("hasOptions"),
                    data_source="yfinance_search",
                )
            )
            seen.add(symbol)
            if len(results) >= limit:
                break
        return results, "ok"
    except Exception:
        return [], "provider_unavailable"


def search_instruments_with_status(query: str, limit: int = 8) -> tuple[list[InstrumentSearchResult], str]:
    clean_query = str(query or "").strip()
    if not clean_query or not _provider_enabled():
        return [], "disabled"

    bucket = int(datetime.now().timestamp() // max(60, settings.market_data_cache_seconds * 5))
    results, provider_status = _yf_search_cached(clean_query, max(1, min(limit, 12)), bucket)

    # Search is autocomplete only. Add a direct-ticker choice when the input has
    # a valid ticker shape, even if Yahoo's search endpoint is empty. Analysis
    # will independently verify the quote through several provider methods.
    direct = normalize_symbol(clean_query)
    if not results and is_valid_symbol_format(direct):
        results.insert(
            0,
            InstrumentSearchResult(
                symbol=direct,
                name="Analyze exact ticker",
                exchange="Direct entry",
                quote_type="EQUITY",
                data_source="direct_ticker_entry",
            ),
        )

    return results[:limit], provider_status


def search_instruments(query: str, limit: int = 8) -> list[InstrumentSearchResult]:
    return search_instruments_with_status(query, limit)[0]


def _fetch_price_history_uncached(normalized: str, provider_period: str, interval: str):
    """Fetch OHLCV data using progressively simpler yfinance calls.

    Keeping this function separate from the public cached wrapper prevents the
    chart endpoint from immediately making a second Yahoo request after the AI
    indicator engine has already downloaded the same history.
    """
    try:
        import yfinance as yf

        _configure_yfinance(yf)
    except Exception:
        return None, normalized, "provider_unavailable"

    transient = False
    received_provider_response = False

    for candidate in symbol_candidates(normalized):
        ticker = yf.Ticker(candidate)

        # Start with a minimal history request. Optional yfinance keyword
        # arguments have changed between releases; an unsupported keyword can
        # otherwise make every chart fail while quote retrieval still works.
        ticker_attempts = [
            {"period": provider_period, "interval": interval, "auto_adjust": False},
            {"period": provider_period, "interval": interval},
        ]
        for kwargs in ticker_attempts:
            try:
                frame = ticker.history(**kwargs)
                received_provider_response = True
                if frame is not None and not frame.empty:
                    return frame, candidate, "ok"
            except Exception as exc:
                transient = transient or _is_transient_error(exc)

        # Download is an independent Yahoo path and is useful when Ticker.history
        # returns an empty frame. Keep its arguments compatible across yfinance
        # versions, then normalize possible MultiIndex responses.
        download_attempts = [
            {
                "period": provider_period,
                "interval": interval,
                "auto_adjust": False,
                "progress": False,
                "threads": False,
            },
            {
                "period": provider_period,
                "interval": interval,
                "progress": False,
                "threads": False,
            },
        ]
        for kwargs in download_attempts:
            try:
                frame = yf.download(candidate, **kwargs)
                received_provider_response = True
                frame = _extract_history_frame(frame, candidate)
                if frame is not None and not frame.empty:
                    return frame, candidate, "ok"
            except Exception as exc:
                transient = transient or _is_transient_error(exc)

    if transient or not received_provider_response:
        return None, normalized, "provider_unavailable"
    return None, normalized, "not_found"


@lru_cache(maxsize=512)
def _get_price_history_cached(
    normalized: str,
    provider_period: str,
    interval: str,
    cache_bucket: int,
):
    del cache_bucket
    return _fetch_price_history_uncached(normalized, provider_period, interval)


def get_price_history(symbol: str, period: str = "1y", interval: str = "1d"):
    """Retrieve verified OHLCV history with retries, aliases, and caching.

    Returns ``(dataframe, canonical_symbol, status)``. The cache is important:
    the AI analysis and the visible chart use the same price history, so the
    chart should reuse the successful analysis download instead of immediately
    making another provider request and being rate-limited.
    """
    normalized = normalize_symbol(symbol)
    provider_period = normalize_history_period(period)
    if not is_valid_symbol_format(normalized):
        return None, normalized, "invalid_format"
    if not _provider_enabled():
        return None, normalized, "provider_unavailable"

    cache_seconds = max(60, int(settings.market_data_cache_seconds or 60))
    cache_bucket = int(datetime.now().timestamp() // cache_seconds)
    return _get_price_history_cached(normalized, provider_period, interval, cache_bucket)


def get_chart_history(symbol: str, period: str = "1y") -> dict[str, Any]:
    """Return chart-ready daily closing prices and summary ranges.

    The latest completed bar remains available when the market is closed.
    """
    requested_period = normalize_history_period(period)

    # The indicator engine already downloads one year of daily history. Reuse
    # that same cached frame for the 1/3/6-month and 1-year chart ranges, then
    # slice it locally. This avoids a second immediate Yahoo request, which was
    # causing the chart to appear unavailable even though analysis had data.
    provider_period = "1y" if requested_period in {"1mo", "3mo", "6mo", "1y", "ytd"} else requested_period
    frame, canonical, status = get_price_history(symbol, provider_period, "1d")
    if status != "ok" or frame is None or frame.empty:
        return {
            "symbol": canonical,
            "period": requested_period,
            "status": status,
            "market_status": _market_status(),
            "as_of": None,
            "points": [],
            "summary": {},
        }

    try:
        full_frame = frame.dropna(subset=["Close"]).copy()
        row_windows = {"1mo": 23, "3mo": 66, "6mo": 132}
        clean = full_frame.tail(row_windows.get(requested_period, len(full_frame))).copy()
        points = []
        for index, row in clean.iterrows():
            timestamp = index.isoformat() if hasattr(index, "isoformat") else str(index)
            points.append({
                "date": timestamp,
                "close": round(_safe_float(row.get("Close")), 4),
                "open": round(_safe_float(row.get("Open")), 4),
                "high": round(_safe_float(row.get("High")), 4),
                "low": round(_safe_float(row.get("Low")), 4),
                "volume": _safe_int(row.get("Volume"), 0),
            })
        last = clean.iloc[-1]
        last_close = _safe_float(last.get("Close"))
        first_close = _safe_float(clean.iloc[0].get("Close"), last_close)
        period_change = last_close - first_close
        period_change_percent = (period_change / first_close * 100) if first_close else 0
        as_of_value = clean.index[-1]
        as_of = as_of_value.isoformat() if hasattr(as_of_value, "isoformat") else str(as_of_value)

        # Pull a year for the 52-week range even when the visible chart is shorter.
        range_frame = full_frame
        if provider_period != "1y":
            yearly, _, yearly_status = get_price_history(canonical, "1y", "1d")
            if yearly_status == "ok" and yearly is not None and not yearly.empty:
                range_frame = yearly.dropna(subset=["Close"])

        return {
            "symbol": canonical,
            "period": requested_period,
            "status": "ok",
            "market_status": _market_status(),
            "as_of": as_of,
            "points": points,
            "summary": {
                "last_price": round(last_close, 2),
                "period_change": round(period_change, 2),
                "period_change_percent": round(period_change_percent, 2),
                "period_low": round(_safe_float(clean["Low"].min()), 2),
                "period_high": round(_safe_float(clean["High"].max()), 2),
                "fifty_two_week_low": round(_safe_float(range_frame["Low"].min()), 2),
                "fifty_two_week_high": round(_safe_float(range_frame["High"].max()), 2),
                "volume": _safe_int(last.get("Volume"), 0),
            },
        }
    except Exception:
        return {
            "symbol": canonical,
            "period": requested_period,
            "status": "provider_unavailable",
            "market_status": _market_status(),
            "as_of": None,
            "points": [],
            "summary": {},
        }

def _sample_quote(symbol: str) -> Quote:
    raw = SAMPLE_QUOTES.get(symbol, {"price": 100.0, "change": 0.0, "change_percent": 0.0, "volume": 1_000_000})
    return Quote(symbol=symbol, market_status=_market_status(), data_source="sample", **raw)


def _premium(price: float, strike: float, contract_type: str, index: int):
    if contract_type == "CALL":
        intrinsic = max(price - strike, 0)
        distance = max(strike - price, 0)
    else:
        intrinsic = max(strike - price, 0)
        distance = max(price - strike, 0)
    time_value = max(0.55, 2.2 - distance * 0.13)
    mid = intrinsic + time_value + (0.04 * index)
    bid = round(max(0.25, mid - 0.04), 2)
    ask = round(bid + max(0.05, bid * 0.045), 2)
    return bid, ask


def _sample_option_chain(symbol: str) -> list[OptionContract]:
    quote = _sample_quote(symbol)
    base = round(quote.price / 5) * 5
    rows: list[OptionContract] = []
    strikes = [base - 10, base - 5, base, base + 5, base + 10]
    for index, strike in enumerate(strikes):
        for contract_type in ["CALL", "PUT"]:
            bid, ask = _premium(quote.price, strike, contract_type, index)
            sample_expiration = date.today() + timedelta(days=30)
            rows.append(
                OptionContract(
                    symbol=f"{quote.symbol}-{contract_type}-{strike}",
                    contract_type=contract_type,
                    strike=float(strike),
                    bid=bid,
                    ask=ask,
                    volume=900 + index * 250,
                    open_interest=2200 + index * 700,
                    implied_volatility=0.24 + index * 0.015,
                    delta=round((0.55 - index * 0.04) if contract_type == "CALL" else (-0.45 + index * 0.04), 2),
                    gamma=0.02,
                    theta=-0.04,
                    vega=0.12,
                    spread_percent=bid_ask_spread_pct(bid, ask),
                    expiration=sample_expiration.isoformat(),
                    days_to_expiration=30,
                )
            )
    return rows


@lru_cache(maxsize=256)
def _yf_option_chain_cached(symbol: str, cache_bucket: int) -> list[OptionContract]:
    del cache_bucket
    try:
        import yfinance as yf

        _configure_yfinance(yf)
    except Exception:
        return []

    for candidate in symbol_candidates(symbol):
        try:
            ticker = yf.Ticker(candidate)
            expirations = list(ticker.options or [])
            if not expirations:
                continue

            today = date.today()
            dated_expirations: list[tuple[str, int]] = []
            for expiration in expirations:
                try:
                    expiration_date = datetime.strptime(expiration, "%Y-%m-%d").date()
                    dte = (expiration_date - today).days
                    if dte >= 0:
                        dated_expirations.append((expiration, dte))
                except ValueError:
                    continue

            preferred = [item for item in dated_expirations if 14 <= item[1] <= 45]
            fallback = [item for item in dated_expirations if item[1] >= 7]
            selected_expirations = preferred[:2] or fallback[:2] or dated_expirations[:1]

            rows: list[OptionContract] = []
            quote = get_quote(candidate)
            if quote.price <= 0:
                continue

            for expiration, days_to_expiration in selected_expirations:
                chain = ticker.option_chain(expiration)
                for contract_type, frame in [("CALL", chain.calls), ("PUT", chain.puts)]:
                    if frame is None or frame.empty:
                        continue
                    for _, row in frame.iterrows():
                        bid = _safe_float(row.get("bid"))
                        ask = _safe_float(row.get("ask"))
                        if bid <= 0 or ask <= 0:
                            continue
                        strike = _safe_float(row.get("strike"))
                        if contract_type == "CALL":
                            delta_proxy = max(0.05, min(0.95, 0.50 + ((quote.price - strike) / max(quote.price, 1)) * 5))
                        else:
                            delta_proxy = -max(0.05, min(0.95, 0.50 + ((strike - quote.price) / max(quote.price, 1)) * 5))
                        rows.append(
                            OptionContract(
                                symbol=str(row.get("contractSymbol", f"{candidate}-{contract_type}-{strike}")),
                                contract_type=contract_type,
                                strike=round(strike, 2),
                                bid=round(bid, 2),
                                ask=round(ask, 2),
                                volume=_safe_int(row.get("volume"), 0),
                                open_interest=_safe_int(row.get("openInterest"), 0),
                                implied_volatility=round(_safe_float(row.get("impliedVolatility"), 0), 4),
                                delta=round(delta_proxy, 2),
                                gamma=0.0,
                                theta=0.0,
                                vega=0.0,
                                spread_percent=bid_ask_spread_pct(bid, ask),
                                expiration=expiration,
                                days_to_expiration=days_to_expiration,
                            )
                        )
                if rows:
                    break

            rows.sort(key=lambda contract: (abs(contract.strike - quote.price), -contract.volume, -contract.open_interest))
            if rows:
                return rows[:80]
        except Exception:
            continue
    return []


def get_option_chain(symbol: str) -> list[OptionContract]:
    normalized = normalize_symbol(symbol)
    if settings.market_data_provider.lower() == "sample":
        return _sample_option_chain(normalized)
    if _provider_enabled() and is_valid_symbol_format(normalized):
        bucket = int(datetime.now().timestamp() // max(60, settings.market_data_cache_seconds * 3))
        return _yf_option_chain_cached(normalized, bucket)
    return []
