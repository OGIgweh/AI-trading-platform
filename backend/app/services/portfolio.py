from app.models.schemas import PortfolioSummary
from app.services.market_clock import market_status_detail


def get_portfolio_summary() -> PortfolioSummary:
    clock = market_status_detail()
    return PortfolioSummary(
        total_value=10000.00,
        daily_pl=126.42,
        buying_power=6400.00,
        open_positions=2,
        market_status=clock["status"],
        market_sentiment="Neutral",
        ai_confidence_level=62,
    )
