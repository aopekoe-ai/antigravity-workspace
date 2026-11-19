from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any

class TradeSignal(BaseModel):
    """戦略が出力する標準シグナルモデル"""
    action: Literal["BUY", "SELL", "NO_TRADE"]
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    suggested_entry_price: float
    suggested_sl_price: float
    suggested_tp_price: float
    sl_distance_pips: float
    tp_distance_pips: float
    risk_reward_ratio: float
    setup_name: str
    rationale_ja: str
    invalidation_level: Optional[float] = None

class BaseStrategy(ABC):
    """
    すべての売買戦略が継承する基底クラス（プラグイン方式）
    相場変化時に新しいロジックを追加・差し替え・テストすることが容易な設計。
    """
    def __init__(self, name: str, params: Dict[str, Any]):
        self.name = name
        self.params = params

    @abstractmethod
    def evaluate(self, market_data: Dict[str, Any]) -> TradeSignal:
        """
        市場データを入力とし、売買シグナルを出力する
        """
        pass
