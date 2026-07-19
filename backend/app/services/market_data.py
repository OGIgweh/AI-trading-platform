from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.models.schemas import Quote, OptionContract
from app.services.risk import bid_ask_spread_pct
from app.services.market_clock import market_status

SAMPLE_QUOTES = {
    "AAPL": {"price": 214.35, "change": 1.26, "change_percent": 0.59, "volume": 58234000},
    "MSFT": {"price": 498.12, "change": -2.15, "change_percent": -0.43, "volume": 25420000},
    "NVDA": {"price": 164.85, "change": 3.41, "change_percent": 2.11, "volume": 189543000},
    "SPY": {"price": 624.91, "change": 0.84, "change_percent": 0.13, "volume": 74523000},
    "QQQ": {"price": 556.40, "change": 1.10, "change_percent": 0.20, "volume": 39120000},
}


def _provider_enabled() -> bool:
    return settings.market_data_provider.lower() in {"auto", "yfinance"}


def _sample_quote(symbol: str) -> Quote:
    raw = SAMPLE_QUOTES.get(symbol, {"price": 100.0, "change": 0.0, "change_percent": 0.0, "volume": 1000000})
    return Quote(symbol=symbol, market_status=_market_status(), data_source="sample", **raw)


def _market_status() -> str:
    # Accurate regular-session status based on NYSE calendar in America/New_York.
    return market_status()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        # pandas/numpy NaN safe check
        if value != value:
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


@lru_cache(maxsize=256)
def _yf_quote_cached(symbol: str, cache_bucket: int) -> Quote | None:
    del cache_bucket
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        last = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else last
        price = _safe_float(last.get("Close"))
        prev_close = _safe_float(prev.get("Close"), price)
        if price <= 0:
            return None
        change = price - prev_close
        change_percent = (change / prev_close * 100) if prev_close else 0
        volume = _safe_int(last.get("Volume"), 0)
        return Quote(
            symbol=symbol,
            price=round(price, 2),
            change=round(change, 2),
            change_percent=round(change_percent, 2),
            volume=volume,
            market_status=_market_status(),
            data_source="yfinance_delayed",
        )
    except Exception:
        return None


def get_quote(symbol: str) -> Quote:
    symbol = symbol.upper().strip()
    if _provider_enabled():
        bucket = int(datetime.now().timestamp() // max(15, settings.market_data_cache_seconds))
        live = _yf_quote_cached(symbol, bucket)
        if live:
            return live
    return _sample_quote(symbol)


def _premium(price: float, strike: float, contract_type: str, i: int):
    if contract_type == "CALL":
        intrinsic = max(price - strike, 0)
        distance = max(strike - price, 0)
    else:
        intrinsic = max(strike - price, 0)
        distance = max(price - strike, 0)
    time_value = max(0.55, 2.2 - distance * 0.13)
    mid = intrinsic + time_value + (0.04 * i)
    bid = round(max(0.25, mid - 0.04), 2)
    ask = round(bid + max(0.05, bid * 0.045), 2)
    return bid, ask


def _sample_option_chain(symbol: str) -> list[OptionContract]:
    q = _sample_quote(symbol)
    base = round(q.price / 5) * 5
    rows: list[OptionContract] = []
    strikes = [base - 10, base - 5, base, base + 5, base + 10]
    for i, strike in enumerate(strikes):
        for t in ["CALL", "PUT"]:
            bid, ask = _premium(q.price, strike, t, i)
            spread_pct = bid_ask_spread_pct(bid, ask)
            rows.append(OptionContract(
                symbol=f"{q.symbol}-{t}-{strike}", contract_type=t, strike=float(strike), bid=bid, ask=ask,
                volume=900 + i * 250, open_interest=2200 + i * 700, implied_volatility=0.24 + i * 0.015,
                delta=round((0.55 - i * 0.04) if t == "CALL" else (-0.45 + i * 0.04), 2),
                gamma=0.02, theta=-0.04, vega=0.12, spread_percent=spread_pct
            ))
    return rows


@lru_cache(maxsize=128)
def _yf_option_chain_cached(symbol: str, cache_bucket: int) -> list[OptionContract]:
    del cache_bucket
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        expirations = list(ticker.options or [])
        if not expirations:
            return []
        # Use the nearest expiration with available data.
        rows: list[OptionContract] = []
        q = get_quote(symbol)
        for expiration in expirations[:3]:
            chain = ticker.option_chain(expiration)
            for contract_type, df in [("CALL", chain.calls), ("PUT", chain.puts)]:
                if df is None or df.empty:
                    continue
                for _, row in df.iterrows():
                    bid = _safe_float(row.get("bid"))
                    ask = _safe_float(row.get("ask"))
                    # Skip broken/non-tradable quotes; wide/zero quotes should become NO TRADE.
                    if bid <= 0 or ask <= 0:
                        continue
                    strike = _safe_float(row.get("strike"))
                    # Yahoo does not provide Greeks. Use a conservative moneyness-based delta proxy
                    # so contracts can be ranked, and expose that limitation in the recommendation evidence.
                    if contract_type == "CALL":
                        delta_proxy = max(0.05, min(0.95, 0.50 + ((q.price - strike) / max(q.price, 1)) * 5))
                    else:
                        delta_proxy = -max(0.05, min(0.95, 0.50 + ((strike - q.price) / max(q.price, 1)) * 5))
                    rows.append(OptionContract(
                        symbol=str(row.get("contractSymbol", f"{symbol}-{contract_type}-{row.get('strike')}")),
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
                    ))
            if rows:
                break
        # Limit payload size but keep enough contracts for the engine to choose liquid contracts.
        rows.sort(key=lambda c: (abs(c.strike - q.price), -c.volume, -c.open_interest))
        return rows[:80]
    except Exception:
        return []


def get_option_chain(symbol: str) -> list[OptionContract]:
    symbol = symbol.upper().strip()
    if _provider_enabled():
        bucket = int(datetime.now().timestamp() // max(60, settings.market_data_cache_seconds * 3))
        live = _yf_option_chain_cached(symbol, bucket)
        if live:
            return live
    return _sample_option_chain(symbol)
