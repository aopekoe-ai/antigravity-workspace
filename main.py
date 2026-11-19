import time
import datetime
import traceback
from config import settings
from core.mt5_client import RobustMT5Client
from core.data_engine import MarketDataEngine
from core.risk_manager import InstitutionalRiskManager
from core.webhook_server import MacroWebhookStore, TVWebhookServer
from core.macro_engine import DualMacroEngine
from core.weekend_research_engine import WeekendResearchEngine
from strategies.smc_liquidity_strategy import SMCLiquiditySweepStrategy
from ai.macro_nlp_guard import MacroNLPGuard
from ai.committee_evaluator import AICommitteeEvaluator
from core.review_engine import ReviewEngine
from notifications.discord_manager import DiscordManager

JST = datetime.timezone(datetime.timedelta(hours=9))


def is_weekend_market_closed(now_utc: datetime.datetime) -> bool:
    """
    全市場休場判定（金曜 22:00 UTC [土曜 07:00 JST] 〜 日曜 22:00 UTC [月曜 07:00 JST]）
    休場中はトレード関連のDiscord定時通知・AI合議体呼び出しを完全停止する。
    """
    wd = now_utc.weekday()  # 0:Mon ... 4:Fri, 5:Sat, 6:Sun
    if wd == 4 and now_utc.hour >= 22:
        return True
    if wd == 5:
        return True
    if wd == 6 and now_utc.hour < 22:
        return True
    return False


def run_trading_daemon():
    """
    【VPS常駐型】24時間リアルタイム・クオンツ取引エンジン v9.1
    - 3系統ロジック別1ポジション（最大3ポジション）順張りピラミッディング対応
    - 6ブロック構成ヘッジファンド日次運用ブリーフィング（毎朝06:00 JST）
    - 週末クオンツ自動検証研究室 ＆ 土曜08:00 JST 検証結果Discord通知（休場中の毎時通知は完全停止）
    """
    print("==================================================================")
    print("🤖 Institutional SMC + Macro Hybrid Trading System v9.1 Starting...")
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
    weekend_lab = WeekendResearchEngine()
    risk_manager = InstitutionalRiskManager(params.get("risk_management", {}))
    strategy = SMCLiquiditySweepStrategy(params=params)
    ai_guard = MacroNLPGuard(cache_ttl_minutes=params.get("ai_guard", {}).get("cache_ttl_minutes", 20))
    committee_evaluator = AICommitteeEvaluator()
    review_engine = ReviewEngine()
    discord_mgr = DiscordManager()

    if not mt5_client.connect():
        print("[FATAL ERROR] MT5への初期接続に失敗しました。MT5が起動しているか確認してください。")
        return

    # 起動時に過去30日分のMT5決済履歴とジャーナルを完全突合＆ログローテーション保全
    review_engine.reconcile_with_mt5_history(days=30)
    review_engine.log_maintainer.run_maintenance()
    for rec in review_engine._load_journal():
        if rec.get("status") == "OPEN" and rec.get("order_id"):
            risk_manager.register_position_engine(rec.get("order_id"), rec.get("entry_engine", "SMC"))

    # 初回起動時に週末検証データ（weekend_macro_study.json）が未生成なら即座にベースライン検証を実行
    if not weekend_lab.study_file.exists():
        weekend_lab.run_weekend_study()

    print(f"[SYSTEM READY] 対象銘柄: {symbol}, 戦略: {strategy.name} (最大同時保有: {risk_manager.max_positions}ポジ/3系統)")
    print("[SYSTEM READY] 3系統ピラミッディング ＋ レジーム連動自己最適化 ＋ 週末検証ラボ 稼働開始...")

    last_hourly_report_hour = -1
    last_daily_review_day = -1
    last_weekend_study_date = None
    last_signal_bar_time = None
    last_macro_entry_ts = 0.0
    last_logged_macro_source = None
    last_logged_regime = None
    was_weekend_closed = False

    # Step 1: 同方向連続SL自滅防止ステート & 決済同期トラッカー
    last_loss_direction = None
    last_loss_time = None
    known_closed_deals = set()

    while True:
        try:
            now = datetime.datetime.now()
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            now_jst = now_utc.astimezone(JST)

            # --- 0. 土日の全市場休場ガード ＆ 週末クオンツ自動検証研究室（土曜08:00 JST Discord配信） ---
            if is_weekend_market_closed(now_utc):
                if not was_weekend_closed:
                    print(f"🌙 [WEEKEND MARKET CLOSED] 全市場休場モードへ移行 ({now_jst.strftime('%Y-%m-%d %H:%M JST')})。土日の毎時トレード通知を停止します。")
                    was_weekend_closed = True

                # 土曜朝（JST 08:00以降）に週1回の相関・複合条件・リードラグ自動検証を実行しDiscordへ配信
                today_jst_str = now_jst.strftime("%Y-%m-%d")
                if now_jst.weekday() == 5 and now_jst.hour >= 8 and last_weekend_study_date != today_jst_str:
                    study_res = weekend_lab.run_weekend_study()
                    weekly_stats = review_engine.get_weekly_summary()
                    discord_mgr.send_weekend_research_report(study_res, weekly_stats)
                    review_engine.log_maintainer.run_maintenance()
                    last_weekend_study_date = today_jst_str

                time.sleep(60)
                continue
            else:
                if was_weekend_closed:
                    print(f"🌅 [MARKET REOPENED] 週明け市場オープン検知 ({now_jst.strftime('%Y-%m-%d %H:%M JST')})。通常スキャンを再開します。")
                    was_weekend_closed = False

            # パラメータ動的リロード
            params = settings.load_strategy_params()
            exec_filters = params.get("execution_filters", {})
            max_spread = exec_filters.get("max_allowed_spread_pips", 3.0)
            strategy.sessions_config = exec_filters.get("allowed_sessions_jst", strategy.sessions_config)
            ai_guard.cache_ttl_minutes = params.get("ai_guard", {}).get("cache_ttl_minutes", 20)
            risk_manager.max_positions = int(params.get("risk_management", {}).get("max_concurrent_positions", 3))

            macro_cfg = dict(params.get("macro_engine", {}))
            base_dyn_params = review_engine.optimizer.load_active_params()
            if "momentum_z_threshold" in base_dyn_params:
                macro_cfg["momentum_z_threshold"] = base_dyn_params["momentum_z_threshold"]

            # 週末研究室で算出された最新相関ウェイト（DXY vs 米金利）を動的反映
            study_data = weekend_lab.load_latest_study()
            rec_weights = study_data.get("recommended_weights", {})
            if "dxy_weight" in rec_weights and "yield_weight" in rec_weights:
                macro_cfg["dxy_weight"] = rec_weights["dxy_weight"]
                macro_cfg["yield_weight"] = rec_weights["yield_weight"]

            macro_engine.update_config(macro_cfg)
            strategy.update_macro_config(macro_cfg)

            # --- A. 市場データ ＆ 特徴量の取得 ---
            market_state = data_engine.get_market_state(
                atr_period=params.get("volatility_parameters", {}).get("atr_period", 14)
            )
            if not market_state:
                mt5_client.connect()
                time.sleep(5)
                continue

            # 現在保有中のポジションが属するエンジン一覧を取得（まだ保有していない別エンジンのピラミッディング機会を解放）
            market_state["active_open_engines"] = risk_manager.get_open_engines(symbol)

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

            # --- A-3. Step 3: 先行指標レジーム連動リアルタイム自己最適化 ---
            active_regime, adapted_params = review_engine.optimizer.classify_and_adapt_regime(
                base_params=base_dyn_params,
                market_state=market_state,
                macro_state=macro_state,
            )
            strategy.update_dynamic_params(adapted_params)
            if "max_allowed_spread_pips" in adapted_params:
                max_spread = adapted_params["max_allowed_spread_pips"]

            if active_regime != last_logged_regime:
                print(
                    f"🎛️ [REGIME ADAPTED] 相場レジーム: {active_regime} "
                    f"(SMC_RR=1:{adapted_params.get('min_risk_reward_ratio')}, "
                    f"Macro_RR=1:{adapted_params.get('macro_min_rr')}, "
                    f"Mom_Z={adapted_params.get('momentum_z_threshold')}, "
                    f"ATR_Mult={adapted_params.get('atr_sl_multiplier')})"
                )
                last_logged_regime = active_regime

            current_spread = market_state["spread_pips"]
            account_state = risk_manager.get_account_state()

            # --- B. サーキットブレーカー（日次最大損失）チェック ---
            can_trade_risk, risk_reason = risk_manager.check_circuit_breaker()
            if not can_trade_risk:
                print(f"[CIRCUIT BREAKER] {risk_reason}")
                discord_mgr.send_circuit_breaker_alert(risk_reason)
                time.sleep(300)
                continue

            # --- B-2. 【複数ポジション個別対応】建値移動 (Break-Even) ＆ マクロ反転トレーリング防御 ---
            be_result = risk_manager.apply_break_even_protection(symbol, market_state["pip_size"])
            if be_result:
                print(f"[BREAK-EVEN TRIGGERED] {be_result}")
                review_engine.record_defense_event("break_even")

            trail_result = risk_manager.apply_macro_trailing_protection(
                symbol=symbol,
                pip_size=market_state["pip_size"],
                macro_state=macro_state,
                atr_m5_dollars=market_state.get("atr_m5_dollars", 1.5),
            )
            if trail_result:
                print(f"[MACRO TRAILING TRIGGERED] {trail_result}")
                review_engine.record_defense_event("macro_trailing")

            # --- B-3. 決済検知 ＆ 損益同期（position_id対応） ＆ 同方向SLトラッキング ---
            try:
                from core.mt5_conn import mt5
                now_check = datetime.datetime.now()
                recent_deals = mt5.history_deals_get(now_check - datetime.timedelta(hours=2), now_check + datetime.timedelta(hours=12))
                if recent_deals:
                    for d in recent_deals:
                        if d.entry == 1 and d.ticket not in known_closed_deals:
                            known_closed_deals.add(d.ticket)
                            net_profit = (
                                float(getattr(d, 'profit', 0.0))
                                + float(getattr(d, 'swap', 0.0))
                                + float(getattr(d, 'commission', 0.0))
                            )
                            review_engine.log_trade_close(
                                order_id=d.order,
                                close_price=d.price,
                                profit=net_profit,
                                position_id=getattr(d, 'position_id', None),
                            )
                            if net_profit < -500:
                                closed_dir = "SELL" if d.type == 0 else "BUY"
                                last_loss_direction = closed_dir
                                last_loss_time = now_check
                                print(f"[SL DETECTED] {closed_dir} が損切り決済 (-¥{abs(net_profit):,.0f})。同方向のエントリーを一時警戒。")
            except Exception:
                pass

            # --- C. 戦略シグナルの評価（3系統ハイブリッド: 未保有エンジンのみ評価してピラミッディング対応） ---
            signal = strategy.evaluate(market_state)
            if getattr(strategy, "last_hard_guard_blocked", False):
                review_engine.record_defense_event("hard_guard")

            # --- D. 毎時00分の定時レポート送信（※平日の市場オープン中のみ送信） ---
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

            # --- D-2. 毎朝06:00 JST（日次クローズ時）の6ブロック運用ブリーフィング送信（※日曜・月曜朝の空レビューは除外） ---
            if now_jst.hour == 6 and now_jst.day != last_daily_review_day and now_jst.weekday() not in (6, 0):
                print(f"[DAILY REVIEW TRIGGER] {now_jst.strftime('%Y-%m-%d %H:%M:%S JST')} - 6ブロック日次運用ブリーフィングを実行中...")
                eval_data = review_engine.generate_daily_review(
                    market_summary=f"Ask: ${market_state['current_ask']:.2f}, ATR: {market_state['atr_m15_pips']} pips, Regime: {active_regime}",
                    market_state=market_state,
                    active_regime=active_regime,
                )
                discord_mgr.send_daily_review_report(eval_data)
                last_daily_review_day = now_jst.day

            # --- E. シグナル発生時の発注判定（3系統別最大3ポジション・順張りピラミッディング） ---
            if signal.action in ["BUY", "SELL"]:
                now_ts = time.time()
                df_bar = market_state.get("df_m5") if market_state.get("df_m5") is not None else market_state.get("df_m15")
                current_bar_time = df_bar.iloc[-1]["time"] if df_bar is not None else None

                if signal.entry_engine in ("MACRO_MOMENTUM", "SMT_DIVERGENCE"):
                    can_fire_dedup = (now_ts - last_macro_entry_ts) >= 180
                else:
                    can_fire_dedup = (current_bar_time != last_signal_bar_time)

                if can_fire_dedup:
                    print(
                        f"\n⚡ [SIGNAL DETECTED] [{signal.entry_engine}/{signal.macro_source}/{active_regime}] "
                        f"{signal.action} - {signal.setup_name} (確信度: {signal.confidence * 100:.0f}%, ロット倍率: {signal.lot_multiplier:.2f}x)"
                    )

                    # 2. スプレッドフィルター
                    if current_spread > max_spread:
                        print(f"[REJECTED] スプレッド過大 ({current_spread} pips > {max_spread} pips). 正常化待機。")
                        review_engine.record_defense_event("spread_block")

                    else:
                        # 3. 3系統ロジック別1ポジション（最大3ポジ・両建て禁止・フリーロール判定）チェック
                        can_open_pos, pos_reason, pyramid_scale = risk_manager.check_can_open_position(
                            symbol=symbol,
                            action=signal.action,
                            entry_engine=signal.entry_engine,
                        )
                        if not can_open_pos:
                            print(f"[REJECTED] {pos_reason}")

                        # 3-2. 同方向SL直後の連敗ループ防止
                        elif (
                            last_loss_direction == signal.action
                            and last_loss_time is not None
                            and (datetime.datetime.now() - last_loss_time).total_seconds() < 900
                        ):
                            elapsed_s = int((datetime.datetime.now() - last_loss_time).total_seconds())
                            print(f"[REJECTED] 直前に {signal.action} でSL被弾 ({elapsed_s}秒前)。同方向の連打自滅を防止するため一時見送り。")
                            review_engine.record_defense_event("sl_cooldown")

                        else:
                            # 4. AI マクロNLPガード判定
                            macro_allowed, macro_reason = ai_guard.check_macro_safety(symbol)
                            if not macro_allowed:
                                print(f"[AI GUARD HALT] マクロ危険水準検知により発注停止: {macro_reason}")
                            else:
                                # 5. 適正ロットサイズの計算（動的ATR基準 × マクロ強弱倍率 × ピラミッディング安全係数）
                                effective_lot_mult = round(signal.lot_multiplier * pyramid_scale, 3)
                                calc_lot = risk_manager.calculate_position_size(
                                    sl_distance_pips=signal.sl_distance_pips,
                                    pip_size=market_state["pip_size"],
                                    lot_multiplier=effective_lot_mult,
                                )

                                # 6. 実発注執行（ブローカー側ハードSL/TP ＋ エンジン識別コメント即時付与）
                                entry_price = market_state["current_ask"] if signal.action == "BUY" else market_state["current_bid"]
                                order_comment = f"v9:{signal.entry_engine}"
                                exec_result = mt5_client.execute_order(
                                    action=signal.action,
                                    volume=calc_lot,
                                    price=entry_price,
                                    sl_price=signal.suggested_sl_price,
                                    tp_price=signal.suggested_tp_price,
                                    comment=order_comment,
                                )

                                if exec_result:
                                    risk_manager.register_position_engine(exec_result.get("order_id"), signal.entry_engine)
                                    if signal.entry_engine in ("MACRO_MOMENTUM", "SMT_DIVERGENCE"):
                                        last_macro_entry_ts = now_ts
                                        if signal.macro_source == "TV_WEBHOOK":
                                            kind = "momentum" if signal.entry_engine == "MACRO_MOMENTUM" else "smt"
                                            webhook_store.mark_consumed(kind)
                                    else:
                                        last_signal_bar_time = current_bar_time

                                    signal_data = signal.model_dump()
                                    signal_data["lot_multiplier"] = effective_lot_mult
                                    signal_data["macro_reason"] = macro_reason
                                    signal_data["active_regime"] = active_regime
                                    signal_data["pyramid_reason"] = pos_reason
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
