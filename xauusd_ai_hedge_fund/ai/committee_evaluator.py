import datetime
import json
from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict, Any
from google import genai
from google.genai import types
from config import settings

class CommitteeReport(BaseModel):
    regime: str = Field(..., description="相場レジーム（例: RANGE_COMPRESSION, BULLISH_SWEEP_WAIT, HIGH_VOLATILITY）")
    action: Literal["TACTICAL_A_MARKET", "TACTICAL_B_PENDING", "TACTICAL_C_ABSTAIN"] = Field(..., description="合議アクション")
    direction: Literal["BUY", "SELL", "NONE"] = Field(..., description="売買方向")
    confidence: float = Field(..., ge=0.0, le=1.0, description="総合確信度 (0.0〜1.0)")
    suggested_sl_pips: float = Field(25.0, description="推奨SL幅(pips)")
    suggested_tp_pips: float = Field(50.0, description="推奨TP幅(pips)")
    cfo_risk_approval: bool = Field(False, description="CFO資金管理承認フラグ")
    cfo_lot_size: float = Field(0.01, description="推奨ロット")
    executive_summary_ja: str = Field(..., description="合議体エグゼクティブ解説（専門用語を交えた高密度な相場環境認識、約100〜150字）")
    devils_advocate_objection: str = Field(..., description="デビルズアドボケート (リスク反論)（鋭い罠・飛び乗り警告、約60〜90字）")
    producer_advice_ja: str = Field(..., description="AIプロデューサー助言（次のセッションでの立ち回り・注目ライン、約60〜90字）")

SYSTEM_PROMPT = """You are the Executive Committee of the Multi-Agent Quantitative Hedge Fund (Institutional XAU/USD).
Synthesize 8 specialist roles (Technical, Macro, Retail Contrarian, SMC Liquidity, Devil's Advocate, CFO, Producer, Orchestrator).
Generate high-density, professional Japanese executive analysis with ZERO conversational filler.
Reflect these 3 core pillars:
1. executive_summary_ja: Professional synthesis of price action, liquidity sweeps (PDH/PDL, Asia H/L), and volatility.
2. devils_advocate_objection: Sharp counter-argument warning against fakeouts, liquidity traps, or momentum exhaustion.
3. producer_advice_ja: Strategic tactical advice for upcoming session transitions (Tokyo/London/NY) and key levels.
"""

class AICommitteeEvaluator:
    """
    【超省トークン型】AI合議体 定時分析エバリュエーター (Gemini 2.5 Flash)
    
    プロンプトを極限まで高密度化し、thinking_budget=0 で思考トークンを完全排除。
    旧仕様と同等のプロ品質（エグゼクティブ解説・デビルズ反論・プロデューサー助言）を
    わずか約300トークンで生成します。
    """
    def __init__(self):
        try:
            self.client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_VERTEX_LOCATION
            )
            self.model_name = settings.VERTEX_MODEL_NAME
            self.available = True
        except Exception as e:
            print(f"[AI COMMITTEE WARNING] Vertex AI Client init error: {e}")
            self.available = False

    def evaluate_hourly(
        self,
        market_state: Dict[str, Any],
        signal: Any,
        account_state: Dict[str, Any],
        active_session: str = "Unknown"
    ) -> CommitteeReport:
        current_ask = market_state.get("current_ask", 0.0)
        spread_pips = market_state.get("spread_pips", 0.0)
        atr_pips = market_state.get("atr_m15_pips", 0.0)
        asia_high = market_state.get("asia_high")
        asia_low = market_state.get("asia_low")
        pdh = market_state.get("pdh")
        pdl = market_state.get("pdl")
        now_jst = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        if not self.available:
            return self._build_fallback(signal, current_ask, spread_pips)

        # 高密度入力プロンプト（約90〜120トークンに圧縮）
        prompt = (
            f"Asset: XAUUSD | JST: {now_jst} | Session: {active_session}\n"
            f"Price: ${current_ask:.2f} (Spread: {spread_pips:.1f}pips) | ATR(M15): {atr_pips:.1f}pips\n"
            f"Levels: AsiaHigh=${asia_high}, AsiaLow=${asia_low}, PDH=${pdh}, PDL=${pdl}\n"
            f"SMC: {signal.setup_name} ({signal.action}) | Note: {signal.rationale_ja}\n"
            f"Account: Balance=¥{account_state.get('balance', 0):,.0f}, Equity=¥{account_state.get('equity', 0):,.0f}"
        )

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=CommitteeReport,
                    temperature=0.2,
                    max_output_tokens=350,
                    thinking_config={
                        "thinking_budget": 0  # 思考トークン消費を0にして超省トークン化
                    }
                )
            )
            data = json.loads(response.text)
            return CommitteeReport.model_validate(data)
        except Exception as e:
            print(f"[AI COMMITTEE ERROR] {e}")
            return self._build_fallback(signal, current_ask, spread_pips)

    def _build_fallback(self, signal: Any, current_ask: float, spread_pips: float) -> CommitteeReport:
        """API一時不通時の安全フェールセーフ"""
        return CommitteeReport(
            regime="RANGE_COMPRESSION",
            action="TACTICAL_C_ABSTAIN",
            direction="NONE",
            confidence=0.0,
            suggested_sl_pips=25.0,
            suggested_tp_pips=50.0,
            cfo_risk_approval=False,
            cfo_lot_size=0.0,
            executive_summary_ja=f"現在価格 ${current_ask:.2f}。{signal.rationale_ja}",
            devils_advocate_objection="市場流動性の偏りおよび急激なスプレッド拡大リスクに警戒が必要です。",
            producer_advice_ja="主要セッション境界でのブレイクアウト確認まで静観を推奨します。"
        )
