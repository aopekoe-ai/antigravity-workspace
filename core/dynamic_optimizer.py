import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple

logger = logging.getLogger("DynamicOptimizer")

class DynamicParamOptimizer:
    """
    【世界トップクオンツ・自己適応型パラメータオプティマイザ】
    
    プロップファーム・ヘッジファンドの運用原則に基づき、
    「資金防衛インターロック（絶対固定枠）」を厳格に死守しながら、
    「市場適応パラメータ（可変枠）」のみを安全リミッター（ガードレール）内で自己最適化する。
    """
    
    # -------------------------------------------------------------
    # 1. 資金防衛インターロック（AIによる書き換え絶対禁止枠）
    # -------------------------------------------------------------
    IMMUTABLE_RULES = {
        "enforce_single_position": True,      # 単一ポジション限定（ナンピン・両建て絶対禁止）
        "max_risk_per_trade_percent": 1.5,   # 1トレード最大許容損失 1.5%
        "max_daily_drawdown_percent": 3.0,   # 日次最大許容損失（サーキットブレーカー） 3.0%
        "hard_sl_required": True,             # ブローカー側ハードSL付与必須
        "max_spread_pips_ceiling": 4.0        # スプレッド許容上限の絶対天井
    }

    # -------------------------------------------------------------
    # 2. 安全ガードレール（可変パラメータの許容レンジ・最大変動幅）
    # -------------------------------------------------------------
    GUARDRAILS = {
        "min_risk_reward_ratio": {
            "min": 1.2,
            "max": 2.5,
            "default": 1.5,
            "max_step": 0.3,
            "description": "最小リスクリワード比率"
        },
        "wick_ratio_threshold": {
            "min": 0.20,
            "max": 0.60,
            "default": 0.30,
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
            "min": 10.0,
            "max": 25.0,
            "default": 12.0,
            "max_step": 3.0,
            "description": "最小SL幅（pips）"
        },
        "max_sl_pips": {
            "min": 40.0,
            "max": 70.0,
            "default": 55.0,
            "max_step": 5.0,
            "description": "最大SL幅（pips）"
        },
        "atr_sl_multiplier": {
            "min": 1.0,
            "max": 2.0,
            "default": 1.4,
            "max_step": 0.2,
            "description": "ATR SL倍率"
        },
        "max_allowed_spread_pips": {
            "min": 2.0,
            "max": 3.5,
            "default": 3.0,
            "max_step": 0.5,
            "description": "許容最大スプレッド（pips）"
        }
    }

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.params_file = self.config_dir / "dynamic_params.json"
        self._ensure_params_file()

    def _ensure_params_file(self):
        """dynamic_params.json が存在しない場合はデフォルト値で初期化"""
        if not self.params_file.exists():
            default_params = {
                k: v["default"] for k, v in self.GUARDRAILS.items()
            }
            default_params["version"] = 1
            default_params["last_updated"] = "INITIAL"
            default_params["reason"] = "Default configuration initialized"
            self._save_params(default_params)

    def load_active_params(self) -> Dict[str, Any]:
        """現在適用中の動的パラメータを取得（整合性チェック付き）"""
        self._ensure_params_file()
        try:
            with open(self.params_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # ガードレール内にクランプされているか念のため再検証
            validated = {}
            for k, rule in self.GUARDRAILS.items():
                val = data.get(k, rule["default"])
                validated[k] = max(rule["min"], min(rule["max"], float(val)))
            validated["version"] = data.get("version", 1)
            validated["last_updated"] = data.get("last_updated", "")
            return validated
        except Exception as e:
            logger.error(f"Error loading dynamic params: {e}, returning defaults")
            return {k: v["default"] for k, v in self.GUARDRAILS.items()}

    def apply_optimization(self, proposed_changes: Dict[str, Any], reason: str, date_str: str) -> Tuple[bool, Dict[str, Any], str]:
        """
        AIまたはレビューエンジンが提案したパラメータ変更案を検証し、
        ガードレール（上下限および1回あたりの最大変動幅）に収まるようクランプして安全に適用。
        
        Returns:
            (success: bool, applied_params: dict, summary_message: str)
        """
        current_params = self.load_active_params()
        new_params = current_params.copy()
        adjustments = []

        for key, proposed_val in proposed_changes.items():
            if key not in self.GUARDRAILS:
                continue  # 未定義パラメータや固定枠の変更要求は安全のため破棄
            
            rule = self.GUARDRAILS[key]
            current_val = current_params.get(key, rule["default"])
            
            try:
                target_val = float(proposed_val)
            except (ValueError, TypeError):
                continue

            # 1. 1回の更新幅（ステップ幅）の制限
            max_step = rule["max_step"]
            delta = target_val - current_val
            if abs(delta) > max_step:
                clamped_delta = max_step if delta > 0 else -max_step
                target_val = current_val + clamped_delta

            # 2. ハード上限・下限の制限
            final_val = round(max(rule["min"], min(rule["max"], target_val)), 3)

            if final_val != current_val:
                new_params[key] = final_val
                adjustments.append(f"{key}: {current_val} -> {final_val} ({rule['description']})")

        if not adjustments:
            return False, current_params, "有効なパラメータ変更はありませんでした（現状維持）。"

        new_params["version"] = current_params.get("version", 1) + 1
        new_params["last_updated"] = date_str
        new_params["reason"] = reason

        self._save_params(new_params)
        summary = f"【自動最適化適用 (v{new_params['version']})】\n" + "\n".join([f"・{adj}" for adj in adjustments]) + f"\n根拠: {reason}"
        return True, new_params, summary

    def _save_params(self, params: Dict[str, Any]):
        try:
            with open(self.params_file, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save dynamic params: {e}")
