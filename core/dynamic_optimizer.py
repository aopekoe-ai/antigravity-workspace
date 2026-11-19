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
            "min": 12.0,
            "max": 25.0,
            "default": 18.0,
            "max_step": 3.0,
            "description": "最小SL幅（pips）"
        },
        "max_sl_pips": {
            "min": 45.0,
            "max": 80.0,
            "default": 55.0,
            "max_step": 5.0,
            "description": "最大SL幅（pips）"
        },
        "atr_sl_multiplier": {
            "min": 1.0,
            "max": 2.0,
            "default": 1.3,
            "max_step": 0.15,
            "description": "SMC ATR SL倍率"
        },
        "max_allowed_spread_pips": {
            "min": 2.0,
            "max": 3.5,
            "default": 3.0,
            "max_step": 0.3,
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
            "max": 2.20,
            "default": 1.70,
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
            adapted["min_risk_reward_ratio"] = self._clamp("min_risk_reward_ratio", adapted["min_risk_reward_ratio"] + 0.20)
            adapted["macro_min_rr"] = self._clamp("macro_min_rr", adapted["macro_min_rr"] + 0.20)

        # 2. 先行指標＋H1トレンド完全一致の強トレンド相場（利を伸ばし、型A感度を上げる）
        elif htf_macro_aligned:
            regime = "REGIME_MACRO_TREND"
            adapted["min_risk_reward_ratio"] = self._clamp("min_risk_reward_ratio", adapted["min_risk_reward_ratio"] + 0.25)
            adapted["macro_min_rr"] = self._clamp("macro_min_rr", adapted["macro_min_rr"] + 0.25)
            adapted["smt_min_rr"] = self._clamp("smt_min_rr", adapted["smt_min_rr"] + 0.20)
            adapted["momentum_z_threshold"] = self._clamp("momentum_z_threshold", adapted["momentum_z_threshold"] - 0.10)
            adapted["atr_sl_multiplier"] = self._clamp("atr_sl_multiplier", adapted["atr_sl_multiplier"] + 0.08)

        # 3. 先行指標ねじれ（DXYと金利が逆行）またはレンジ錯綜相場（確実な早めの利確＋ダマシブレイク防御）
        elif macro_conflict:
            regime = "REGIME_MACRO_CHOP"
            adapted["min_risk_reward_ratio"] = self._clamp("min_risk_reward_ratio", adapted["min_risk_reward_ratio"] - 0.10)
            adapted["momentum_z_threshold"] = self._clamp("momentum_z_threshold", adapted["momentum_z_threshold"] + 0.15)
            adapted["wick_ratio_threshold"] = self._clamp("wick_ratio_threshold", adapted["wick_ratio_threshold"] - 0.02)

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
        AI提案と統合、またはAIオフライン時の自律キャリブレーションとして機能する。
        """
        current = self.load_active_params()
        proposals: Dict[str, float] = {}

        recent = [t for t in closed_trades if t.get("profit") is not None][-50:]
        if not recent:
            return proposals

        wins = [t for t in recent if float(t.get("profit", 0)) > 0]
        losses = [t for t in recent if float(t.get("profit", 0)) < 0]
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
            # 過剰取引で勝率が低下している場合はわずかに厳選
            proposals["wick_ratio_threshold"] = self._clamp(
                "wick_ratio_threshold", current["wick_ratio_threshold"] + 0.03
            )
            proposals["momentum_z_threshold"] = self._clamp(
                "momentum_z_threshold", current["momentum_z_threshold"] + 0.05
            )

        # 2. 勝率・損益構造に応じたSL倍率＆RR微調整
        if len(recent) >= 10:
            if win_rate >= 0.58:
                proposals["min_risk_reward_ratio"] = self._clamp(
                    "min_risk_reward_ratio", current["min_risk_reward_ratio"] + 0.05
                )
            elif win_rate < 0.45 and len(losses) >= 6:
                # 損切り貧乏を防ぐためATR SL倍率をわずかに広げてノイズ耐性強化
                proposals["atr_sl_multiplier"] = self._clamp(
                    "atr_sl_multiplier", current["atr_sl_multiplier"] + 0.05
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
