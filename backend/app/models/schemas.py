from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class AnalyzeRequest(BaseModel):
    symbol: str = Field(default="AAPL", min_length=1, max_length=12)
    account_value: float = 10000
    strategy: str = "long_call"
    min_confidence: int = 75

class Quote(BaseModel):
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    market_status: str
    data_source: str = "sample"

class OptionContract(BaseModel):
    symbol: str
    contract_type: str
    strike: float
    bid: float
    ask: float
    volume: int
    open_interest: int
    implied_volatility: float
    delta: float
    gamma: float
    theta: float
    vega: float
    spread_percent: float

class PortfolioSummary(BaseModel):
    total_value: float
    daily_pl: float
    buying_power: float
    open_positions: int
    market_status: str
    market_sentiment: str
    ai_confidence_level: int

class Recommendation(BaseModel):
    symbol: str
    recommendation: str
    confidence: int
    threshold: int
    trade_type: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    profit_targets: List[float] = []
    position_size: Optional[int] = None
    risk_level: str = "Controlled"
    expected_holding_period: str = "1-5 trading days"
    explanation: str
    risks: List[str]
    evidence: Dict[str, Any]

class OrderPreviewRequest(BaseModel):
    symbol: str
    side: str
    quantity: int
    order_type: str = "limit"
    limit_price: Optional[float] = None

class OrderPreview(BaseModel):
    allowed: bool
    live_trading_enabled: bool
    message: str
    estimated_cost: Optional[float] = None
