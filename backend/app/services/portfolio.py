from app.models.schemas import PortfolioSummary

def get_portfolio_summary() -> PortfolioSummary:
    return PortfolioSummary(total_value=10000.00, daily_pl=126.42, buying_power=6400.00, open_positions=2, market_status="CLOSED", market_sentiment="Neutral", ai_confidence_level=62)
