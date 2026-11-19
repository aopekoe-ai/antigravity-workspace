import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from config import settings
from core.dynamic_optimizer import DynamicParamOptimizer
from core.log_maintainer import LogMaintainer
from core.mt5_conn import mt5

JST = datetime.timezone(datetime.timedelta(hours=9))


class ReviewEngine:
    """
    【自律型PDCA・6ブロック運用ブリーフィング ＆ MT5実績完全同期エンジン v9.1】

    1. トレード実績（約定・決済・保有時間・損益・発動エンジン・セッション・レジーム）の永続ログ記録
    2. 防御エンジン実績（ハードガード・連敗防止クールダウン・建値移動救済・マクロトレーリング）のカウント集計
    3. MT5履歴（position_id / order_id）との自動突合・バックフィル同期
    4. 毎朝06:00 JST の6ブロック・ヘッジファンド日次運用ブリーフィング生成 ＆ 週間サマリー算出
    """

    BOT_MAGIC = 202611

    def __init__(self):
        self.log_dir = Path(settings.LOG_DIR)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.log_dir / "trade_journal.json"
        self.learning_file = self.log_dir / "learning_journal.md"
        self.defense_file = self.log_dir / "daily_defense_stats.json"
        config_dir = Path(settings.BASE_DIR) / "config" if hasattr(settings, "BASE_DIR") else Path("config")
        self.optimizer = DynamicParamOptimizer(config_dir=config_dir)
        self.log_maintainer = LogMaintainer(log_dir=self.log_dir)

        try:
            self.client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_VERTEX_LOCATION
            )
            self.model_name = settings.VERTEX_MODEL_NAME
            self.available = True
        except Exception:
            self.available = False

    def record_defense_event(self, kind: str) -> None:
        """
        防御エンジンの発動回数（hard_guard / sl_cooldown / spread_block / break_even / macro_trailing）を日次記録
        """
        today_str = datetime.datetime.now(datetime.timezone.utc).astimezone(JST).strftime("%Y-%m-%d")
        data = self._load_defense_stats()
        day_bucket = data.get(today_str, {
            "hard_guard": 0,
            "sl_cooldown": 0,
            "spread_block": 0,
            "break_even": 0,
            "macro_trailing": 0,
        })
        day_bucket[kind] = int(day_bucket.get(kind, 0)) + 1
        data[today_str] = day_bucket
        # 直近14日分のみ保持して肥大化防止
        for k in sorted(data.keys())[:-14]:
            del data[k]
        self._save_defense_stats(data)

    def _load_defense_stats(self) -> Dict[str, Any]:
        if self.defense_file.exists():
            try:
                with open(self.defense_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_defense_stats(self, data: Dict[str, Any]) -> None:
        try:
            tmp = self.defense_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.defense_file)
        except Exception:
            pass

    def _infer_session_from_setup(self, setup_name: str, time_str: str) -> str:
        s = str(setup_name or "")
        for name in ("Asia", "London_Pre", "London", "NewYork"):
            if name in s:
                return "London" if name == "London_Pre" else name
        try:
            dt = datetime.datetime.strptime(time_str[:19], "%Y-%m-%d %H:%M:%S")
            # UTC -> JST 換算の概算
            h_jst = (dt.hour + 9) % 24
            if 8 <= h_jst < 15:
                return "Asia"
            if 15 <= h_jst < 21:
                return "London"
            return "NewYork"
        except Exception:
            return "NewYork"

    def _infer_engine_from_record(self, rec: Dict[str, Any]) -> str:
        eng = rec.get("entry_engine")
        if eng in ("MACRO_MOMENTUM", "SMT_DIVERGENCE", "SMC"):
            return eng
        s = str(rec.get("setup_name", ""))
        if s.startswith("MacroA_"):
            return "MACRO_MOMENTUM"
        if s.startswith("MacroB_"):
            return "SMT_DIVERGENCE"
        return "SMC"

    def log_trade_execution(self, trade_info: Dict[str, Any], signal_info: Dict[str, Any]):
        """エントリー約定時の履歴を記録"""
        journal = self._load_journal()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        setup_name = signal_info.get("setup_name", "")
        record = {
            "order_id": str(trade_info.get("order_id", "")),
            "time": now_str,
            "symbol": trade_info.get("symbol", "XAUUSD"),
            "action": trade_info.get("action"),
            "volume": trade_info.get("volume"),
            "price": trade_info.get("price"),
            "sl": trade_info.get("sl"),
            "tp": trade_info.get("tp"),
            "setup_name": setup_name,
            "entry_engine": signal_info.get("entry_engine", "SMC"),
            "session": self._infer_session_from_setup(setup_name, now_str),
            "macro_source": signal_info.get("macro_source", "NONE"),
            "lot_multiplier": signal_info.get("lot_multiplier", 1.0),
            "active_regime": signal_info.get("active_regime", "REGIME_NORMAL_FLOW"),
            "rationale": signal_info.get("rationale_ja"),
            "magic": self.BOT_MAGIC,
            "status": "OPEN",
            "close_price": None,
            "profit": None,
            "close_time": None
        }
        journal.append(record)
        self._save_journal(journal)

    def log_trade_close(
        self,
        order_id: Any,
        close_price: float,
        profit: float,
        position_id: Optional[Any] = None,
        close_time_str: Optional[str] = None,
    ) -> bool:
        """決済時の損益・結果を記録"""
        journal = self._load_journal()
        now_str = close_time_str or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target_ids = {str(order_id)}
        if position_id is not None:
            target_ids.add(str(position_id))

        updated = False
        for rec in journal:
            rec_id = str(rec.get("order_id", ""))
            if rec_id in target_ids and rec.get("status") == "OPEN":
                rec["status"] = "CLOSED"
                rec["close_price"] = round(float(close_price), 3)
                rec["profit"] = round(float(profit), 0)
                rec["close_time"] = now_str
                updated = True
                break

        if updated:
            self._save_journal(journal)
        return updated

    def reconcile_with_mt5_history(self, days: int = 30) -> int:
        """MT5の過去約定履歴と trade_journal.json を突合し、未同期のCLOSEDトレードを完全バックフィル同期"""
        journal = self._load_journal()
        open_recs = [r for r in journal if r.get("status") == "OPEN"]
        if not open_recs:
            return 0

        try:
            now_dt = datetime.datetime.now()
            from_dt = now_dt - datetime.timedelta(days=days)
            deals = mt5.history_deals_get(from_dt, now_dt + datetime.timedelta(hours=12))
            if not deals:
                return 0
        except Exception as e:
            print(f"[RECONCILE WARN] MT5履歴取得スキップ: {e}")
            return 0

        close_map: Dict[str, Any] = {}
        for d in deals:
            if getattr(d, "entry", -1) == 1:
                pos_id = str(getattr(d, "position_id", ""))
                ord_id = str(getattr(d, "order", ""))
                if pos_id:
                    close_map[pos_id] = d
                if ord_id:
                    close_map[ord_id] = d

        reconciled_count = 0
        for rec in journal:
            if rec.get("status") != "OPEN":
                continue
            oid = str(rec.get("order_id", ""))
            if oid and oid in close_map:
                d = close_map[oid]
                net_profit = (
                    float(getattr(d, "profit", 0.0))
                    + float(getattr(d, "swap", 0.0))
                    + float(getattr(d, "commission", 0.0))
                )
                deal_ts = getattr(d, "time", 0)
                close_str = (
                    datetime.datetime.fromtimestamp(deal_ts).strftime("%Y-%m-%d %H:%M:%S")
                    if deal_ts > 0
                    else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                rec["status"] = "CLOSED"
                rec["close_price"] = round(float(getattr(d, "price", 0.0)), 3)
                rec["profit"] = round(net_profit, 0)
                rec["close_time"] = close_str
                reconciled_count += 1

        if reconciled_count > 0:
            self._save_journal(journal)
            print(f"✅ [JOURNAL RECONCILED] MT5決済履歴から {reconciled_count} 件のトレード損益を同期完了。")
        return reconciled_count

    def _filter_trades_since_hours(self, hours: int = 24) -> List[Dict[str, Any]]:
        """直近N時間以内にエントリーまたは決済されたトレードを取得"""
        journal = self._load_journal()
        now_dt = datetime.datetime.now()
        cutoff = now_dt - datetime.timedelta(hours=hours)
        matched = []
        for t in journal:
            t_str = str(t.get("close_time") or t.get("time") or "")
            try:
                dt = datetime.datetime.strptime(t_str[:19], "%Y-%m-%d %H:%M:%S")
                if dt >= cutoff:
                    matched.append(t)
            except Exception:
                pass
        return matched

    def get_today_trades(self) -> List[Dict[str, Any]]:
        """直近24時間のトレード一覧を取得"""
        trades = self._filter_trades_since_hours(hours=24)
        if not trades:
            journal = self._load_journal()
            today_date = datetime.datetime.now().strftime("%Y-%m-%d")
            trades = [t for t in journal if t.get("time", "").startswith(today_date)]
        return trades

    def get_recent_closed_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """直近の決済済みBOTトレード一覧を取得"""
        journal = self._load_journal()
        closed = [t for t in journal if t.get("status") == "CLOSED" and t.get("profit") is not None]
        return closed[-limit:]

    def _compute_metrics_block(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """トレードリストから勝率・PF・建値撤退数・エンジン別/セッション別内訳・ベスト/ワーストを算出"""
        closed = [t for t in trades if t.get("profit") is not None]
        total_pnl = sum(float(t.get("profit", 0)) for t in closed)

        # -300円〜+800円以内の微益/微損決済は「建値撤退（BE救済）」として独立カウント
        be_trades = [t for t in closed if -300 <= float(t.get("profit", 0)) <= 800]
        true_wins = [t for t in closed if float(t.get("profit", 0)) > 800]
        true_losses = [t for t in closed if float(t.get("profit", 0)) < -300]

        all_wins = [t for t in closed if float(t.get("profit", 0)) > 0]
        all_losses = [t for t in closed if float(t.get("profit", 0)) < 0]

        gross_win = sum(float(t.get("profit", 0)) for t in all_wins)
        gross_loss = abs(sum(float(t.get("profit", 0)) for t in all_losses))
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (9.99 if gross_win > 0 else 1.00)

        denom = len(true_wins) + len(true_losses)
        win_rate_pct = round((len(true_wins) / denom) * 100.0, 1) if denom > 0 else (
            round((len(all_wins) / len(closed)) * 100.0, 1) if closed else 0.0
        )

        avg_win = round(sum(float(t.get("profit", 0)) for t in true_wins) / len(true_wins), 0) if true_wins else 0.0
        avg_loss = round(sum(float(t.get("profit", 0)) for t in true_losses) / len(true_losses), 0) if true_losses else 0.0

        # エンジン別集計
        engines = {
            "MACRO_MOMENTUM": {"label": "🚀 型A(マクロ急変)", "wins": 0, "losses": 0, "be": 0, "pnl": 0.0},
            "SMT_DIVERGENCE": {"label": "🎯 型B(SMT吸収)", "wins": 0, "losses": 0, "be": 0, "pnl": 0.0},
            "SMC": {"label": "🏛️ 系統3(SMC)", "wins": 0, "losses": 0, "be": 0, "pnl": 0.0},
        }
        sessions = {
            "Asia": {"label": "東京", "wins": 0, "losses": 0, "pnl": 0.0},
            "London": {"label": "ロンドン", "wins": 0, "losses": 0, "pnl": 0.0},
            "NewYork": {"label": "NY", "wins": 0, "losses": 0, "pnl": 0.0},
        }

        for t in closed:
            p = float(t.get("profit", 0))
            eng = self._infer_engine_from_record(t)
            sess = t.get("session") or self._infer_session_from_setup(t.get("setup_name", ""), t.get("time", ""))
            if sess not in sessions:
                sess = "NewYork"

            engines[eng]["pnl"] += p
            sessions[sess]["pnl"] += p

            if -300 <= p <= 800:
                engines[eng]["be"] += 1
            elif p > 800:
                engines[eng]["wins"] += 1
                sessions[sess]["wins"] += 1
            else:
                engines[eng]["losses"] += 1
                sessions[sess]["losses"] += 1

        best_trade = max(closed, key=lambda x: float(x.get("profit", 0))) if closed else None
        worst_trade = min(closed, key=lambda x: float(x.get("profit", 0))) if closed else None

        return {
            "total_count": len(trades),
            "closed_count": len(closed),
            "wins": len(all_wins),
            "losses": len(all_losses),
            "true_wins": len(true_wins),
            "true_losses": len(true_losses),
            "be_count": len(be_trades),
            "win_rate_pct": win_rate_pct,
            "profit_factor": pf,
            "total_profit": round(total_pnl, 0),
            "avg_win_jpy": avg_win,
            "avg_loss_jpy": avg_loss,
            "engines": engines,
            "sessions": sessions,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
        }

    def get_weekly_summary(self) -> Dict[str, Any]:
        """週末レポート用の直近7日間トレード総決算を算出"""
        self.reconcile_with_mt5_history(days=10)
        week_trades = self._filter_trades_since_hours(hours=24 * 7)
        return self._compute_metrics_block(week_trades)

    def generate_daily_review(
        self,
        market_summary: str = "",
        market_state: Optional[Dict[str, Any]] = None,
        active_regime: str = "REGIME_NORMAL_FLOW",
    ) -> Dict[str, Any]:
        """
        【6ブロック・ヘッジファンド日次運用ブリーフィング】を生成
        """
        self.reconcile_with_mt5_history(days=7)

        today_trades = self.get_today_trades()
        week_trades = self._filter_trades_since_hours(hours=24 * 7)
        recent_closed = self.get_recent_closed_trades(limit=50)

        m_today = self._compute_metrics_block(today_trades)
        m_week = self._compute_metrics_block(week_trades)

        # 口座残高・日次リターン%
        acc_info = mt5.account_info()
        balance = float(acc_info.balance) if acc_info else 500000.0
        start_bal = max(1.0, balance - m_today["total_profit"])
        daily_ret_pct = round((m_today["total_profit"] / start_bal) * 100.0, 2)

        # 過去24時間のゴールド高値・安値・レンジ幅・マクロ状態
        high_24h, low_24h, range_pips_24h = 0.0, 0.0, 0.0
        current_px = 0.0
        pdh, pdl = None, None
        h1_trend, m15_trend = "NEUTRAL", "NEUTRAL"
        macro_state = {}

        if market_state:
            current_px = float(market_state.get("current_ask", 0.0))
            pdh = market_state.get("pdh")
            pdl = market_state.get("pdl")
            h1_trend = market_state.get("h1_trend", "NEUTRAL")
            m15_trend = market_state.get("m15_trend", "NEUTRAL")
            macro_state = market_state.get("macro_state") or {}
            df_h1 = market_state.get("df_h1")
            if df_h1 is not None and len(df_h1) >= 24:
                sub_24 = df_h1.iloc[-24:]
                high_24h = float(sub_24["high"].max())
                low_24h = float(sub_24["low"].min())
                range_pips_24h = round((high_24h - low_24h) / 0.10, 1)

        # 防御エンジン実績集計
        now_jst = datetime.datetime.now(datetime.timezone.utc).astimezone(JST)
        today_jst_str = now_jst.strftime("%Y-%m-%d")
        yest_jst_str = (now_jst - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        def_all = self._load_defense_stats()
        d_today = def_all.get(today_jst_str, {})
        d_yest = def_all.get(yest_jst_str, {})

        # 06:00 JST 時点では前日JST＋当日早朝JSTの合算が直近24時間の実績
        hard_guard_cnt = int(d_today.get("hard_guard", 0)) + int(d_yest.get("hard_guard", 0))
        cooldown_cnt = int(d_today.get("sl_cooldown", 0)) + int(d_yest.get("sl_cooldown", 0))
        spread_cnt = int(d_today.get("spread_block", 0)) + int(d_yest.get("spread_block", 0))
        be_cnt = max(m_today["be_count"], int(d_today.get("break_even", 0)) + int(d_yest.get("break_even", 0)))
        trail_cnt = int(d_today.get("macro_trailing", 0)) + int(d_yest.get("macro_trailing", 0))

        avg_loss_abs = abs(m_today["avg_loss_jpy"]) if m_today["avg_loss_jpy"] < 0 else 8500.0
        est_saved_jpy = round((min(hard_guard_cnt, 5) * 0.6 + min(cooldown_cnt, 4) * 0.8 + be_cnt * 0.7) * avg_loss_abs, 0)

        before_params = self.optimizer.load_active_params()
        quant_proposals = self.optimizer.compute_quant_calibration(
            closed_trades=recent_closed,
            today_trade_count=m_today["total_count"],
        )

        best_t = m_today["best_trade"]
        worst_t = m_today["worst_trade"]
        best_desc = (
            f"{best_t.get('action')} [{best_t.get('setup_name')}] (¥{float(best_t.get('profit', 0)):+,.0f})"
            if best_t and float(best_t.get("profit", 0)) > 0 else "該当なし"
        )
        worst_desc = (
            f"{worst_t.get('action')} [{worst_t.get('setup_name')}] (¥{float(worst_t.get('profit', 0)):+,.0f})"
            if worst_t and float(worst_t.get("profit", 0)) < 0 else "損切りなし"
        )

        evaluation_data: Dict[str, Any] = {
            "date": today_jst_str,
            "balance": balance,
            "daily_return_pct": daily_ret_pct,
            "weekly_profit": m_week["total_profit"],
            "weekly_pf": m_week["profit_factor"],
            "trade_count": m_today["total_count"],
            "target_frequency_met": (m_today["total_count"] >= 5),
            "wins": m_today["wins"],
            "losses": m_today["losses"],
            "true_wins": m_today["true_wins"],
            "true_losses": m_today["true_losses"],
            "be_count": be_cnt,
            "win_rate_pct": m_today["win_rate_pct"],
            "profit_factor": m_today["profit_factor"],
            "total_profit": m_today["total_profit"],
            "avg_win_jpy": m_today["avg_win_jpy"],
            "avg_loss_jpy": m_today["avg_loss_jpy"],
            "engines": m_today["engines"],
            "sessions": m_today["sessions"],
            "best_trade_desc": best_desc,
            "worst_trade_desc": worst_desc,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "range_pips_24h": range_pips_24h,
            "current_price": current_px,
            "pdh": pdh,
            "pdl": pdl,
            "h1_trend": h1_trend,
            "m15_trend": m15_trend,
            "active_regime": active_regime,
            "macro_state": macro_state,
            "defense_stats": {
                "hard_guard": hard_guard_cnt,
                "sl_cooldown": cooldown_cnt,
                "spread_block": spread_cnt,
                "break_even": be_cnt,
                "macro_trailing": trail_cnt,
                "est_saved_jpy": est_saved_jpy,
            },
            "before_params": before_params,
            "market_summary": market_summary,
            "trades": today_trades,
        }

        # AI 6ブロック深掘り分析（thinking_budget=0 でトークンを節約しつつ密度を最大化）
        if self.available:
            prompt = (
                f"Date:{today_jst_str} XAUUSD HedgeFund Daily Briefing\n"
                f"24h Range: ${low_24h:.2f}-${high_24h:.2f} ({range_pips_24h}pips), Now:${current_px:.2f}, H1:{h1_trend}, M15:{m15_trend}, Regime:{active_regime}\n"
                f"Macro: src={macro_state.get('source')}, DXY_Z={macro_state.get('dxy_z',0)}, Yield_Z={macro_state.get('yield_z',0)}, Bias={macro_state.get('macro_bias_score',0)}\n"
                f"PnL: {m_today['total_profit']:+,.0f}JPY ({daily_ret_pct:+.2f}%), Trades:{m_today['total_count']} ({m_today['true_wins']}W/{m_today['true_losses']}L/{be_cnt}BE), PF:{m_today['profit_factor']}\n"
                f"Best:{best_desc} | Worst:{worst_desc}\n"
                f"Engines:{json.dumps({k:v['pnl'] for k,v in m_today['engines'].items()})} | Sessions:{json.dumps({k:v['pnl'] for k,v in m_today['sessions'].items()})}\n"
                f"Defense blocks: HardGuard={hard_guard_cnt}, SLCooldown={cooldown_cnt}, BE={be_cnt}\n"
                f"Params:{json.dumps(before_params)} | QuantProposal:{json.dumps(quant_proposals)}\n\n"
                "Write a sharp, institutional Japanese briefing in JSON:\n"
                '{\n'
                '  "frequency_verdict": "適正 / 少なすぎ / 多すぎ",\n'
                '  "market_narrative_ja": "過去24時間の値動き・マクロ背景(DXY/米金利/原油)と市場参加者の投資家心理の具体的解説(2〜3文)",\n'
                '  "trade_autopsy_ja": "3系統エンジン戦績・ベスト勝因・ワースト敗因の具体的解剖(2〜3文)",\n'
                '  "session_outlook_ja": "昨日のボラ消化度から見た本日(東京・ロンドン・NY)のボラ余力予測とPDH/PDL攻略作戦(2〜3文)",\n'
                '  "producer_proposal_ja": "AIプロデューサー視点での新たな改善提案・機関投資家トレンド助言(2文)",\n'
                '  "proposed_params": {"wick_ratio_threshold": 0.25},\n'
                '  "optimization_reason": "パラメータ調整の明確な根拠"\n'
                '}'
            )

            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.25,
                        max_output_tokens=700,
                        thinking_config={"thinking_budget": 0}
                    )
                )
                ai_res = json.loads(response.text)
                evaluation_data.update(ai_res)

                merged_proposals = dict(quant_proposals)
                if isinstance(ai_res.get("proposed_params"), dict):
                    merged_proposals.update(ai_res["proposed_params"])

                opt_reason = ai_res.get("optimization_reason", "日次クオンツ＋AIハイブリッド最適化")
                success, after_params, opt_summary = self.optimizer.apply_optimization(
                    proposed_changes=merged_proposals,
                    reason=opt_reason,
                    date_str=evaluation_data["date"]
                )
                evaluation_data["after_params"] = after_params
                evaluation_data["optimization_applied"] = success
                evaluation_data["optimization_summary"] = opt_summary

            except Exception as e:
                self._fill_fallback_narrative(evaluation_data, quant_proposals, f"AI通信フォールバック ({e})")
        else:
            self._fill_fallback_narrative(evaluation_data, quant_proposals, "クオンツ自律較正モード")

        evaluation_data["frequency_reason"] = evaluation_data.get("market_narrative_ja", "")
        evaluation_data["regime_fit"] = evaluation_data.get("trade_autopsy_ja", "")
        evaluation_data["lessons_learned"] = evaluation_data.get("producer_proposal_ja", "")

        self._append_learning_journal(evaluation_data)
        self.log_maintainer.run_maintenance()
        return evaluation_data

    def _fill_fallback_narrative(self, eval_data: Dict[str, Any], quant_proposals: Dict[str, Any], note: str) -> None:
        tc = eval_data["trade_count"]
        rng = eval_data["range_pips_24h"]
        h1 = eval_data["h1_trend"]
        eval_data["frequency_verdict"] = "適正" if tc >= 5 else "少なすぎ（機会探索中）"
        eval_data["market_narrative_ja"] = (
            f"過去24時間のゴールド変動幅は {rng} pips（高値 ${eval_data['high_24h']:.2f} / 安値 ${eval_data['low_24h']:.2f}）、"
            f"上位足H1は {h1} トレンドで推移。DXYと米金利の綱引きの中で流動性スイープが発生しています。"
        )
        eval_data["trade_autopsy_ja"] = (
            f"直近24時間は {tc}戦 {eval_data['true_wins']}勝 {eval_data['true_losses']}敗 {eval_data['be_count']}建値撤退（PF {eval_data['profit_factor']}）。"
            f"ベスト: {eval_data['best_trade_desc']} / ワースト: {eval_data['worst_trade_desc']}。"
        )
        eval_data["session_outlook_ja"] = (
            f"本日の重要流動性ターゲットは PDH ${eval_data['pdh'] or 0:.2f} / PDL ${eval_data['pdl'] or 0:.2f}。"
            f"上位足({h1})方向への順張りピラミッディング（最大3ポジ）でロンドン・NYの本流を狙います。"
        )
        eval_data["producer_proposal_ja"] = (
            f"先行指標のリードラグ（5〜15分波）と建値移動によるフリーロール積み増しを継続。（{note}）"
        )
        success, after_params, opt_summary = self.optimizer.apply_optimization(
            proposed_changes=quant_proposals,
            reason="日次クオンツ統計自動較正",
            date_str=eval_data["date"]
        )
        eval_data["after_params"] = after_params
        eval_data["optimization_applied"] = success
        eval_data["optimization_summary"] = opt_summary

    def _append_learning_journal(self, eval_data: Dict[str, Any]):
        """教訓を learning_journal.md に追記蓄積"""
        entry = (
            f"\n### 📅 {eval_data.get('date')} [取引: {eval_data.get('trade_count')}回 "
            f"({eval_data.get('true_wins', 0)}勝{eval_data.get('true_losses', 0)}敗{eval_data.get('be_count', 0)}建値 / "
            f"¥{eval_data.get('total_profit', 0):+,.0f} / PF:{eval_data.get('profit_factor', 1.0)})]\n"
            f"- **🌍 相場＆投資家心理**: {eval_data.get('market_narrative_ja')}\n"
            f"- **🔍 戦績＆敗因解剖**: {eval_data.get('trade_autopsy_ja')}\n"
            f"- **🎬 本日の作戦＆プロデューサー提案**: {eval_data.get('session_outlook_ja')} / {eval_data.get('producer_proposal_ja')}\n"
            f"- **⚙️ パラメータ自動最適化**: {eval_data.get('optimization_summary', '現状維持')}\n"
        )
        try:
            with open(self.learning_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[JOURNAL ERROR] {e}")

    def _load_journal(self) -> List[Dict[str, Any]]:
        if self.journal_file.exists():
            try:
                with open(self.journal_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_journal(self, journal: List[Dict[str, Any]]):
        try:
            tmp_path = self.journal_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(journal, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.journal_file)
        except Exception as e:
            print(f"[SAVE JOURNAL ERROR] {e}")
