import datetime
import json
import threading
import time
import traceback
from typing import Any, Dict

from config import settings
from core.mt5_client import RobustMT5Client
from core.data_engine import MarketDataEngine
from core.risk_manager import InstitutionalRiskManager
from core.webhook_server import MacroWebhookStore, TVWebhookServer
from core.macro_engine import DualMacroEngine
from core.weekend_research_engine import WeekendResearchEngine
from core.quant_db import QuantDatabase
from strategies.smc_liquidity_strategy import SMCLiquiditySweepStrategy
from ai.macro_nlp_guard import MacroNLPGuard
from ai.committee_evaluator import AICommitteeEvaluator
from core.review_engine import ReviewEngine
from notifications.discord_manager import DiscordManager

JST = datetime.timezone(datetime.timedelta(hours=9))


def is_weekend_market_closed(now_utc: datetime.datetime) -> bool:
    """全市場休場判定（金曜 22:00 UTC [土曜 07:00 JST] 〜 日曜 22:00 UTC [月曜 07:00 JST]）"""
    wd = now_utc.weekday()
    if wd == 4 and now_utc.hour >= 22:
        return True
    if wd == 5:
        return True
    if wd == 6 and now_utc.hour < 22:
        return True
    return False


def _build_sessions_from_controls(dash_ctrl: Dict[str, Any]):
    sessions = []
    if dash_ctrl.get("session_asia", True):
        sessions.append({"name": "Asia", "start_hour": 8, "end_hour": 15})
    if dash_ctrl.get("session_london", True):
        sessions.append({"name": "London_Pre", "start_hour": 15, "end_hour": 16})
        sessions.append({"name": "London", "start_hour": 16, "end_hour": 24})
    if dash_ctrl.get("session_ny", True):
        sessions.append({"name": "NewYork", "start_hour": 21, "end_hour": 6})
    return sessions


def run_trading_daemon():
    """
    【VPS常駐型】24時間リアルタイム・クオンツ取引エンジン v9.2
    - 3系統ロジック別1ポジション（最大3ポジション）順張りピラミッディング
    - SQLite WAL 時系列DB ＆ シャドートレード（見送りシグナル）自動採点 ＆ What-If高速バックテスト
    - スマホ＆PC対応 4タブ運用Webダッシュボード（ロジック改修方針・通知設定・MT5証券会社/口座切替）
    """
    print("==================================================================")
    print("🤖 Institutional SMC + Macro Hybrid Trading System v9.2 Starting...")
    print("==================================================================")

    mt5_lock = threading.RLock()
    state_lock = threading.Lock()

    params = settings.load_strategy_params()
    symbol = params.get("symbol", "XAUUSD")
    macro_cfg = params.get("macro_engine", {})

    mt5_client = RobustMT5Client(
        symbol=symbol,
        login=settings.MT5_LOGIN,
        password=settings.MT5_PASSWORD,
        server=settings.MT5_SERVER,
        path=settings.MT5_PATH
    )
    symbol = mt5_client.symbol
    data_engine = MarketDataEngine(symbol=symbol)
    webhook_store = MacroWebhookStore(cache_path=settings.LOG_DIR / "tv_signals.json")
    macro_engine = DualMacroEngine(webhook_store=webhook_store, config=macro_cfg)
    weekend_lab = WeekendResearchEngine()
    quant_db = QuantDatabase(db_path=settings.LOG_DIR / "quant_fund.db")
    risk_manager = InstitutionalRiskManager(params.get("risk_management", {}))
    strategy = SMCLiquiditySweepStrategy(params=params)
    ai_guard = MacroNLPGuard(cache_ttl_minutes=params.get("ai_guard", {}).get("cache_ttl_minutes", 20))
    committee_evaluator = AICommitteeEvaluator()
    review_engine = ReviewEngine()
    discord_mgr = DiscordManager()

    # ダッシュボード表示用オンメモリスナップショット
    live_cache: Dict[str, Any] = {
        "market": {},
        "macro": {},
        "broker": {},
        "open_positions": [],
        "active_regime": "REGIME_NORMAL_FLOW",
    }

    def handle_dashboard_api(method: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """ダッシュボードからのGET/POST APIリクエストをスレッドセーフに処理"""
        if method == "GET" and path == "/api/state":
            cur_params = settings.load_strategy_params()
            dyn_params = review_engine.optimizer.load_active_params()
            rm_cfg = cur_params.get("risk_management", {})
            ex_cfg = cur_params.get("execution_filters", {})
            d_ctrl = cur_params.get("dashboard_controls", {})

            with state_lock:
                mkt_snap = dict(live_cache.get("market") or {})
                mac_snap = dict(live_cache.get("macro") or {})
                brk_snap = dict(live_cache.get("broker") or {})
                pos_snap = list(live_cache.get("open_positions") or [])
                reg_snap = str(live_cache.get("active_regime", "REGIME_NORMAL_FLOW"))

            today_m = review_engine._compute_metrics_block(review_engine.get_today_trades())
            week_m = review_engine._compute_metrics_block(review_engine._filter_trades_since_hours(24 * 7))
            recent_trades = list(reversed(review_engine._load_journal()[-30:]))

            # ライブ適用中の仕様値（M5 ATR連動の実効値＋レジーム適応後の実効値）を算出
            atr_d = float(mkt_snap.get("atr_m5_dollars") or 2.0)
            _, adapted_now = review_engine.optimizer.classify_and_adapt_regime(
                base_params=dyn_params,
                market_state=mkt_snap,
                macro_state=mac_snap,
            )
            w_study = weekend_lab.load_latest_study()
            rec_w = w_study.get("recommended_weights") or {}
            live_spec = {
                "effective_min_sl_pips": max(18.0, round((atr_d * 1.0) / 0.10, 1)),
                "effective_max_sl_pips": max(50.0, round((atr_d * 3.5) / 0.10, 1)),
                "effective_min_fvg_gap": max(0.40, round(atr_d * 0.30, 2)),
                "effective_momentum_z_threshold": adapted_now.get("momentum_z_threshold", 1.50),
                "effective_macro_sl_atr_mult": adapted_now.get("macro_sl_atr_multiplier", 1.70),
                "effective_macro_min_rr": adapted_now.get("macro_min_rr", 1.80),
                "effective_smt_min_rr": adapted_now.get("smt_min_rr", 2.00),
                "effective_smc_min_rr": adapted_now.get("min_risk_reward_ratio", 1.50),
                "effective_wick_ratio": adapted_now.get("wick_ratio_threshold", 0.25),
                "effective_atr_sl_mult": adapted_now.get("atr_sl_multiplier", 1.30),
                "dxy_weight": rec_w.get("dxy_weight", 0.70),
                "yield_weight": rec_w.get("yield_weight", 0.30),
            }

            # 日々のロジック変更＆自己最適化履歴の抽出
            opt_history = []
            try:
                raw_dp_path = review_engine.optimizer.params_file
                if raw_dp_path.exists():
                    raw_dp = json.loads(raw_dp_path.read_text(encoding="utf-8"))
                    opt_history.append({
                        "title": f"🎛️ 動的パラメータ最適化 v{raw_dp.get('version', 1)} ({raw_dp.get('last_updated', '')})",
                        "badge": f"Regime: {reg_snap.replace('REGIME_', '')}",
                        "detail": (
                            f"変更根拠: {raw_dp.get('reason', '日次自動較正')}\n"
                            f"現在ベース値: 型A_Z閾値={dyn_params.get('momentum_z_threshold')}σ / 型A_RR=1:{dyn_params.get('macro_min_rr')} / "
                            f"型B_RR=1:{dyn_params.get('smt_min_rr')} / SMC_RR=1:{dyn_params.get('min_risk_reward_ratio')} / "
                            f"ヒゲ比率={dyn_params.get('wick_ratio_threshold')} / FVG最小ギャップ=${dyn_params.get('min_fvg_gap_dollars')} / ATR倍率={dyn_params.get('atr_sl_multiplier')}"
                        ),
                    })
                if review_engine.learning_file.exists():
                    lj_txt = review_engine.learning_file.read_text(encoding="utf-8")
                    for sec in reversed(lj_txt.split("\n### 📅 ")[1:]):
                        lines = [ln.strip() for ln in sec.strip().splitlines() if ln.strip()]
                        if lines:
                            opt_history.append({
                                "title": f"📅 {lines[0]}",
                                "badge": "日次PDCA教訓・最適化ログ",
                                "detail": "\n".join(lines[1:6]),
                            })
                        if len(opt_history) >= 12:
                            break
            except Exception:
                pass

            return {
                "market": mkt_snap,
                "macro": mac_snap,
                "broker": brk_snap,
                "open_positions": pos_snap,
                "active_regime": reg_snap,
                "max_positions": risk_manager.max_positions,
                "live_spec": live_spec,
                "optimization_history": opt_history,
                "today_metrics": today_m,
                "weekly_metrics": week_m,
                "recent_trades": recent_trades,
                "shadow_scorecard": quant_db.get_shadow_scorecard(days=7),
                "weekend_study": w_study,
                "m1_series": quant_db.get_recent_macro_series(limit=90),
                "dynamic_params": dyn_params,
                "control_config": {
                    "stance": d_ctrl.get("stance", "BALANCED"),
                    "trading_paused": d_ctrl.get("trading_paused", False),
                    "enable_type_a": d_ctrl.get("enable_type_a", True),
                    "enable_type_b": d_ctrl.get("enable_type_b", True),
                    "enable_smc": d_ctrl.get("enable_smc", True),
                    "session_asia": d_ctrl.get("session_asia", True),
                    "session_london": d_ctrl.get("session_london", True),
                    "session_ny": d_ctrl.get("session_ny", True),
                    "max_concurrent_positions": rm_cfg.get("max_concurrent_positions", 3),
                    "risk_per_trade_percent": rm_cfg.get("risk_per_trade_percent", 1.5),
                    "max_daily_drawdown_percent": rm_cfg.get("max_daily_drawdown_percent", 3.0),
                    "max_lot_size": rm_cfg.get("max_lot_size", 0.50),
                    "max_allowed_spread_pips": ex_cfg.get("max_allowed_spread_pips", 3.0),
                    "sl_cooldown_minutes": d_ctrl.get("sl_cooldown_minutes", 15),
                    "owner_directive_ja": d_ctrl.get("owner_directive_ja", ""),
                    "notify_hourly": d_ctrl.get("notify_hourly", True),
                    "notify_weekend": d_ctrl.get("notify_weekend", True),
                    "daily_report_hour_jst": d_ctrl.get("daily_report_hour_jst", 6),
                },
            }

        if method == "POST" and path == "/api/control/stance":
            stance = str(payload.get("stance", "BALANCED")).upper()
            cur_params = settings.load_strategy_params()
            d_ctrl = cur_params.setdefault("dashboard_controls", {})
            rm_cfg = cur_params.setdefault("risk_management", {})
            mac_c = cur_params.setdefault("macro_engine", {})
            d_ctrl["stance"] = stance

            if stance == "AGGRESSIVE":
                d_ctrl["trading_paused"] = False
                rm_cfg["max_concurrent_positions"] = 3
                mac_c["momentum_z_threshold"] = 1.35
                review_engine.optimizer.apply_optimization(
                    {"momentum_z_threshold": 1.35, "wick_ratio_threshold": 0.23, "macro_min_rr": 2.0},
                    reason="ダッシュボード操作: 積極トレンド追撃モード切替",
                    date_str=datetime.datetime.now().strftime("%Y-%m-%d"),
                )
            elif stance == "DEFENSIVE":
                d_ctrl["trading_paused"] = False
                rm_cfg["max_concurrent_positions"] = 1
                mac_c["momentum_z_threshold"] = 1.70
                review_engine.optimizer.apply_optimization(
                    {"momentum_z_threshold": 1.65, "wick_ratio_threshold": 0.30, "min_risk_reward_ratio": 1.5},
                    reason="ダッシュボード操作: 厳選・資金防衛モード切替",
                    date_str=datetime.datetime.now().strftime("%Y-%m-%d"),
                )
            elif stance == "PAUSED":
                d_ctrl["trading_paused"] = True
            else:  # BALANCED
                d_ctrl["trading_paused"] = False
                rm_cfg["max_concurrent_positions"] = 3
                mac_c["momentum_z_threshold"] = 1.50
                review_engine.optimizer.apply_optimization(
                    {"momentum_z_threshold": 1.50, "wick_ratio_threshold": 0.25, "macro_min_rr": 1.8},
                    reason="ダッシュボード操作: 標準バランスモード切替",
                    date_str=datetime.datetime.now().strftime("%Y-%m-%d"),
                )

            settings.save_strategy_params(cur_params)
            risk_manager.max_positions = int(rm_cfg.get("max_concurrent_positions", 3))
            return {"success": True, "message": f"運用スタンスを [{stance}] に切り替えました"}

        if method == "POST" and path == "/api/control/params":
            cur_params = settings.load_strategy_params()
            d_ctrl = cur_params.setdefault("dashboard_controls", {})
            rm_cfg = cur_params.setdefault("risk_management", {})
            ex_cfg = cur_params.setdefault("execution_filters", {})
            mac_c = cur_params.setdefault("macro_engine", {})

            for b_key in ("enable_type_a", "enable_type_b", "enable_smc", "session_asia", "session_london", "session_ny", "notify_hourly", "notify_weekend"):
                if b_key in payload:
                    d_ctrl[b_key] = bool(payload[b_key])

            if "owner_directive_ja" in payload:
                d_ctrl["owner_directive_ja"] = str(payload["owner_directive_ja"])
            if "sl_cooldown_minutes" in payload:
                d_ctrl["sl_cooldown_minutes"] = max(1, min(120, int(payload["sl_cooldown_minutes"])))
            if "daily_report_hour_jst" in payload:
                d_ctrl["daily_report_hour_jst"] = max(0, min(23, int(payload["daily_report_hour_jst"])))

            if "max_concurrent_positions" in payload:
                rm_cfg["max_concurrent_positions"] = max(1, min(3, int(payload["max_concurrent_positions"])))
                risk_manager.max_positions = rm_cfg["max_concurrent_positions"]
            if "risk_per_trade_percent" in payload:
                rm_cfg["risk_per_trade_percent"] = max(0.2, min(3.5, float(payload["risk_per_trade_percent"])))
                risk_manager.risk_per_trade_pct = rm_cfg["risk_per_trade_percent"]
            if "max_daily_drawdown_percent" in payload:
                rm_cfg["max_daily_drawdown_percent"] = max(1.0, min(8.0, float(payload["max_daily_drawdown_percent"])))
                risk_manager.max_daily_dd_pct = rm_cfg["max_daily_drawdown_percent"]
            if "max_lot_size" in payload:
                rm_cfg["max_lot_size"] = max(0.01, min(2.0, float(payload["max_lot_size"])))
                risk_manager.max_lot = rm_cfg["max_lot_size"]
            if "max_allowed_spread_pips" in payload:
                ex_cfg["max_allowed_spread_pips"] = max(1.0, min(5.0, float(payload["max_allowed_spread_pips"])))

            ex_cfg["allowed_sessions_jst"] = _build_sessions_from_controls(d_ctrl)

            # What-If バックテストからの直接パラメータ反映
            dyn_updates = {}
            for dk in ("momentum_z_threshold", "macro_min_rr", "min_risk_reward_ratio", "atr_sl_multiplier", "wick_ratio_threshold"):
                if dk in payload:
                    dyn_updates[dk] = float(payload[dk])
                    if dk in ("momentum_z_threshold", "macro_min_rr"):
                        mac_c[dk] = float(payload[dk])
            if dyn_updates:
                review_engine.optimizer.apply_optimization(
                    dyn_updates,
                    reason="ダッシュボード What-If シミュレーション設定の本番適用",
                    date_str=datetime.datetime.now().strftime("%Y-%m-%d"),
                )

            settings.save_strategy_params(cur_params)
            return {"success": True, "message": "設定・改修方針を保存しました（即座にBOTへ反映）"}

        if method == "POST" and path == "/api/control/position":
            act = str(payload.get("action", ""))
            with mt5_lock:
                if act == "close_ticket" and payload.get("ticket"):
                    r = mt5_client.close_position_by_ticket(int(payload["ticket"]))
                    msg = f"ポジション #{payload['ticket']} を決済しました" if r.get("success") else r.get("error", "決済失敗")
                elif act == "close_all":
                    r = mt5_client.close_all_positions()
                    msg = f"全ポジション ({r.get('closed_count', 0)}件) を一括決済しました"
                elif act == "lock_be_all":
                    r = mt5_client.lock_break_even_all(pip_size=0.10)
                    msg = f"含み益ポジション ({r.get('locked_count', 0)}件) のSLを建値ロックしました"
                else:
                    return {"success": False, "message": "不明なポジション操作です"}

                # スナップショット即時更新
                with state_lock:
                    live_cache["open_positions"] = mt5_client.get_open_positions_detail(risk_manager.ticket_engine_map)
                    live_cache["broker"] = mt5_client.get_broker_info()
            return {"success": bool(r.get("success", True)), "message": msg, "detail": r}

        if method == "POST" and path == "/api/control/broker":
            login = int(payload.get("login", 0))
            server = str(payload.get("server", "")).strip()
            password = str(payload.get("password", ""))
            sym = str(payload.get("symbol", "")).strip()
            with mt5_lock:
                res = mt5_client.switch_account_live(login=login, password=password, server=server, symbol=sym)
                if res.get("success"):
                    new_sym = res.get("active_symbol", "XAUUSD")
                    data_engine.symbol = new_sym
                    cur_params = settings.load_strategy_params()
                    cur_params["symbol"] = new_sym
                    if res.get("detected_symbols"):
                        det = res["detected_symbols"]
                        cur_params.setdefault("macro_engine", {})["mt5_symbols"] = {
                            "dxy": det.get("dxy", "DXY"),
                            "yield_proxy": det.get("yield_proxy", "USDJPY"),
                            "oil": det.get("oil", "USOIL"),
                            "equity": det.get("equity", "USTEC"),
                            "aud": det.get("aud", "AUDUSD"),
                        }
                    settings.save_strategy_params(cur_params)
                    with state_lock:
                        live_cache["broker"] = mt5_client.get_broker_info()
                        live_cache["open_positions"] = mt5_client.get_open_positions_detail(risk_manager.ticket_engine_map)
            return res

        if method == "POST" and path == "/api/lab/backtest":
            trades = review_engine._load_journal()
            return quant_db.run_what_if_backtest(
                journal_trades=trades,
                z_thresh=float(payload.get("z_thresh", 1.5)),
                macro_rr=float(payload.get("macro_rr", 1.8)),
                smc_rr=float(payload.get("smc_rr", 1.5)),
                atr_sl_mult=float(payload.get("atr_sl_mult", 1.3)),
                max_pos=int(payload.get("max_pos", 3)),
                days=int(payload.get("days", 14)),
            )

        if method == "POST" and path == "/api/lab/trigger":
            task = str(payload.get("task", ""))
            with mt5_lock:
                if task == "daily_report":
                    with state_lock:
                        mkt_s = dict(live_cache.get("market") or {})
                        reg_s = str(live_cache.get("active_regime", "REGIME_NORMAL_FLOW"))
                    eval_d = review_engine.generate_daily_review(
                        market_summary="ダッシュボードからの手動レポート配信",
                        market_state=mkt_s,
                        active_regime=reg_s,
                    )
                    discord_mgr.send_daily_review_report(eval_d)
                    return {"success": True, "message": "6ブロック日次運用ブリーフィングをDiscordへ送信しました！"}
                elif task == "weekend_study":
                    study_res = weekend_lab.run_weekend_study()
                    w_stats = review_engine.get_weekly_summary()
                    discord_mgr.send_weekend_research_report(study_res, w_stats)
                    return {"success": True, "message": "最新相関・リードラグ検証を実行しDiscordへ送信しました！"}
            return {"success": False, "message": "不明なタスクです"}

        return {"error": "unknown_route"}

    # TradingView Webhook ＆ Webダッシュボードサーバー起動
    webhook_port = int(macro_cfg.get("webhook_port", settings.TV_WEBHOOK_PORT))
    webhook_server = TVWebhookServer(
        store=webhook_store,
        secret_token=settings.TV_WEBHOOK_TOKEN,
        dashboard_key=settings.DASHBOARD_KEY,
        api_dispatcher=handle_dashboard_api,
        host="0.0.0.0",
        port=webhook_port,
    )
    webhook_server.start()

    with mt5_lock:
        if not mt5_client.connect():
            print("[FATAL ERROR] MT5への初期接続に失敗しました。MT5が起動しているか確認してください。")
            return

        review_engine.reconcile_with_mt5_history(days=30)
        review_engine.log_maintainer.run_maintenance()
        for rec in review_engine._load_journal():
            if rec.get("status") == "OPEN" and rec.get("order_id"):
                risk_manager.register_position_engine(rec.get("order_id"), rec.get("entry_engine", "SMC"))

        if not weekend_lab.study_file.exists():
            weekend_lab.run_weekend_study()

        init_state = data_engine.get_market_state()
        if init_state and init_state.get("df_m1") is not None:
            quant_db.seed_from_mt5_m1(
                init_state["df_m1"],
                h1_trend=init_state.get("h1_trend", "NEUTRAL"),
                m15_trend=init_state.get("m15_trend", "NEUTRAL"),
                atr_m5=init_state.get("atr_m5_dollars", 2.0),
            )

    print(f"[SYSTEM READY] 対象銘柄: {mt5_client.symbol}, 戦略: {strategy.name} (最大同時保有: {risk_manager.max_positions}ポジ/3系統)")
    print(f"📱 [DASHBOARD URL] {settings.get_dashboard_url()}")

    last_hourly_report_hour = -1
    last_daily_review_day = -1
    last_weekend_study_date = None
    last_signal_bar_time = None
    last_macro_entry_ts = 0.0
    last_logged_macro_source = None
    last_logged_regime = None
    was_weekend_closed = False

    last_loss_direction = None
    last_loss_time = None
    known_closed_deals = set()

    while True:
        try:
            now = datetime.datetime.now()
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            now_jst = now_utc.astimezone(JST)

            params = settings.load_strategy_params()
            dash_ctrl = params.get("dashboard_controls") or {}
            notify_hourly = dash_ctrl.get("notify_hourly", True)
            notify_weekend = dash_ctrl.get("notify_weekend", True)
            daily_report_hour_jst = int(dash_ctrl.get("daily_report_hour_jst", 6))
            sl_cooldown_sec = int(dash_ctrl.get("sl_cooldown_minutes", 15)) * 60

            # --- 0. 土日の全市場休場ガード ＆ 週末クオンツ自動検証研究室 ---
            if is_weekend_market_closed(now_utc):
                if not was_weekend_closed:
                    print(f"🌙 [WEEKEND MARKET CLOSED] 全市場休場モードへ移行 ({now_jst.strftime('%Y-%m-%d %H:%M JST')})。土日の毎時トレード通知を停止します。")
                    was_weekend_closed = True

                today_jst_str = now_jst.strftime("%Y-%m-%d")
                if now_jst.weekday() == 5 and now_jst.hour >= 8 and last_weekend_study_date != today_jst_str:
                    with mt5_lock:
                        study_res = weekend_lab.run_weekend_study()
                        weekly_stats = review_engine.get_weekly_summary()
                        if notify_weekend:
                            discord_mgr.send_weekend_research_report(study_res, weekly_stats)
                        review_engine.log_maintainer.run_maintenance()
                        quant_db.prune_old_records(keep_days=90)
                    last_weekend_study_date = today_jst_str

                time.sleep(60)
                continue
            else:
                if was_weekend_closed:
                    print(f"🌅 [MARKET REOPENED] 週明け市場オープン検知 ({now_jst.strftime('%Y-%m-%d %H:%M JST')})。通常スキャンを再開します。")
                    was_weekend_closed = False

            symbol = mt5_client.symbol
            data_engine.symbol = symbol
            exec_filters = params.get("execution_filters", {})
            max_spread = exec_filters.get("max_allowed_spread_pips", 3.0)
            strategy.sessions_config = _build_sessions_from_controls(dash_ctrl) or exec_filters.get("allowed_sessions_jst", strategy.sessions_config)
            ai_guard.cache_ttl_minutes = params.get("ai_guard", {}).get("cache_ttl_minutes", 20)

            rm_cfg = params.get("risk_management", {})
            risk_manager.max_positions = int(rm_cfg.get("max_concurrent_positions", 3))
            risk_manager.risk_per_trade_pct = float(rm_cfg.get("risk_per_trade_percent", 1.5))
            risk_manager.max_daily_dd_pct = float(rm_cfg.get("max_daily_drawdown_percent", 3.0))
            risk_manager.max_lot = float(rm_cfg.get("max_lot_size", 0.50))

            macro_cfg = dict(params.get("macro_engine", {}))
            base_dyn_params = review_engine.optimizer.load_active_params()
            if "momentum_z_threshold" in base_dyn_params:
                macro_cfg["momentum_z_threshold"] = base_dyn_params["momentum_z_threshold"]

            study_data = weekend_lab.load_latest_study()
            rec_weights = study_data.get("recommended_weights", {})
            if "dxy_weight" in rec_weights and "yield_weight" in rec_weights:
                macro_cfg["dxy_weight"] = rec_weights["dxy_weight"]
                macro_cfg["yield_weight"] = rec_weights["yield_weight"]

            macro_engine.update_config(macro_cfg)
            strategy.update_macro_config(macro_cfg)

            with mt5_lock:
                # --- A. 市場データ ＆ 特徴量の取得 ---
                market_state = data_engine.get_market_state(
                    atr_period=params.get("volatility_parameters", {}).get("atr_period", 14)
                )
                if not market_state:
                    mt5_client.connect()
                    time.sleep(5)
                    continue

                market_state["active_open_engines"] = risk_manager.get_open_engines(symbol)
                market_state["dashboard_controls"] = dash_ctrl

                # --- A-2. デュアル先行指標エンジン評価 ---
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

                if active_regime != last_logged_regime:
                    print(
                        f"🎛️ [REGIME ADAPTED] 相場レジーム: {active_regime} "
                        f"(SMC_RR=1:{adapted_params.get('min_risk_reward_ratio')}, "
                        f"Macro_RR=1:{adapted_params.get('macro_min_rr')}, "
                        f"Mom_Z={adapted_params.get('momentum_z_threshold')}, "
                        f"ATR_Mult={adapted_params.get('atr_sl_multiplier')})"
                    )
                    last_logged_regime = active_regime

                # --- A-4. SQLite 時系列DBへの1分足記録 ＆ シャドートレード自動採点 ---
                quant_db.record_minute_snapshot(market_state, macro_state, active_regime)
                quant_db.evaluate_pending_shadows(
                    current_bid=market_state["current_bid"],
                    current_ask=market_state["current_ask"],
                )

                current_spread = market_state["spread_pips"]
                account_state = risk_manager.get_account_state()
                open_pos_detail = mt5_client.get_open_positions_detail(risk_manager.ticket_engine_map)
                brk_info = mt5_client.get_broker_info()

                with state_lock:
                    live_cache["market"] = {
                        "symbol": market_state.get("symbol"),
                        "current_ask": market_state.get("current_ask"),
                        "current_bid": market_state.get("current_bid"),
                        "spread_pips": market_state.get("spread_pips"),
                        "atr_m5_dollars": market_state.get("atr_m5_dollars"),
                        "atr_m15_pips": market_state.get("atr_m15_pips"),
                        "h1_trend": market_state.get("h1_trend"),
                        "m15_trend": market_state.get("m15_trend"),
                        "pdh": market_state.get("pdh"),
                        "pdl": market_state.get("pdl"),
                        "asia_high": market_state.get("asia_high"),
                        "asia_low": market_state.get("asia_low"),
                    }
                    live_cache["macro"] = macro_state
                    live_cache["broker"] = brk_info
                    live_cache["open_positions"] = open_pos_detail
                    live_cache["active_regime"] = active_regime

                # --- B. サーキットブレーカーチェック ---
                can_trade_risk, risk_reason = risk_manager.check_circuit_breaker()
                if not can_trade_risk:
                    print(f"[CIRCUIT BREAKER] {risk_reason}")
                    discord_mgr.send_circuit_breaker_alert(risk_reason)
                    time.sleep(300)
                    continue

                # --- B-2. 建値移動 (Break-Even) ＆ マクロ反転トレーリング防御 ---
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

                # --- B-3. 決済検知 ＆ 損益同期 ＆ 同方向SLトラッキング ---
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

                # --- C. 戦略シグナルの評価 ---
                signal = strategy.evaluate(market_state)
                if getattr(strategy, "last_hard_guard_blocked", False):
                    review_engine.record_defense_event("hard_guard")
                    bc = getattr(strategy, "last_blocked_candidate", None)
                    if bc:
                        quant_db.record_shadow_trade(
                            action=bc.action,
                            entry_engine=bc.entry_engine,
                            setup_name=bc.setup_name,
                            block_reason="MACRO_HARD_GUARD",
                            entry_price=bc.suggested_entry_price,
                            sl_price=bc.suggested_sl_price,
                            tp_price=bc.suggested_tp_price,
                            sl_pips=bc.sl_distance_pips,
                            tp_pips=bc.tp_distance_pips,
                        )

                # --- D. 毎時00分の定時レポート送信 ---
                if notify_hourly and now.minute == 0 and now.hour != last_hourly_report_hour:
                    print(f"[HOURLY REPORT TRIGGER] {now.strftime('%Y-%m-%d %H:%M:%S')}")
                    active_session = strategy.get_active_session() or "Interbank_OffHours"
                    committee_report = committee_evaluator.evaluate_hourly(
                        market_state=market_state,
                        signal=signal,
                        account_state=account_state,
                        active_session=active_session
                    )
                    discord_mgr.send_hourly_status(market_state, signal, account_state, committee_report=committee_report)
                    last_hourly_report_hour = now.hour

                # --- D-2. 日次運用ブリーフィング送信（デフォルト06:00 JST、画面から変更可） ---
                if now_jst.hour == daily_report_hour_jst and now_jst.day != last_daily_review_day and now_jst.weekday() not in (6, 0):
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

                        if current_spread > max_spread:
                            print(f"[REJECTED] スプレッド過大 ({current_spread} pips > {max_spread} pips). 正常化待機。")
                            review_engine.record_defense_event("spread_block")
                            quant_db.record_shadow_trade(
                                action=signal.action, entry_engine=signal.entry_engine, setup_name=signal.setup_name,
                                block_reason="SPREAD_GATE", entry_price=signal.suggested_entry_price,
                                sl_price=signal.suggested_sl_price, tp_price=signal.suggested_tp_price,
                                sl_pips=signal.sl_distance_pips, tp_pips=signal.tp_distance_pips,
                            )

                        else:
                            can_open_pos, pos_reason, pyramid_scale = risk_manager.check_can_open_position(
                                symbol=symbol,
                                action=signal.action,
                                entry_engine=signal.entry_engine,
                            )
                            if not can_open_pos:
                                print(f"[REJECTED] {pos_reason}")

                            elif (
                                last_loss_direction == signal.action
                                and last_loss_time is not None
                                and (datetime.datetime.now() - last_loss_time).total_seconds() < sl_cooldown_sec
                            ):
                                elapsed_s = int((datetime.datetime.now() - last_loss_time).total_seconds())
                                print(f"[REJECTED] 直前に {signal.action} でSL被弾 ({elapsed_s}秒前)。同方向の連打自滅を防止するため一時見送り。")
                                review_engine.record_defense_event("sl_cooldown")
                                quant_db.record_shadow_trade(
                                    action=signal.action, entry_engine=signal.entry_engine, setup_name=signal.setup_name,
                                    block_reason="SL_COOLDOWN", entry_price=signal.suggested_entry_price,
                                    sl_price=signal.suggested_sl_price, tp_price=signal.suggested_tp_price,
                                    sl_pips=signal.sl_distance_pips, tp_pips=signal.tp_distance_pips,
                                )

                            else:
                                macro_allowed, macro_reason = ai_guard.check_macro_safety(symbol)
                                if not macro_allowed:
                                    print(f"[AI GUARD HALT] マクロ危険水準検知により発注停止: {macro_reason}")
                                else:
                                    effective_lot_mult = round(signal.lot_multiplier * pyramid_scale, 3)
                                    calc_lot = risk_manager.calculate_position_size(
                                        sl_distance_pips=signal.sl_distance_pips,
                                        pip_size=market_state["pip_size"],
                                        lot_multiplier=effective_lot_mult,
                                    )

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
