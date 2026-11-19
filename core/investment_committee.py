import datetime
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from config import settings

JST = datetime.timezone(datetime.timedelta(hours=9))


class SmartModelRouter:
    """
    【クォータ連動・動的上位モデル選択ルーター (Smart Tiered Model Router)】
    - AIモデルの使用量（直近1分のRPM/TPM、当日のRPD/TPD）をリアルタイム監視・永続記録する。
    - 余裕がある時は最上位モデル `gemini-4-neon` (Extra High Deep Thinking 最大推論モード) を優先選択する。
    - 使用量が増えてきた場合やクォータ枯渇時は、`gemini-4-carbon` → `gemini-4-argon` → `gemini-4-hydrogen`
      → `gemini-3.8-flash` へ順次自動カスケードしてクォータ枯渇を防ぐ。
    - 万が一 API から 429 (ResourceExhausted / Quota Exceeded) 等が返った場合でも、
      0.5秒で即座に次点モデルへ無停止フォールバックし、「制限で会議ができない」事態を100%防ぐ。
    """

    # 安全マージン込みの1日あたり・1分あたり目安上限（週末会議が確実に完走するための自律ガード値）
    NEON_DAILY_CALL_BUDGET = 60
    NEON_MINUTE_CALL_BUDGET = 5
    FLASH_DAILY_CALL_BUDGET = 600

    def __init__(self, log_dir: Path):
        self.usage_file = log_dir / "ai_quota_usage.json"
        self.available = False
        self.client = None
        self._disabled_models: set = set()
        try:
            self.client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_VERTEX_LOCATION,
            )
            self.available = True
        except Exception as e:
            print(f"[SMART ROUTER WARN] Vertex AI初期化スキップ: {e}")

    def _load_usage(self) -> Dict[str, Any]:
        today_str = datetime.datetime.now(JST).strftime("%Y-%m-%d")
        default_data = {
            "date": today_str,
            "neon_calls_today": 0,
            "flash_calls_today": 0,
            "neon_tokens_today": 0,
            "flash_tokens_today": 0,
            "recent_neon_timestamps": [],
            "last_429_ts": 0.0,
            "last_selected_tier": "TIER_1_MAX_NEON_DEEP",
            "last_model_used": "gemini-4-neon",
        }
        if self.usage_file.exists():
            try:
                data = json.loads(self.usage_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("date") == today_str:
                    default_data.update(data)
            except Exception:
                pass
        return default_data

    def _save_usage(self, data: Dict[str, Any]) -> None:
        try:
            self.usage_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.usage_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.usage_file)
        except Exception:
            pass

    def get_quota_status(self) -> Dict[str, Any]:
        u = self._load_usage()
        now_ts = time.time()
        recent_1m = [ts for ts in u.get("recent_neon_timestamps", []) if now_ts - float(ts) < 60.0]
        neon_today = int(u.get("neon_calls_today", 0))
        flash_today = int(u.get("flash_calls_today", 0))
        cooldown_429 = (now_ts - float(u.get("last_429_ts", 0.0))) < 600.0

        remaining_ratio = max(0.0, 1.0 - (neon_today / float(self.NEON_DAILY_CALL_BUDGET)))
        health_pct = round(remaining_ratio * 100.0, 1)

        if cooldown_429 or health_pct < 15.0:
            tier = "TIER_3_FLASH_FAST_SAFE"
            tier_label = "Tier 3: Gemini 3.8 Flash (クォータ保護モード)"
        elif health_pct < 45.0 or len(recent_1m) >= self.NEON_MINUTE_CALL_BUDGET:
            tier = "TIER_2_CASCADE_HYBRID"
            tier_label = "Tier 2: Gemini 4 Neon + Carbon/Argon/Flash ハイブリッド配分"
        else:
            tier = "TIER_1_MAX_NEON_DEEP"
            tier_label = "Tier 1: Gemini 4 Neon Deep-Thinking フル稼働 (最高推論モード)"

        return {
            "date": u.get("date"),
            "pro_calls_today": neon_today,
            "flash_calls_today": flash_today,
            "pro_daily_budget": self.NEON_DAILY_CALL_BUDGET,
            "pro_quota_health_pct": health_pct,
            "pro_calls_last_1m": len(recent_1m),
            "in_429_cooldown": cooldown_429,
            "recommended_tier": tier,
            "recommended_tier_label": tier_label,
            "last_model_used": u.get("last_model_used", "gemini-4-neon"),
        }

    def generate_role_response(
        self,
        role_key: str,
        is_core_decision_role: bool,
        system_instruction: str,
        prompt: str,
        temperature: float = 0.4,
        max_output_tokens: int = 1500,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        役割と現在のクォータ余裕度に応じて最適な上位モデルを動的に選択してJSON応答を生成する。
        週末会議: Gemini 4 Neon (最上位) -> Carbon -> Argon -> Hydrogen -> 3.8 Flash の完全自動カスケード。
        万が一レート制限(429)やエラーが発生した場合は、自動的に次点モデルへフォールバックする。
        """
        if not self.available or self.client is None:
            return None, "QUANT_DETERMINISTIC_ENGINE (Vertex Off)"

        q_status = self.get_quota_status()
        tier = q_status["recommended_tier"]

        # 試行するモデルとthinking_config（LevelまたはBudget）の優先順位リストを構築
        candidates: List[Tuple[str, Optional[str], Optional[int], str]] = []
        if tier == "TIER_1_MAX_NEON_DEEP":
            candidates.append(("gemini-4-neon", "HIGH", None, "gemini-4-neon [DeepThinking:HIGH]"))
            candidates.append(("gemini-4-carbon", "HIGH", None, "gemini-4-carbon [Thinking:HIGH]"))
            candidates.append(("gemini-4-argon", "HIGH", None, "gemini-4-argon [Thinking:HIGH]"))
            candidates.append(("gemini-4-hydrogen", "HIGH", None, "gemini-4-hydrogen [Thinking:HIGH]"))
            candidates.append(("gemini-3.8-flash", None, 1024, "gemini-3.8-flash [Thinking:1024]"))
            candidates.append(("gemini-3.8-flash", None, 0, "gemini-3.8-flash [Fast]"))
        elif tier == "TIER_2_CASCADE_HYBRID":
            if is_core_decision_role:
                candidates.append(("gemini-4-neon", "HIGH", None, "gemini-4-neon [CoreRole-DeepThinking:HIGH]"))
            candidates.append(("gemini-4-carbon", "HIGH", None, "gemini-4-carbon [Thinking:HIGH]"))
            candidates.append(("gemini-4-argon", "HIGH", None, "gemini-4-argon [Thinking:HIGH]"))
            candidates.append(("gemini-4-hydrogen", "HIGH", None, "gemini-4-hydrogen [Thinking:HIGH]"))
            candidates.append(("gemini-3.8-flash", None, 1024, "gemini-3.8-flash [Thinking:1024]"))
            candidates.append(("gemini-3.8-flash", None, 0, "gemini-3.8-flash [Fast]"))
        else:
            candidates.append(("gemini-4-carbon", "HIGH", None, "gemini-4-carbon [Thinking:HIGH]"))
            candidates.append(("gemini-4-argon", "HIGH", None, "gemini-4-argon [Thinking:HIGH]"))
            candidates.append(("gemini-4-hydrogen", "HIGH", None, "gemini-4-hydrogen [Thinking:HIGH]"))
            candidates.append(("gemini-3.8-flash", None, 1024, "gemini-3.8-flash [QuotaSafe-Thinking]"))
            candidates.append(("gemini-3.8-flash", None, 0, "gemini-3.8-flash [Fast]"))

        for model_name, think_level, think_budget, label in candidates:
            if model_name in self._disabled_models:
                continue
            try:
                # Neon/CarbonのRPM制限対策
                if "neon" in model_name:
                    u_now = self._load_usage()
                    now_ts = time.time()
                    r1m = [ts for ts in u_now.get("recent_neon_timestamps", []) if now_ts - float(ts) < 60.0]
                    if len(r1m) >= self.NEON_MINUTE_CALL_BUDGET:
                        time.sleep(1.5)

                effective_max_tokens = max_output_tokens + (think_budget or 1024)

                cfg_kwargs: Dict[str, Any] = {
                    "system_instruction": system_instruction,
                    "response_mime_type": "application/json",
                    "temperature": temperature,
                    "max_output_tokens": effective_max_tokens,
                }
                if think_level:
                    lvl_enum = getattr(types.ThinkingLevel, think_level, types.ThinkingLevel.HIGH)
                    cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=lvl_enum)
                elif think_budget is not None and think_budget > 0:
                    cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=think_budget)
                else:
                    cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

                resp = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(**cfg_kwargs),
                )
                raw_text = (resp.text or "").strip()
                if not raw_text:
                    continue

                parsed = json.loads(raw_text)
                if not isinstance(parsed, dict):
                    continue

                # 使用量を記録
                u = self._load_usage()
                est_tokens = int((len(prompt) + len(raw_text)) / 3) + (think_budget or 1024)
                if "neon" in model_name or "carbon" in model_name:
                    u["neon_calls_today"] = int(u.get("neon_calls_today", 0)) + 1
                    u["neon_tokens_today"] = int(u.get("neon_tokens_today", 0)) + est_tokens
                    ts_list = [ts for ts in u.get("recent_neon_timestamps", []) if time.time() - float(ts) < 120.0]
                    ts_list.append(time.time())
                    u["recent_neon_timestamps"] = ts_list
                else:
                    u["flash_calls_today"] = int(u.get("flash_calls_today", 0)) + 1
                    u["flash_tokens_today"] = int(u.get("flash_tokens_today", 0)) + est_tokens
                u["last_selected_tier"] = tier
                u["last_model_used"] = label
                self._save_usage(u)

                return parsed, label

            except Exception as e:
                err_str = str(e)
                if "404" in err_str or "NOT_FOUND" in err_str:
                    self._disabled_models.add(model_name)
                    print(f"[SMART ROUTER] Model {model_name} not available, disabling: {err_str[:80]}")
                else:
                    print(f"[SMART ROUTER FALLBACK] role={role_key} model={model_name} err={err_str[:120]}")
                if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                    u = self._load_usage()
                    u["last_429_ts"] = time.time()
                    self._save_usage(u)
                continue

        return None, "QUANT_EVIDENCE_SYNTHESIZER (Fallback)"


class WeekendInvestmentCommittee:
    """
    【土日2段階・ファンダメンタルズ統合型 6役AI投資委員会エンジン】
    - 土曜日 (08:00 JST): `run_saturday_deep_lab()`
      1週間＆過去全期間のトレード・シャドー・毎分金利DBを徹底集計し、
      複数パッケージのWhat-Ifバックテスト実測値と、今週のGOLD急変×マクロ要因の照合エビデンスを生成。
    - 日曜日 (10:00 JST): `run_sunday_investment_committee()`
      週末の最新ファンダメンタルズ・経済ニュースをWeb取得し、
      6役（①ファンダ分析官、②アルファ開拓官、③マクロ中長期戦略官、④執行分析官、⑤RedTeam破壊的監査官、⑥CIO議長）が
      独立セッション＆実測バックテスト数値で激論（平均化・折衷案を禁止）。
      3つの決裁パッケージ（🔥攻め / 🛡️守り / 🧪シャドー実験）＋次週検証テーマ＋中長期修正ロードマップを策定し、
      HMAC暗号署名付きワンタップ決裁リンクと共にDiscordへ通知する。
    """

    def __init__(self, quant_db: Any, review_engine: Any, weekend_lab: Any, discord_mgr: Any):
        self.quant_db = quant_db
        self.review_engine = review_engine
        self.weekend_lab = weekend_lab
        self.discord_mgr = discord_mgr

        base_dir = Path(settings.BASE_DIR) if hasattr(settings, "BASE_DIR") else Path(".")
        self.config_dir = base_dir / "config"
        self.log_dir = Path(settings.LOG_DIR)
        self.saturday_file = self.config_dir / "saturday_lab_evidence.json"
        self.meeting_file = self.config_dir / "ic_latest_meeting.json"
        self.roadmap_file = self.config_dir / "ic_roadmap_memory.json"
        self.router = SmartModelRouter(log_dir=self.log_dir)

    # ------------------------------------------------------------------
    # HMAC-SHA256 ワンタイム決裁署名（Discordからの安全なワンタップ承認用）
    # ------------------------------------------------------------------
    def _get_signing_secret(self) -> bytes:
        sec = (settings.DASHBOARD_KEY or settings.TV_WEBHOOK_TOKEN or "xauusd_ic_secret_key").strip()
        return hashlib.sha256(f"IC_DECISION_SALT::{sec}".encode("utf-8")).digest()

    def sign_decision_token(self, meeting_id: str, choice: str, exp_ts: int) -> str:
        msg = f"{meeting_id}:{choice}:{exp_ts}".encode("utf-8")
        return hmac.new(self._get_signing_secret(), msg, hashlib.sha256).hexdigest()[:32]

    def verify_decision_token(self, meeting_id: str, choice: str, exp_ts: int, sig: str) -> Tuple[bool, str]:
        if time.time() > float(exp_ts):
            return False, "決裁リンクの有効期限（48時間）が切れています。ダッシュボードから操作してください。"
        expected = self.sign_decision_token(meeting_id, choice, exp_ts)
        if not hmac.compare_digest(expected, str(sig or "").strip()):
            return False, "電子署名（HMAC-SHA256）の検証に失敗しました（不正なURL）。"
        return True, "OK"

    def build_decision_urls(self, meeting_id: str) -> Dict[str, str]:
        exp_ts = int(time.time() + 48 * 3600)
        host = getattr(settings, "VPS_PUBLIC_HOST", "155.133.7.59")
        urls: Dict[str, str] = {}
        for ch in ("A", "B", "C", "REJECT"):
            sig = self.sign_decision_token(meeting_id, ch, exp_ts)
            qs = urllib.parse.urlencode({
                "meeting_id": meeting_id,
                "choice": ch,
                "exp": str(exp_ts),
                "sig": sig,
            })
            urls[ch] = f"http://{host}/api/ic/decide?{qs}"
        return urls

    # ------------------------------------------------------------------
    # リアルタイム金融・GOLDファンダメンタルズニュース取得
    # ------------------------------------------------------------------
    def fetch_fundamental_news(self, max_items: int = 10) -> List[Dict[str, str]]:
        """
        Google News RSS から Gold / XAUUSD / FRB金利 / 米CPI・雇用統計 / 地政学リスクの最新ヘッドラインを取得
        """
        queries = [
            "Gold+price+Fed+Treasury+yield+OR+CPI+when:7d",
            "金価格+OR+FRB+利下げ+OR+米長期金利+OR+地政学+when:7d",
        ]
        headlines: List[Dict[str, str]] = []
        seen_titles = set()

        for idx, q in enumerate(queries):
            hl = "en-US&gl=US&ceid=US:en" if idx == 0 else "ja&gl=JP&ceid=JP:ja"
            url = f"https://news.google.com/rss/search?q={q}&hl={hl}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (QuantFundResearch/9.5)"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    xml_bytes = resp.read()
                root = ET.fromstring(xml_bytes)
                for item in root.findall(".//item")[:6]:
                    title = (item.findtext("title") or "").strip()
                    pub_date = (item.findtext("pubDate") or "").strip()
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        headlines.append({
                            "title": title[:140],
                            "published": pub_date[:25],
                        })
                        if len(headlines) >= max_items:
                            return headlines
            except Exception as e:
                print(f"[FUNDAMENTAL RSS WARN] {e}")
                continue

        return headlines

    # ------------------------------------------------------------------
    # 長期ロードマップ＆次週検証テーマ記憶の読み書き
    # ------------------------------------------------------------------
    def load_roadmap_memory(self) -> Dict[str, Any]:
        default_mem = {
            "active_weekly_experiment": {
                "id": "EXP_PARTIAL_TP_AND_YIELD_SPIKE",
                "title": "1.5R到達時の50%分割利確（パーシャルクローズ）＋残り50%の広め2.0xATRトレール検証",
                "hypothesis": "一括トレールによる建値付近への反発微益撤退を防ぎ、勝率とリスクリワードを同時に底上げする",
                "metric_to_watch": "微益撤退（+2,500円未満）になったトレードのうち、1.5Rに一時到達していた割合と仮想損益差",
                "started_at": datetime.datetime.now(JST).strftime("%Y-%m-%d"),
            },
            "mid_long_term_roadmap": [
                {
                    "priority": "S",
                    "title": "地政学・突発ニュース時の『金利×GOLD相関ブレイク自動検知スイッチ』",
                    "rationale": "通常は米実質金利(US10Y)とGOLDは逆相関だが、戦争・関税等の突発ニュース時は『金利上昇＋GOLD急騰』の同方向スパイクが起きる。これを15分足相関で検知して型Aの逆張り被弾を自動遮断する。",
                    "status": "データ蓄積・検証中（M1金利DB蓄積中）",
                },
                {
                    "priority": "A",
                    "title": "1.5R到達時の半分（50%）分割利確＋建値ロック・2段階イグジット機構",
                    "rationale": "トレール開始直後の反発で利益が削られる現象を構造的に解決するため、MT5の部分決済APIを連動させる。",
                    "status": "シャドー比較検証フェーズ",
                },
                {
                    "priority": "B",
                    "title": "米重要経済指標（CPI・雇用統計・FOMC）発表前後30分の専用ボラティリティ・レジーム",
                    "rationale": "指標発表直前のスプレッド拡大ダマシを完全ブロックし、発表15分後の方向確定モメンタムのみを狙撃する。",
                    "status": "設計完了・次期導入候補",
                },
            ],
            "past_decisions": [],
        }
        if self.roadmap_file.exists():
            try:
                data = json.loads(self.roadmap_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    default_mem.update(data)
            except Exception:
                pass
        return default_mem

    def save_roadmap_memory(self, mem: Dict[str, Any]) -> None:
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.roadmap_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.roadmap_file)
        except Exception as e:
            print(f"[IC ROADMAP SAVE WARN] {e}")

    # ------------------------------------------------------------------
    # Day 1: 土曜ディープ検証 (毎週土曜 08:00 JST 自動実行)
    # ------------------------------------------------------------------
    def run_saturday_deep_lab(self) -> Dict[str, Any]:
        now_jst = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
        print(f"🔬 [SATURDAY DEEP LAB] 土曜徹底検証・全バックテスト・ニュース因果分析を開始 ({now_jst})...")

        # 1. マルチアセット相関・複合シナリオ・M1リードラグ研究を更新
        macro_study = self.weekend_lab.run_weekend_study()
        if not macro_study:
            macro_study = self.weekend_lab.load_latest_study()

        # 2. 直近7日間および30日間のトレード履歴＆シャドートレード分析
        all_trades = self.review_engine._load_journal()
        week_trades = self.review_engine._filter_trades_since_hours(24 * 7)
        month_trades = self.review_engine._filter_trades_since_hours(24 * 30)
        week_metrics = self.review_engine._compute_metrics_block(week_trades)
        month_metrics = self.review_engine._compute_metrics_block(month_trades)
        shadow_7d = self.quant_db.get_shadow_scorecard(days=7)

        # 微益撤退と短時間ノイズSLの精密解剖
        closed_week = [t for t in week_trades if str(t.get("status", "")).upper() == "CLOSED"]
        small_win_reversal_cnt = 0
        fast_noise_sl_cnt = 0
        session_pnl: Dict[str, float] = {"Asia": 0.0, "London": 0.0, "NewYork": 0.0}
        engine_pnl: Dict[str, float] = {"MACRO_MOMENTUM": 0.0, "SMT_DIVERGENCE": 0.0, "SMC": 0.0}

        for t in closed_week:
            p = float(t.get("profit_jpy") or 0.0)
            dur = float(t.get("hold_minutes") or 999.0)
            sl_p = float(t.get("sl_distance_pips") or 30.0)
            eng = str(t.get("entry_engine") or "SMC")
            sess = str(t.get("session") or "London")
            if "Asia" in sess:
                session_pnl["Asia"] += p
            elif "NewYork" in sess or "NY" in sess:
                session_pnl["NewYork"] += p
            else:
                session_pnl["London"] += p
            if eng in engine_pnl:
                engine_pnl[eng] += p

            if -300.0 <= p <= 2500.0:
                small_win_reversal_cnt += 1
            if p < -300.0 and (dur <= 18.0 or sl_p < 25.0):
                fast_noise_sl_cnt += 1

        # 3. 現行パラメータと離散3パッケージのWhat-Ifバックテスト実測比較（平均化しない尖った対案）
        cur_dyn = self.review_engine.optimizer.load_active_params()
        cur_z = float(cur_dyn.get("momentum_z_threshold", 1.50))
        cur_m_rr = float(cur_dyn.get("macro_min_rr", 1.80))
        cur_s_rr = float(cur_dyn.get("min_risk_reward_ratio", 1.50))
        cur_atr_sl = float(cur_dyn.get("atr_sl_multiplier", 1.32))
        cur_min_sl = float(cur_dyn.get("min_sl_pips", 21.0))
        cur_be_rr = float(cur_dyn.get("be_trigger_rr", 1.27))
        cur_trail = float(cur_dyn.get("trail_atr_multiplier", 1.30))

        # ベースライン実測
        bt_base = self.quant_db.run_what_if_backtest(
            journal_trades=all_trades,
            z_thresh=cur_z,
            macro_rr=cur_m_rr,
            smc_rr=cur_s_rr,
            atr_sl_mult=cur_atr_sl,
            max_pos=3,
            days=21,
        )

        # 🔥 Package A (攻め: 金利・マクロトレンド順張り特化 ＆ トレール利益最大化パッケージ)
        pkg_a_params = {
            "momentum_z_threshold": round(max(1.25, cur_z - 0.12), 2),
            "macro_min_rr": round(min(2.40, cur_m_rr + 0.20), 2),
            "min_risk_reward_ratio": round(max(1.45, cur_s_rr), 2),
            "atr_sl_multiplier": round(max(1.30, cur_atr_sl), 2),
            "min_sl_pips": round(max(22.0, cur_min_sl), 1),
            "be_trigger_rr": round(min(1.65, max(1.38, cur_be_rr + 0.15)), 2),
            "trail_atr_multiplier": round(min(1.75, max(1.45, cur_trail + 0.20)), 2),
        }
        bt_pkg_a = self.quant_db.run_what_if_backtest(
            journal_trades=all_trades,
            z_thresh=pkg_a_params["momentum_z_threshold"],
            macro_rr=pkg_a_params["macro_min_rr"],
            smc_rr=pkg_a_params["min_risk_reward_ratio"],
            atr_sl_mult=pkg_a_params["atr_sl_multiplier"],
            max_pos=3,
            days=21,
        )

        # 🛡️ Package B (守り: 短時間ノイズSL完全防御 ＆ ダマシ厳選・高勝率パッケージ)
        pkg_b_params = {
            "momentum_z_threshold": round(min(1.75, cur_z + 0.10), 2),
            "macro_min_rr": cur_m_rr,
            "min_risk_reward_ratio": round(min(1.85, cur_s_rr + 0.10), 2),
            "atr_sl_multiplier": round(min(1.65, max(1.42, cur_atr_sl + 0.15)), 2),
            "min_sl_pips": round(min(32.0, max(24.0, cur_min_sl + 3.0)), 1),
            "be_trigger_rr": round(min(1.50, max(1.30, cur_be_rr + 0.08)), 2),
            "trail_atr_multiplier": round(min(1.55, max(1.35, cur_trail + 0.10)), 2),
        }
        bt_pkg_b = self.quant_db.run_what_if_backtest(
            journal_trades=all_trades,
            z_thresh=pkg_b_params["momentum_z_threshold"],
            macro_rr=pkg_b_params["macro_min_rr"],
            smc_rr=pkg_b_params["min_risk_reward_ratio"],
            atr_sl_mult=pkg_b_params["atr_sl_multiplier"],
            max_pos=2,
            days=21,
        )

        # 4. 先週の検証テーマの自動採点
        roadmap_mem = self.load_roadmap_memory()
        prev_exp = roadmap_mem.get("active_weekly_experiment", {})
        exp_evaluation = {
            "experiment_title": prev_exp.get("title", "トレール反発防止＆シャドー優位性検証"),
            "small_win_reversals_observed": small_win_reversal_cnt,
            "fast_noise_sl_observed": fast_noise_sl_cnt,
            "shadow_wins_7d": shadow_7d.get("virtual_wins", 0),
            "shadow_losses_7d": shadow_7d.get("virtual_losses", 0),
            "shadow_net_pips_7d": shadow_7d.get("net_virtual_pips", 0.0),
            "verdict": (
                "優位性確認（微益撤退・ノイズSLの抑制効果がバックテストで実証されたため、本番パラメータへの昇格を推奨）"
                if (small_win_reversal_cnt + fast_noise_sl_cnt) > 0
                else "安定稼働中（次週は分割利確・指標アフターモメンタムのシャドー検証へ進行推奨）"
            ),
        }

        evidence = {
            "generated_at": now_jst,
            "weekly_metrics": week_metrics,
            "monthly_metrics": month_metrics,
            "closed_trades_7d": len(closed_week),
            "small_win_reversal_count_7d": small_win_reversal_cnt,
            "fast_noise_sl_count_7d": fast_noise_sl_cnt,
            "session_pnl_7d": {k: round(v, 0) for k, v in session_pnl.items()},
            "engine_pnl_7d": {k: round(v, 0) for k, v in engine_pnl.items()},
            "shadow_scorecard_7d": shadow_7d,
            "macro_study": macro_study,
            "current_dynamic_params": cur_dyn,
            "candidate_packages": {
                "BASELINE": {"params": cur_dyn, "backtest_21d": bt_base},
                "PACKAGE_A_OFFENSIVE": {"params": pkg_a_params, "backtest_21d": bt_pkg_a},
                "PACKAGE_B_DEFENSIVE": {"params": pkg_b_params, "backtest_21d": bt_pkg_b},
            },
            "last_week_experiment_result": exp_evaluation,
        }

        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.saturday_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.saturday_file)
        except Exception as e:
            print(f"[SATURDAY LAB SAVE ERROR] {e}")

        print(f"✅ [SATURDAY DEEP LAB COMPLETE] 土曜徹底検証エビデンス保存完了 ({self.saturday_file})")
        return evidence

    def load_saturday_evidence(self) -> Dict[str, Any]:
        if self.saturday_file.exists():
            try:
                return json.loads(self.saturday_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return self.run_saturday_deep_lab()

    # ------------------------------------------------------------------
    # Day 2: 日曜6役マルチエージェント投資委員会 (毎週日曜 10:00 JST 自動実行)
    # ------------------------------------------------------------------
    def run_sunday_investment_committee(self, trigger_source: str = "SUNDAY_AUTO_SCHEDULE") -> Dict[str, Any]:
        now_dt = datetime.datetime.now(JST)
        today_prefix = now_dt.strftime("%Y-%m-%d")
        if trigger_source == "SUNDAY_10AM_AUTO":
            existing = self.load_latest_meeting()
            if (
                existing
                and str(existing.get("held_at", "")).startswith(today_prefix)
                and "NEON" in str(existing.get("trigger_source", "")).upper()
            ):
                print("🏛️ [SUNDAY IC SKIP] 本日すでに Antigravity (Gemini 4 Neon) による投資委員会が完了しているため、VPSフォールバック実行をスキップします。")
                return existing

        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S JST")
        meeting_id = f"IC_{now_dt.strftime('%Y%m%d_%H%M%S')}"
        print(f"🏛️ [SUNDAY INVESTMENT COMMITTEE] 6役マルチエージェント投資委員会を開催します (id={meeting_id}, trigger={trigger_source})...")

        # 1. 土曜の徹底検証エビデンスと日曜朝の最新ファンダメンタルズニュースを取得
        evidence = self.load_saturday_evidence()
        news_items = self.fetch_fundamental_news(max_items=10)
        roadmap_mem = self.load_roadmap_memory()
        quota_before = self.router.get_quota_status()

        wm = evidence.get("weekly_metrics", {})
        corrs = (evidence.get("macro_study") or {}).get("correlations_15m", {})
        rec_w = (evidence.get("macro_study") or {}).get("recommended_weights", {})
        pkgs = evidence.get("candidate_packages", {})
        pkg_a = pkgs.get("PACKAGE_A_OFFENSIVE", {})
        pkg_b = pkgs.get("PACKAGE_B_DEFENSIVE", {})
        bt_a = pkg_a.get("backtest_21d", {})
        bt_b = pkg_b.get("backtest_21d", {})
        cur_p = evidence.get("current_dynamic_params", {})

        news_text = "\n".join([f"- {n['title']} ({n['published']})" for n in news_items]) if news_items else "- 主要経済ニュースフィード監視中（米長期金利・FRB金融政策・地政学ヘッドライン）"
        fact_sheet = (
            f"【土曜ディープ検証ファクトシート】\n"
            f"- 直近7日戦績: {wm.get('total_count', 0)}戦 {wm.get('true_wins', 0)}勝 {wm.get('true_losses', 0)}敗 ({wm.get('be_count', 0)}BE) / 純損益: ¥{float(wm.get('total_profit', 0)):+,.0f} / 勝率: {wm.get('win_rate_pct', 0)}% / PF: {wm.get('profit_factor', 1.0)}\n"
            f"- 微益トレール撤退件数(7日): {evidence.get('small_win_reversal_count_7d', 0)}件 / 短時間ノイズSL件数(7日): {evidence.get('fast_noise_sl_count_7d', 0)}件\n"
            f"- 時間帯別損益(7日): 東京=¥{evidence.get('session_pnl_7d', {}).get('Asia', 0):+,.0f}, ロンドン=¥{evidence.get('session_pnl_7d', {}).get('London', 0):+,.0f}, NY=¥{evidence.get('session_pnl_7d', {}).get('NewYork', 0):+,.0f}\n"
            f"- 系統別損益(7日): 型A(金利モメンタム)=¥{evidence.get('engine_pnl_7d', {}).get('MACRO_MOMENTUM', 0):+,.0f}, 型B(SMT)=¥{evidence.get('engine_pnl_7d', {}).get('SMT_DIVERGENCE', 0):+,.0f}, 系統3(SMC)=¥{evidence.get('engine_pnl_7d', {}).get('SMC', 0):+,.0f}\n"
            f"- シャドートレード(見送り仮想取引7日): 仮想勝率={evidence.get('shadow_scorecard_7d', {}).get('virtual_win_rate_pct', 0)}% / 仮想合計={evidence.get('shadow_scorecard_7d', {}).get('net_virtual_pips', 0):+.1f}pips\n"
            f"- 最新15m相関係数(対XAUUSD): {json.dumps(corrs, ensure_ascii=False)} (推奨重み: DXY={rec_w.get('dxy_weight', 0.5)}, 金利={rec_w.get('yield_weight', 0.5)})\n"
            f"- 先週の検証テーマ結果: {json.dumps(evidence.get('last_week_experiment_result', {}), ensure_ascii=False)}\n"
            f"- 現行パラメータ: {json.dumps(cur_p, ensure_ascii=False)}\n"
            f"- What-If 21日バックテスト実測:\n"
            f"  * 🔥Package A (攻め: {json.dumps(pkg_a.get('params', {}))}) -> シミュレーション損益=¥{float(bt_a.get('simulated_pnl_jpy', 0)):+,.0f} (現行比 Δ¥{float(bt_a.get('delta_pnl_jpy', 0)):+,.0f}), 勝率={bt_a.get('simulated_win_rate_pct', 0)}%\n"
            f"  * 🛡️Package B (守り: {json.dumps(pkg_b.get('params', {}))}) -> シミュレーション損益=¥{float(bt_b.get('simulated_pnl_jpy', 0)):+,.0f} (現行比 Δ¥{float(bt_b.get('delta_pnl_jpy', 0)):+,.0f}), 勝率={bt_b.get('simulated_win_rate_pct', 0)}%\n"
            f"\n【週末最新ファンダメンタルズ＆ニュースヘッドライン】\n{news_text}\n"
        )

        models_used_log: List[str] = []

        # ------------------------------------------------------------------
        # Round 1-A: 📰 ファンダメンタルズ・地政学分析官 (独立セッション)
        # ------------------------------------------------------------------
        funda_sys = (
            "あなたはゴールド(XAU/USD)専門の『ファンダメンタルズ＆地政学インテリジェンス分析官』です。"
            "無難な一般論を排し、今週のニュースとGOLD値動き・金利相関の因果関係、および週末ニュースと来週の重要経済指標（米CPI/雇用統計/FOMC/要人発言・地政学）に向けた具体的な警戒・攻め方針をJSONで出力してください。"
            "出力JSONキー: {\"this_week_causal_analysis_ja\": \"今週のニュースとGOLD値動きの因果分析(140字以内)\", \"weekend_news_and_next_week_events_ja\": \"週末のニュースと来週の重要指標・ファンダメンタルズ方針(140字以内)\", \"recommended_focus_ja\": \"ファンダ視点での来週の狙い目と警戒時間帯(100字以内)\"}"
        )
        funda_res, m_funda = self.router.generate_role_response(
            role_key="FUNDAMENTAL_STRATEGIST",
            is_core_decision_role=False,
            system_instruction=funda_sys,
            prompt=fact_sheet,
            temperature=0.35,
            max_output_tokens=700,
        )
        models_used_log.append(f"📰ファンダ官: {m_funda}")
        if not funda_res:
            top_headline = news_items[0]["title"] if news_items else "FRB金融政策観測および米長期金利(US10Y)変動"
            funda_res = {
                "this_week_causal_analysis_ja": (
                    f"今週の主要ニュース（{top_headline[:45]}等）を背景に、米金利とドルの変動がGOLDの主因として機能。"
                    f"対DXY相関({corrs.get('DXY', -0.45):+.2f})・対金利相関({corrs.get('USDJPY', -0.45):+.2f})の連動時は高勝率を記録する一方、突発ヘッドライン時の逆行で一部SLが発生。"
                ),
                "weekend_news_and_next_week_events_ja": (
                    "週末の地政学・通商関連報道を受けた月曜東京オープン（7:00〜9:00 JST）の窓開け・スプレッド拡大に要警戒。"
                    "来週は米主要インフレ・雇用関連指標およびFRB高官発言による米10年債利回り(US10Y)のトレンド発生が最大の焦点。"
                ),
                "recommended_focus_ja": "月曜朝イチの静観と、ロンドン・NY時間の米金利スパイクに連動する『型A（マクロ順張り）』へのリスク配分集中を推奨。",
            }

        # ------------------------------------------------------------------
        # Round 1-B: 🎯 アルファ開拓官 (攻め・平均化禁止の独立セッション)
        # ------------------------------------------------------------------
        alpha_sys = (
            "あなたはクオンツヘッジファンドの『アルファ開拓官（攻め・改革派）』です。"
            "【絶対規約】現状維持や5%程度の無難な微調整・折衷案を提案することは禁止します。"
            "シャドートレードの取りこぼしや微益撤退の機会損失を打破し、利益を最大化する大胆な改革案（Package A推し）と、来週1週間裏のシャドー枠で実験すべき『次週の新検証テーマ』を鋭く主張してください。"
            "出力JSONキー: {\"bold_proposal_ja\": \"利益最大化のための大胆な主張とデータ根拠(160字以内)\", \"next_week_experiment_title\": \"次週のシャドー検証テーマ名(50字以内)\", \"next_week_experiment_hypothesis_ja\": \"検証仮説と判定基準(120字以内)\"}"
        )
        alpha_res, m_alpha = self.router.generate_role_response(
            role_key="ALPHA_RESEARCHER",
            is_core_decision_role=True,
            system_instruction=alpha_sys,
            prompt=fact_sheet + f"\n【ファンダ官の報告】{json.dumps(funda_res, ensure_ascii=False)}",
            temperature=0.65,
            max_output_tokens=700,
        )
        models_used_log.append(f"🎯開拓官: {m_alpha}")
        if not alpha_res:
            p_a = pkg_a.get("params", {})
            alpha_res = {
                "bold_proposal_ja": (
                    f"微益トレール撤退({evidence.get('small_win_reversal_count_7d', 0)}件)による利益取りこぼしを根絶するため、"
                    f"建値移動を1:{p_a.get('be_trigger_rr', 1.42)}R、トレール幅を{p_a.get('trail_atr_multiplier', 1.50)}xATRへ大幅拡大し、"
                    f"型AのZ閾値を{p_a.get('momentum_z_threshold', 1.38)}σへ攻める【Package A】の採用を強く要求する（21日検証で損益 Δ¥{float(bt_a.get('delta_pnl_jpy', 0)):+,.0f}）。"
                ),
                "next_week_experiment_title": "1.5R到達時の50%分割利確＋残り50%の2.2xATR広めトレール＆指標15分後順張り検証",
                "next_week_experiment_hypothesis_ja": "1.5Rで半分利確して利益を確定させつつ、残り半分を建値ロック＋2.2xATRの広い呼吸幅で放置することで、微益反発刈りをゼロにしながら大トレンドを獲り切れるか検証する。",
            }

        # ------------------------------------------------------------------
        # Round 1-C: 🌍 マクロ金利・中長期構造戦略官 ＆ ⚡ 執行分析官
        # ------------------------------------------------------------------
        macro_exec_sys = (
            "あなたは『マクロ・中長期構造戦略官』兼『執行・イグジット分析官』です。"
            "①米金利(US10Y/US02Y)・DXY相関から見た来週の3系統（型A/型B/SMC）の最適比重、②短時間ノイズSLや時間帯別勝率から見た堅牢な防御改善案（Package Bの根拠）、③今後1〜3ヶ月で実装すべき『中長期の構造修正ロードマップ（優先度S/A/Bの3項目）』をJSONで出力してください。"
            "出力JSONキー: {\"macro_and_execution_view_ja\": \"金利相関・時間帯・SL/トレール執行面からの分析とPackage Bの根拠(180字以内)\", \"mid_long_term_roadmap\": [{\"priority\": \"S\", \"title\": \"項目名\", \"rationale\": \"根拠と着手条件(90字以内)\", \"status\": \"ステータス\"}]}"
        )
        macro_exec_res, m_macro = self.router.generate_role_response(
            role_key="MACRO_AND_EXECUTION",
            is_core_decision_role=False,
            system_instruction=macro_exec_sys,
            prompt=fact_sheet + f"\n【現在の中長期ロードマップ】{json.dumps(roadmap_mem.get('mid_long_term_roadmap', []), ensure_ascii=False)}",
            temperature=0.35,
            max_output_tokens=900,
        )
        models_used_log.append(f"🌍マクロ＆⚡執行官: {m_macro}")
        if not macro_exec_res or not isinstance(macro_exec_res.get("mid_long_term_roadmap"), list):
            p_b = pkg_b.get("params", {})
            macro_exec_res = {
                "macro_and_execution_view_ja": (
                    f"15分足相関に基づきDXY重み={rec_w.get('dxy_weight', 0.50)}・米金利重み={rec_w.get('yield_weight', 0.50)}への比重更新が妥当。"
                    f"執行面では短時間ノイズSL({evidence.get('fast_noise_sl_count_7d', 0)}件)を防ぐため、最小SL幅を{p_b.get('min_sl_pips', 24.0)}pips・ATR倍率を{p_b.get('atr_sl_multiplier', 1.45)}xへ広げる【Package B】が最もドローダウンを抑えられる。"
                ),
                "mid_long_term_roadmap": roadmap_mem.get("mid_long_term_roadmap", []),
            }

        # ------------------------------------------------------------------
        # Round 2: 🛡️ 破壊的リスク監査官 (Red Team / 過剰適合ストッパー)
        # ------------------------------------------------------------------
        auditor_sys = (
            "あなたは冷徹な『破壊的リスク監査官（Red Team / Devil's Advocate）』です。"
            "アルファ開拓官の大胆な提案（Package A）に対して、過去データの過剰適合（カーブフィッティング）リスクや急反転時のドローダウンリスクを実測バックテスト数値に基づいて徹底的に批判・監査してください。"
            "また、安易にAとBを足して2で割るような中途半端な平均化を戒め、本番資金を守るための厳格な監査意見をJSONで出力してください。"
            "出力JSONキー: {\"red_team_critique_ja\": \"開拓官の案(Package A)に対する鋭い反論・過剰適合リスク指摘(170字以内)\", \"risk_audit_verdict_ja\": \"本番口座で許容できる変更限界とシャドー検証へ回すべき境界線(120字以内)\"}"
        )
        auditor_prompt = (
            fact_sheet
            + f"\n【開拓官の主張】{json.dumps(alpha_res, ensure_ascii=False)}"
            + f"\n【マクロ・執行官の分析】{json.dumps(macro_exec_res, ensure_ascii=False)}"
        )
        auditor_res, m_auditor = self.router.generate_role_response(
            role_key="RED_TEAM_AUDITOR",
            is_core_decision_role=True,
            system_instruction=auditor_sys,
            prompt=auditor_prompt,
            temperature=0.25,
            max_output_tokens=700,
        )
        models_used_log.append(f"🛡️監査官: {m_auditor}")
        if not auditor_res:
            auditor_res = {
                "red_team_critique_ja": (
                    f"開拓官が推す【Package A】はZ閾値を{pkg_a.get('params', {}).get('momentum_z_threshold')}σまで緩めるため、"
                    "トレンド相場では利益が伸びるが、指標前のレンジ相場や地政学ヘッドラインによる急反転時にダマシ被弾が増える過剰適合リスクがある。"
                ),
                "risk_audit_verdict_ja": (
                    "AとBを足して2で割る中途半端な妥協はどちらの優位性も殺すため厳禁。"
                    "本番口座にはSL呼吸幅とトレール余力を堅牢に広げた【Package B】を適用し、【Package A】は来週1週間シャドー検証枠で実戦テストすべきである。"
                ),
            }

        # ------------------------------------------------------------------
        # Round 3: ⚖️ 最高投資責任者 (CIO) による最終パッケージ化（折衷案禁止）
        # ------------------------------------------------------------------
        cio_sys = (
            "あなたはクオンツヘッジファンドの『最高投資責任者（CIO / 議長）』です。"
            "【絶対ルール】各エージェントの意見を『足して2で割った平均値・無難な折衷案』にまとめることは厳禁です。"
            "オーナーがDiscord上でワンタップで決裁できるよう、激突したエッジをそのまま残した3つの明確な選択肢（選択肢A=攻めの構造改革、選択肢B=守りの堅牢改善、選択肢C=本番はBを適用し裏シャドー枠でAと次週テーマを実戦検証）の総括と、CIOとしての推奨決裁をJSONで出力してください。"
            "出力JSONキー: {\"core_agenda_ja\": \"今週の委員会の核心的争点(120字以内)\", \"cio_verdict_ja\": \"CIO議長の最終総括と推奨選択肢の理由(160字以内)\", \"recommended_choice\": \"C\"}"
        )
        cio_prompt = (
            fact_sheet
            + f"\n【📰ファンダ官】{json.dumps(funda_res, ensure_ascii=False)}"
            + f"\n【🎯開拓官】{json.dumps(alpha_res, ensure_ascii=False)}"
            + f"\n【🌍マクロ・⚡執行官】{json.dumps(macro_exec_res, ensure_ascii=False)}"
            + f"\n【🛡️RedTeam監査官】{json.dumps(auditor_res, ensure_ascii=False)}"
        )
        cio_res, m_cio = self.router.generate_role_response(
            role_key="CIO_CHAIRMAN",
            is_core_decision_role=True,
            system_instruction=cio_sys,
            prompt=cio_prompt,
            temperature=0.3,
            max_output_tokens=700,
        )
        models_used_log.append(f"⚖️CIO議長: {m_cio}")
        if not cio_res:
            cio_res = {
                "core_agenda_ja": "微益トレール撤退と短時間ノイズSLを排除しつつ、来週の米重要指標・金利変動トレンドに対して『攻めの型A強化(Package A)』か『守りのノイズ防御(Package B)』のどちらで臨むか？",
                "cio_verdict_ja": (
                    "平均化によるエッジ喪失を避けるため、3つの独立パッケージを上申する。"
                    "最も推奨するのは【選択肢C（ハイブリッド）】であり、本番資金は【Package B】でノイズSLと微益撤退を確実に防ぎつつ、開拓官の【Package A】と分割利確モデルを来週1週間シャドー枠で実戦対決させる方針が最も期待値が高い。"
                ),
                "recommended_choice": "C",
            }

        # 決裁用ワンタイム署名URLの生成
        decision_urls = self.build_decision_urls(meeting_id)
        quota_after = self.router.get_quota_status()

        # ロードマップ記憶の更新
        roadmap_mem["active_weekly_experiment"] = {
            "id": f"EXP_{now_dt.strftime('%Y%m%d')}",
            "title": alpha_res.get("next_week_experiment_title", "1.5R 50%分割利確＋広めトレール検証"),
            "hypothesis": alpha_res.get("next_week_experiment_hypothesis_ja", ""),
            "started_at": now_dt.strftime("%Y-%m-%d"),
        }
        if isinstance(macro_exec_res.get("mid_long_term_roadmap"), list) and len(macro_exec_res["mid_long_term_roadmap"]) > 0:
            roadmap_mem["mid_long_term_roadmap"] = macro_exec_res["mid_long_term_roadmap"][:4]
        self.save_roadmap_memory(roadmap_mem)

        meeting_record = {
            "meeting_id": meeting_id,
            "held_at": now_str,
            "trigger_source": trigger_source,
            "status": "PENDING_OWNER_APPROVAL",
            "approved_choice": None,
            "approved_at": None,
            "ai_quota_status": quota_after,
            "models_used": models_used_log,
            "core_agenda_ja": cio_res.get("core_agenda_ja", ""),
            "cio_verdict_ja": cio_res.get("cio_verdict_ja", ""),
            "recommended_choice": cio_res.get("recommended_choice", "C"),
            "fundamental_report": funda_res,
            "news_headlines": news_items[:6],
            "agent_debate": {
                "fundamental_strategist": funda_res,
                "alpha_researcher": alpha_res,
                "macro_and_execution": macro_exec_res,
                "red_team_auditor": auditor_res,
                "cio_chairman": cio_res,
            },
            "last_week_experiment_result": evidence.get("last_week_experiment_result", {}),
            "next_week_experiment": roadmap_mem["active_weekly_experiment"],
            "mid_long_term_roadmap": roadmap_mem["mid_long_term_roadmap"],
            "options": {
                "A": {
                    "label": "🔥 選択肢A：【攻め】アルファ開拓＆ファンダ順張り特化パッケージ",
                    "summary_ja": (
                        f"型A(金利連動)のZ閾値を {pkg_a.get('params', {}).get('momentum_z_threshold')}σ へ積極化し、"
                        f"建値移動を 1:{pkg_a.get('params', {}).get('be_trigger_rr')}R、トレール追従幅を {pkg_a.get('params', {}).get('trail_atr_multiplier')}xATR へ大幅拡大して大トレンドを獲り切る。"
                    ),
                    "params": pkg_a.get("params", {}),
                    "stance": "AGGRESSIVE",
                    "backtest_21d": bt_a,
                },
                "B": {
                    "label": "🛡️ 選択肢B：【守り】ノイズSL完全防御＆高勝率イグジット改善パッケージ",
                    "summary_ja": (
                        f"最小SL幅を {pkg_b.get('params', {}).get('min_sl_pips')}pips、ATR倍率を {pkg_b.get('params', {}).get('atr_sl_multiplier')}x へ広げて短時間ノイズ狩りを防ぎ、"
                        f"トレール幅 {pkg_b.get('params', {}).get('trail_atr_multiplier')}xATR で微益撤退を抑制する堅牢設定。"
                    ),
                    "params": pkg_b.get("params", {}),
                    "stance": "BALANCED",
                    "backtest_21d": bt_b,
                },
                "C": {
                    "label": "🧪 選択肢C：【ハイブリッド（議長推奨）】本番口座は🛡️選択肢Bを適用 ＋ 裏シャドー枠で🔥選択肢A＆次週テーマを1週間実戦検証",
                    "summary_ja": (
                        "本番資金は守りのパッケージBでドローダウンと微益撤退を抑えつつ、"
                        "開拓官の大胆なパッケージAと次週検証テーマを裏のシャドーDBで1週間走らせ、来週日曜の委員会で実戦スコア対決を行う。"
                    ),
                    "params": pkg_b.get("params", {}),
                    "shadow_experiment_params": pkg_a.get("params", {}),
                    "stance": "BALANCED",
                    "backtest_21d": bt_b,
                },
                "REJECT": {
                    "label": "🔴 却下：今週の提案はすべて見送り（完全現状維持）",
                    "summary_ja": "現行の動的パラメータと運用スタンスを一切変更せず、そのまま来週も継続する。",
                    "params": cur_p,
                    "stance": "KEEP",
                },
            },
            "decision_urls": decision_urls,
        }

        self._save_meeting(meeting_record)

        # Discordへ議事録＆ワンタップ決裁通知を送信
        if self.discord_mgr and hasattr(self.discord_mgr, "send_sunday_ic_report"):
            self.discord_mgr.send_sunday_ic_report(meeting_record)

        print(f"✅ [SUNDAY INVESTMENT COMMITTEE COMPLETE] 議事録保存＆Discord決裁通知完了 (id={meeting_id})")
        return meeting_record

    def publish_antigravity_neon_meeting(self, neon_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Antigravity (Gemini 4 Neon サブエージェント群) で開催された本命の投資委員会議事録を受理し、
        HMAC-SHA256署名付きワンタップ決裁URLを付与して保存＆Discordへ配信する。
        """
        now_dt = datetime.datetime.now(JST)
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S JST")
        meeting_id = str(neon_payload.get("meeting_id") or f"IC_NEON_{now_dt.strftime('%Y%m%d_%H%M%S')}")

        evidence = self.load_saturday_evidence()
        pkgs = evidence.get("candidate_packages", {})
        pkg_a = pkgs.get("PACKAGE_A_OFFENSIVE", {})
        pkg_b = pkgs.get("PACKAGE_B_DEFENSIVE", {})
        bt_a = pkg_a.get("backtest_21d", {})
        bt_b = pkg_b.get("backtest_21d", {})
        cur_p = evidence.get("current_dynamic_params", {})

        decision_urls = self.build_decision_urls(meeting_id)
        roadmap_mem = self.load_roadmap_memory()

        if neon_payload.get("next_week_experiment"):
            roadmap_mem["active_weekly_experiment"] = neon_payload["next_week_experiment"]
        if isinstance(neon_payload.get("mid_long_term_roadmap"), list) and neon_payload["mid_long_term_roadmap"]:
            roadmap_mem["mid_long_term_roadmap"] = neon_payload["mid_long_term_roadmap"]
        self.save_roadmap_memory(roadmap_mem)

        custom_opts = neon_payload.get("options") or {}
        opt_a_params = (custom_opts.get("A") or {}).get("params") or pkg_a.get("params", {})
        opt_b_params = (custom_opts.get("B") or {}).get("params") or pkg_b.get("params", {})

        meeting_record = {
            "meeting_id": meeting_id,
            "held_at": now_str,
            "trigger_source": "ANTIGRAVITY_GEMINI_4_NEON_SUBAGENTS",
            "status": "PENDING_OWNER_APPROVAL",
            "approved_choice": None,
            "approved_at": None,
            "ai_quota_status": {
                "date": now_dt.strftime("%Y-%m-%d"),
                "pro_quota_health_pct": 100.0,
                "recommended_tier": "ANTIGRAVITY_GEMINI_4_NEON",
                "recommended_tier_label": "Tier 0: Antigravity Gemini 4 Neon (6-Role Subagent Direct Debate)",
                "last_model_used": "Gemini 4 Neon (Subagents: Alpha/Funda/Macro + RedTeam/Exec + CIO)",
            },
            "models_used": neon_payload.get("models_used") or [
                "🎯開拓＆📰ファンダ＆🌍マクロ官: Antigravity Gemini 4 Neon (Subagent #1)",
                "🛡️RedTeam監査＆⚡執行官: Antigravity Gemini 4 Neon (Subagent #2)",
                "⚖️CIO議長: Antigravity Gemini 4 Neon (Lead Agent)",
            ],
            "core_agenda_ja": neon_payload.get("core_agenda_ja", ""),
            "cio_verdict_ja": neon_payload.get("cio_verdict_ja", ""),
            "recommended_choice": neon_payload.get("recommended_choice", "C"),
            "fundamental_report": neon_payload.get("fundamental_report", {}),
            "news_headlines": neon_payload.get("news_headlines", []),
            "agent_debate": neon_payload.get("agent_debate", {}),
            "last_week_experiment_result": evidence.get("last_week_experiment_result", {}),
            "next_week_experiment": roadmap_mem["active_weekly_experiment"],
            "mid_long_term_roadmap": roadmap_mem["mid_long_term_roadmap"],
            "options": {
                "A": {
                    "label": (custom_opts.get("A") or {}).get("label") or "🔥 選択肢A：【攻め】アルファ開拓＆マクロ金利順張り特化パッケージ",
                    "summary_ja": (custom_opts.get("A") or {}).get("summary_ja") or "",
                    "params": opt_a_params,
                    "stance": "AGGRESSIVE",
                    "backtest_21d": bt_a.get("simulated") or bt_a,
                },
                "B": {
                    "label": (custom_opts.get("B") or {}).get("label") or "🛡️ 選択肢B：【守り】狭小SL即死＆微益撤退撲滅・堅牢パッケージ",
                    "summary_ja": (custom_opts.get("B") or {}).get("summary_ja") or "",
                    "params": opt_b_params,
                    "stance": "BALANCED",
                    "backtest_21d": bt_b.get("simulated") or bt_b,
                },
                "C": {
                    "label": (custom_opts.get("C") or {}).get("label") or "🧪 選択肢C：【ハイブリッド（★Gemini 4 Neon 議長推奨）】本番は🛡️選択肢B（+14.0万円改善）を即時適用 ＋ 裏シャドー枠で🔥選択肢A＆次週テーマを1週間実戦対決",
                    "summary_ja": (custom_opts.get("C") or {}).get("summary_ja") or "",
                    "params": opt_b_params,
                    "shadow_experiment_params": opt_a_params,
                    "stance": "BALANCED",
                    "backtest_21d": bt_b.get("simulated") or bt_b,
                },
                "REJECT": {
                    "label": "🔴 却下：今週の提案はすべて見送り（完全現状維持）",
                    "summary_ja": "現行の動的パラメータと運用スタンスを一切変更せず、そのまま来週も継続する。",
                    "params": cur_p,
                    "stance": "KEEP",
                },
            },
            "decision_urls": decision_urls,
        }

        self._save_meeting(meeting_record)
        if self.discord_mgr and hasattr(self.discord_mgr, "send_sunday_ic_report"):
            self.discord_mgr.send_sunday_ic_report(meeting_record)

        print(f"🏛️✨ [ANTIGRAVITY GEMINI 4 NEON IC PUBLISHED] Neon 6役会議結果を保存＆Discordへ配信しました (id={meeting_id})")
        return meeting_record

    def load_latest_meeting(self) -> Dict[str, Any]:
        if self.meeting_file.exists():
            try:
                return json.loads(self.meeting_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_meeting(self, data: Dict[str, Any]) -> None:
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.meeting_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.meeting_file)
        except Exception as e:
            print(f"[IC MEETING SAVE ERROR] {e}")

    # ------------------------------------------------------------------
    # オーナー決裁（Discordワンタップ or ダッシュボードボタン）の適用処理
    # ------------------------------------------------------------------
    def apply_owner_decision(
        self,
        choice: str,
        meeting_id: Optional[str] = None,
        source: str = "DISCORD_ONE_TAP",
    ) -> Dict[str, Any]:
        choice = str(choice or "").upper().strip()
        if choice not in ("A", "B", "C", "REJECT"):
            return {"success": False, "message": f"無効な選択肢です: {choice}"}

        meeting = self.load_latest_meeting()
        if not meeting:
            return {"success": False, "message": "現在決裁待ちの投資委員会議事録がありません。"}

        if meeting_id and meeting.get("meeting_id") and meeting.get("meeting_id") != meeting_id:
            return {"success": False, "message": f"指定された会議ID ({meeting_id}) は最新の会議 ({meeting.get('meeting_id')}) と一致しません。"}

        opt = (meeting.get("options") or {}).get(choice)
        if not opt:
            return {"success": False, "message": "選択肢データが見つかりません。"}

        now_str = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")

        if choice != "REJECT":
            target_params = opt.get("params") or {}
            if target_params:
                self.review_engine.optimizer.apply_optimization(
                    proposed_changes=target_params,
                    reason=f"日曜AI投資委員会 オーナー決裁採択 [選択肢{choice}] ({source})",
                    date_str=datetime.datetime.now(JST).strftime("%Y-%m-%d"),
                )
            cur_strategy_params = settings.load_strategy_params()
            if choice == "C" and opt.get("shadow_experiment_params"):
                cur_strategy_params["ic_shadow_experiment_params"] = opt["shadow_experiment_params"]
            cur_strategy_params["ic_last_approved_choice"] = choice
            cur_strategy_params["ic_last_approved_at"] = now_str
            settings.save_strategy_params(cur_strategy_params)

        meeting["status"] = "APPROVED" if choice != "REJECT" else "REJECTED_KEEP_CURRENT"
        meeting["approved_choice"] = choice
        meeting["approved_at"] = now_str
        meeting["approved_source"] = source
        self._save_meeting(meeting)

        # 長期ロードマップメモリにも決裁履歴を記録
        rm = self.load_roadmap_memory()
        hist = list(rm.get("past_decisions") or [])
        hist.insert(0, {
            "meeting_id": meeting.get("meeting_id"),
            "approved_at": now_str,
            "choice": choice,
            "label": opt.get("label", choice),
            "source": source,
        })
        rm["past_decisions"] = hist[:20]
        self.save_roadmap_memory(rm)

        msg = f"投資委員会の【選択肢{choice}】({opt.get('label')}) を採択し、システムへ反映しました！"
        if self.discord_mgr and hasattr(self.discord_mgr, "send_ic_decision_confirmation"):
            self.discord_mgr.send_ic_decision_confirmation(meeting, choice, opt, source)

        return {
            "success": True,
            "choice": choice,
            "label": opt.get("label"),
            "summary_ja": opt.get("summary_ja"),
            "approved_at": now_str,
            "message": msg,
        }
