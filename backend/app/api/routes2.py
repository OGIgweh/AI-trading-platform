from fastapi import APIRouter, HTTPException
from app.core.config import settings
from app.models.schemas import AnalyzeRequest, OrderPreviewRequest, OrderPreview
from app.services.market_data import get_quote, get_option_chain
from app.services.ai_engine import analyze_trade
from app.services.portfolio import get_portfolio_summary

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name, "live_trading_enabled": settings.live_trading_enabled}

@router.get("/portfolio/summary")
def portfolio_summary():
    return get_portfolio_summary()

@router.get("/market/quote/{symbol}")
def market_quote(symbol: str):
    return get_quote(symbol)

@router.get("/market/options/{symbol}")
def market_options(symbol: str):
    return get_option_chain(symbol)

@router.post("/ai/analyze")
def ai_analyze(req: AnalyzeRequest):
    return analyze_trade(req)

@router.post("/orders/preview")
def order_preview(req: OrderPreviewRequest):
    estimated = req.quantity * (req.limit_price or get_quote(req.symbol).price)
    return OrderPreview(allowed=False, live_trading_enabled=settings.live_trading_enabled, estimated_cost=round(estimated, 2), message="Live order execution is disabled. This starter only supports safe order preview/paper-mode workflows.")

@router.post("/orders/submit")
def order_submit():
    raise HTTPException(status_code=403, detail="Live trading is disabled by design in this starter project.")
