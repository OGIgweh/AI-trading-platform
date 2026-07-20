from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.models.schemas import AnalyzeRequest, OrderPreview, OrderPreviewRequest, RecommendationsRequest
from app.services.ai_engine import analyze_trade, generate_recommendations
from app.services.market_clock import market_status_detail
from app.services.market_data import (
    get_option_chain,
    get_quote,
    get_quote_lookup,
    search_instruments_with_status,
)
from app.services.portfolio import get_portfolio_summary

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "live_trading_enabled": settings.live_trading_enabled,
    }


@router.get("/portfolio/summary")
def portfolio_summary():
    return get_portfolio_summary()


@router.get("/market/status")
def market_clock_status():
    return market_status_detail()


@router.get("/market/search")
def market_search(
    q: str = Query(min_length=1, max_length=80),
    limit: int = Query(default=8, ge=1, le=12),
):
    results, provider_status = search_instruments_with_status(q, limit)
    return {
        "query": q,
        "provider_status": provider_status,
        "results": results,
        "message": (
            "Autocomplete is temporarily unavailable; exact ticker entry still works."
            if provider_status == "provider_unavailable"
            else "Search completed."
        ),
    }


@router.get("/market/quote/{symbol}")
def market_quote(symbol: str):
    lookup = get_quote_lookup(symbol)
    if lookup.status == "invalid_format":
        raise HTTPException(status_code=422, detail=lookup.message)
    if lookup.status == "provider_unavailable":
        raise HTTPException(status_code=503, detail=lookup.message)
    if lookup.status == "not_found":
        raise HTTPException(status_code=404, detail=lookup.message)
    return lookup.quote


@router.get("/market/options/{symbol}")
def market_options(symbol: str):
    lookup = get_quote_lookup(symbol)
    if lookup.status == "invalid_format":
        raise HTTPException(status_code=422, detail=lookup.message)
    if lookup.status == "provider_unavailable":
        # Do not falsely claim the ticker is invalid. The AI analysis endpoint
        # will return a transparent NO_TRADE result for this condition.
        raise HTTPException(status_code=503, detail=lookup.message)
    if lookup.status == "not_found":
        raise HTTPException(status_code=404, detail=lookup.message)
    return get_option_chain(lookup.canonical_symbol)


@router.post("/ai/analyze")
def ai_analyze(req: AnalyzeRequest):
    return analyze_trade(req)


@router.post("/ai/recommendations")
def ai_recommendations(req: RecommendationsRequest):
    return generate_recommendations(req)


@router.get("/ai/recommendations")
def ai_recommendations_get():
    return generate_recommendations(RecommendationsRequest())


@router.post("/orders/preview")
def order_preview(req: OrderPreviewRequest):
    current = get_quote(req.symbol)
    if current.data_source in {"provider_unavailable", "not_found", "invalid_symbol"} or current.price <= 0:
        raise HTTPException(status_code=503, detail=f"A verified quote is not currently available for {req.symbol}.")
    estimated = req.quantity * (req.limit_price or current.price)
    return OrderPreview(
        allowed=False,
        live_trading_enabled=settings.live_trading_enabled,
        estimated_cost=round(estimated, 2),
        message="Live order execution is disabled. This build supports safe order preview/paper-mode workflows only.",
    )


@router.post("/orders/submit")
def order_submit():
    raise HTTPException(status_code=403, detail="Live trading is disabled by design.")
