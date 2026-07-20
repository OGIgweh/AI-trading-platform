from fastapi import APIRouter, HTTPException, Query
from app.core.config import settings
from app.models.schemas import AnalyzeRequest, RecommendationsRequest, OrderPreviewRequest, OrderPreview
from app.services.market_data import get_quote, get_option_chain, search_instruments
from app.services.ai_engine import analyze_trade, generate_recommendations
from app.services.portfolio import get_portfolio_summary
from app.services.market_clock import market_status_detail

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name, "live_trading_enabled": settings.live_trading_enabled}

@router.get("/portfolio/summary")
def portfolio_summary():
    return get_portfolio_summary()


@router.get("/market/status")
def market_clock_status():
    return market_status_detail()


@router.get("/market/search")
def market_search(q: str = Query(min_length=1, max_length=80), limit: int = Query(default=8, ge=1, le=12)):
    return {"query": q, "results": search_instruments(q, limit)}


@router.get("/market/quote/{symbol}")
def market_quote(symbol: str):
    result = get_quote(symbol)
    if result.data_source == "unavailable" or result.price <= 0:
        raise HTTPException(status_code=404, detail=f"No verified market quote was found for {symbol.upper().strip()}. Search for the company and select a supported ticker.")
    return result

@router.get("/market/options/{symbol}")
def market_options(symbol: str):
    return get_option_chain(symbol)

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
    if current.data_source == "unavailable" or current.price <= 0:
        raise HTTPException(status_code=404, detail=f"No verified quote found for {req.symbol}.")
    estimated = req.quantity * (req.limit_price or current.price)
    return OrderPreview(allowed=False, live_trading_enabled=settings.live_trading_enabled, estimated_cost=round(estimated, 2), message="Live order execution is disabled. This build supports safe order preview/paper-mode workflows only.")

@router.post("/orders/submit")
def order_submit():
    raise HTTPException(status_code=403, detail="Live trading is disabled by design.")
