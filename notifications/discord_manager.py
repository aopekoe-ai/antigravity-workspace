import requests
import datetime
from typing import Dict, Any, Optional
from config import settings


class DiscordManager:
    """
    Discord通知・6ブロック日次運用ブリーフィング・週末クオンツ研究室レポート・約定アラートの一元管理クラス v9.1
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
        pyramid_note = signal_info.get("pyramid_reason", "3系統別最大3ポジ管理")
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
        dash_url = settings.get_dashboard_url() if hasattr(settings, "get_dashboard_url") else "http://155.133.7.59/dashboard"
        fields.append({
            "name": "🛡️ ポジション＆安全担保",
            "value": f"✅ {pyramid_note}\n✅ ブローカー側ハードSL即時付与 ＆ 個別建値移動・マクロ反転トレーリング監視中\n📱 [スマホ管理ダッシュボードを開く]({dash_url})",
            "inline": False
        })

        embed = {
            "title": f"⚡ 【実約定完了】 {trade_info.get('symbol')} {action} #{trade_info.get('order_id')}",
            "color": color,
            "fields": fields,
            "footer": {"text": f"SMC + Macro Hybrid Execution Engine v9.1 • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        }
        self._post_webhook([embed])

    def send_hourly_status(
        self,
        market_data: Dict[str, Any],
        signal: Any,
        account_state: Dict[str, Any],
        committee_report: Optional[Any] = None
    ):
        """毎時00分の定時AI合議体レポート（※土日休場中はmain.py側で完全停止）"""
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
            "footer": {"text": f"Multi-Agent AI Hedge Fund Platform v9.1 • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        }
        self._post_webhook([embed])

    def send_macro_halt_alert(self, symbol: str, action: str, reason: str):
        """AIマクロ安全門番による一時見送り通知（※ユーザー要望により完全無効化）"""
        return

    def send_daily_review_report(self, eval_data: Dict[str, Any]):
        """
        【6ブロック刷新版】毎朝06:00 JST ヘッジファンド日次運用ブリーフィング送信
        """
        if not self.webhook_url:
            return

        trade_count = eval_data.get("trade_count", 0)
        pnl = float(eval_data.get("total_profit", 0))
        daily_ret = float(eval_data.get("daily_return_pct", 0.0))
        balance = float(eval_data.get("balance", 0))
        weekly_pnl = float(eval_data.get("weekly_profit", 0))
        weekly_pf = eval_data.get("weekly_pf", 1.0)

        t_wins = eval_data.get("true_wins", eval_data.get("wins", 0))
        t_losses = eval_data.get("true_losses", eval_data.get("losses", 0))
        be_cnt = eval_data.get("be_count", 0)
        wr = eval_data.get("win_rate_pct", 0.0)
        pf = eval_data.get("profit_factor", 1.0)
        avg_w = float(eval_data.get("avg_win_jpy", 0))
        avg_l = float(eval_data.get("avg_loss_jpy", 0))

        color = 0x26a69a if pnl > 0 else (0xef5350 if pnl < 0 else 0x5c6bc0)

        # ブロック①: エグゼクティブ損益 ＆ 口座スコアカード
        b1_text = (
            f"• **直近24h損益**: **`¥{pnl:+,.0f}`** (`{daily_ret:+.2f}%`) ／ **現在残高**: `¥{balance:,.0f}` (直近7日: `¥{weekly_pnl:+,.0f}`, PF `{weekly_pf}`)\n"
            f"• **戦績内訳**: **{trade_count}戦 `{t_wins}勝 {t_losses}敗 {be_cnt}建値撤退`** (実質勝率: **`{wr}%`** ／ **PF: `{pf}`**)\n"
            f"• **平均損益**: 平均利確 `¥{avg_w:+,.0f}` vs 平均損切り `¥{avg_l:+,.0f}` (頻度判定: **{eval_data.get('frequency_verdict', '適正')}**)"
        )

        # ブロック②: 3系統エンジン別 ＆ セッション別戦績
        engs = eval_data.get("engines", {})
        sess = eval_data.get("sessions", {})
        eng_lines = []
        for k in ("MACRO_MOMENTUM", "SMT_DIVERGENCE", "SMC"):
            e = engs.get(k, {})
            if e:
                eng_lines.append(
                    f"・{e.get('label', k)}: `{e.get('wins',0)}勝 {e.get('losses',0)}敗 {e.get('be',0)}BE` (**`¥{float(e.get('pnl',0)):+,.0f}`**)"
                )
        sess_parts = []
        for k in ("Asia", "London", "NewYork"):
            s = sess.get(k, {})
            if s:
                sess_parts.append(f"{s.get('label', k)}: `{s.get('wins',0)}勝{s.get('losses',0)}敗` (`¥{float(s.get('pnl',0)):+,.0f}`)")
        b2_text = "\n".join(eng_lines) + "\n• **時間帯別**: " + " ／ ".join(sess_parts)

        # ブロック③: 過去24時間の値動き・マクロ要因 ＆ 投資家心理
        h24 = float(eval_data.get("high_24h", 0))
        l24 = float(eval_data.get("low_24h", 0))
        r24 = eval_data.get("range_pips_24h", 0)
        ms = eval_data.get("macro_state") or {}
        b3_text = (
            f"• **24hレンジ**: 高値 `${h24:.2f}` 〜 安値 `${l24:.2f}` (変動幅 **`{r24} pips`**) | H1: `{eval_data.get('h1_trend')}` / M15: `{eval_data.get('m15_trend')}`\n"
            f"• **先行指標**: Source `{ms.get('source', 'MT5_M1')}` (DXY Z: `{ms.get('dxy_z',0):+.2f}`, 金利 Z: `{ms.get('yield_z',0):+.2f}`, Bias: `{ms.get('macro_bias_score',0):+.2f}`)\n"
            f"> {eval_data.get('market_narrative_ja') or eval_data.get('frequency_reason', '分析中')}"
        )

        # ブロック④: ベスト/ワースト敗因解剖 ＆ 防御エンジン実績
        df_s = eval_data.get("defense_stats") or {}
        b4_text = (
            f"• **ベスト**: `{eval_data.get('best_trade_desc', 'なし')}` ／ **ワースト**: `{eval_data.get('worst_trade_desc', 'なし')}`\n"
            f"• **🛡️ 防御エンジン救済実績**: マクロ逆行ブロック `{df_s.get('hard_guard',0)}回` ／ 連敗防止クールダウン `{df_s.get('sl_cooldown',0)}回` ／ 建値移動(BE)救済 `{df_s.get('break_even',0)}回` (推定 **`¥{float(df_s.get('est_saved_jpy',0)):,.0f}`** の被弾を回避)\n"
            f"> {eval_data.get('trade_autopsy_ja') or eval_data.get('regime_fit', '分析中')}"
        )

        # ブロック⑤: パラメータ自己最適化の具体差分 ＆ レジーム状態
        bp = eval_data.get("before_params") or {}
        ap = eval_data.get("after_params") or bp
        opt_summary = eval_data.get("optimization_summary", "現状維持")
        b5_text = (
            f"• **現在レジーム**: `{eval_data.get('active_regime', 'REGIME_NORMAL_FLOW')}`\n"
            f"• **主要設定値**: SMC_RR `1:{ap.get('min_risk_reward_ratio', 1.5)}` | 型A_RR `1:{ap.get('macro_min_rr', 1.8)}` | 型B_RR `1:{ap.get('smt_min_rr', 2.0)}` | 型A_Z閾値 `{ap.get('momentum_z_threshold', 1.5)}` | ヒゲ閾値 `{ap.get('wick_ratio_threshold', 0.25)}` | ATR倍率 `{ap.get('atr_sl_multiplier', 1.3)}`\n"
            f"> {opt_summary}"
        )

        # ブロック⑥: 本日のセッション展望（ボラ余力・重要ライン）＆ AIプロデューサー提案
        pdh = eval_data.get("pdh")
        pdl = eval_data.get("pdl")
        lvl_txt = f"前日高値(PDH): `${pdh:.2f}` ／ 前日安値(PDL): `${pdl:.2f}`" if (pdh and pdl) else "主要フラクタル高安を監視"
        dash_url = settings.get_dashboard_url() if hasattr(settings, "get_dashboard_url") else "http://155.133.7.59/dashboard"
        b6_text = (
            f"• **注目流動性ターゲット**: {lvl_txt}\n"
            f"• **📈 本日の立ち回り・ボラ余力**: {eval_data.get('session_outlook_ja', '上位足順張り継続')}\n"
            f"• **🎬 AIプロデューサー提案**: {eval_data.get('producer_proposal_ja') or eval_data.get('lessons_learned', '')}\n"
            f"• **📱 ワンタップ管理画面**: [**👉 スマホでクオンツ管理ダッシュボードを開く（検証・方針変更・口座切替）**]({dash_url})"
        )

        embed = {
            "title": f"📋 【XAU/USD ヘッジファンド日次運用ブリーフィング】 ({eval_data.get('date')})",
            "color": color,
            "fields": [
                {"name": "① 💰 エグゼクティブ損益 ＆ 口座スコアカード", "value": b1_text, "inline": False},
                {"name": "② ⚙️ 3系統エンジン別 ＆ 時間帯別（東京・ロンドン・NY）戦績", "value": b2_text, "inline": False},
                {"name": "③ 🌍 過去24時間の値動き・マクロ要因 ＆ 投資家心理", "value": b3_text, "inline": False},
                {"name": "④ 🔍 ベスト/ワースト解剖 ＆ 🛡️ 防御エンジン救済実績", "value": b4_text, "inline": False},
                {"name": "⑤ 🎛️ パラメータ自己最適化 ＆ 動的レジーム設定", "value": b5_text, "inline": False},
                {"name": "⑥ 🎬 本日のセッション展望 ＆ AIプロデューサー改善提案", "value": b6_text, "inline": False},
            ],
            "footer": {"text": f"Autonomous Hedge Fund PDCA Engine v9.1 (3-Engine Max 3-Pos) • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        }
        self._post_webhook([embed])

    def send_weekend_research_report(self, study_data: Dict[str, Any], weekly_stats: Optional[Dict[str, Any]] = None):
        """
        【毎週土曜 08:00 JST 配信】週末クオンツ自動検証研究室レポート送信
        """
        if not self.webhook_url or not study_data:
            return

        w_stats = weekly_stats or {}
        w_pnl = float(w_stats.get("total_profit", 0))
        w_cnt = w_stats.get("total_count", 0)
        w_tw = w_stats.get("true_wins", 0)
        w_tl = w_stats.get("true_losses", 0)
        w_be = w_stats.get("be_count", 0)
        w_wr = w_stats.get("win_rate_pct", 0.0)
        w_pf = w_stats.get("profit_factor", 1.0)

        corrs = study_data.get("correlations_15m", {})
        weights = study_data.get("recommended_weights", {})
        sc = study_data.get("conditional_scenarios", {})
        ll = study_data.get("lead_lag_profile", {})
        hb = ll.get("horizon_breakdown", {})

        # 1. 週間トレード総決算
        engs = w_stats.get("engines", {})
        eng_summary = " / ".join(
            [f"{v.get('label', k)}: `¥{float(v.get('pnl',0)):+,.0f}`" for k, v in engs.items()]
        ) if engs else "集計中"
        f1_text = (
            f"• **週間総損益**: **`¥{w_pnl:+,.0f}`** (`{w_cnt}戦 {w_tw}勝 {w_tl}敗 {w_be}建値` / 実質勝率 **`{w_wr}%`** / **PF `{w_pf}`**)\n"
            f"• **エンジン別貢献**: {eng_summary}"
        )

        # 2. 最新15分リターン相関係数 ＆ 翌週の自動適用ウェイト
        corr_lines = [f"`{k}`: **`{v:+.3f}`**" for k, v in sorted(corrs.items(), key=lambda item: abs(item[1]), reverse=True)]
        f2_text = (
            f"• **対XAUUSD相関係数 (M5足 {study_data.get('m5_bars_analyzed', 0)}本)**: " + " ｜ ".join(corr_lines) + "\n"
            f"• **⚙️ 翌週へ自動適用された最適ウェイト**: ドル指数(`DXY`) = **`{weights.get('dxy_weight', 0.5):.2f}`** ／ 米金利(`US10Y/USDJPY`) = **`{weights.get('yield_weight', 0.5):.2f}`**"
        )

        # 3. 複合シナリオ勝率マトリクス
        b_down = sc.get("both_down_gold_bull", {})
        b_up = sc.get("both_up_gold_bear", {})
        c_yd = sc.get("yield_down_dxy_up_conflict", {})
        c_du = sc.get("dxy_down_yield_up_conflict", {})
        o_geo = sc.get("oil_up_geopolitical_risk_off", {})
        o_inf = sc.get("oil_up_inflation_yield_up", {})
        f3_text = (
            f"• `DXY↓ × 金利↓` (全面追い風): 上昇率 **`{b_down.get('up_rate_pct',0)}%`** (15m平均 `{b_down.get('avg_pips_15m',0):+.1f} pips`, n={b_down.get('samples',0)})\n"
            f"• `DXY↑ × 金利↑` (全面逆風): 下落率 **`{b_up.get('down_rate_pct',0)}%`** (15m平均 `{b_up.get('avg_pips_15m',0):+.1f} pips`, n={b_up.get('samples',0)})\n"
            f"• `DXY↓ × 金利↑` (ねじれ・ドル安優先): 上昇率 **`{c_du.get('up_rate_pct',0)}%`** (15m平均 `{c_du.get('avg_pips_15m',0):+.1f} pips`)\n"
            f"• `金利↓ × DXY↑` (ねじれ・金利安優先): 上昇率 **`{c_yd.get('up_rate_pct',0)}%`** (15m平均 `{c_yd.get('avg_pips_15m',0):+.1f} pips`)\n"
            f"• `原油↑ × 株↓ × 金利↓` (地政学リスクオフ): 上昇率 **`{o_geo.get('up_rate_pct',0)}%`** (`{o_geo.get('avg_pips_15m',0):+.1f} pips`)\n"
            f"• `原油↑ × 金利↑` (インフレ型原油高アノマリー): 下落率 **`{o_inf.get('down_rate_pct',0)}%`** (`{o_inf.get('avg_pips_15m',0):+.1f} pips`)"
        )

        # 4. M1リードラグ（時間差）プロファイル
        lag_parts = []
        for m in (1, 3, 5, 10, 15):
            st = hb.get(f"t_plus_{m}m", {})
            if st:
                lag_parts.append(f"`+{m}分`: 勝率 `{st.get('directional_hit_rate_pct',0)}%` (`{st.get('avg_favorable_pips',0):+.1f}pips`)")
        dash_url = settings.get_dashboard_url() if hasattr(settings, "get_dashboard_url") else "http://155.133.7.59/dashboard"
        f4_text = (
            f"• **ショック後の経過時間別エッジ (M1足 {ll.get('m1_bars_analyzed',0)}本)**:\n  " + " → ".join(lag_parts) + "\n"
            f"• **🎯 最適保有ピーク**: 先行指標急変から **`{ll.get('optimal_peak_lag_minutes', 15)}分後`** (平均 **`{ll.get('peak_avg_favorable_pips', 0):+.1f} pips`**)\n"
            f"• **📱 ワンタップ管理画面**: [**👉 スマホでクオンツ管理ダッシュボードを開く（What-If検証・設定変更）**]({dash_url})"
        )

        embed = {
            "title": f"🔬 【週末クオンツ研究室】週次相関・複合アノマリー・時間差自動検証レポート ({study_data.get('generated_at', '')[:10]})",
            "color": 0x7e57c2,
            "fields": [
                {"name": "① 📊 今週1週間のトレード総決算", "value": f1_text, "inline": False},
                {"name": "② 🔗 最新15分リターン相関係数 ＆ 翌週の自動適用ウェイト", "value": f2_text, "inline": False},
                {"name": "③ 🔀 複合シナリオ実測勝率（「片方が下げて他が上がった時」等）", "value": f3_text, "inline": False},
                {"name": "④ ⏱️ M1リードラグ（時間差：何分後に最も伸びるか）実測波形", "value": f4_text, "inline": False},
            ],
            "footer": {"text": "Weekend Autonomous Quant Research Lab v9.1 • 毎週土曜 08:00 JST 自動更新"}
        }
        self._post_webhook([embed])

    def send_sunday_ic_report(self, meeting_data: Dict[str, Any]):
        """
        【毎週日曜 10:00 JST 配信】6役マルチエージェント投資委員会（ファンダ統合・3択決裁リンク付き）レポート送信
        """
        if not self.webhook_url or not meeting_data:
            return

        m_id = meeting_data.get("meeting_id", "IC_SUNDAY")
        funda = meeting_data.get("fundamental_report") or {}
        debate = meeting_data.get("agent_debate") or {}
        alpha = debate.get("alpha_researcher") or {}
        macro_ex = debate.get("macro_and_execution") or {}
        auditor = debate.get("red_team_auditor") or {}
        cio = debate.get("cio_chairman") or {}
        opts = meeting_data.get("options") or {}
        urls = meeting_data.get("decision_urls") or {}
        prev_exp = meeting_data.get("last_week_experiment_result") or {}
        next_exp = meeting_data.get("next_week_experiment") or {}
        roadmap = meeting_data.get("mid_long_term_roadmap") or []
        q_stat = meeting_data.get("ai_quota_status") or {}

        # ① ファンダメンタルズ＆ニュース因果分析
        f1_text = (
            f"• **今週の値動き×ニュース因果**: {funda.get('this_week_causal_analysis_ja', '分析済')}\n"
            f"• **週末新着ニュース＆来週の重要イベント**: {funda.get('weekend_news_and_next_week_events_ja', '監視中')}\n"
            f"• **🎯 ファンダ推奨フォーカス**: **{funda.get('recommended_focus_ja', '米金利連動重視')}**"
        )[:1000]

        # ② 6役エージェント激論ハイライト（平均化禁止）
        f2_text = (
            f"• **⚡ 核心争点**: `{meeting_data.get('core_agenda_ja', '')}`\n"
            f"• **🎯 アルファ開拓官 (攻め)**: {alpha.get('bold_proposal_ja', '')}\n"
            f"• **🌍 マクロ＆⚡執行官 (構造・現場)**: {macro_ex.get('macro_and_execution_view_ja', '')}\n"
            f"• **🛡️ RedTeam監査官 (反証・過剰適合ブロック)**: {auditor.get('red_team_critique_ja', '')}\n"
            f"• **⚖️ CIO議長裁定**: **{cio.get('cio_verdict_ja', '')}**"
        )[:1000]

        # ③ 妥協なき3つの決裁パッケージ（過去21日DBバックテスト実測付き）
        opt_a = opts.get("A") or {}
        opt_b = opts.get("B") or {}
        opt_c = opts.get("C") or {}
        bt_a = opt_a.get("backtest_21d") or {}
        bt_b = opt_b.get("backtest_21d") or {}
        f3_text = (
            f"• **{opt_a.get('label', '🔥 選択肢A')}**\n"
            f"  └ {opt_a.get('summary_ja', '')} *(21日DB検証: `¥{float(bt_a.get('simulated_pnl_jpy',0)):+,.0f}` / 現行比 `Δ¥{float(bt_a.get('delta_pnl_jpy',0)):+,.0f}`)*\n"
            f"• **{opt_b.get('label', '🛡️ 選択肢B')}**\n"
            f"  └ {opt_b.get('summary_ja', '')} *(21日DB検証: `¥{float(bt_b.get('simulated_pnl_jpy',0)):+,.0f}` / 勝率 `{bt_b.get('simulated_win_rate_pct',0)}%`)*\n"
            f"• **{opt_c.get('label', '🧪 選択肢C')}**\n"
            f"  └ {opt_c.get('summary_ja', '')}"
        )[:1000]

        # ④ 先週の検証答え合わせ ＆ 次週のシャドー検証テーマ
        f4_text = (
            f"• **先週の検証採点**: `{prev_exp.get('experiment_title', '週次検証')}` → {prev_exp.get('verdict', '完了')}\n"
            f"• **🔬 次週（来週1週間）の新シャドー検証テーマ**: **`{next_exp.get('title', '')}`**\n"
            f"  └ 仮説: {next_exp.get('hypothesis', '')}"
        )[:1000]

        # ⑤ 中長期（1〜3ヶ月）の修正方針ロードマップ
        rm_lines = []
        for item in roadmap[:3]:
            rm_lines.append(f"• **[優先度:{item.get('priority', 'A')}] {item.get('title', '')}** (`{item.get('status', '計画中')}`)\n  └ {item.get('rationale', '')}")
        f5_text = ("\n".join(rm_lines) if rm_lines else "• 中長期構造ロードマップ継続監視中")[:1000]

        # ⑥ オーナー決裁ワンタップリンク（HMAC署名付き）
        dash_url = settings.get_dashboard_url() if hasattr(settings, "get_dashboard_url") else "http://155.133.7.59/dashboard"
        f6_text = (
            f"🟢 [**👉 🔥【選択肢A：攻めの改革案】を承認して本番適用**]({urls.get('A', dash_url)})\n"
            f"🛡️ [**👉 🛡️【選択肢B：守りの堅牢案】を承認して本番適用**]({urls.get('B', dash_url)})\n"
            f"🧪 [**👉 🧪【選択肢C：本番はB＋裏シャドーでAを実験】を採択 (★CIO推奨)**]({urls.get('C', dash_url)})\n"
            f"🔴 [**👉 ❌【すべて却下】今週は変更せず完全現状維持**]({urls.get('REJECT', dash_url)})\n"
            f"📱 [**🌐 ダッシュボードで詳細な議論ログ・パラメータを確認する**]({dash_url})"
        )[:1000]

        models_info = " / ".join(meeting_data.get("models_used", [])[:3])
        footer_txt = (
            f"Sunday AI Investment Committee ({m_id}) • "
            f"Quota余裕度: {q_stat.get('pro_quota_health_pct', 100)}% ({q_stat.get('recommended_tier_label', 'Tier 1')}) • {models_info}"
        )[:200]

        embed = {
            "title": f"🏛️ 【日曜AI投資委員会】6役エージェント激論＆来週方針の決裁要請 ({meeting_data.get('held_at', '')[:10]})",
            "color": 0xf59e0b,
            "fields": [
                {"name": "① 📰 ファンダメンタルズ分析（今週のニュース因果 ＆ 週末ニュース・来週イベント）", "value": f1_text, "inline": False},
                {"name": "② 🗣️ 6役エージェント激論ハイライト（折衷案・平均化禁止）", "value": f2_text, "inline": False},
                {"name": "③ ⚔️ 来週の戦術パッケージ（実測DBバックテスト証拠付き3択）", "value": f3_text, "inline": False},
                {"name": "④ 🔬 先週の検証結果 ＆ 次週（来週1週間）のシャドー検証テーマ", "value": f4_text, "inline": False},
                {"name": "⑤ 🗺️ 中長期（1〜3ヶ月）のロジック構造修正ロードマップ", "value": f5_text, "inline": False},
                {"name": "⑥ 👑 オーナー決裁アクション（ワンタップで来週の方針を確定・暗号署名保護）", "value": f6_text, "inline": False},
            ],
            "footer": {"text": footer_txt},
        }
        self._post_webhook([embed])

    def send_ic_decision_confirmation(
        self,
        meeting_data: Dict[str, Any],
        choice: str,
        option_data: Dict[str, Any],
        source: str,
    ):
        """オーナーがDiscordまたはダッシュボードから投資委員会の提案を決裁した際の即時アンサー通知"""
        if not self.webhook_url:
            return
        color = 0x10b981 if choice != "REJECT" else 0x64748b
        params_str = json.dumps(option_data.get("params") or {}, ensure_ascii=False)
        next_exp = (meeting_data.get("next_week_experiment") or {}).get("title", "シャドー検証継続")
        embed = {
            "title": f"✅ 【投資委員会・オーナー決裁完了】 選択肢 [{choice}] を適用しました",
            "color": color,
            "description": (
                f"**採択パッケージ**: {option_data.get('label', choice)}\n"
                f"**適用内容**: {option_data.get('summary_ja', '')}\n"
                f"**反映パラメータ**: `{params_str}`\n"
                f"**次週シャドー検証テーマ**: `{next_exp}`\n"
                f"**決裁経路**: `{source}` (`{meeting_data.get('meeting_id', '')}`)"
            ),
            "footer": {"text": f"XAU/USD AI Investment Committee • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"},
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
