import time
import datetime
import traceback
from config import settings
from core.mt5_client import RobustMT5Client
from core.data_engine import MarketDataEngine
from core.risk_manager import InstitutionalRiskManager
from core.webhook_server import MacroWebhookStore, TVWebhookServer
from core.macro_engine import DualMacroEngine
from strategies.smc_liquidity_strategy import SMCLiquiditySweepStrategy
from ai.macro_nlp_guard import MacroNLPGuard
from ai.committee_evaluator import AICommitteeEvaluator
from core.review_engine import ReviewEngine
from notifications.discord_manager import DiscordManager


def run_trading_daemon():
    """
    【VPS常駐型】24時間リアルタイム・クオンツ取引エンジン v9.0
    SMC 3トリガー ＋ 型A（コンフルエンス・マクロモメンタム）＋ 型B（SMTダイバージェンス）
    TradingView Webhook 主系 ＆ Exness MT5 M1 自動フェイルオーバー構成
    """
    print("==================================================================")
    print("🤖 Institutional SMC + Macro Hybrid Trading System v9.0 Starting...")
    print("==================================================================")

    # 1. パラメータの初期ロード
    params = settings.load_strategy_params()
    symbol = params.get("symbol", "XAUUSD")
    macro_cfg = params.get("macro_engine", {})

    # 2. TradingView Webhook 受信サーバー起動（バックグラウンド軽量スレッド）
    webhook_store = MacroWebhookStore(cache_path=settings.LOG_DIR / "tv_signals.json")
    webhook_port = int(macro_cfg.get("webhook_port", settings.TV_WEBHOOK_PORT))
    webhook_server = None
    if macro_cfg.get("enabled", True):
        webhook_server = TVWebhookServer(
            store=webhook_store,
            secret_token=settings.TV_WEBHOOK_TOKEN,
            host="0.0.0.0",
            port=webhook_port,
        )
        webhook_server.start()

    # 3. コアモジュールの初期化
    mt5_client = RobustMT5Client(
        symbol=symbol,
        login=settings.MT5_LOGIN,
        password=settings.MT5_PASSWORD,
        server=settings.MT5_SERVER,
        path=settings.MT5_PATH
    )
    data_engine = MarketDataEngine(symbol=symbol)
    macro_engine = DualMacroEngine(webhook_store=webhook_store, config=macro_cfg)
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
    print("[SYSTEM READY] 3系統ハイブリッド（SMC + 型Aマクロモメンタム + 型B SMT）スキャン開始...")

    last_hourly_report_hour = -1
    last_daily_review_day = -1
    last_signal_bar_time = None
    last_macro_entry_ts = 0.0
    last_logged_macro_source = None

    # Step 1: 同方向連続SL自滅防止ステート & 決済同期トラッカー
    last_loss_direction = None
    last_loss_time = None
    known_closed_deals = set()

    while True:
        try:
            now = datetime.datetime.now()
            # パラメータ動的リロード（相場急変時にファイルを編集すれば即反映）
            params = settings.load_strategy_params()
            exec_filters = params.get("execution_filters", {})
            max_spread = exec_filters.get("max_allowed_spread_pips", 3.0)
            strategy.sessions_config = exec_filters.get("allowed_sessions_jst", strategy.sessions_config)
            ai_guard.cache_ttl_minutes = params.get("ai_guard", {}).get("cache_ttl_minutes", 20)

            macro_cfg = params.get("macro_engine", {})
            macro_engine.update_config(macro_cfg)
            strategy.update_macro_config(macro_cfg)

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
                mt5_client.connect()
                time.sleep(5)
                continue

            # --- A-2. デュアル先行指標エンジン評価（TV主系 / MT5 M1自動フェイルオーバー） ---
            macro_state = {}
            if macro_cfg.get("enabled", True):
                macro_state = macro_engine.evaluate_macro_state(
                    df_xau_m1=market_state.get("df_m1"),
                    atr_m5_dollars=market_state.get("atr_m5_dollars", 1.5),
                )
                cur_src = macro_state.get("source", "NONE")
                if cur_src != last_logged_macro_source:
                    print(
                        f"🔄 [MACRO SOURCE ACTIVE] 現在の先行指標ソース: {cur_src} "
                        f"(DXY Z={macro_state.get('dxy_z', 0):+.2f}, Yield Z={macro_state.get('yield_z', 0):+.2f}, "
                        f"Bias={macro_state.get('macro_bias_score', 0):+.2f})"
                    )
                    last_logged_macro_source = cur_src
            market_state["macro_state"] = macro_state

            current_spread = market_state["spread_pips"]
            account_state = risk_manager.get_account_state()

            # --- B. サーキットブレーカー（日次最大損失）チェック ---
            can_trade_risk, risk_reason = risk_manager.check_circuit_breaker()
            if not can_trade_risk:
                print(f"[CIRCUIT BREAKER] {risk_reason}")
                discord_mgr.send_circuit_breaker_alert(risk_reason)
                time.sleep(300)
                continue

            # --- B-2. 【プロップファーム仕様】建値移動 (Break-Even) ＆ マクロ反転トレーリング防御 ---
            be_result = risk_manager.apply_break_even_protection(symbol, market_state["pip_size"])
            if be_result:
                print(f"[BREAK-EVEN TRIGGERED] {be_result}")

            trail_result = risk_manager.apply_macro_trailing_protection(
                symbol=symbol,
                pip_size=market_state["pip_size"],
                macro_state=macro_state,
                atr_m5_dollars=market_state.get("atr_m5_dollars", 1.5),
            )
            if trail_result:
                print(f"[MACRO TRAILING TRIGGERED] {trail_result}")

            # --- B-3. 決済検知 ＆ 損益同期 ＆ 同方向SLトラッキング ---
            try:
                from core.mt5_conn import mt5
                now_check = datetime.datetime.now()
                recent_deals = mt5.history_deals_get(now_check - datetime.timedelta(hours=2), now_check)
                if recent_deals:
                    for d in recent_deals:
                        if d.entry == 1 and d.ticket not in known_closed_deals:
                            known_closed_deals.add(d.ticket)
                            profit = getattr(d, 'profit', 0.0)
                            review_engine.log_trade_close(d.order, d.price, profit)
                            if profit < -500:
                                closed_dir = "SELL" if d.type == 0 else "BUY"
                                last_loss_direction = closed_dir
                                last_loss_time = now_check
                                print(f"[SL DETECTED] {closed_dir} が損切り決済 (-¥{abs(profit):,.0f})。同方向のエントリーを一時警戒。")
            except Exception:
                pass

            # --- C. 戦略シグナルの評価（3系統ハイブリッド: 型A + 型B + 既存SMC） ---
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
                now_ts = time.time()
                df_bar = market_state.get("df_m5") if market_state.get("df_m5") is not None else market_state.get("df_m15")
                current_bar_time = df_bar.iloc[-1]["time"] if df_bar is not None else None

                # 重複エントリー防止:
                # - SMCは同一M5バー内で1回まで
                # - 指標発信系（型A/型B）は直近エントリーから180秒のクールダウンで機動的かつ多重発注を防止
                if signal.entry_engine in ("MACRO_MOMENTUM", "SMT_DIVERGENCE"):
                    can_fire_dedup = (now_ts - last_macro_entry_ts) >= 180
                else:
                    can_fire_dedup = (current_bar_time != last_signal_bar_time)

                if can_fire_dedup:
                    print(
                        f"\n⚡ [SIGNAL DETECTED] [{signal.entry_engine}/{signal.macro_source}] "
                        f"{signal.action} - {signal.setup_name} (確信度: {signal.confidence * 100:.0f}%, ロット倍率: {signal.lot_multiplier:.2f}x)"
                    )

                    # 2. スプレッドフィルター（スリッページ防止・Exness異常拡大ゲート）
                    if current_spread > max_spread:
                        print(f"[REJECTED] スプレッド過大 ({current_spread} pips > {max_spread} pips). 正常化待機。")

                    # 3. 単一ポジション限定チェック
                    elif risk_manager.enforce_single_pos and risk_manager.has_open_positions(symbol):
                        print(f"[REJECTED] 既に {symbol} のポジションを保有中。単ポジ厳守のため新規発注をブロック。")

                    # 3-2. 同方向SL直後の連敗ループ防止（直前SLと同じ方向の場合、15分間は同方向エントリーを見送り）
                    elif (
                        last_loss_direction == signal.action
                        and last_loss_time is not None
                        and (datetime.datetime.now() - last_loss_time).total_seconds() < 900
                    ):
                        elapsed_s = int((datetime.datetime.now() - last_loss_time).total_seconds())
                        print(f"[REJECTED] 直前に {signal.action} でSL被弾 ({elapsed_s}秒前)。同方向の連打自滅を防止するため一時見送り。")

                    else:
                        # 4. AI マクロNLPガード判定（超省トークンTTL20分キャッシュ）
                        macro_allowed, macro_reason = ai_guard.check_macro_safety(symbol)
                        if not macro_allowed:
                            print(f"[AI GUARD HALT] マクロ危険水準検知により発注停止: {macro_reason}")
                        else:
                            # 5. 適正ロットサイズの計算（動的ATR基準 × マクロ強弱倍率）
                            calc_lot = risk_manager.calculate_position_size(
                                sl_distance_pips=signal.sl_distance_pips,
                                pip_size=market_state["pip_size"],
                                lot_multiplier=signal.lot_multiplier,
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
                                last_signal_bar_time = current_bar_time
                                if signal.entry_engine in ("MACRO_MOMENTUM", "SMT_DIVERGENCE"):
                                    last_macro_entry_ts = now_ts
                                    # TradingView由来のトリガーを消費済みにして二重発火を完全防止
                                    if signal.macro_source == "TV_WEBHOOK":
                                        kind = "momentum" if signal.entry_engine == "MACRO_MOMENTUM" else "smt"
                                        webhook_store.mark_consumed(kind)

                                signal_data = signal.model_dump()
                                signal_data["macro_reason"] = macro_reason
                                review_engine.log_trade_execution(exec_result, signal_data)
                                discord_mgr.send_execution_alert(exec_result, signal_data)

            # スキャン待機（15秒ごとにスキャン）
            time.sleep(15)

        except KeyboardInterrupt:
            print("\n[STOP] ユーザーによる停止要求を受け付けました。")
            break
        except Exception as e:
            print(f"[CRITICAL LOOP ERROR] {e}")
            traceback.print_exc()
            time.sleep(10)

    if webhook_server:
        webhook_server.stop()
    mt5_client.disconnect()
    print("[SYSTEM STOPPED] MT5を切断し、システムを終了しました。")


if __name__ == "__main__":
    run_trading_daemon()
