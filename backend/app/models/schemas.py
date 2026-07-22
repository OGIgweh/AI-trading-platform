from typing import List, Dict, Optional, Any, Literal
from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    symbol: str = Field(default="AAPL", min_length=1, max_length=24)
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


class InstrumentSearchResult(BaseModel):
    symbol: str
    name: str
    exchange: str = "Unknown"
    quote_type: str = "EQUITY"
    currency: Optional[str] = None
    market_state: Optional[str] = None
    has_options: Optional[bool] = None
    data_source: str = "yfinance_search"


class Quote(BaseModel):
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    market_status: str
    data_source: str = "sample"
    as_of: Optional[str] = None
    previous_close: Optional[float] = None
    day_low: Optional[float] = None
    day_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    fifty_two_week_high: Optional[float] = None


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
    expiration: Optional[str] = None
    days_to_expiration: Optional[int] = None


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


class SuggestedOptionsOrder(BaseModel):
    """A broker-entry-ready view of the qualified options recommendation.

    This is intentionally separate from order execution. It maps the engine's
    selected contract to the fields a user sees in a typical brokerage ticket.
    """

    asset_class: Literal["OPTIONS"] = "OPTIONS"
    strategy: str
    underlying_symbol: str
    underlying_price: float
    leg_count: int = 1
    action: Literal["BUY_TO_OPEN"] = "BUY_TO_OPEN"
    quantity: int
    expiration: str
    days_to_expiration: Optional[int] = None
    strike: float
    option_type: Literal["CALL", "PUT"]
    contract_symbol: str
    bid: float
    mid: float
    ask: float
    order_type: Literal["LIMIT"] = "LIMIT"
    limit_price: float
    timing: Literal["DAY"] = "DAY"
    special_instructions: Literal["NONE"] = "NONE"
    estimated_amount: float
    estimated_max_loss: float
    price_basis: str = "Midpoint of current bid/ask"
    review_required: bool = True
    live_submission_enabled: bool = False


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
    profit_targets: List[float] = Field(default_factory=list)
    position_size: Optional[int] = None
    max_risk_dollars: Optional[float] = None
    risk_level: str = "Controlled"
    expected_holding_period: str = "1-5 trading days"
    explanation: str
    risks: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    suggested_order: Optional[SuggestedOptionsOrder] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)
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
