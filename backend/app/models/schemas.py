from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class AnalyzeRequest(BaseModel):
    symbol: str = Field(default="AAPL", min_length=1, max_length=12)
    account_value: float = Field(default=10000, gt=0)
    strategy: str = "auto"
    min_confidence: int = Field(default=75, ge=1, le=100)
    max_risk_percent: float = Field(default=1.0, gt=0, le=5)

class RecommendationsRequest(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"])
    account_value: float = Field(default=10000, gt=0)
    min_confidence: int = Field(default=75, ge=1, le=100)
    max_risk_percent: float = Field(default=1.0, gt=0, le=5)
    include_no_trade: bool = True

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

class EvidenceItem(BaseModel):
    category: str
    name: str
    value: Any
    signal: str = Field(description="bullish, bearish, neutral, pass, fail, warning, info")
    score: int = Field(default=0, ge=-100, le=100)
    weight: float = Field(default=0)
    passed: bool = False
    explanation: str
    data_source: str = "unknown"

class ScoreBreakdown(BaseModel):
    technical_score: int = 0
    options_score: int = 0
    market_score: int = 0
    risk_score: int = 0
    final_confidence: int = 0
    threshold: int = 75

class Recommendation(BaseModel):
    symbol: str
    recommendation: str
    confidence: int
    threshold: int
    trade_type: Optional[str] = None
    direction: Optional[str] = None
    contract_symbol: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    profit_targets: List[float] = []
    position_size: Optional[int] = None
    max_risk_dollars: Optional[float] = None
    risk_level: str = "Controlled"
    expected_holding_period: str = "1-5 trading days"
    explanation: str
    risks: List[str]
    invalidation_conditions: List[str] = []
    evidence: List[EvidenceItem] = []
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    raw_data: Dict[str, Any] = {}
    data_quality: str = "unverified"

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
