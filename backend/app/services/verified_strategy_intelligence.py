from __future__ import annotations

import math
from functools import lru_cache
from time import time
from typing import Any

import httpx

from app.core.config import settings


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


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "verified", "active", "complete", "completed"}


def _clean_symbol(symbol: Any) -> str:
    return str(symbol or "").upper().strip().replace("/", "-")


def provider_status_detail() -> dict:
    return {
        "enabled": settings.verified_strategy_intelligence_enabled,
        "alphaledger": {
            "configured": bool(settings.alphaledger_api_url),
            "mode": "authorized_json_endpoint" if settings.alphaledger_api_url else "not_configured",
            "note": (
                "Uses only an explicitly configured authorized/export JSON endpoint. "
                "The application does not scrape undocumented AlphaLedger endpoints."
            ),
        },
        "minimum_alpha_score": settings.alphaledger_min_alpha_score,
        "minimum_sharpe_ratio": settings.alphaledger_min_sharpe,
        "maximum_drawdown_percent": settings.alphaledger_max_drawdown_percent,
        "minimum_track_record_days": settings.alphaledger_min_track_record_days,
        "minimum_relevant_strategies": settings.alphaledger_min_relevant_strategies,
        "max_confidence_adjustment": settings.alphaledger_max_score_adjustment,
    }


def _extract_rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("strategies", "results", "data", "accounts", "leaderboard"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    # Some authorized endpoints may return one strategy object directly.
    if any(key in payload for key in ("alpha_score", "sharpe_ratio", "strategy_name", "provider")):
        return [payload]
    return []


def _extract_exposures(row: dict) -> list[dict]:
    exposures: list[dict] = []
    candidates = []
    for key in ("positions", "current_positions", "exposures", "current_exposure"):
        value = row.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.append(value)

    # Also accept a simple row-level symbol/direction pair.
    if row.get("symbol") or row.get("asset") or row.get("ticker"):
        candidates.append(row)

    for item in candidates:
        if not isinstance(item, dict):
            continue
        symbol = _clean_symbol(item.get("symbol") or item.get("asset") or item.get("ticker"))
        raw_direction = str(item.get("direction") or item.get("side") or item.get("position_side") or "").upper().strip()
        direction = (
            "LONG" if raw_direction in {"LONG", "BUY", "BULLISH", "CALL"}
            else "SHORT" if raw_direction in {"SHORT", "SELL", "BEARISH", "PUT", "SELL_SHORT"}
            else "NONE"
        )
        if not symbol:
            continue
        exposures.append({
            "symbol": symbol,
            "direction": direction,
            "weight": max(0.0, _safe_float(item.get("weight") or item.get("allocation") or item.get("exposure_weight"), 1.0)),
        })
    return exposures


def _normalize_strategy(row: dict) -> dict:
    audit_raw = row.get("audit_status") or row.get("audit") or row.get("cpa_audit") or row.get("us_cpa_audit")
    ownership_raw = row.get("ownership_validated") or row.get("verified") or row.get("account_verified") or row.get("validation_status")
    return {
        "provider": "alphaledger",
        "strategy_name": str(row.get("strategy_name") or row.get("strategy") or row.get("name") or "AlphaLedger strategy"),
        "provider_name": str(row.get("provider_name") or row.get("provider") or row.get("manager") or "Unknown"),
        "alpha_score": _safe_float(row.get("alpha_score") or row.get("alphaScore") or row.get("score"), 0.0),
        "total_return_percent": _safe_float(row.get("total_return_percent") or row.get("total_return") or row.get("return_percent") or row.get("return"), 0.0),
        "sharpe_ratio": _safe_float(row.get("sharpe_ratio") or row.get("sharpe") or row.get("sharpeRatio"), 0.0),
        "max_drawdown_percent": abs(_safe_float(row.get("max_drawdown_percent") or row.get("max_drawdown") or row.get("max_dd") or row.get("drawdown"), 0.0)),
        "calmar_ratio": _safe_float(row.get("calmar_ratio") or row.get("calmar") or row.get("calmarRatio"), 0.0),
        "performance_days": max(0, _safe_int(row.get("performance_days") or row.get("track_record_days") or row.get("history_days") or row.get("age_days"), 0)),
        "ownership_validated": _safe_bool(ownership_raw),
        "audit_active": _safe_bool(audit_raw),
        "audit_status": str(audit_raw or "not_reported"),
        "alphaledger_id": row.get("alphaledger_id") or row.get("alpha_ledger_id") or row.get("id"),
        "exposures": _extract_exposures(row),
    }


def _quality_score(strategy: dict) -> tuple[int, bool, list[str]]:
    alpha = max(0.0, min(100.0, _safe_float(strategy.get("alpha_score"))))
    sharpe = max(0.0, _safe_float(strategy.get("sharpe_ratio")))
    drawdown = max(0.0, _safe_float(strategy.get("max_drawdown_percent")))
    days = max(0, _safe_int(strategy.get("performance_days")))
    verified = bool(strategy.get("ownership_validated"))
    audited = bool(strategy.get("audit_active"))

    alpha_component = alpha * 0.35
    sharpe_component = min(sharpe / 2.5, 1.0) * 25.0
    drawdown_component = max(0.0, 1.0 - min(drawdown, 60.0) / 60.0) * 20.0
    duration_component = min(days / 365.0, 1.0) * 10.0
    verification_component = 5.0 if verified else 0.0
    audit_component = 5.0 if audited else 0.0
    score = round(alpha_component + sharpe_component + drawdown_component + duration_component + verification_component + audit_component)

    blockers: list[str] = []
    if not verified:
        blockers.append("Ownership is not reported as validated.")
    if alpha < settings.alphaledger_min_alpha_score:
        blockers.append(f"Alpha Score {alpha:.1f} is below the configured minimum {settings.alphaledger_min_alpha_score:.1f}.")
    if sharpe < settings.alphaledger_min_sharpe:
        blockers.append(f"Sharpe ratio {sharpe:.2f} is below the configured minimum {settings.alphaledger_min_sharpe:.2f}.")
    if drawdown > settings.alphaledger_max_drawdown_percent:
        blockers.append(f"Maximum drawdown {drawdown:.1f}% exceeds the configured limit {settings.alphaledger_max_drawdown_percent:.1f}%.")
    if days and days < settings.alphaledger_min_track_record_days:
        blockers.append(f"Track record {days} days is below the configured minimum {settings.alphaledger_min_track_record_days} days.")
    if days <= 0:
        blockers.append("Track-record duration was not supplied by the authorized data source.")
    return max(0, min(100, score)), not blockers, blockers


def _request_alphaledger(symbol: str) -> list[dict]:
    if not settings.alphaledger_api_url:
        return []
    headers = {"Accept": "application/json"}
    if settings.alphaledger_api_token:
        headers["Authorization"] = f"Bearer {settings.alphaledger_api_token}"
    try:
        with httpx.Client(timeout=settings.alphaledger_timeout_seconds, follow_redirects=True) as client:
            response = client.get(settings.alphaledger_api_url, params={"symbol": symbol}, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    normalized = []
    for row in _extract_rows(payload):
        strategy = _normalize_strategy(row)
        quality_score, qualified, blockers = _quality_score(strategy)
        strategy.update({
            "quality_score": quality_score,
            "qualified": qualified,
            "qualification_blockers": blockers,
        })
        normalized.append(strategy)
    return normalized


def _direction_for_symbol(strategy: dict, symbol: str) -> tuple[str, float]:
    canonical = _clean_symbol(symbol)
    for exposure in strategy.get("exposures") or []:
        if _clean_symbol(exposure.get("symbol")) == canonical:
            return str(exposure.get("direction") or "NONE"), max(0.05, _safe_float(exposure.get("weight"), 1.0))
    return "NONE", 0.0


def _aggregate(symbol: str, strategies: list[dict]) -> dict:
    qualified = [row for row in strategies if row.get("qualified")]
    quality_values = [int(row.get("quality_score") or 0) for row in qualified]
    quality_score = round(sum(quality_values) / len(quality_values)) if quality_values else 0

    relevant: list[dict] = []
    long_weight = 0.0
    short_weight = 0.0
    for row in qualified:
        direction, exposure_weight = _direction_for_symbol(row, symbol)
        if direction not in {"LONG", "SHORT"}:
            continue
        row_with_match = {**row, "matched_symbol": _clean_symbol(symbol), "matched_direction": direction, "exposure_weight": round(exposure_weight, 4)}
        relevant.append(row_with_match)
        weighted_quality = max(0.01, float(row.get("quality_score", 0)) / 100.0) * exposure_weight
        if direction == "LONG":
            long_weight += weighted_quality
        else:
            short_weight += weighted_quality

    total = long_weight + short_weight
    if total <= 0:
        return {
            "symbol": _clean_symbol(symbol),
            "applicable": False,
            "status": "metrics_only" if strategies else "unavailable",
            "consensus": "N/A",
            "score": 50,
            "confidence": 0,
            "quality_score": quality_score,
            "qualified_strategies": len(qualified),
            "matched_strategies": 0,
            "strategies_reviewed": len(strategies),
            "top_strategies": sorted(strategies, key=lambda r: (r.get("quality_score", 0), r.get("alpha_score", 0)), reverse=True)[:8],
            "message": (
                "Verified strategy metrics are available, but no qualified AlphaLedger strategy supplied a current exposure matching this ticker. Metrics are displayed but do not change trade confidence."
                if strategies else
                "No authorized AlphaLedger strategy data is currently available."
            ),
        }

    directional = (long_weight - short_weight) / total
    score = round(50 + directional * 50)
    dominance = abs(directional)
    coverage = min(1.0, len(relevant) / max(1, settings.alphaledger_min_relevant_strategies))
    confidence = round(100 * dominance * coverage)
    consensus = "BULLISH" if directional >= 0.20 else "BEARISH" if directional <= -0.20 else "MIXED"
    verified = len(relevant) >= settings.alphaledger_min_relevant_strategies and confidence >= 35
    return {
        "symbol": _clean_symbol(symbol),
        "applicable": True,
        "status": "verified" if verified else "insufficient_relevant_data",
        "consensus": consensus,
        "score": score,
        "confidence": confidence,
        "quality_score": quality_score,
        "qualified_strategies": len(qualified),
        "matched_strategies": len(relevant),
        "strategies_reviewed": len(strategies),
        "long_weight": round(long_weight, 4),
        "short_weight": round(short_weight, 4),
        "top_strategies": sorted(relevant or strategies, key=lambda r: (r.get("quality_score", 0), r.get("alpha_score", 0)), reverse=True)[:8],
        "message": (
            "Qualified, ownership-validated AlphaLedger strategy records include current exposure matching this ticker. This is supplemental evidence only."
            if verified else
            "Some qualified AlphaLedger strategies match this ticker, but coverage is not strong enough to adjust recommendation confidence."
        ),
    }


@lru_cache(maxsize=256)
def _snapshot_cached(symbol: str, cache_bucket: int) -> dict:
    del cache_bucket
    strategies = _request_alphaledger(symbol)
    result = _aggregate(symbol, strategies)
    result["providers_used"] = ["alphaledger"] if strategies else []
    result["provider_status"] = provider_status_detail()
    return result


def verified_strategy_intelligence_snapshot(symbol: str) -> dict:
    clean = _clean_symbol(symbol)
    if not settings.verified_strategy_intelligence_enabled:
        return {
            "symbol": clean, "applicable": False, "status": "disabled", "consensus": "N/A", "score": 50,
            "confidence": 0, "quality_score": 0, "qualified_strategies": 0, "matched_strategies": 0,
            "strategies_reviewed": 0, "providers_used": [], "top_strategies": [],
            "message": "Verified strategy intelligence is disabled.", "provider_status": provider_status_detail(),
        }
    if not settings.alphaledger_api_url:
        return {
            "symbol": clean, "applicable": False, "status": "not_configured", "consensus": "N/A", "score": 50,
            "confidence": 0, "quality_score": 0, "qualified_strategies": 0, "matched_strategies": 0,
            "strategies_reviewed": 0, "providers_used": [], "top_strategies": [],
            "message": "AlphaLedger adapter is ready, but no authorized/export JSON endpoint has been configured.",
            "provider_status": provider_status_detail(),
        }
    bucket = int(time() // max(60, settings.alphaledger_data_cache_seconds))
    return _snapshot_cached(clean, bucket)


def verified_strategy_alignment_adjustment(snapshot: dict, direction: str) -> tuple[int, str]:
    """Return a bounded adjustment only for verified, symbol-matched strategy exposure.

    Generic leaderboard performance metrics never change a stock/options recommendation
    unless the authorized AlphaLedger payload explicitly reports exposure to the same asset.
    """
    if not snapshot.get("applicable") or snapshot.get("status") != "verified":
        return 0, "Verified strategy intelligence did not meet the symbol-matched evidence gate."
    if snapshot.get("matched_strategies", 0) < settings.alphaledger_min_relevant_strategies:
        return 0, "Too few qualified AlphaLedger strategies report current exposure to this ticker."

    consensus = snapshot.get("consensus")
    bullish = direction in {"CALL", "LONG", "BUY"}
    bearish = direction in {"PUT", "SHORT", "SELL_SHORT"}
    aligned = (bullish and consensus == "BULLISH") or (bearish and consensus == "BEARISH")
    opposed = (bullish and consensus == "BEARISH") or (bearish and consensus == "BULLISH")
    magnitude = min(
        settings.alphaledger_max_score_adjustment,
        round(settings.alphaledger_max_score_adjustment * float(snapshot.get("confidence", 0) or 0) / 100.0),
    )
    if aligned:
        return magnitude, f"Verified, symbol-matched AlphaLedger strategy exposure aligns with the proposed direction (+{magnitude})."
    if opposed:
        return -magnitude, f"Verified, symbol-matched AlphaLedger strategy exposure opposes the proposed direction (-{magnitude})."
    return 0, "Qualified AlphaLedger strategy exposure is mixed and does not adjust confidence."
