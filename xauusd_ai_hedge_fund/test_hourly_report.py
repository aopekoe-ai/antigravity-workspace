import sys
from config import settings
from core.data_engine import MarketDataEngine
from strategies.smc_liquidity_strategy import SMCLiquiditySweepStrategy
from ai.committee_evaluator import AICommitteeEvaluator
from notifications.discord_manager import DiscordManager

def test_report():
    print("Testing AI Committee Hourly Report with Ultra-Low Token Prompt...")
    symbol = "XAUUSD"
    dummy_market_state = {
        "symbol": symbol,
        "current_ask": 3899.57,
        "current_bid": 3899.40,
        "spread_pips": 1.7,
        "atr_m15_pips": 24.5,
        "asia_high": 3915.20,
        "asia_low": 3888.60,
        "pdh": 3922.00,
        "pdl": 3875.50
    }
    dummy_signal = type("Signal", (), {
        "setup_name": "Scanning_London",
        "action": "NO_TRADE",
        "confidence": 0.0,
        "rationale_ja": "[Londonセッション] アジア高安/前日高安 のブレイク＆リジェクションを待機中。優位性のある歪みが発生するまで静観。"
    })()
    dummy_account = {"balance": 498419, "equity": 498419}

    evaluator = AICommitteeEvaluator()
    print("Calling Gemini 2.5 Flash with compressed context...")
    report = evaluator.evaluate_hourly(dummy_market_state, dummy_signal, dummy_account, active_session="London")
    print("\n--- [GEMINI RESPONSE REPORT] ---")
    print(f"相場レジーム: {report.regime}")
    print(f"判定アクション: {report.action} ({report.direction}) 確信度: {report.confidence*100:.1f}%")
    print(f"エグゼクティブ解説:\n{report.executive_summary_ja}")
    print(f"デビルズ反論:\n{report.devils_advocate_objection}")
    print(f"プロデューサー助言:\n{report.producer_advice_ja}")

    print("\nSending rich Discord notification...")
    mgr = DiscordManager()
    mgr.send_hourly_status(dummy_market_state, dummy_signal, dummy_account, committee_report=report)
    print("Discord notification sent successfully!")

if __name__ == "__main__":
    test_report()
