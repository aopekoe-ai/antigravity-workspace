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


class ReviewEngine:
    """
    【自律型PDCA・振り返り ＆ MT5実績完全同期エンジン v9.0 (Step 3)】

    1. トレード実績（約定・決済・保有時間・損益・発動エンジン・レジーム）の永続ログ記録
    2. MT5履歴（position_id / order_id / magic=202611）との自動突合・バックフィル同期（手動裁量トレード完全分離）
    3. クオンツ統計自己較正 ＋ Gemini 2.5 Flash による日次振り返り＆パラメータ自動最適化
    4. 長期稼働用ログローテーション・gzipアーカイブ保全 (LogMaintainer連携)
    """

    BOT_MAGIC = 202611

    def __init__(self):
        self.log_dir = Path(settings.LOG_DIR)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.log_dir / "trade_journal.json"
        self.learning_file = self.log_dir / "learning_journal.md"
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

    def log_trade_execution(self, trade_info: Dict[str, Any], signal_info: Dict[str, Any]):
        """エントリー約定時の履歴を記録"""
        journal = self._load_journal()
        record = {
            "order_id": str(trade_info.get("order_id", "")),
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": trade_info.get("symbol", "XAUUSD"),
            "action": trade_info.get("action"),
            "volume": trade_info.get("volume"),
            "price": trade_info.get("price"),
            "sl": trade_info.get("sl"),
            "tp": trade_info.get("tp"),
            "setup_name": signal_info.get("setup_name"),
            "entry_engine": signal_info.get("entry_engine", "SMC"),
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
        """
        決済時の損益・結果を記録（文字列/整数および position_id / order_id の両方に完全対応）
        """
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
        """
        MT5の過去約定履歴（history_deals_get）と trade_journal.json を突合し、
        未同期のCLOSEDトレード（position_id一致）を完全バックフィル同期する。
        """
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

        # entry == 1 (OUT: 決済Deal) を position_id および order でインデックス化
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

    def get_today_trades(self) -> List[Dict[str, Any]]:
        """本日（直近24時間）のBOTトレード一覧を取得"""
        journal = self._load_journal()
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")
        return [t for t in journal if t.get("time", "").startswith(today_date)]

    def get_recent_closed_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """直近の決済済みBOTトレード一覧を取得"""
        journal = self._load_journal()
        closed = [t for t in journal if t.get("status") == "CLOSED" and t.get("profit") is not None]
        return closed[-limit:]

    def generate_daily_review(self, market_summary: str = "") -> Dict[str, Any]:
        """
        日次クローズ時の振り返り自己診断（MT5履歴同期 ＋ クオンツ統計自己較正 ＋ Gemini分析 ＋ ログ保全）
        """
        # 1. まずMT5履歴と完全突合して損益を最新化
        self.reconcile_with_mt5_history(days=7)

        today_trades = self.get_today_trades()
        recent_closed = self.get_recent_closed_trades(limit=50)

        trade_count = len(today_trades)
        total_profit = sum([float(t.get("profit", 0)) for t in today_trades if t.get("profit") is not None])
        wins = len([t for t in today_trades if (t.get("profit") or 0) > 0])
        losses = len([t for t in today_trades if (t.get("profit") or 0) < 0])

        # エンジン別内訳集計
        engine_counts: Dict[str, int] = {}
        for t in today_trades:
            eng = t.get("entry_engine", "SMC")
            engine_counts[eng] = engine_counts.get(eng, 0) + 1

        evaluation_data: Dict[str, Any] = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "trade_count": trade_count,
            "target_frequency_met": (trade_count >= 5),
            "wins": wins,
            "losses": losses,
            "total_profit": total_profit,
            "engine_breakdown": engine_counts,
            "market_summary": market_summary,
            "trades": today_trades
        }

        # 2. クオンツ統計ベースのベースライン較正案を算出
        quant_proposals = self.optimizer.compute_quant_calibration(
            closed_trades=recent_closed,
            today_trade_count=trade_count,
        )

        # 3. AI振り返り分析のプロンプト（超省トークン thinking_budget=0）
        if self.available:
            active_params = self.optimizer.load_active_params()
            r_wins = len([t for t in recent_closed if (t.get("profit") or 0) > 0])
            r_total = len(recent_closed)
            r_wr = round((r_wins / r_total) * 100, 1) if r_total > 0 else 0.0

            prompt = (
                f"Date: {evaluation_data['date']} | Asset: XAUUSD (3-Engine Hybrid v9.0)\n"
                f"Today: {trade_count} trades (Target: 5+), Wins: {wins}, Losses: {losses}, PnL: {total_profit:+,.0f} JPY.\n"
                f"Engines today: {engine_counts} | Rolling {r_total} trades WR: {r_wr}%\n"
                f"Setups: {[t.get('setup_name') for t in today_trades[-10:]]}\n"
                f"Active Params: {json.dumps(active_params, ensure_ascii=False)}\n"
                f"Quant Baseline Proposal: {json.dumps(quant_proposals, ensure_ascii=False)}\n\n"
                "Evaluate & propose safe parameter micro-adjustments within tunable keys: "
                "wick_ratio_threshold (0.20-0.55), min_fvg_gap_dollars (0.20-0.80), min_risk_reward_ratio (1.3-2.5), "
                "atr_sl_multiplier (1.0-2.0), momentum_z_threshold (1.25-2.00), macro_min_rr (1.6-2.4), smt_min_rr (1.6-2.5).\n"
                'Output JSON strictly:\n'
                '{\n'
                '  "frequency_verdict": "適正/少なすぎ/多すぎ",\n'
                '  "frequency_reason": "簡潔な理由",\n'
                '  "regime_fit": "3系統(SMC/型A/型B)と相場の相性評価",\n'
                '  "lessons_learned": "蓄積すべき改善教訓",\n'
                '  "proposed_params": {"wick_ratio_threshold": 0.25},\n'
                '  "optimization_reason": "最適化の根拠"\n'
                '}'
            )

            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.2,
                        max_output_tokens=450,
                        thinking_config={"thinking_budget": 0}
                    )
                )
                ai_res = json.loads(response.text)
                evaluation_data.update(ai_res)

                # クオンツ統計提案とAI提案をマージして安全ガードレール内で適用
                merged_proposals = dict(quant_proposals)
                if isinstance(ai_res.get("proposed_params"), dict):
                    merged_proposals.update(ai_res["proposed_params"])

                opt_reason = ai_res.get("optimization_reason", "日次クオンツ＋AIハイブリッド最適化")
                success, new_p, opt_summary = self.optimizer.apply_optimization(
                    proposed_changes=merged_proposals,
                    reason=opt_reason,
                    date_str=evaluation_data["date"]
                )
                evaluation_data["optimization_applied"] = success
                evaluation_data["optimization_summary"] = opt_summary

            except Exception as e:
                evaluation_data["frequency_verdict"] = "達成" if trade_count >= 5 else "少なすぎ"
                evaluation_data["frequency_reason"] = f"本日取引: {trade_count}回 (AI通信フォールバック: {e})"
                evaluation_data["regime_fit"] = "クオンツ統計較正を適用"
                evaluation_data["lessons_learned"] = "単一ポジション限定・ハードSL・上位足順張りを継続。"
                success, _, opt_summary = self.optimizer.apply_optimization(
                    proposed_changes=quant_proposals,
                    reason="クオンツ統計フォールバック自動較正",
                    date_str=evaluation_data["date"]
                )
                evaluation_data["optimization_applied"] = success
                evaluation_data["optimization_summary"] = opt_summary
        else:
            evaluation_data["frequency_verdict"] = "達成" if trade_count >= 5 else "未達 (ボラティリティ待機)"
            evaluation_data["frequency_reason"] = f"本日取引回数: {trade_count}回"
            evaluation_data["regime_fit"] = "3系統ハイブリッド稼働中"
            evaluation_data["lessons_learned"] = "クオンツ統計による自律パラメータ較正を実施。"
            success, _, opt_summary = self.optimizer.apply_optimization(
                proposed_changes=quant_proposals,
                reason="クオンツ統計自律較正",
                date_str=evaluation_data["date"]
            )
            evaluation_data["optimization_applied"] = success
            evaluation_data["optimization_summary"] = opt_summary

        # 4. 教訓ジャーナルへの追記 ＆ ログ・アーカイブローテーション実行
        self._append_learning_journal(evaluation_data)
        self.log_maintainer.run_maintenance()
        return evaluation_data

    def _append_learning_journal(self, eval_data: Dict[str, Any]):
        """教訓を learning_journal.md に追記蓄積"""
        entry = (
            f"\n### 📅 {eval_data.get('date')} [取引: {eval_data.get('trade_count')}回 "
            f"({eval_data.get('wins', 0)}勝{eval_data.get('losses', 0)}敗 / ¥{eval_data.get('total_profit', 0):+,.0f}) "
            f"/ 判定: {eval_data.get('frequency_verdict')}]\n"
            f"- **取引頻度評価**: {eval_data.get('frequency_reason')}\n"
            f"- **相場とロジックの相性**: {eval_data.get('regime_fit')}\n"
            f"- **💡 蓄積された改善教訓**: {eval_data.get('lessons_learned')}\n"
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
