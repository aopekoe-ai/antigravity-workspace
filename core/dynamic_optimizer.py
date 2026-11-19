import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("DynamicOptimizer")


class DynamicParamOptimizer:
    """
    【世界トップクオンツ・自己適応型パラメータオプティマイザ v9.0 (Step 3)】

    1. 資金防衛インターロック（絶対固定枠）を厳守。
    2. 日次クオンツ統計＋AIハイブリッド自己較正（純クオンツ実績に基づく勝率・期待値最大化）。
    3. リアルタイム先行指標レジーム適応（MACRO_TREND / GEO_VOLATILITY / MACRO_CHOP / NORMAL_FLOW）
       により、15秒スキャンごとに相場環境へ最適なRR比・感度・SL倍率を動的供給する。
    """

    # -------------------------------------------------------------
    # 1. 資金防衛インターロック（AIによる書き換え絶対禁止枠）
    # -------------------------------------------------------------
    IMMUTABLE_RULES = {
        "enforce_single_position": True,      # 単一ポジション限定（ナンピン・両建て絶対禁止）
        "max_risk_per_trade_percent": 1.5,    # 1トレード最大許容損失 1.5%
        "max_daily_drawdown_percent": 3.0,    # 日次最大許容損失（サーキットブレーカー） 3.0%
        "hard_sl_required": True,             # ブローカー側ハードSL付与必須
        "max_spread_pips_ceiling": 4.0        # スプレッド許容上限の絶対天井
    }

    # -------------------------------------------------------------
    # 2. 安全ガードレール（可変パラメータの許容レンジ・最大変動幅）
    # -------------------------------------------------------------
    GUARDRAILS = {
        "min_risk_reward_ratio": {
            "min": 1.3,
            "max": 2.5,
            "default": 1.5,
            "max_step": 0.25,
            "description": "SMC最小リスクリワード比率"
        },
        "wick_ratio_threshold": {
            "min": 0.20,
            "max": 0.55,
            "default": 0.25,
            "max_step": 0.05,
            "description": "フラクタルスイープ判定のヒゲ比率閾値"
        },
        "min_fvg_gap_dollars": {
            "min": 0.20,
            "max": 0.80,
            "default": 0.30,
            "max_step": 0.10,
            "description": "FVG検出の最小ギャップ（ドル）"
        },
        "min_sl_pips": {
            "min": 18.0,
            "max": 45.0,
            "default": 22.0,
            "max_step": 4.0,
            "description": "最小SL幅（pips・狭すぎる損切り防止）"
        },
        "max_sl_pips": {
            "min": 45.0,
            "max": 90.0,
            "default": 60.0,
            "max_step": 5.0,
            "description": "最大SL幅（pips）"
        },
        "atr_sl_multiplier": {
            "min": 1.0,
            "max": 2.5,
            "default": 1.40,
            "max_step": 0.15,
            "description": "SMC ATR SL倍率（ノイズ狩り耐性）"
        },
        "max_allowed_spread_pips": {
            "min": 2.0,
            "max": 15.0,
            "default": 3.0,
            "max_step": 0.5,
            "description": "許容最大スプレッド（pips）"
        },
        "momentum_z_threshold": {
            "min": 1.25,
            "max": 2.00,
            "default": 1.50,
            "max_step": 0.10,
            "description": "型Aマクロモメンタム発火Zスコア閾値"
        },
        "macro_sl_atr_multiplier": {
            "min": 1.40,
            "max": 2.60,
            "default": 1.75,
            "max_step": 0.15,
            "description": "型AマクロモメンタムM5 ATR SL倍率"
        },
        "macro_min_rr": {
            "min": 1.60,
            "max": 2.40,
            "default": 1.80,
            "max_step": 0.20,
            "description": "型Aマクロモメンタム最小RR比"
        },
        "smt_min_rr": {
            "min": 1.60,
            "max": 2.50,
            "default": 2.00,
            "max_step": 0.20,
            "description": "型B SMTダイバージェンス最小RR比"
        },
        "be_trigger_rr": {
            "min": 0.95,
            "max": 1.80,
            "default": 1.15,
            "max_step": 0.15,
            "description": "建値移動(BE)発動の必要RR倍率（早すぎる建値刈り防止）"
        },
        "trail_atr_multiplier": {
            "min": 0.80,
            "max": 1.85,
            "default": 1.15,
            "max_step": 0.15,
            "description": "マクロ反転トレール時のSL追従距離（M5 ATR倍率・反発ノイズ耐性）"
        },
    }

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.params_file = self.config_dir / "dynamic_params.json"
        self._ensure_params_file()

    def _ensure_params_file(self):
        """dynamic_params.json が存在しない場合はデフォルト値で初期化"""
        if not self.params_file.exists():
            default_params = {k: v["default"] for k, v in self.GUARDRAILS.items()}
            default_params["version"] = 1
            default_params["last_updated"] = "INITIAL"
            default_params["reason"] = "Default configuration initialized"
            self._save_params(default_params)

    def _clamp(self, key: str, val: float) -> float:
        rule = self.GUARDRAILS[key]
        return round(max(rule["min"], min(rule["max"], float(val))), 3)

    def load_active_params(self) -> Dict[str, Any]:
        """現在適用中のベース動的パラメータを取得（整合性チェック付き）"""
        self._ensure_params_file()
        try:
            with open(self.params_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            validated = {}
            for k, rule in self.GUARDRAILS.items():
                val = data.get(k, rule["default"])
                validated[k] = self._clamp(k, val)
            validated["version"] = data.get("version", 1)
            validated["last_updated"] = data.get("last_updated", "")
            return validated
        except Exception as e:
            logger.error(f"Error loading dynamic params: {e}, returning defaults")
            return {k: v["default"] for k, v in self.GUARDRAILS.items()}

    def classify_and_adapt_regime(
        self,
        base_params: Dict[str, Any],
        market_state: Dict[str, Any],
        macro_state: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        """
        【Step 3 コア機能】先行指標×上位足トレンドから現在の相場レジームを判定し、
        ガードレール内でリアルタイム最適化した実効パラメータを返す（ファイルを汚さずオンメモリ適応）。
        """
        adapted = dict(base_params)
        if not macro_state or macro_state.get("source", "NONE") == "NONE":
            adapted["active_regime"] = "REGIME_NORMAL_FLOW"
            return "REGIME_NORMAL_FLOW", adapted

        h1_trend = market_state.get("h1_trend", "NEUTRAL")
        atr_m5 = float(market_state.get("atr_m5_dollars", 2.0))
        bias = float(macro_state.get("macro_bias_score", 0.0))
        dxy_z = float(macro_state.get("dxy_z", 0.0))
        yield_z = float(macro_state.get("yield_z", 0.0))
        geo_risk = bool(macro_state.get("is_geopolitical_risk_off", False))

        htf_macro_aligned = (
            (h1_trend == "BULLISH" and bias >= 0.40)
            or (h1_trend == "BEARISH" and bias <= -0.40)
        )
        macro_conflict = (dxy_z * yield_z < -0.30) or (h1_trend == "NEUTRAL" and abs(bias) < 0.20)

        # 1. 地政学リスクオフ・超高ボラティリティ相場
        if geo_risk or (atr_m5 >= 6.5 and abs(bias) >= 0.35):
            regime = "REGIME_GEO_VOLATILITY"
            adapted["atr_sl_multiplier"] = self._clamp("atr_sl_multiplier", adapted["atr_sl_multiplier"] + 0.15)
            adapted["macro_sl_atr_multiplier"] = self._clamp("macro_sl_atr_multiplier", adapted["macro_sl_atr_multiplier"] + 0.15)
            adapted["min_sl_pips"] = self._clamp("min_sl_pips", adapted.get("min_sl_pips", 22.0) + 4.0)
            adapted["min_risk_reward_ratio"] = self._clamp("min_risk_reward_ratio", adapted["min_risk_reward_ratio"] + 0.20)
            adapted["macro_min_rr"] = self._clamp("macro_min_rr", adapted["macro_min_rr"] + 0.20)
            adapted["be_trigger_rr"] = self._clamp("be_trigger_rr", adapted.get("be_trigger_rr", 1.15) + 0.15)
            adapted["trail_atr_multiplier"] = self._clamp("trail_atr_multiplier", adapted.get("trail_atr_multiplier", 1.15) + 0.20)

        # 2. 先行指標＋H1トレンド完全一致の強トレンド相場（利を伸ばし、トレール幅に余裕を持たせて押し目反発刈りを防ぐ）
        elif htf_macro_aligned:
            regime = "REGIME_MACRO_TREND"
            adapted["min_risk_reward_ratio"] = self._clamp("min_risk_reward_ratio", adapted["min_risk_reward_ratio"] + 0.25)
            adapted["macro_min_rr"] = self._clamp("macro_min_rr", adapted["macro_min_rr"] + 0.25)
            adapted["smt_min_rr"] = self._clamp("smt_min_rr", adapted["smt_min_rr"] + 0.20)
            adapted["momentum_z_threshold"] = self._clamp("momentum_z_threshold", adapted["momentum_z_threshold"] - 0.10)
            adapted["atr_sl_multiplier"] = self._clamp("atr_sl_multiplier", adapted["atr_sl_multiplier"] + 0.08)
            adapted["be_trigger_rr"] = self._clamp("be_trigger_rr", adapted.get("be_trigger_rr", 1.15) + 0.10)
            adapted["trail_atr_multiplier"] = self._clamp("trail_atr_multiplier", adapted.get("trail_atr_multiplier", 1.15) + 0.15)

        # 3. 先行指標ねじれ（DXYと金利が逆行）またはレンジ錯綜相場（確実な早めの利確＋ダマシブレイク防御）
        elif macro_conflict:
            regime = "REGIME_MACRO_CHOP"
            adapted["min_risk_reward_ratio"] = self._clamp("min_risk_reward_ratio", adapted["min_risk_reward_ratio"] - 0.10)
            adapted["momentum_z_threshold"] = self._clamp("momentum_z_threshold", adapted["momentum_z_threshold"] + 0.15)
            adapted["wick_ratio_threshold"] = self._clamp("wick_ratio_threshold", adapted["wick_ratio_threshold"] - 0.02)
            adapted["be_trigger_rr"] = self._clamp("be_trigger_rr", adapted.get("be_trigger_rr", 1.15) - 0.05)

        # 4. 通常順張りバランス相場
        else:
            regime = "REGIME_NORMAL_FLOW"

        adapted["active_regime"] = regime
        return regime, adapted

    def compute_quant_calibration(
        self,
        closed_trades: List[Dict[str, Any]],
        today_trade_count: int,
    ) -> Dict[str, Any]:
        """
        直近の確定クオンツトレード実績（最大50件）から数理的にベースパラメータ微調整案を算出。
        - 【機能A】トレール・建値移動直後の反発による「微益撤退（早すぎるトレール刈り）」の自動検知＆トレール幅・BE発動タイミング拡大
        - 【機能B】損切幅が狭すぎてすぐ損切りされる「短時間ノイズSL（早すぎる損切り）」の自動検知＆最小SL幅・ATR倍率拡大
        """
        current = self.load_active_params()
        proposals: Dict[str, float] = {}

        recent = [t for t in closed_trades if t.get("profit") is not None][-50:]
        if not recent:
            return proposals

        wins = [t for t in recent if float(t.get("profit", 0)) > 0]
        losses = [t for t in recent if float(t.get("profit", 0)) < 0]
        true_losses = [t for t in recent if float(t.get("profit", 0)) < -300]
        # 微益・建値撤退（トレールやBEで小さく決済されたトレード: -300円〜+2,500円）
        small_trail_exits = [t for t in recent if -300 <= float(t.get("profit", 0)) <= 2500]
        full_tp_wins = [t for t in recent if float(t.get("profit", 0)) > 2500]

        win_rate = len(wins) / len(recent) if recent else 0.5

        # 1. 取引頻度が少なすぎる場合（5回未満）、機会確保のため感度閾値を小幅緩和
        if today_trade_count < 5:
            proposals["wick_ratio_threshold"] = self._clamp(
                "wick_ratio_threshold", current["wick_ratio_threshold"] - 0.02
            )
            proposals["momentum_z_threshold"] = self._clamp(
                "momentum_z_threshold", current["momentum_z_threshold"] - 0.05
            )
        elif today_trade_count > 16 and win_rate < 0.50:
            proposals["wick_ratio_threshold"] = self._clamp(
                "wick_ratio_threshold", current["wick_ratio_threshold"] + 0.03
            )
            proposals["momentum_z_threshold"] = self._clamp(
                "momentum_z_threshold", current["momentum_z_threshold"] + 0.05
            )

        # 2. 【トレール直後の反発・微益撤退の自動修正】
        # 負け以外のトレードのうち、トレールや建値移動で小さく降ろされた割合が30%以上（または2件以上）ある場合、
        # トレール追従幅(trail_atr_multiplier)と建値移動タイミング(be_trigger_rr)を広げて押し目・戻りの反発に耐えさせる
        non_losing_count = len(small_trail_exits) + len(full_tp_wins)
        if len(small_trail_exits) >= 2 and non_losing_count > 0:
            premature_ratio = len(small_trail_exits) / non_losing_count
            if premature_ratio >= 0.30:
                proposals["trail_atr_multiplier"] = self._clamp(
                    "trail_atr_multiplier", current.get("trail_atr_multiplier", 1.15) + 0.15
                )
                proposals["be_trigger_rr"] = self._clamp(
                    "be_trigger_rr", current.get("be_trigger_rr", 1.15) + 0.12
                )

        # 3. 【損切幅が小さすぎてすぐ損切りされる現象（短時間ノイズSL）の自動修正】
        # エントリーから15分以内にSL到達したトレード、または初期SL幅が25pips未満で狩られたトレードをカウント
        fast_or_tight_sl_count = 0
        for t in true_losses:
            is_fast = False
            try:
                t_open = datetime.datetime.strptime(str(t.get("time", ""))[:19], "%Y-%m-%d %H:%M:%S")
                t_close = datetime.datetime.strptime(str(t.get("close_time", ""))[:19], "%Y-%m-%d %H:%M:%S")
                hold_min = (t_close - t_open).total_seconds() / 60.0
                if 0 <= hold_min <= 18.0:
                    is_fast = True
            except Exception:
                pass
            sl_px = float(t.get("sl") or 0.0)
            en_px = float(t.get("price") or 0.0)
            sl_pips = abs(en_px - sl_px) / 0.10 if (sl_px > 0 and en_px > 0) else 30.0
            if is_fast or sl_pips < 25.0:
                fast_or_tight_sl_count += 1

        if fast_or_tight_sl_count >= 2 or (len(recent) >= 6 and win_rate < 0.48 and len(true_losses) >= 3):
            # 損切幅が狭すぎてノイズで刈られているため、最小SL幅(min_sl_pips)とATR SL倍率を同時に引き上げる
            proposals["min_sl_pips"] = self._clamp(
                "min_sl_pips", current.get("min_sl_pips", 22.0) + 3.0
            )
            proposals["atr_sl_multiplier"] = self._clamp(
                "atr_sl_multiplier", current.get("atr_sl_multiplier", 1.40) + 0.12
            )
            proposals["macro_sl_atr_multiplier"] = self._clamp(
                "macro_sl_atr_multiplier", current.get("macro_sl_atr_multiplier", 1.75) + 0.12
            )
        elif len(recent) >= 10 and win_rate >= 0.60 and len(full_tp_wins) >= 5:
            proposals["min_risk_reward_ratio"] = self._clamp(
                "min_risk_reward_ratio", current["min_risk_reward_ratio"] + 0.05
            )

        return proposals

    def apply_optimization(self, proposed_changes: Dict[str, Any], reason: str, date_str: str) -> Tuple[bool, Dict[str, Any], str]:
        """
        提案されたパラメータ変更案を検証し、ガードレール（上下限および1回あたりの最大変動幅）に収まるよう安全に適用。
        """
        current_params = self.load_active_params()
        new_params = current_params.copy()
        adjustments = []

        for key, proposed_val in (proposed_changes or {}).items():
            if key not in self.GUARDRAILS:
                continue

            rule = self.GUARDRAILS[key]
            current_val = current_params.get(key, rule["default"])

            try:
                target_val = float(proposed_val)
            except (ValueError, TypeError):
                continue

            max_step = rule["max_step"]
            delta = target_val - current_val
            if abs(delta) > max_step:
                clamped_delta = max_step if delta > 0 else -max_step
                target_val = current_val + clamped_delta

            final_val = self._clamp(key, target_val)

            if final_val != current_val:
                new_params[key] = final_val
                adjustments.append(f"{key}: {current_val} -> {final_val} ({rule['description']})")

        if not adjustments:
            return False, current_params, "有効なパラメータ変更はありませんでした（現状維持）。"

        new_params["version"] = current_params.get("version", 1) + 1
        new_params["last_updated"] = date_str
        new_params["reason"] = reason

        self._save_params(new_params)
        summary = (
            f"【自動最適化適用 (v{new_params['version']})】\n"
            + "\n".join([f"・{adj}" for adj in adjustments])
            + f"\n根拠: {reason}"
        )
        return True, new_params, summary

    def _save_params(self, params: Dict[str, Any]):
        try:
            with open(self.params_file, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save dynamic params: {e}")

    def get_guardrails_summary_ja(self) -> str:
        lines = ["🔒 **絶対固定枠 (変更不可)**:"]
        lines.append("・単一ポジション限定 / 1トレード最大損失 1.5% / 日次最大DD 3.0% / ハードSL必須")
        lines.append("\n🎛️ **自己最適化ガードレール (許容範囲)**:")
        for k, v in self.GUARDRAILS.items():
            lines.append(f"・`{k}` ({v['description']}): {v['min']} 〜 {v['max']} (最大変動幅 ±{v['max_step']})")
        return "\n".join(lines)
