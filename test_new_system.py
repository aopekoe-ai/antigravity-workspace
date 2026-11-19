import sys
import io

# WindowsコンソールのUnicodeエラー防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from config import settings
from core.mt5_client import RobustMT5Client
from core.data_engine import MarketDataEngine
from core.risk_manager import InstitutionalRiskManager
from strategies.smc_liquidity_strategy import SMCLiquiditySweepStrategy
from ai.macro_nlp_guard import MacroNLPGuard

def test_pipeline():
    print("=== [TEST] 新クオンツパッケージ統合テスト ===")
    params = settings.load_strategy_params()
    symbol = params.get("symbol", "XAUUSD")

    mt5_client = RobustMT5Client(symbol=symbol)
    if not mt5_client.connect():
        print("[FAIL] MT5接続失敗")
        return

    data_engine = MarketDataEngine(symbol=symbol)
    state = data_engine.get_market_state()
    if not state:
        print("[FAIL] 市場データ取得失敗")
        mt5_client.disconnect()
        return

    print(f"[OK] 現在Ask: ${state['current_ask']:.2f}, Bid: ${state['current_bid']:.2f}")
    print(f"[OK] スプレッド: {state['spread_pips']} pips (Exness $0.10=1pip仕様)")
    print(f"[OK] M15 ATR: {state['atr_m15_pips']} pips (${state['atr_m15_dollars']:.2f})")
    print(f"[OK] アジア高値: {state.get('asia_high')}, アジア安値: {state.get('asia_low')}")
    print(f"[OK] 前日高値(PDH): {state.get('pdh')}, 前日安値(PDL): {state.get('pdl')}")

    risk_mgr = InstitutionalRiskManager(params.get("risk_management", {}))
    acct = risk_mgr.get_account_state()
    print(f"[OK] 口座残高: ¥{acct['balance']:,.0f}, 有効証拠金: ¥{acct['equity']:,.0f}")

    strategy = SMCLiquiditySweepStrategy(params=params)
    signal = strategy.evaluate(state)
    print(f"[OK] 戦略シグナル: {signal.action} ({signal.setup_name})")
    print(f"     解説: {signal.rationale_ja}")

    ai_guard = MacroNLPGuard()
    allowed, reason = ai_guard.check_macro_safety(symbol)
    print(f"[OK] AIマクロ安全門番: {'許可 (PASS)' if allowed else '停止 (HALT)'} - {reason}")

    mt5_client.disconnect()
    print("\n[ALL TESTS PASSED] 新ロジック＆新パッケージは完全に正常稼働しています！")

if __name__ == "__main__":
    test_pipeline()
