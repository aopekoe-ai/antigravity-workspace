import os
import json
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
from config import settings
from core.dynamic_optimizer import DynamicParamOptimizer

class ReviewEngine:
    """
    【自律型PDCA・振り返りエンジン】
    
    1. トレード実績（約定・決済・保有時間・損益）の永続ログ記録
    2. 平常時5回以上をベンチマークとした日次自己診断（トレード過少/過多/相性分析）
    3. Gemini 2.5 Flash による日次振り返りレポート生成 & Discord通知
    4. 振り返り教訓の蓄積 (learning_journal.md) によるデグレ防止
    """
    def __init__(self):
        self.log_dir = Path(settings.LOG_DIR)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.journal_file = self.log_dir / "trade_journal.json"
        self.learning_file = self.log_dir / "learning_journal.md"
        self.optimizer = DynamicParamOptimizer(config_dir=Path(settings.CONFIG_DIR) if hasattr(settings, "CONFIG_DIR") else Path("config"))
        
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
            "order_id": trade_info.get("order_id"),
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": trade_info.get("symbol", "XAUUSD"),
            "action": trade_info.get("action"),
            "volume": trade_info.get("volume"),
            "price": trade_info.get("price"),
            "sl": trade_info.get("sl"),
            "tp": trade_info.get("tp"),
            "setup_name": signal_info.get("setup_name"),
            "rationale": signal_info.get("rationale_ja"),
            "status": "OPEN",
            "close_price": None,
            "profit": None,
            "close_time": None
        }
        journal.append(record)
        self._save_journal(journal)

    def log_trade_close(self, order_id: int, close_price: float, profit: float):
        """決済時の損益・結果を記録"""
        journal = self._load_journal()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for rec in journal:
            if rec.get("order_id") == order_id and rec.get("status") == "OPEN":
                rec["status"] = "CLOSED"
                rec["close_price"] = close_price
                rec["profit"] = profit
                rec["close_time"] = now_str
                break
        self._save_journal(journal)

    def get_today_trades(self) -> List[Dict[str, Any]]:
        """本日（直近24時間）のトレード一覧を取得"""
        journal = self._load_journal()
        today_date = datetime.datetime.now().strftime("%Y-%m-%d")
        return [t for t in journal if t.get("time", "").startswith(today_date)]

    def generate_daily_review(self, market_summary: str = "") -> Dict[str, Any]:
        """
        日次クローズ時の振り返り自己診断（平常時5回以上の達成度、相性、教訓）を生成
        """
        today_trades = self.get_today_trades()
        trade_count = len(today_trades)
        total_profit = sum([t.get("profit", 0) for t in today_trades if t.get("profit") is not None])
        wins = len([t for t in today_trades if (t.get("profit") or 0) > 0])
        losses = len([t for t in today_trades if (t.get("profit") or 0) < 0])

        evaluation_data = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "trade_count": trade_count,
            "target_frequency_met": (trade_count >= 5),
            "wins": wins,
            "losses": losses,
            "total_profit": total_profit,
            "market_summary": market_summary,
            "trades": today_trades
        }

        # AI振り返り分析のプロンプト
        if self.available:
            active_params = self.optimizer.load_active_params()
            prompt = (
                f"Date: {evaluation_data['date']} | Asset: XAUUSD\n"
                f"Today's Trades: {trade_count} trades (Target: 5+ trades in normal markets). "
                f"Wins: {wins}, Losses: {losses}, PnL: {total_profit:+,.0f} JPY.\n"
                f"Setups executed: {[t.get('setup_name') for t in today_trades]}\n"
                f"Current Tunable Parameters: {json.dumps(active_params, ensure_ascii=False)}\n\n"
                "Evaluate the day's performance based on 4 aspects:\n"
                "1. Frequency Assessment: Did we achieve 5+ trades? (Too few / Appropriate / Too many)\n"
                "2. Regime & Strategy Alignment: How well did SMC sweeps / EMA bounces match today's price action?\n"
                "3. Lesson Learned (Preventing Degradation): Concrete rule or refinement to accumulate without regressing past rules.\n"
                "4. Safe Parameter Optimization Proposal:\n"
                "   Suggest micro-adjustments if needed (e.g. if trades < 5 and normal market, wick_ratio_threshold from 0.40 to 0.35, or min_fvg_gap_dollars from 0.40 to 0.35).\n"
                "   Never touch risk/drawdown. Only suggest tunable keys: wick_ratio_threshold (0.25-0.60), min_fvg_gap_dollars (0.25-0.80), min_risk_reward_ratio (1.5-2.5), min_sl_pips (10-25), max_sl_pips (40-70), atr_sl_multiplier (1.0-2.0), max_allowed_spread_pips (2.0-3.5).\n\n"
                'Output JSON strictly in format:\n'
                '{\n'
                '  "frequency_verdict": "適正/少なすぎ/多すぎ",\n'
                '  "frequency_reason": "簡潔な理由",\n'
                '  "regime_fit": "相性評価",\n'
                '  "lessons_learned": "蓄積すべき改善教訓",\n'
                '  "proposed_params": {"wick_ratio_threshold": 0.35},\n'
                '  "optimization_reason": "取引回数5回未満の改善のためヒゲ比率閾値を微調整"\n'
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

                # パラメータ自動最適化を安全ガードレール内で適用
                proposed = ai_res.get("proposed_params", {})
                opt_reason = ai_res.get("optimization_reason", "日次PDCA最適化")
                success, new_p, opt_summary = self.optimizer.apply_optimization(
                    proposed_changes=proposed,
                    reason=opt_reason,
                    date_str=evaluation_data["date"]
                )
                evaluation_data["optimization_applied"] = success
                evaluation_data["optimization_summary"] = opt_summary

            except Exception as e:
                evaluation_data["frequency_verdict"] = "正常"
                evaluation_data["frequency_reason"] = f"分析フェールセーフ ({e})"
                evaluation_data["regime_fit"] = "レンジ・トレンド双方を監視中"
                evaluation_data["lessons_learned"] = "単一ポジション限定とスプレッド管理を徹底維持。"
                evaluation_data["optimization_applied"] = False
                evaluation_data["optimization_summary"] = "フェールセーフ発動のためパラメータ維持。"
        else:
            evaluation_data["frequency_verdict"] = "達成" if trade_count >= 5 else "未達 (ボラティリティ待機)"
            evaluation_data["frequency_reason"] = f"本日取引回数: {trade_count}回"
            evaluation_data["regime_fit"] = "SMC流動性スイープ稼働中"
            evaluation_data["lessons_learned"] = "平常時5回以上の機会確保のため、M5スイング高安の監視を継続。"
            evaluation_data["optimization_applied"] = False
            evaluation_data["optimization_summary"] = "オフライン環境のため現状パラメータ維持。"

        # 教訓ジャーナルへの追記（ナレッジ蓄積・デグレ防止）
        self._append_learning_journal(evaluation_data)
        return evaluation_data

    def _append_learning_journal(self, eval_data: Dict[str, Any]):
        """教訓を learning_journal.md に追記蓄積"""
        entry = (
            f"\n### 📅 {eval_data.get('date')} [取引: {eval_data.get('trade_count')}回 / 判定: {eval_data.get('frequency_verdict')}]\n"
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
            with open(self.journal_file, "w", encoding="utf-8") as f:
                json.dump(journal, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[SAVE JOURNAL ERROR] {e}")
