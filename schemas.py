from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime

class CandleData(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = 0

class MarketAnalysisPayload(BaseModel):
    symbol: str = "XAUUSD"
    current_price: float
    spread_pips: float
    candles_m5: Optional[List[CandleData]] = []
    candles_m15: Optional[List[CandleData]] = []
    candles_h1: Optional[List[CandleData]] = []
    candles_h4: Optional[List[CandleData]] = []
    candles_d1: Optional[List[CandleData]] = []
    fred_macro_summary: Optional[str] = "US Real Rates (TIPS) stable, DXY neutral"
    best_fit_ma_info: Optional[str] = "H1: 89EMA, H4: 55EMA"
    retail_sentiment_ratio: Optional[float] = 0.50  # 0.0 - 1.0 (例: 0.70 = 70% Long)

class IndividualAgentVerdict(BaseModel):
    agent_name: str
    bias: Literal["BUY", "SELL", "NEUTRAL", "ABSTAIN"]
    confidence: float = Field(..., ge=0.0, le=1.0, description="確信度スコア 0.0〜1.0")
    key_reasoning: str
    warning_or_risk: Optional[str] = None

class CommitteeDecision(BaseModel):
    symbol: str = "XAUUSD"
    timestamp: str
    regime: Literal["TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOLATILITY_SPIKE"]
    action: Literal["TACTICAL_A_MARKET", "TACTICAL_B_PENDING", "TACTICAL_C_ABSTAIN"]
    direction: Literal["BUY", "SELL", "NONE"]
    final_confidence: float = Field(..., ge=0.0, le=1.0)
    suggested_sl_pips: float = 20.0
    suggested_tp_pips: float = 40.0
    agent_verdicts: List[IndividualAgentVerdict]
    devils_advocate_objection: str
    cfo_risk_approval: bool
    cfo_lot_size: float = 0.01  # 小資金モード初期値
    executive_summary_ja: str
    producer_advice_ja: Optional[str] = None
