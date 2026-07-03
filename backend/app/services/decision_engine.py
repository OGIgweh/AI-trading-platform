from app.core.config import settings
from app.models.schemas import AnalyzeRequest, Recommendation
from app.services.market_data import MarketDataService
from app.services.indicators import technical_snapshot
from app.services.risk import bid_ask_spread_pct, position_contracts

class DecisionEngine:
    def __init__(self):
        self.market = MarketDataService()

    def analyze(self, req: AnalyzeRequest) -> Recommendation:
        symbol = req.symbol.upper()
        threshold = req.user_threshold or settings.min_confidence
        quote = self.market.get_quote(symbol)
        options = self.market.get_option_chain(symbol)
        tech = technical_snapshot(symbol)
        missing = []
        risks = []

        if quote.is_stale or quote.price <= 0:
            missing.append("verified real-time quote")
        if not options:
            missing.append("options chain with Greeks")
        if tech.get("score", 0) == 0:
            missing.append("technical indicator data")

        if missing:
            return Recommendation(
                symbol=symbol, recommendation="NO_TRADE", confidence=0, threshold=threshold,
                explanation="NO TRADE RECOMMENDED because required verified evidence is missing.",
                evidence={"quote": quote.model_dump(), "technical": tech, "options_count": len(options)},
                risks=["Incomplete data could lead to unsafe trade decisions"], missing_data=missing
            )

        selected = options[0] if req.strategy.lower() in {"long_call", "call", "calls"} else options[1]
        spread = bid_ask_spread_pct(selected.bid, selected.ask)
        if spread > settings.max_bid_ask_spread_pct:
            risks.append(f"Bid/ask spread too wide: {spread}%")
        if selected.volume < 500 or selected.open_interest < 1000:
            risks.append("Options liquidity below preferred threshold")
        if quote.market_status != "OPEN":
            risks.append("Market is closed; do not place market orders")

        technical_score = tech.get("score", 0)
        options_score = 80 if not risks else 55
        market_score = 65 if quote.market_status == "OPEN" else 55
        risk_score = 85 if len(risks) <= 1 else 50
        confidence = round((technical_score * .35) + (options_score * .30) + (market_score * .15) + (risk_score * .20))

        mid = round((selected.bid + selected.ask) / 2, 2)
        contracts = position_contracts(req.account_value, mid)

        if confidence < threshold or risks:
            return Recommendation(
                symbol=symbol, recommendation="NO_TRADE", trade_type=req.strategy, confidence=confidence, threshold=threshold,
                explanation="NO TRADE RECOMMENDED because confidence is below threshold or risk filters failed.",
                evidence={"quote": quote.model_dump(), "technical": tech, "selected_option": selected.model_dump(), "spread_pct": spread},
                risks=risks or ["Confidence below configured threshold"], missing_data=[]
            )

        return Recommendation(
            symbol=symbol, recommendation="TRADE", trade_type=req.strategy, confidence=confidence, threshold=threshold,
            entry_price=mid, stop_loss=round(mid * .75, 2), profit_targets=[round(mid * 1.25, 2), round(mid * 1.5, 2)],
            position_size=contracts, risk_level="MEDIUM", expected_holding_period="1-10 trading days",
            explanation="Trade qualifies because technical trend, option liquidity, spread, and risk filters align. User approval is still required before order placement.",
            evidence={"quote": quote.model_dump(), "technical": tech, "selected_option": selected.model_dump(), "spread_pct": spread},
            risks=["Options can expire worthless", "Market conditions may change rapidly", "Use limit orders only"], missing_data=[]
        )
