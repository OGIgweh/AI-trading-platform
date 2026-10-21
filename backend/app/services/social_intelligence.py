from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import settings


CRYPTO_ALIASES = {
    "BTC": "BTC", "BTC-USD": "BTC", "XBT": "BTC",
    "ETH": "ETH", "ETH-USD": "ETH",
    "SOL": "SOL", "SOL-USD": "SOL",
    "HYPE": "HYPE", "HYPE-USD": "HYPE",
    "ARB": "ARB", "ARB-USD": "ARB",
    "AVAX": "AVAX", "AVAX-USD": "AVAX",
    "DOGE": "DOGE", "DOGE-USD": "DOGE",
    "LINK": "LINK", "LINK-USD": "LINK",
    "SUI": "SUI", "SUI-USD": "SUI",
    "XRP": "XRP", "XRP-USD": "XRP",
}


def normalize_crypto_asset(symbol: str) -> str | None:
    clean = str(symbol or "").upper().strip()
    return CRYPTO_ALIASES.get(clean)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_win_rate(value: Any) -> float:
    rate = _safe_float(value, 0.0)
    if rate > 1.0:
        rate /= 100.0
    return max(0.0, min(1.0, rate))


def _wallets() -> list[str]:
    values = []
    for value in settings.social_hyperliquid_wallets.split(","):
        address = value.strip()
        if address.startswith("0x") and len(address) == 42:
            values.append(address)
    return list(dict.fromkeys(values))[: settings.social_max_traders]


def provider_status_detail() -> dict:
    return {
        "enabled": settings.social_intelligence_enabled,
        "invo": {
            "configured": bool(settings.invo_social_api_url),
            "mode": "authorized_json_endpoint" if settings.invo_social_api_url else "not_configured",
            "note": "No undocumented Invo endpoint is scraped. Configure an authorized/export endpoint when available.",
        },
        "hyperliquid": {
            "configured": bool(_wallets()),
            "tracked_wallets": len(_wallets()),
            "api_url": settings.hyperliquid_api_url,
            "note": "Uses Hyperliquid's public info API for explicitly configured wallet addresses.",
        },
        "minimum_closed_trades": settings.social_min_closed_trades,
        "minimum_win_rate": settings.social_min_win_rate,
        "max_confidence_adjustment": settings.social_max_score_adjustment,
    }


def _request_invo(asset: str) -> list[dict]:
    if not settings.invo_social_api_url:
        return []
    headers = {"Accept": "application/json"}
    if settings.invo_api_token:
        headers["Authorization"] = f"Bearer {settings.invo_api_token}"
    try:
        with httpx.Client(timeout=settings.social_data_timeout_seconds, follow_redirects=True) as client:
            response = client.get(settings.invo_social_api_url, params={"symbol": asset}, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("traders") or payload.get("results") or payload.get("data") or []
    else:
        rows = []

    normalized: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        position = row.get("position") if isinstance(row.get("position"), dict) else row
        coin = str(position.get("symbol") or position.get("asset") or position.get("coin") or "").upper()
        if coin and coin != asset:
            continue
        raw_direction = str(position.get("direction") or position.get("side") or "").upper()
        direction = "LONG" if raw_direction in {"LONG", "BUY", "B"} else "SHORT" if raw_direction in {"SHORT", "SELL", "A"} else "NONE"
        green = _safe_int(row.get("green_trades") or row.get("wins"), 0)
        red = _safe_int(row.get("red_trades") or row.get("losses"), 0)
        closed = _safe_int(row.get("closed_trades"), green + red)
        win_rate = _normalize_win_rate(row.get("win_rate"))
        if win_rate == 0 and green + red > 0:
            win_rate = green / (green + red)
        normalized.append({
            "provider": "invo",
            "trader": str(row.get("handle") or row.get("username") or row.get("name") or "Invo trader"),
            "wallet": row.get("wallet") or row.get("address"),
            "asset": asset,
            "direction": direction,
            "win_rate": round(win_rate, 4),
            "closed_trades": closed,
            "total_return_percent": _safe_float(row.get("total_return_percent") or row.get("total_return") or row.get("roi"), 0.0),
            "current_pnl_percent": _safe_float(position.get("pnl_percent") or position.get("pnl") or row.get("current_pnl_percent"), 0.0),
            "entry_price": _safe_float(position.get("entry_price") or position.get("entryPx"), 0.0),
            "leverage": _safe_float(position.get("leverage"), 0.0),
            "position_size": _safe_float(position.get("position_size") or position.get("size"), 0.0),
            "source_verified": bool(row.get("verified", True)),
        })
    return normalized[: settings.social_max_traders]


def _hl_post(payload: dict) -> Any:
    try:
        with httpx.Client(timeout=settings.social_data_timeout_seconds) as client:
            response = client.post(settings.hyperliquid_api_url, json=payload, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


def _hyperliquid_trader(address: str, asset: str) -> dict | None:
    state = _hl_post({"type": "clearinghouseState", "user": address})
    fills = _hl_post({"type": "userFills", "user": address, "aggregateByTime": True})
    if not isinstance(state, dict) or not isinstance(fills, list):
        return None

    profitable = 0
    losing = 0
    total_closed_pnl = 0.0
    for fill in fills[: settings.social_fill_lookback]:
        if not isinstance(fill, dict):
            continue
        pnl = _safe_float(fill.get("closedPnl"), 0.0)
        if pnl > 0:
            profitable += 1
            total_closed_pnl += pnl
        elif pnl < 0:
            losing += 1
            total_closed_pnl += pnl
    closed = profitable + losing
    win_rate = profitable / closed if closed else 0.0

    direction = "NONE"
    entry_price = 0.0
    leverage = 0.0
    position_size = 0.0
    current_pnl_percent = 0.0
    for wrapper in state.get("assetPositions", []) or []:
        position = wrapper.get("position", {}) if isinstance(wrapper, dict) else {}
        if str(position.get("coin", "")).upper() != asset:
            continue
        size = _safe_float(position.get("szi"), 0.0)
        if size > 0:
            direction = "LONG"
        elif size < 0:
            direction = "SHORT"
        position_size = abs(size)
        entry_price = _safe_float(position.get("entryPx"), 0.0)
        leverage_data = position.get("leverage") or {}
        if isinstance(leverage_data, dict):
            leverage = _safe_float(leverage_data.get("value"), 0.0)
        unrealized = _safe_float(position.get("unrealizedPnl"), 0.0)
        position_value = _safe_float(position.get("positionValue"), 0.0)
        current_pnl_percent = (unrealized / position_value * 100) if position_value else 0.0
        break

    return {
        "provider": "hyperliquid",
        "trader": f"{address[:6]}…{address[-4:]}",
        "wallet": address,
        "asset": asset,
        "direction": direction,
        "win_rate": round(win_rate, 4),
        "closed_trades": closed,
        "total_return_percent": 0.0,
        "current_pnl_percent": round(current_pnl_percent, 2),
        "entry_price": entry_price,
        "leverage": leverage,
        "position_size": position_size,
        "closed_pnl_sample": round(total_closed_pnl, 2),
        "source_verified": True,
    }


def _trader_weight(row: dict) -> float:
    closed = max(0, _safe_int(row.get("closed_trades"), 0))
    win_rate = _normalize_win_rate(row.get("win_rate"))
    if closed < settings.social_min_closed_trades or win_rate < settings.social_min_win_rate:
        return 0.0
    sample_weight = min(1.0, closed / 60.0)
    skill_weight = min(1.0, max(0.0, (win_rate - 0.50) / 0.25))
    return max(0.05, sample_weight * skill_weight)


def _aggregate(asset: str, traders: list[dict], providers_used: list[str]) -> dict:
    qualified = []
    long_weight = 0.0
    short_weight = 0.0
    for row in traders:
        weight = _trader_weight(row)
        row = {**row, "quality_weight": round(weight, 4)}
        if weight > 0 and row.get("direction") in {"LONG", "SHORT"}:
            qualified.append(row)
            if row["direction"] == "LONG":
                long_weight += weight
            else:
                short_weight += weight

    total = long_weight + short_weight
    if total <= 0:
        return {
            "symbol": asset,
            "applicable": True,
            "status": "insufficient_data",
            "consensus": "UNAVAILABLE",
            "score": 50,
            "confidence": 0,
            "qualified_traders": 0,
            "traders_reviewed": len(traders),
            "long_weight": 0,
            "short_weight": 0,
            "providers_used": providers_used,
            "top_traders": sorted(traders, key=lambda r: (_normalize_win_rate(r.get("win_rate")), _safe_int(r.get("closed_trades"))), reverse=True)[:8],
            "message": "Social/whale data is present but not enough high-sample, high-win-rate traders have an active position in this asset.",
        }

    directional = (long_weight - short_weight) / total
    score = round(50 + directional * 50)
    dominance = abs(directional)
    coverage = min(1.0, len(qualified) / 5.0)
    confidence = round(100 * dominance * coverage)
    consensus = "BULLISH" if directional >= 0.20 else "BEARISH" if directional <= -0.20 else "MIXED"
    return {
        "symbol": asset,
        "applicable": True,
        "status": "verified",
        "consensus": consensus,
        "score": max(0, min(100, score)),
        "confidence": max(0, min(100, confidence)),
        "qualified_traders": len(qualified),
        "traders_reviewed": len(traders),
        "long_weight": round(long_weight, 3),
        "short_weight": round(short_weight, 3),
        "providers_used": providers_used,
        "top_traders": sorted(qualified, key=lambda r: (r.get("quality_weight", 0), _normalize_win_rate(r.get("win_rate"))), reverse=True)[:8],
        "message": "Consensus is weighted by verified direction, closed-trade sample size, and win rate; it is supplemental evidence, not a trade trigger.",
    }


@lru_cache(maxsize=128)
def _snapshot_cached(asset: str, cache_bucket: int) -> dict:
    del cache_bucket
    traders: list[dict] = []
    providers_used: list[str] = []

    invo_rows = _request_invo(asset)
    if invo_rows:
        traders.extend(invo_rows)
        providers_used.append("invo")

    for address in _wallets():
        row = _hyperliquid_trader(address, asset)
        if row:
            traders.append(row)
    if any(row.get("provider") == "hyperliquid" for row in traders):
        providers_used.append("hyperliquid")

    result = _aggregate(asset, traders, providers_used)
    result["provider_status"] = provider_status_detail()
    return result


def social_intelligence_snapshot(symbol: str) -> dict:
    if not settings.social_intelligence_enabled:
        return {
            "symbol": str(symbol).upper(), "applicable": False, "status": "disabled",
            "consensus": "UNAVAILABLE", "score": 50, "confidence": 0,
            "qualified_traders": 0, "traders_reviewed": 0, "providers_used": [], "top_traders": [],
            "message": "Social/whale intelligence is disabled.", "provider_status": provider_status_detail(),
        }
    asset = normalize_crypto_asset(symbol)
    if not asset:
        return {
            "symbol": str(symbol).upper(), "applicable": False, "status": "not_applicable",
            "consensus": "N/A", "score": 50, "confidence": 0,
            "qualified_traders": 0, "traders_reviewed": 0, "providers_used": [], "top_traders": [],
            "message": "Crypto social/whale intelligence is not applied to equity or equity-option recommendations.",
            "provider_status": provider_status_detail(),
        }
    from time import time
    bucket = int(time() // max(60, settings.social_data_cache_seconds))
    return _snapshot_cached(asset, bucket)


def social_alignment_adjustment(snapshot: dict, direction: str) -> tuple[int, str]:
    """Return a bounded supplemental adjustment for an asset-matched crypto signal.

    This is intentionally inactive for stocks/options because crypto-trader behavior
    is not treated as causal evidence for an equity recommendation.
    """
    if not snapshot.get("applicable") or snapshot.get("status") != "verified":
        return 0, "Social/whale intelligence did not meet the verified-data gate."
    if snapshot.get("qualified_traders", 0) < 3 or snapshot.get("confidence", 0) < 40:
        return 0, "Social/whale coverage is too thin to adjust confidence."

    consensus = snapshot.get("consensus")
    aligned = (direction in {"CALL", "LONG", "BUY"} and consensus == "BULLISH") or (direction in {"PUT", "SHORT", "SELL_SHORT"} and consensus == "BEARISH")
    opposed = (direction in {"CALL", "LONG", "BUY"} and consensus == "BEARISH") or (direction in {"PUT", "SHORT", "SELL_SHORT"} and consensus == "BULLISH")
    magnitude = min(settings.social_max_score_adjustment, round(settings.social_max_score_adjustment * snapshot.get("confidence", 0) / 100))
    if aligned:
        return magnitude, f"Verified top-trader consensus aligns with the proposed direction (+{magnitude})."
    if opposed:
        return -magnitude, f"Verified top-trader consensus opposes the proposed direction (-{magnitude})."
    return 0, "Top-trader consensus is mixed and does not adjust confidence."
