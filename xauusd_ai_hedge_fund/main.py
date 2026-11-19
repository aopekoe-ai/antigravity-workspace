import time
import datetime
import traceback
from config import settings
from core.mt5_client import RobustMT5Client
from core.data_engine import MarketDataEngine
from core.risk_manager import InstitutionalRiskManager
from strategies.smc_liquidity_strategy import SMCLiquiditySweepStrategy
from ai.macro_nlp_guard import MacroNLPGuard
from ai.committee_evaluator import AICommitteeEvaluator
from core.review_engine import ReviewEngine
from notifications.discord_manager import DiscordManager

def run_trading_daemon():
    """
    【VPS常駐型】24時間リアルタイム・クオンツ取引エンジン
    """
    print("==================================================================")
    print("🤖 Institutional SMC Quantitative Trading System v8.0 Starting...")
    print("==================================================================")

    # 1. パラメータの初期ロード
    params = settings.load_strategy_params()
    symbol = params.get("symbol", "XAUUSD")

    # 2. コアモジュールの初期化
    mt5_client = RobustMT5Client(
        symbol=symbol,
        login=settings.MT5_LOGIN,
        password=settings.MT5_PASSWORD,
        server=settings.MT5_SERVER,
        path=settings.MT5_PATH
    )
    data_engine = MarketDataEngine(symbol=symbol)
    risk_manager = InstitutionalRiskManager(params.get("risk_management", {}))
    strategy = SMCLiquiditySweepStrategy(params=params)
    ai_guard = MacroNLPGuard(cache_ttl_minutes=params.get("ai_guard", {}).get("cache_ttl_minutes", 20))
    committee_evaluator = AICommitteeEvaluator()
    review_engine = ReviewEngine()
    discord_mgr = DiscordManager()

    if not mt5_client.connect():
        print("[FATAL ERROR] MT5への初期接続に失敗しました。MT5が起動しているか確認してください。")
        return

    print(f"[SYSTEM READY] 対象銘柄: {symbol}, 戦略: {strategy.name}")
    print("[SYSTEM READY] 常時スキャンループを開始します（Ctrl+C で安全終了）...")

    last_hourly_report_hour = -1
    last_daily_review_day = -1
    last_signal_time = None

    while True:
        try:
            now = datetime.datetime.now()
            # パラメータ動的リロード（相場急変時にファイルを編集すれば即反映）
            params = settings.load_strategy_params()
            exec_filters = params.get("execution_filters", {})
            max_spread = exec_filters.get("max_allowed_spread_pips", 3.0)
            strategy.sessions_config = exec_filters.get("allowed_sessions_jst", strategy.sessions_config)
            ai_guard.cache_ttl_minutes = params.get("ai_guard", {}).get("cache_ttl_minutes", 20)

            # 動的オプティマイザの最適化パラメータをリアルタイム反映
            dyn_params = review_engine.optimizer.load_active_params()
            strategy.update_dynamic_params(dyn_params)
            if "max_allowed_spread_pips" in dyn_params:
                max_spread = dyn_params["max_allowed_spread_pips"]

            # --- A. 市場データ ＆ 特徴量の取得 ---
            market_state = data_engine.get_market_state(
                atr_period=params.get("volatility_parameters", {}).get("atr_period", 14)
            )
            if not market_state:
                # MT5切断時の自動再接続
                mt5_client.connect()
                time.sleep(5)
                continue

            current_spread = market_state["spread_pips"]
            account_state = risk_manager.get_account_state()

            # --- B. サーキットブレーカー（日次最大損失）チェック ---
            can_trade_risk, risk_reason = risk_manager.check_circuit_breaker()
            if not can_trade_risk:
                print(f"[CIRCUIT BREAKER] {risk_reason}")
                discord_mgr.send_circuit_breaker_alert(risk_reason)
                time.sleep(300)  # 5分待機
                continue

            # --- B-2. 【プロップファーム仕様】建値移動 (Break-Even) 自動防御 ---
            be_result = risk_manager.apply_break_even_protection(symbol, market_state["pip_size"])
            if be_result:
                print(f"[BREAK-EVEN TRIGGERED] {be_result}")

            # --- C. 戦略シグナルの評価（SMC流動性スイープ） ---
            signal = strategy.evaluate(market_state)

            # --- D. 毎時00分の定時レポート送信 ---
            if now.minute == 0 and now.hour != last_hourly_report_hour:
                print(f"[HOURLY REPORT TRIGGER] {now.strftime('%Y-%m-%d %H:%M:%S')}")
                active_session = strategy.get_active_session() or "Interbank_OffHours"
                print(f"[AI COMMITTEE] {active_session} セッションのAI合議体分析を実行中...")
                committee_report = committee_evaluator.evaluate_hourly(
                    market_state=market_state,
                    signal=signal,
                    account_state=account_state,
                    active_session=active_session
                )
                discord_mgr.send_hourly_status(market_state, signal, account_state, committee_report=committee_report)
                last_hourly_report_hour = now.hour

            # --- D-2. 毎朝06:00 JST（日次クローズ時）の自律振り返り ＆ 改善レポート送信 ---
            if now.hour == 6 and now.day != last_daily_review_day:
                print(f"[DAILY REVIEW TRIGGER] {now.strftime('%Y-%m-%d %H:%M:%S')} - 日次振り返りPDCAを実行中...")
                eval_data = review_engine.generate_daily_review(
                    market_summary=f"Ask: ${market_state['current_ask']:.2f}, ATR: {market_state['atr_m15_pips']} pips"
                )
                discord_mgr.send_daily_review_report(eval_data)
                last_daily_review_day = now.day

            # --- E. シグナル発生時の発注判定 ---
            if signal.action in ["BUY", "SELL"]:
                # 1. 重複エントリー防止（同一バーでの多重発注防止: M5ベース）
                df_bar = market_state.get("df_m5") if market_state.get("df_m5") is not None else market_state.get("df_m15")
                current_bar_time = df_bar.iloc[-1]["time"] if df_bar is not None else None
                if current_bar_time != last_signal_time:
                    print(f"\n⚡ [SIGNAL DETECTED] {signal.action} - {signal.setup_name} (確信度: {signal.confidence * 100:.0f}%)")

                    # 2. スプレッドフィルター（スリッページ防止）
                    if current_spread > max_spread:
                        print(f"[REJECTED] スプレッド過大 ({current_spread} pips > {max_spread} pips). 見送り。")
                    
                    # 3. 単一ポジション限定チェック
                    elif risk_manager.enforce_single_pos and risk_manager.has_open_positions(symbol):
                        print(f"[REJECTED] 既に {symbol} のポジションを保有中。単ポジ厳守のため新規発注をブロック。")

                    else:
                        # 4. AI マクロNLPガード判定
                        macro_allowed, macro_reason = ai_guard.check_macro_safety(symbol)
                        if not macro_allowed:
                            print(f"[AI GUARD HALT] マクロ危険水準検知により発注停止: {macro_reason}")
                            # 通知は行わない（ユーザー要望により静観時の通知およびメッセージ作成を完全廃止）
                        else:
                            # 5. 適正ロットサイズの計算（動的ATR基準）
                            calc_lot = risk_manager.calculate_position_size(
                                sl_distance_pips=signal.sl_distance_pips,
                                pip_size=market_state["pip_size"]
                            )

                            # 6. 実発注執行（ブローカー側ハードSL/TP即時付与）
                            entry_price = market_state["current_ask"] if signal.action == "BUY" else market_state["current_bid"]
                            exec_result = mt5_client.execute_order(
                                action=signal.action,
                                volume=calc_lot,
                                price=entry_price,
                                sl_price=signal.suggested_sl_price,
                                tp_price=signal.suggested_tp_price
                            )

                            if exec_result:
                                last_signal_time = current_bar_time
                                signal_data = signal.model_dump()
                                signal_data["macro_reason"] = macro_reason
                                review_engine.log_trade_execution(exec_result, signal_data)
                                discord_mgr.send_execution_alert(exec_result, signal_data)

            # スキャン待機（15秒ごとにスキャン。CPU負荷を抑えつつ機会損失をゼロに）
            time.sleep(15)

        except KeyboardInterrupt:
            print("\n[STOP] ユーザーによる停止要求を受け付けました。")
            break
        except Exception as e:
            print(f"[CRITICAL LOOP ERROR] {e}")
            traceback.print_exc()
            time.sleep(10)

    mt5_client.disconnect()
    print("[SYSTEM STOPPED] MT5を切断し、システムを終了しました。")

if __name__ == "__main__":
    run_trading_daemon()
