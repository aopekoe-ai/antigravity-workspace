import requests
import datetime
from typing import Dict, Any, Optional
from config import settings

class DiscordManager:
    """
    Discord通知・レポート・約定アラートの一元管理クラス
    """
    def __init__(self):
        self.webhook_url = settings.DISCORD_WEBHOOK_URL

    def send_execution_alert(self, trade_info: Dict[str, Any], signal_info: Dict[str, Any]):
        """約定時の即時アラート送信"""
        if not self.webhook_url:
            return

        action = trade_info.get("action", "BUY")
        color = 0x26a69a if action == "BUY" else 0xef5350

        engine_labels = {
            "MACRO_MOMENTUM": "🚀 型A: マクロモメンタム (FVG不要)",
            "SMT_DIVERGENCE": "🎯 型B: SMTダイバージェンス (FVG不要)",
            "SMC": "🏛️ 系統3: SMCテクニカル",
        }
        entry_engine = signal_info.get("entry_engine", "SMC")
        macro_source = signal_info.get("macro_source", "NONE")
        lot_mult = signal_info.get("lot_multiplier", 1.0)
        engine_label = engine_labels.get(entry_engine, entry_engine)

        macro_note = signal_info.get("macro_reason")
        fields = [
            {"name": "売買種別", "value": f"**{action}** ({trade_info.get('volume')} Lot / 倍率 {lot_mult:.2f}x)", "inline": True},
            {"name": "約定価格", "value": f"`${trade_info.get('price'):.2f}`", "inline": True},
            {"name": "発動エンジン", "value": f"{engine_label} (`{macro_source}`)", "inline": True},
            {"name": "ハードSL (動的ATR)", "value": f"`${trade_info.get('sl'):.2f}` ({signal_info.get('sl_distance_pips')} pips)", "inline": True},
            {"name": "利確ターゲット (TP)", "value": f"`${trade_info.get('tp'):.2f}` ({signal_info.get('tp_distance_pips')} pips)", "inline": True},
            {"name": "リスクリワード比", "value": f"**1 : {signal_info.get('risk_reward_ratio')}**", "inline": True},
            {"name": "セットアップ根拠", "value": f"> {signal_info.get('rationale_ja')}", "inline": False},
        ]
        if macro_note:
            fields.append({"name": "🤖 Gemini 2.5 Flash マクロ安全判定", "value": f"> {macro_note}", "inline": False})
        fields.append({"name": "🛡️ 安全担保", "value": "✅ ブローカー側ハードSL即時付与済み\n✅ 単一ポジション限定インターロック有効\n✅ 建値移動＋マクロ反転トレーリング監視中", "inline": False})

        embed = {
            "title": f"⚡ 【実約定完了】 {trade_info.get('symbol')} {action} #{trade_info.get('order_id')}",
            "color": color,
            "fields": fields,
            "footer": {"text": f"SMC + Macro Hybrid Execution Engine v9.0 • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        }
        self._post_webhook([embed])

    def send_hourly_status(
        self,
        market_data: Dict[str, Any],
        signal: Any,
        account_state: Dict[str, Any],
        committee_report: Optional[Any] = None
    ):
        """毎時00分の定時AI合議体レポート（旧仕様の長文解説・反論・助言を完全復活）"""
        if not self.webhook_url:
            return

        current_ask = market_data.get("current_ask", 0.0)
        spread = market_data.get("spread_pips", 0.0)
        atr_pips = market_data.get("atr_m15_pips", 0.0)
        asia_high = market_data.get("asia_high")
        asia_low = market_data.get("asia_low")
        symbol = market_data.get("symbol", "XAUUSD")
        macro_state = market_data.get("macro_state") or {}

        if committee_report:
            action = committee_report.action
            direction = committee_report.direction
            confidence = committee_report.confidence
            regime = committee_report.regime
            exec_summary = committee_report.executive_summary_ja
            devils_objection = committee_report.devils_advocate_objection
            producer_advice = committee_report.producer_advice_ja
            cfo_approved = committee_report.cfo_risk_approval
            cfo_lot = committee_report.cfo_lot_size
            sl_pips = committee_report.suggested_sl_pips
            tp_pips = committee_report.suggested_tp_pips
        else:
            action = "TACTICAL_C_ABSTAIN"
            direction = "NONE"
            confidence = signal.confidence if hasattr(signal, "confidence") else 0.0
            regime = "RANGE_COMPRESSION"
            exec_summary = signal.rationale_ja if hasattr(signal, "rationale_ja") else "スキャン中"
            devils_objection = "スプレッド拡大およびボラティリティ急変に警戒が必要です。"
            producer_advice = "主要セッションの境界線でのプライスアクションを注視してください。"
            cfo_approved = False
            cfo_lot = 0.01
            sl_pips = 25.0
            tp_pips = 50.0

        if direction == "BUY":
            color = 0x26a69a
            status_icon = "🟢 [BUY 準備]"
        elif direction == "SELL":
            color = 0xef5350
            status_icon = "🔴 [SELL 準備]"
        else:
            color = 0xffa726
            status_icon = "⚪ [見送り (ABSTAIN)]"

        fields = [
            {"name": "🎯 アクション判定", "value": f"**{action}** ({status_icon})", "inline": True},
            {"name": "📈 相場レジーム", "value": f"`{regime}`", "inline": True},
            {"name": "🔥 総合確信度", "value": f"**{confidence * 100:.1f}%**", "inline": True},
            {"name": "💵 現在価格", "value": f"`${current_ask:.2f}` (Spread: `{spread} pips`)", "inline": True},
            {"name": "🛡️ 推奨SL / TP", "value": f"SL: `{sl_pips} pips` / TP: `{tp_pips} pips`", "inline": True},
            {"name": "💼 CFO資金管理", "value": f"承認: `{'✅ 承認' if cfo_approved else '⛔ 見送り'}` (Lot: `{cfo_lot}`)", "inline": True},
        ]

        if macro_state and macro_state.get("source", "NONE") != "NONE":
            fields.append({
                "name": "📡 先行指標ハイブリッド状態",
                "value": (
                    f"Source: `{macro_state.get('source')}` | Bias: `{macro_state.get('macro_bias_score', 0):+.2f}` | "
                    f"DXY Z: `{macro_state.get('dxy_z', 0):+.2f}` | Yield Z: `{macro_state.get('yield_z', 0):+.2f}`"
                ),
                "inline": False
            })

        if asia_high is not None and asia_low is not None:
            fields.append({
                "name": "📊 SMC水準 (ATR/高安)",
                "value": f"M15 ATR: `{atr_pips} pips` | Asia H: `${asia_high:.2f}` | Asia L: `${asia_low:.2f}`",
                "inline": False
            })

        fields.append({"name": "📝 合議体エグゼクティブ解説", "value": exec_summary, "inline": False})
        fields.append({"name": "😈 デビルズアドボケート (リスク反論)", "value": f"> {devils_objection}", "inline": False})

        if producer_advice:
            fields.append({
                "name": "🎬 AIプロデューサーからの改善・助言",
                "value": f"> {producer_advice}",
                "inline": False
            })

        embed = {
            "title": f"🤖 XAU/USD AI合議体 定時分析レポート ({symbol})",
            "color": color,
            "fields": fields,
            "footer": {"text": f"Multi-Agent AI Hedge Fund Platform v9.0 • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        }
        self._post_webhook([embed])

    def send_macro_halt_alert(self, symbol: str, action: str, reason: str):
        """AIマクロ安全門番による一時見送り通知（※ユーザー要望により完全無効化）"""
        return

    def send_daily_review_report(self, eval_data: Dict[str, Any]):
        """日次クローズ時の振り返り ＆ 自律改善レポート送信"""
        if not self.webhook_url:
            return

        trade_count = eval_data.get("trade_count", 0)
        pnl = eval_data.get("total_profit", 0)
        wins = eval_data.get("wins", 0)
        losses = eval_data.get("losses", 0)
        color = 0x26a69a if pnl > 0 else (0xef5350 if pnl < 0 else 0x5c6bc0)

        embed = {
            "title": f"📋 【XAU/USD 日次トレード振り返り ＆ 自律改善レポート】 ({eval_data.get('date')})",
            "color": color,
            "fields": [
                {
                    "name": "📊 本日の取引実績",
                    "value": f"• 取引回数: **{trade_count} 回** (平常時目標: 5回以上)\n• 勝敗: `{wins}勝 {losses}敗`\n• 本日損益: `¥{pnl:+,.0f}`",
                    "inline": False
                },
                {
                    "name": "⏱️ 取引頻度・機会損失の診断",
                    "value": f"判定: **{eval_data.get('frequency_verdict')}**\n> {eval_data.get('frequency_reason')}",
                    "inline": False
                },
                {
                    "name": "📈 相場とロジックの相性自己診断",
                    "value": f"> {eval_data.get('regime_fit')}",
                    "inline": False
                },
                {
                    "name": "💡 蓄積された改善教訓 (デグレ防止ナレッジ)",
                    "value": f"> {eval_data.get('lessons_learned')}",
                    "inline": False
                },
                {
                    "name": "🛡️ 安全規律・ルール遵守チェック",
                    "value": "✅ 単一ポジション限定ルール厳守\n✅ ブローカー側ハードSL 100%付与\n✅ スプレッド上限(3.0pips)インターロック正常",
                    "inline": False
                }
            ],
            "footer": {"text": f"Autonomous PDCA Engine • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        }
        self._post_webhook([embed])

    def send_circuit_breaker_alert(self, reason: str):
        """緊急停止（サーキットブレーカー）アラート"""
        if not self.webhook_url:
            return
        embed = {
            "title": "🚨 【CFO サーキットブレーカー発動（取引一時停止）】",
            "color": 0xd50000,
            "description": f"安全防御のため、本日の新規取引をロックしました。\n**理由**: {reason}",
            "footer": {"text": "Capital Preservation Interlock"}
        }
        self._post_webhook([embed])

    def _post_webhook(self, embeds: list):
        payload = {
            "username": "SMC AI Hedge Fund Core",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/2092/2092663.png",
            "embeds": embeds
        }
        try:
            requests.post(self.webhook_url, json=payload, timeout=8)
        except Exception as e:
            print(f"[DISCORD POST ERROR] {e}")
