from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import StringIO
from typing import Any
from urllib.parse import quote as url_quote

import httpx
import pandas as pd

from app.core.config import settings
from app.models.schemas import InstrumentSearchResult, OptionContract, Quote
from app.services.market_clock import market_status
from app.services.risk import bid_ask_spread_pct


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
        return int(float(value))
    except Exception:
        return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]



def _tradier_symbol(symbol: str) -> str:
    clean = str(symbol or "").upper().strip()
    if "-" in clean:
        root, suffix = clean.rsplit("-", 1)
        if root.isalpha() and suffix in {"A", "B", "C"}:
            return f"{root}/{suffix}"
    return clean

def _tradier_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.tradier_api_token}",
        "Accept": "application/json",
        "User-Agent": "AI-Trading-Platform/1.0",
    }


def tradier_enabled() -> bool:
    return bool(settings.tradier_api_token.strip())


def tradier_base_url() -> str:
    explicit = settings.tradier_base_url.strip()
    if explicit:
        return explicit.rstrip("/")
    return "https://sandbox.tradier.com/v1" if settings.tradier_sandbox else "https://api.tradier.com/v1"


def _tradier_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    timeout = max(5.0, float(settings.market_data_timeout_seconds))
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(f"{tradier_base_url()}{path}", params=params, headers=_tradier_headers())
        response.raise_for_status()
        return response.json()


def fetch_tradier_quote(symbol: str) -> Quote | None:
    if not tradier_enabled():
        return None
    provider_symbol = _tradier_symbol(symbol)
    payload = _tradier_get("/markets/quotes", {"symbols": provider_symbol, "greeks": "false"})
    quote = (payload.get("quotes") or {}).get("quote")
    if isinstance(quote, list):
        quote = next((item for item in quote if str(item.get("symbol", "")).upper() in {symbol.upper(), provider_symbol.upper()}), quote[0] if quote else None)
    if not isinstance(quote, dict):
        return None

    price = _safe_float(quote.get("last") or quote.get("close"))
    if price <= 0:
        return None
    previous = _safe_float(quote.get("prevclose"), price)
    change = _safe_float(quote.get("change"), price - previous)
    change_pct = _safe_float(quote.get("change_percentage"), (change / previous * 100) if previous else 0)
    trade_date = quote.get("trade_date")
    if trade_date:
        try:
            # Tradier trade_date is generally epoch milliseconds.
            as_of = datetime.fromtimestamp(float(trade_date) / 1000, tz=timezone.utc).astimezone().isoformat()
        except Exception:
            as_of = datetime.now().astimezone().isoformat()
    else:
        as_of = datetime.now().astimezone().isoformat()

    source = "tradier_delayed" if settings.tradier_sandbox else "tradier_realtime"
    return Quote(
        symbol=str(quote.get("symbol") or symbol).upper(),
        price=round(price, 2),
        change=round(change, 2),
        change_percent=round(change_pct, 2),
        volume=_safe_int(quote.get("volume")),
        market_status=market_status(),
        data_source=source,
        as_of=as_of,
        previous_close=round(previous, 2),
        day_low=round(_safe_float(quote.get("low"), price), 2),
        day_high=round(_safe_float(quote.get("high"), price), 2),
        fifty_two_week_low=round(_safe_float(quote.get("week_52_low")), 2) or None,
        fifty_two_week_high=round(_safe_float(quote.get("week_52_high")), 2) or None,
    )


def fetch_tradier_history(symbol: str, period: str) -> pd.DataFrame | None:
    if not tradier_enabled():
        return None
    today = date.today()
    starts = {
        "1d": today - timedelta(days=7),
        "5d": today - timedelta(days=14),
        "1mo": today - timedelta(days=45),
        "3mo": today - timedelta(days=120),
        "6mo": today - timedelta(days=230),
        "1y": today - timedelta(days=400),
        "2y": today - timedelta(days=800),
        "5y": today - timedelta(days=2000),
        "10y": today - timedelta(days=4000),
        "ytd": date(today.year, 1, 1),
        "max": date(1990, 1, 1),
    }
    payload = _tradier_get(
        "/markets/history",
        {
            "symbol": _tradier_symbol(symbol),
            "interval": "daily",
            "start": starts.get(period, starts["1y"]).isoformat(),
            "end": today.isoformat(),
        },
    )
    days = _as_list((payload.get("history") or {}).get("day"))
    if not days:
        return None
    frame = pd.DataFrame(days)
    rename = {"date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    frame = frame.rename(columns=rename)
    if "Date" not in frame or "Close" not in frame:
        return None
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date", "Close"]).set_index("Date").sort_index()
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.empty:
        return None
    frame.attrs["data_source"] = "tradier_delayed" if settings.tradier_sandbox else "tradier_realtime"
    return frame


def fetch_tradier_search(query: str, limit: int = 8) -> list[InstrumentSearchResult]:
    if not tradier_enabled():
        return []
    payload = _tradier_get("/markets/search", {"q": query, "indexes": "false"})
    securities = _as_list((payload.get("securities") or {}).get("security"))
    results: list[InstrumentSearchResult] = []
    for item in securities:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "stock").upper()
        if kind not in {"STOCK", "ETF"}:
            continue
        symbol = str(item.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        results.append(
            InstrumentSearchResult(
                symbol=symbol,
                name=str(item.get("description") or symbol),
                exchange=str(item.get("exchange") or "Unknown"),
                quote_type="ETF" if kind == "ETF" else "EQUITY",
                data_source="tradier_search",
            )
        )
        if len(results) >= limit:
            break
    return results


def fetch_tradier_options(symbol: str) -> list[OptionContract]:
    if not tradier_enabled():
        return []
    expirations_payload = _tradier_get(
        "/markets/options/expirations",
        {"symbol": _tradier_symbol(symbol), "includeAllRoots": "false", "strikes": "false", "contractSize": "false"},
    )
    expiration_values = _as_list((expirations_payload.get("expirations") or {}).get("date"))
    dated: list[tuple[str, int]] = []
    today = date.today()
    for value in expiration_values:
        try:
            exp = datetime.strptime(str(value), "%Y-%m-%d").date()
            dte = (exp - today).days
            if dte >= 0:
                dated.append((exp.isoformat(), dte))
        except Exception:
            continue
    preferred = [item for item in dated if 14 <= item[1] <= 45]
    fallback = [item for item in dated if item[1] >= 7]
    selected = preferred[:2] or fallback[:2] or dated[:1]
    source = "tradier_delayed_options" if settings.tradier_sandbox else "tradier_realtime_options"
    rows: list[OptionContract] = []
    for expiration, dte in selected:
        payload = _tradier_get(
            "/markets/options/chains",
            {"symbol": _tradier_symbol(symbol), "expiration": expiration, "greeks": "true"},
        )
        options = _as_list((payload.get("options") or {}).get("option"))
        for item in options:
            if not isinstance(item, dict):
                continue
            bid = _safe_float(item.get("bid"))
            ask = _safe_float(item.get("ask"))
            strike = _safe_float(item.get("strike"))
            if bid <= 0 or ask <= 0 or strike <= 0:
                continue
            option_type = str(item.get("option_type") or item.get("type") or "").upper()
            if option_type not in {"CALL", "PUT"}:
                continue
            greeks = item.get("greeks") or {}
            rows.append(
                OptionContract(
                    symbol=str(item.get("symbol") or ""),
                    contract_type=option_type,
                    strike=round(strike, 2),
                    bid=round(bid, 2),
                    ask=round(ask, 2),
                    volume=_safe_int(item.get("volume")),
                    open_interest=_safe_int(item.get("open_interest")),
                    implied_volatility=round(_safe_float(greeks.get("mid_iv") or greeks.get("smv_vol") or item.get("implied_volatility")), 4),
                    delta=round(_safe_float(greeks.get("delta")), 4),
                    gamma=round(_safe_float(greeks.get("gamma")), 4),
                    theta=round(_safe_float(greeks.get("theta")), 4),
                    vega=round(_safe_float(greeks.get("vega")), 4),
                    spread_percent=bid_ask_spread_pct(bid, ask),
                    expiration=str(item.get("expiration_date") or expiration),
                    days_to_expiration=dte,
                    data_source=source,
                )
            )
        if rows:
            break
    return rows



def _yahoo_chart_symbol(symbol: str) -> str:
    """Return the Yahoo-compatible symbol used by the public chart endpoint."""
    return str(symbol or "").upper().strip().replace("/", "-")


def _yahoo_range(period: str) -> str:
    supported = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    clean = str(period or "1y").lower().strip()
    return clean if clean in supported else "1y"


def _yahoo_chart_payload_to_frame(payload: dict[str, Any], source: str = "yahoo_chart_delayed") -> pd.DataFrame | None:
    """Convert Yahoo's keyless chart JSON response into a normalized OHLCV frame."""
    try:
        chart = payload.get("chart") or {}
        if chart.get("error"):
            return None
        results = chart.get("result") or []
        if not results:
            return None
        result = results[0] or {}
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quote_rows = indicators.get("quote") or []
        if not timestamps or not quote_rows:
            return None
        quote_data = quote_rows[0] or {}
        adjclose_rows = indicators.get("adjclose") or []
        adjusted = (adjclose_rows[0] or {}).get("adjclose") if adjclose_rows else None

        rows: list[dict[str, Any]] = []
        for index, stamp in enumerate(timestamps):
            close_values = quote_data.get("close") or []
            close = close_values[index] if index < len(close_values) else None
            if close is None:
                continue
            def value(name: str, default: Any = None):
                values = quote_data.get(name) or []
                return values[index] if index < len(values) and values[index] is not None else default
            rows.append({
                "Date": datetime.fromtimestamp(float(stamp), tz=timezone.utc),
                "Open": value("open", close),
                "High": value("high", close),
                "Low": value("low", close),
                "Close": close,
                "Adj Close": adjusted[index] if adjusted and index < len(adjusted) and adjusted[index] is not None else close,
                "Volume": value("volume", 0),
            })
        if not rows:
            return None
        frame = pd.DataFrame(rows).set_index("Date").sort_index()
        for column in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["Close"])
        if frame.empty:
            return None
        frame.attrs["data_source"] = source
        meta = result.get("meta") or {}
        frame.attrs["currency"] = meta.get("currency")
        frame.attrs["exchange_timezone"] = meta.get("exchangeTimezoneName")
        return frame
    except Exception:
        return None


def fetch_yahoo_chart_history(symbol: str, period: str, interval: str = "1d") -> pd.DataFrame | None:
    """Fetch public Yahoo chart data without yfinance cookies/crumbs.

    Render data-center IPs are sometimes rate-limited by yfinance's cookie and
    quote-summary paths. The v8 chart endpoint is a separate, keyless endpoint
    and is tried through both Yahoo hosts with conservative browser headers.
    """
    provider_symbol = _yahoo_chart_symbol(symbol)
    if not provider_symbol:
        return None
    params = {
        "range": _yahoo_range(period),
        "interval": interval,
        "includePrePost": "false",
        "events": "div,splits,capitalGains",
        "includeAdjustedClose": "true",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    timeout = max(5.0, float(settings.market_data_timeout_seconds))
    endpoints = (
        "https://query1.finance.yahoo.com/v8/finance/chart",
        "https://query2.finance.yahoo.com/v8/finance/chart",
    )
    for endpoint in endpoints:
        for _ in range(max(1, int(settings.market_data_retries) + 1)):
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                    response = client.get(f"{endpoint}/{url_quote(provider_symbol, safe='')}", params=params)
                    if response.status_code in {401, 403, 429, 500, 502, 503, 504}:
                        continue
                    response.raise_for_status()
                    frame = _yahoo_chart_payload_to_frame(response.json())
                    if frame is not None and not frame.empty:
                        return frame
            except Exception:
                continue
    return None

def _stooq_symbol(symbol: str) -> str | None:
    clean = symbol.upper().strip()
    if not clean or clean.startswith("^") or "=" in clean:
        return None
    # Stooq US listings use SYMBOL.US. Preserve share-class hyphens.
    if "." in clean and not clean.endswith((".A", ".B", ".C")):
        return None
    return f"{clean.lower()}.us"


def _period_start(period: str) -> date:
    today = date.today()
    days = {
        "1d": 10,
        "5d": 20,
        "1mo": 50,
        "3mo": 130,
        "6mo": 240,
        "1y": 410,
        "2y": 820,
        "5y": 2050,
        "10y": 4100,
    }
    if period == "ytd":
        return date(today.year, 1, 1)
    if period == "max":
        return date(1990, 1, 1)
    return today - timedelta(days=days.get(period, 410))


def fetch_stooq_history(symbol: str, period: str) -> pd.DataFrame | None:
    if not settings.stooq_fallback_enabled:
        return None
    provider_symbol = _stooq_symbol(symbol)
    if not provider_symbol:
        return None
    base_params = {
        "s": provider_symbol,
        "i": "d",
        "d1": _period_start(period).strftime("%Y%m%d"),
        "d2": date.today().strftime("%Y%m%d"),
    }
    timeout = max(5.0, float(settings.market_data_timeout_seconds))
    endpoints = ("https://stooq.com/q/d/l/", "https://stooq.pl/q/d/l/")
    parameter_sets = (base_params, {"s": provider_symbol, "i": "d"})
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/csv,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    for endpoint in endpoints:
        for params in parameter_sets:
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                    response = client.get(endpoint, params=params)
                    response.raise_for_status()
                text = response.text.strip().lstrip("\ufeff")
                if not text.lower().startswith("date,"):
                    continue
                frame = pd.read_csv(StringIO(text))
                if frame.empty or "Date" not in frame or "Close" not in frame:
                    continue
                frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
                frame = frame.dropna(subset=["Date", "Close"]).set_index("Date").sort_index()
                for column in ["Open", "High", "Low", "Close", "Volume"]:
                    if column in frame:
                        frame[column] = pd.to_numeric(frame[column], errors="coerce")
                if frame.empty:
                    continue
                start_date = pd.Timestamp(_period_start(period))
                frame = frame.loc[frame.index >= start_date] if not frame.empty else frame
                frame.attrs["data_source"] = "stooq_eod"
                return frame
            except Exception:
                continue
    return None


def quote_from_history(symbol: str, frame: pd.DataFrame, source: str) -> Quote | None:
    if frame is None or frame.empty:
        return None
    clean = frame.dropna(subset=["Close"])
    if clean.empty:
        return None
    last = clean.iloc[-1]
    previous_row = clean.iloc[-2] if len(clean) > 1 else last
    price = _safe_float(last.get("Close"))
    previous = _safe_float(previous_row.get("Close"), price)
    if price <= 0:
        return None
    change = price - previous
    as_of_value = clean.index[-1]
    as_of = as_of_value.isoformat() if hasattr(as_of_value, "isoformat") else str(as_of_value)
    year = clean.tail(260)
    return Quote(
        symbol=symbol,
        price=round(price, 2),
        change=round(change, 2),
        change_percent=round((change / previous * 100) if previous else 0, 2),
        volume=_safe_int(last.get("Volume")),
        market_status=market_status(),
        data_source=source,
        as_of=as_of,
        previous_close=round(previous, 2),
        day_low=round(_safe_float(last.get("Low"), price), 2),
        day_high=round(_safe_float(last.get("High"), price), 2),
        fifty_two_week_low=round(_safe_float(year["Low"].min()), 2) if "Low" in year else None,
        fifty_two_week_high=round(_safe_float(year["High"].max()), 2) if "High" in year else None,
    )
