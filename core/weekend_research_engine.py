import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config import settings
from core.mt5_conn import mt5


class WeekendResearchEngine:
    """
    【週末クオンツ自動検証研究室 (Weekend Macro-Correlation & Lead-Lag Lab)】

    毎週土曜日の市場クローズ後（土曜 08:00 JST）に自動起動し、直近の2026年最新実データ（M1 / M5）から：
    1. 各先行指標（DXY, USDJPY[米金利代替], USOIL, USTEC, AUDUSD）とゴールドの最新相関係数
    2. 複合条件（「金利が下げて他が上がった時」「原油高×金利高 vs 原油高×株安」など）のゴールド勝率・平均変動幅
    3. リードラグ（先行指標が動いてから1分後・3分後・5分後・10分後・15分後のどこでゴールドが最も伸びるか）
    を総当たりで統計検証し、`config/weekend_macro_study.json` を自動更新して翌週の `DualMacroEngine` に反映する。
    """

    SYMBOLS = ["XAUUSD", "DXY", "USDJPY", "USOIL", "USTEC", "AUDUSD"]

    def __init__(self):
        base_dir = Path(settings.BASE_DIR) if hasattr(settings, "BASE_DIR") else Path(".")
        self.config_dir = base_dir / "config"
        self.log_dir = Path(settings.LOG_DIR)
        self.study_file = self.config_dir / "weekend_macro_study.json"
        self.report_file = self.log_dir / "weekend_research_journal.md"

    def _fetch_df(self, symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
        try:
            mt5.symbol_select(symbol, True)
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None or len(rates) < 100:
                return None
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            return df[["time", "close"]].rename(columns={"close": symbol})
        except Exception:
            return None

    def run_weekend_study(self, m5_bars: int = 2400, m1_bars: int = 3000) -> Dict[str, Any]:
        """
        M5足（約2週間分）およびM1足（直近約50時間分）を用いた相関・複合条件・時間差の網羅検証
        """
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"🔬 [WEEKEND LAB] 最新相関・リードラグ・複合レジーム自動検証を開始 ({now_str})...")

        # 1. M5マルチアセット同期データ構築
        m5_dfs: List[pd.DataFrame] = []
        for sym in self.SYMBOLS:
            df = self._fetch_df(sym, mt5.TIMEFRAME_M5, m5_bars)
            if df is not None:
                m5_dfs.append(df)

        if len(m5_dfs) < 3:
            print("[WEEKEND LAB WARN] データ取得不足のため検証をスキップしました。")
            return {}

        merged_m5 = m5_dfs[0]
        for df in m5_dfs[1:]:
            merged_m5 = pd.merge(merged_m5, df, on="time", how="inner")

        if "XAUUSD" not in merged_m5.columns or len(merged_m5) < 200:
            return {}

        # 15分（M5×3本）リターンとZスコア（直近36本=3時間ローリング標準偏差で正規化）
        ret_15m = merged_m5.set_index("time").pct_change(3).dropna()
        vol_15m = ret_15m.rolling(36).std().replace(0, np.nan)
        z_15m = (ret_15m / vol_15m).dropna()

        # --- A. 相関係数マトリクス算出 ---
        correlations: Dict[str, float] = {}
        for sym in self.SYMBOLS:
            if sym != "XAUUSD" and sym in ret_15m.columns:
                c_val = float(ret_15m["XAUUSD"].corr(ret_15m[sym]))
                if np.isfinite(c_val):
                    correlations[sym] = round(c_val, 3)

        # DXYとUSDJPY(米金利プロキシ)の逆相関強度から最適バイアス重みを自動算出
        dxy_strength = max(0.15, abs(min(0.0, correlations.get("DXY", -0.45))))
        jpy_strength = max(0.15, abs(min(0.0, correlations.get("USDJPY", -0.45))))
        total_str = dxy_strength + jpy_strength
        w_dxy = round(max(0.30, min(0.70, dxy_strength / total_str)), 3)
        w_yield = round(1.0 - w_dxy, 3)

        # --- B. 複合条件（片方が下げて残りが上がった時どうなるか）の検証 ---
        xau_price_m5 = merged_m5.set_index("time")["XAUUSD"]
        # 15分後のゴールド変動幅（pips: $0.10 = 1 pip）
        fwd_xau_15m_pips = ((xau_price_m5.shift(-3) - xau_price_m5) / 0.10).reindex(z_15m.index)

        def _eval_scenario(mask: pd.Series, expected_dir: str) -> Dict[str, Any]:
            sub = fwd_xau_15m_pips[mask].dropna()
            n = int(len(sub))
            if n == 0:
                return {"samples": 0, "up_rate_pct": 0.0, "down_rate_pct": 0.0, "avg_pips_15m": 0.0, "verdict": "データなし"}
            up_rate = round(float((sub > 0).mean() * 100.0), 1)
            down_rate = round(float((sub < 0).mean() * 100.0), 1)
            avg_pips = round(float(sub.mean()), 1)
            win_rate = up_rate if expected_dir == "UP" else down_rate
            return {
                "samples": n,
                "up_rate_pct": up_rate,
                "down_rate_pct": down_rate,
                "avg_pips_15m": avg_pips,
                "expected_hit_rate_pct": win_rate,
            }

        has_dxy_jpy = ("DXY" in z_15m.columns and "USDJPY" in z_15m.columns)
        scenarios: Dict[str, Any] = {}
        if has_dxy_jpy:
            zd = z_15m["DXY"]
            zj = z_15m["USDJPY"]
            # 1. 両方下落（ドル安＋金利低下 → ゴールド買い本命）
            scenarios["both_down_gold_bull"] = _eval_scenario((zd <= -0.8) & (zj <= -0.8), "UP")
            # 2. 両方上昇（ドル高＋金利上昇 → ゴールド売り本命）
            scenarios["both_up_gold_bear"] = _eval_scenario((zd >= 0.8) & (zj >= 0.8), "DOWN")
            # 3. ねじれ①: 金利(USDJPY)は下げたが、DXYは上がった時（欧州通貨安・米金利低下）
            scenarios["yield_down_dxy_up_conflict"] = _eval_scenario((zj <= -0.8) & (zd >= 0.5), "UP")
            # 4. ねじれ②: DXYは下げたが、金利(USDJPY)は上がった時（ユーロ高・米金利上昇）
            scenarios["dxy_down_yield_up_conflict"] = _eval_scenario((zd <= -0.8) & (zj >= 0.5), "UP")

            if "USOIL" in z_15m.columns and "USTEC" in z_15m.columns:
                zo = z_15m["USOIL"]
                ze = z_15m["USTEC"]
                # 5. 原油高×株安×金利低下（地政学リスクオフ）
                scenarios["oil_up_geopolitical_risk_off"] = _eval_scenario((zo >= 0.8) & (ze <= -0.5) & (zj <= -0.5), "UP")
                # 6. 原油高×金利上昇（インフレ警戒型原油高の2026年アノマリー検証）
                scenarios["oil_up_inflation_yield_up"] = _eval_scenario((zo >= 0.8) & (zj >= 0.6), "DOWN")

        # --- C. リードラグ（時間差：何分後にゴールドが最も反応するか）M1検証 ---
        lead_lag_profile: Dict[str, Any] = {}
        df_xau_m1 = self._fetch_df("XAUUSD", mt5.TIMEFRAME_M1, m1_bars)
        df_dxy_m1 = self._fetch_df("DXY", mt5.TIMEFRAME_M1, m1_bars)
        df_jpy_m1 = self._fetch_df("USDJPY", mt5.TIMEFRAME_M1, m1_bars)

        if df_xau_m1 is not None and df_dxy_m1 is not None and df_jpy_m1 is not None:
            m1_all = pd.merge(df_xau_m1, df_dxy_m1, on="time", how="inner")
            m1_all = pd.merge(m1_all, df_jpy_m1, on="time", how="inner").set_index("time")

            if len(m1_all) >= 300:
                r3_dxy = m1_all["DXY"].pct_change(3)
                r3_jpy = m1_all["USDJPY"].pct_change(3)
                sd_dxy = r3_dxy.rolling(30).std().replace(0, np.nan)
                sd_jpy = r3_jpy.rolling(30).std().replace(0, np.nan)
                z3_dxy = r3_dxy / sd_dxy
                z3_jpy = r3_jpy / sd_jpy

                # 2市場同時ショック発生点
                bull_impulse = (z3_dxy <= -1.2) & (z3_jpy <= -1.0)
                bear_impulse = (z3_dxy >= 1.2) & (z3_jpy >= 1.0)

                lag_minutes = [1, 2, 3, 5, 10, 15]
                lag_stats: Dict[str, Dict[str, float]] = {}
                best_lag_min = 5
                best_avg_pips = -999.0

                for lag in lag_minutes:
                    fwd_pips = (m1_all["XAUUSD"].shift(-lag) - m1_all["XAUUSD"]) / 0.10
                    bull_moves = fwd_pips[bull_impulse].dropna()
                    bear_moves = (-fwd_pips[bear_impulse]).dropna()
                    combined = pd.concat([bull_moves, bear_moves])

                    if len(combined) > 0:
                        avg_p = round(float(combined.mean()), 1)
                        hit_r = round(float((combined > 0).mean() * 100.0), 1)
                        lag_stats[f"t_plus_{lag}m"] = {
                            "samples": int(len(combined)),
                            "directional_hit_rate_pct": hit_r,
                            "avg_favorable_pips": avg_p,
                        }
                        if avg_p > best_avg_pips:
                            best_avg_pips = avg_p
                            best_lag_min = lag

                lead_lag_profile = {
                    "m1_bars_analyzed": int(len(m1_all)),
                    "optimal_peak_lag_minutes": best_lag_min,
                    "peak_avg_favorable_pips": best_avg_pips if best_avg_pips > -900 else 0.0,
                    "horizon_breakdown": lag_stats,
                }

        study_result = {
            "generated_at": now_str,
            "m5_bars_analyzed": int(len(merged_m5)),
            "correlations_15m": correlations,
            "recommended_weights": {
                "dxy_weight": w_dxy,
                "yield_weight": w_yield,
            },
            "conditional_scenarios": scenarios,
            "lead_lag_profile": lead_lag_profile,
        }

        self._save_study(study_result)
        self._append_markdown_report(study_result)
        print(
            f"✅ [WEEKEND LAB COMPLETE] 検証完了! 相関: {correlations} | "
            f"推奨重み: DXY={w_dxy:.2f}, Yield={w_yield:.2f} | 最適ラグ: {lead_lag_profile.get('optimal_peak_lag_minutes', 5)}分"
        )
        return study_result

    def load_latest_study(self) -> Dict[str, Any]:
        if self.study_file.exists():
            try:
                with open(self.study_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_study(self, data: Dict[str, Any]) -> None:
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.study_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.study_file)
        except Exception as e:
            print(f"[WEEKEND LAB ERROR] 保存失敗: {e}")

    def _append_markdown_report(self, res: Dict[str, Any]) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            corrs = res.get("correlations_15m", {})
            weights = res.get("recommended_weights", {})
            sc = res.get("conditional_scenarios", {})
            ll = res.get("lead_lag_profile", {})

            b_down = sc.get("both_down_gold_bull", {})
            b_up = sc.get("both_up_gold_bear", {})
            c_yd = sc.get("yield_down_dxy_up_conflict", {})
            c_du = sc.get("dxy_down_yield_up_conflict", {})
            o_geo = sc.get("oil_up_geopolitical_risk_off", {})
            o_inf = sc.get("oil_up_inflation_yield_up", {})

            md = (
                f"\n## 🔬 {res.get('generated_at')} 週末クオンツ相関・リードラグ自動検証レポート\n"
                f"- **分析サンプル数**: M5足 `{res.get('m5_bars_analyzed')}` 本 / M1足 `{ll.get('m1_bars_analyzed', 0)}` 本\n"
                f"- **15分リターン相関係数 (対XAUUSD)**: `{json.dumps(corrs, ensure_ascii=False)}`\n"
                f"- **自動更新されたバイアス重み**: DXY = `{weights.get('dxy_weight')}` / 米金利(US10Y・USDJPY) = `{weights.get('yield_weight')}`\n"
                f"- **複合シナリオ実測結果 (15分後)**:\n"
                f"  1. `DXY↓ × 金利↓` (全面追い風): 上昇勝率 **{b_down.get('up_rate_pct', 0)}%** (平均 `{b_down.get('avg_pips_15m', 0):+.1f} pips`, n={b_down.get('samples', 0)})\n"
                f"  2. `DXY↑ × 金利↑` (全面逆風): 下落勝率 **{b_up.get('down_rate_pct', 0)}%** (平均 `{b_up.get('avg_pips_15m', 0):+.1f} pips`, n={b_up.get('samples', 0)})\n"
                f"  3. `金利↓ × DXY↑` (ねじれ①): 上昇率 `{c_yd.get('up_rate_pct', 0)}%` / 下落率 `{c_yd.get('down_rate_pct', 0)}%` (平均 `{c_yd.get('avg_pips_15m', 0):+.1f} pips`)\n"
                f"  4. `DXY↓ × 金利↑` (ねじれ②): 上昇率 `{c_du.get('up_rate_pct', 0)}%` / 下落率 `{c_du.get('down_rate_pct', 0)}%` (平均 `{c_du.get('avg_pips_15m', 0):+.1f} pips`)\n"
                f"  5. `原油↑ × 株↓ × 金利↓` (地政学リスクオフ): 上昇率 **{o_geo.get('up_rate_pct', 0)}%** (平均 `{o_geo.get('avg_pips_15m', 0):+.1f} pips`)\n"
                f"  6. `原油↑ × 金利↑` (インフレ型原油高): 下落率 **{o_inf.get('down_rate_pct', 0)}%** (平均 `{o_inf.get('avg_pips_15m', 0):+.1f} pips`)\n"
                f"- **リードラグ（時間差）ピーク**: 先行指標急変から **`{ll.get('optimal_peak_lag_minutes', 5)}分後`** に最大順行 (平均 `{ll.get('peak_avg_favorable_pips', 0):+.1f} pips`)\n"
            )
            with open(self.report_file, "a", encoding="utf-8") as f:
                f.write(md)
        except Exception as e:
            print(f"[WEEKEND LAB REPORT WARN] {e}")
