import json
import datetime
import sys
from google import genai
from google.genai import types
import config
from schemas import MarketAnalysisPayload, CommitteeDecision, IndividualAgentVerdict

# Windowsコンソールの文字化け防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Vertex AIクライアントの初期化 (us-central1: Geminiモデル配置リージョン)
client = genai.Client(
    vertexai=True,
    project=config.GCP_PROJECT_ID,
    location=config.GCP_VERTEX_LOCATION
)

SYSTEM_PROMPT = """
You are the Executive Committee of the Multi-Agent Autonomous Quantitative Trading Platform (v7.0 Master Edition).
You analyze XAU/USD (Gold) and financial markets by synthesizing inputs from 8 specialized roles:

1. [Technical Analyst]: Evaluates Dow theory (highs/lows), multi-timeframe moving averages (20/55/89/200 EMA), dynamic best-fit MAs, support/resistance, and candlestick patterns.
2. [Macro & Lead-Lag Agent]: Analyzes US Real Yields (TIPS), DXY, and the top 5 lead-lag correlation indicators. Employs dynamic rolling anomaly weighting (prefers recent 3-month regime).
3. [Contrarian Sentiment Agent]: Reads retail long/short ratios (e.g. OANDA). If retail is heavily long (>70%), looks for short liquidity sweeps by smart money.
4. [Alpha Discovery Architect]: Identifies session-specific anomalies (Tokyo, London Open 16:00 JST, NY Open 21:00 JST, London Fix) and Smart Money Concepts (Order Blocks, FVG, Liquidity Pools).
5. [Devil's Advocate (Risk Manager)]: Actively argues AGAINST taking trades. Identifies fakeout patterns, higher-timeframe resistance, and slippage traps.
6. [CFO & Dynamic Exit Guard]: Enforces capital preservation. Under Micro Account Mode (e.g. 30,000 JPY / 0.01 lot), strictly approves SINGLE POSITION ONLY and TIGHT SL (15-25 pips).
7. [AI Producer]: Watches institutional hedge fund trends, detects regime shifts, and suggests strategic enhancements.
8. [Orchestrator]: Moderates the committee debate, aggregates scores, and determines the final action (TACTICAL_A_MARKET, TACTICAL_B_PENDING, or TACTICAL_C_ABSTAIN).

RULES:
- In RANGE or LOW VOLATILITY conditions: Do NOT perpetually abstain. Actively evaluate Mean Reversion and Dynamic Best-Fit MA bounces (e.g. buying at support/range lows with tight SL, selling at resistance/range highs).
- In TREND conditions: Seek pullbacks to key moving averages (20/55/89 EMA) or high-probability breakout continuations.
- When fakeout risk is moderate or high, DO NOT use TACTICAL_A_MARKET. Use TACTICAL_B_PENDING (retest wait) or TACTICAL_C_ABSTAIN.
- The CFO veto is absolute: if risk is truly unacceptable (e.g. extreme uncertainty, high event risk), action MUST be TACTICAL_C_ABSTAIN.
- Output all analysis explanations in clear Japanese for the user (executive_summary_ja, producer_advice_ja).
"""

def evaluate_market_committee(payload: MarketAnalysisPayload) -> CommitteeDecision:
    """
    Tier 1クオンツフィルタ ＆ Tier 2 AI Multi-Agent 合議体判定を実行する
    """
    # --- Tier 1: 高速クオンツスクリーニング ---
    # スプレッドが広すぎる場合 (例: 5.0 pips以上 = 経済指標直後や早朝) は機械的に即時見送り
    if payload.spread_pips > 5.0:
        return CommitteeDecision(
            symbol=payload.symbol,
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            regime="HIGH_VOLATILITY_SPIKE",
            action="TACTICAL_C_ABSTAIN",
            direction="NONE",
            final_confidence=0.0,
            suggested_sl_pips=20.0,
            suggested_tp_pips=40.0,
            agent_verdicts=[
                IndividualAgentVerdict(
                    agent_name="Risk_Filter_Tier1",
                    bias="ABSTAIN",
                    confidence=1.0,
                    key_reasoning=f"スプレッド異常拡大を検知 ({payload.spread_pips:.1f} pips > 5.0 pips)。スリッページ防止のため見送り。",
                    warning_or_risk="Spread spike trap"
                )
            ],
            devils_advocate_objection="スプレッド拡大によるコスト負けリスクが極めて高い状態です。",
            cfo_risk_approval=False,
            cfo_lot_size=0.0,
            executive_summary_ja=f"【見送り (Abstain)】現在スプレッドが {payload.spread_pips:.1f} pips と高騰しています。飛び乗りによる損失を防ぐため、スプレッド縮小までエントリーを機械的にインターロックしました。"
        )

    # --- Tier 2: AI Multi-Agent Committee (Gemini 2.5 Flash) ---
    prompt_content = f"""
Current Market State for {payload.symbol}:
- Current Price: {payload.current_price}
- Current Spread: {payload.spread_pips} pips
- Retail Sentiment (Long Ratio): {payload.retail_sentiment_ratio * 100:.1f}%
- Macro/FRED Summary: {payload.fred_macro_summary}
- Best-Fit Dynamic MA Info: {payload.best_fit_ma_info}

Candle Summary:
- H1 Candles (Latest 5): {[c.model_dump() for c in (payload.candles_h1[-5:] if payload.candles_h1 else [])]}
- M15 Candles (Latest 5): {[c.model_dump() for c in (payload.candles_m15[-5:] if payload.candles_m15 else [])]}

Please conduct the full multi-agent committee debate, populate individual agent verdicts, and synthesize the final decision.
"""

    try:
        response = client.models.generate_content(
            model=config.VERTEX_MODEL_NAME,
            contents=prompt_content,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=CommitteeDecision,
                temperature=0.2,
            )
        )
        decision_dict = json.loads(response.text)
        return CommitteeDecision.model_validate(decision_dict)
    except Exception as e:
        print(f"[ERROR] Gemini Multi-Agent Committee execution error: {e}")
        # 安全フェールセーフ: エラー時は見送り判定
        return CommitteeDecision(
            symbol=payload.symbol,
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            regime="RANGE",
            action="TACTICAL_C_ABSTAIN",
            direction="NONE",
            final_confidence=0.0,
            suggested_sl_pips=20.0,
            suggested_tp_pips=40.0,
            agent_verdicts=[],
            devils_advocate_objection="AI推論エラーによるフェールセーフ発動。",
            cfo_risk_approval=False,
            cfo_lot_size=0.01,
            executive_summary_ja="【フェールセーフ作動】AI合議体プロセスの一時的待機のため、今回は安全に見送り（Abstain）としました。"
        )

if __name__ == "__main__":
    dummy_payload = MarketAnalysisPayload(
        symbol="XAUUSD",
        current_price=2685.50,
        spread_pips=1.8,
        retail_sentiment_ratio=0.74,
        fred_macro_summary="US 10Y Yields falling slightly, DXY pulling back",
        best_fit_ma_info="H1: 89EMA support strong (bounce count: 3)",
    )
    print("--- Multi-Agent Committee 動作テスト開始 ---")
    decision = evaluate_market_committee(dummy_payload)
    print(f"判定アクション: {decision.action}")
    print(f"相場レジーム: {decision.regime}")
    print(f"売買方向: {decision.direction}")
    print(f"確信度: {decision.final_confidence * 100:.1f}%")
    print(f"推奨SL幅: {decision.suggested_sl_pips} pips / 推奨TP幅: {decision.suggested_tp_pips} pips")
    print(f"CFOリスク承認: {decision.cfo_risk_approval} (Lot: {decision.cfo_lot_size})")
    print(f"\n【合議体エグゼクティブサマリー】:\n{decision.executive_summary_ja}")
    if decision.producer_advice_ja:
        print(f"\n【AIプロデューサーからの助言】:\n{decision.producer_advice_ja}")
