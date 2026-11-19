import datetime
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from strategies.base_strategy import BaseStrategy, TradeSignal


class SMCLiquiditySweepStrategy(BaseStrategy):
    """
    【世界トップクオンツ・プロップファーム仕様 v9.0 (SMC + Macro Hybrid Edition)】
    上位足（H1/M15）トレンドフォローを絶対軸とし、3系統エンジンで機会損失ゼロと高期待値を両立：

    【系統1: 型A コンフルエンス・マクロモメンタム (FVG不要)】
      - DXY + US10Y（MT5バックアップ時は DXY + USDJPY）の2市場同時急変＋初動往復ビンタ回避
        ＋ゴールド追随確認＋飛び乗り防止（Max Chase）で、FVGを待たずにトレンド初動〜第2波を捕捉。
    【系統2: 型B SMTダイバージェンス (FVG不要)】
      - DXYが新高値/新安値を更新したのにXAUUSDが追随しない「機関の吸収」を検知し、
        上位足トレンド方向の最高精度押し目・戻り目をFVGなしで即捕捉。
    【系統3: 既存SMC 3大トリガー ＋ マクロ強弱オーバーレイ】
      1. フラクタル・ピボット流動性スイープ (Fractal Pivot Sweep)
      2. ICT Fair Value Gap (FVG / 不均衡ゾーン) リテスト
      3. トレンドモメンタム EMA20 プルバック反発
      ※先行指標が極端逆行（<=-0.70）時のみハード防御、微逆行時はロット0.75xで機会温存、
        順行一致時はロット1.25xブースト＆TP15%拡張。
    """

    def __init__(self, params: Dict[str, Any]):
        super().__init__(name="SMC_Macro_Hybrid_v9.0", params=params)
        vol_params = params.get("volatility_parameters", {})
        self.atr_multiplier = vol_params.get("atr_sl_multiplier", 1.3)
        self.min_sl_pips = vol_params.get("min_sl_pips", 12.0)
        self.max_sl_pips = vol_params.get("max_sl_pips", 55.0)
        self.min_rr = vol_params.get("min_risk_reward_ratio", 1.5)
        self.wick_ratio = 0.30
        self.min_fvg_gap = 0.30
        self.sessions_config = params.get("execution_filters", {}).get("allowed_sessions_jst", [
            {"name": "Asia", "start_hour": 8, "end_hour": 15},
            {"name": "London_Pre", "start_hour": 15, "end_hour": 16},
            {"name": "London", "start_hour": 16, "end_hour": 24},
            {"name": "NewYork", "start_hour": 21, "end_hour": 6}
        ])
        self.macro_cfg = params.get("macro_engine", {})

    def update_dynamic_params(self, dynamic_params: Dict[str, Any]):
        """自己最適化エンジンによって更新された動的パラメータを反映"""
        if "min_risk_reward_ratio" in dynamic_params:
            self.min_rr = float(dynamic_params["min_risk_reward_ratio"])
        if "wick_ratio_threshold" in dynamic_params:
            self.wick_ratio = float(dynamic_params["wick_ratio_threshold"])
        if "min_fvg_gap_dollars" in dynamic_params:
            self.min_fvg_gap = float(dynamic_params["min_fvg_gap_dollars"])
        if "min_sl_pips" in dynamic_params:
            self.min_sl_pips = float(dynamic_params["min_sl_pips"])
        if "max_sl_pips" in dynamic_params:
            self.max_sl_pips = float(dynamic_params["max_sl_pips"])
        if "atr_sl_multiplier" in dynamic_params:
            self.atr_multiplier = float(dynamic_params["atr_sl_multiplier"])
        for m_key in ("momentum_z_threshold", "macro_sl_atr_multiplier", "macro_min_rr", "smt_min_rr"):
            if m_key in dynamic_params:
                self.macro_cfg[m_key] = float(dynamic_params[m_key])
        if "active_regime" in dynamic_params:
            self.active_regime = str(dynamic_params["active_regime"])

    def update_macro_config(self, macro_cfg: Dict[str, Any]):
        if macro_cfg:
            self.macro_cfg = macro_cfg

    def get_active_session(self) -> Optional[str]:
        """現在時刻（JST）の取引許可セッション判定"""
        now_jst = datetime.datetime.now()
        hour = now_jst.hour
        for s in self.sessions_config:
            s_start = s.get("start_hour", 0)
            s_end = s.get("end_hour", 24)
            name = s.get("name", "Unknown")
            if s_start <= s_end:
                if s_start <= hour < s_end:
                    return name
            else:
                if hour >= s_start or hour < s_end:
                    return name
        return None

    def _find_fractals(self, df: pd.DataFrame, lookback: int = 40) -> Tuple[List[float], List[float]]:
        """M5足からフラクタル高値（山）とフラクタル安値（谷）の流動性プールを検出"""
        highs = []
        lows = []
        start_idx = max(2, len(df) - lookback)
        for i in range(start_idx, len(df) - 2):
            if (df['high'].iloc[i] > df['high'].iloc[i-1] and
                df['high'].iloc[i] > df['high'].iloc[i-2] and
                df['high'].iloc[i] > df['high'].iloc[i+1] and
                df['high'].iloc[i] > df['high'].iloc[i+2]):
                highs.append(float(df['high'].iloc[i]))

            if (df['low'].iloc[i] < df['low'].iloc[i-1] and
                df['low'].iloc[i] < df['low'].iloc[i-2] and
                df['low'].iloc[i] < df['low'].iloc[i+1] and
                df['low'].iloc[i] < df['low'].iloc[i+2]):
                lows.append(float(df['low'].iloc[i]))
        return highs, lows

    def _find_recent_fvg(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """直近の未埋めフェアバリューギャップ（FVG）を検出"""
        for i in range(len(df) - 6, len(df) - 2):
            c_p2 = df.iloc[i-1]
            c_c0 = df.iloc[i+1]

            if c_c0['low'] > c_p2['high']:
                gap = c_c0['low'] - c_p2['high']
                if gap >= getattr(self, '_current_min_fvg_gap', 0.40):
                    return {"type": "BULLISH_FVG", "top": float(c_c0['low']), "bottom": float(c_p2['high']), "index": i}

            if c_p2['low'] > c_c0['high']:
                gap = c_p2['low'] - c_c0['high']
                if gap >= getattr(self, '_current_min_fvg_gap', 0.40):
                    return {"type": "BEARISH_FVG", "top": float(c_p2['low']), "bottom": float(c_c0['high']), "index": i}
        return None

    def _apply_macro_overlay(
        self,
        signal: TradeSignal,
        macro_state: Dict[str, Any],
        current_ask: float,
        current_bid: float,
        pip_size: float,
    ) -> Optional[TradeSignal]:
        """
        既存SMCシグナルへの先行指標オーバーレイ（ハード防御 / ソフト減額 / 順行ブースト）
        機会を殺さないため、極端な逆行時のみブロックし、軽微な逆行はロット縮小で対応する。
        """
        if not macro_state or macro_state.get("source", "NONE") == "NONE":
            return signal

        bias = float(macro_state.get("macro_bias_score", 0.0))
        source = str(macro_state.get("source", "MT5_M1"))
        geo_risk_off = bool(macro_state.get("is_geopolitical_risk_off", False))

        hard_th = float(self.macro_cfg.get("hard_guard_threshold", 0.70))
        soft_th = float(self.macro_cfg.get("soft_guard_threshold", 0.35))
        boost_mult = float(self.macro_cfg.get("boost_lot_multiplier", 1.25))
        soft_mult = float(self.macro_cfg.get("soft_guard_lot_multiplier", 0.75))

        aligned_score = bias if signal.action == "BUY" else -bias

        # 1. ハードガード（2市場が強烈に逆行している自滅局面のみブロック）
        if aligned_score <= -hard_th:
            self.last_hard_guard_blocked = True
            print(
                f"[MACRO HARD GUARD] {signal.setup_name} ({signal.action}) を見送り "
                f"(source={source}, aligned_score={aligned_score:+.2f} <= -{hard_th:.2f})"
            )
            return None

        signal.macro_source = source

        # 2. ソフトガード（軽微逆行 → 取引機会は残しつつロットを0.75xへ圧縮）
        if aligned_score <= -soft_th:
            signal.lot_multiplier = soft_mult
            signal.rationale_ja += (
                f" [マクロ微逆行({source}, score={aligned_score:+.2f}): ロット{soft_mult:.2f}xでリスク圧縮]"
            )
            return signal

        # 3. 順行ブースト（マクロが味方、またはBUY時の地政学リスクオフ → ロット1.25x ＆ TP+15%拡張）
        if aligned_score >= soft_th or (signal.action == "BUY" and geo_risk_off):
            signal.lot_multiplier = boost_mult
            boosted_tp_pips = round(signal.tp_distance_pips * 1.15, 1)
            signal.tp_distance_pips = boosted_tp_pips
            if signal.action == "BUY":
                signal.suggested_tp_price = round(current_ask + (boosted_tp_pips * pip_size), 2)
            else:
                signal.suggested_tp_price = round(current_bid - (boosted_tp_pips * pip_size), 2)
            signal.risk_reward_ratio = round(boosted_tp_pips / signal.sl_distance_pips, 2)
            signal.confidence = min(0.95, round(signal.confidence + 0.04, 2))
            geo_note = "+地政学リスクオフ" if (signal.action == "BUY" and geo_risk_off) else ""
            signal.rationale_ja += (
                f" [マクロ順行ブースト({source}{geo_note}, score={aligned_score:+.2f}): "
                f"ロット{boost_mult:.2f}x & TP拡張 RR 1:{signal.risk_reward_ratio}]"
            )
            return signal

        return signal

    def evaluate(self, market_data: Dict[str, Any]) -> TradeSignal:
        df_m5 = market_data.get("df_m5")
        current_ask = market_data.get("current_ask", 0.0)
        current_bid = market_data.get("current_bid", 0.0)
        pip_size = market_data.get("pip_size", 0.10)
        atr_dollars = market_data.get("atr_m5_dollars") or (market_data.get("atr_m15_dollars", 2.0) * 0.7)
        asia_high = market_data.get("asia_high")
        asia_low = market_data.get("asia_low")
        pdh = market_data.get("pdh")
        pdl = market_data.get("pdl")
        h1_trend = market_data.get("h1_trend", "NEUTRAL")
        m15_trend = market_data.get("m15_trend", "NEUTRAL")
        macro_state = market_data.get("macro_state") or {}

        effective_min_sl_pips = max(18.0, round((atr_dollars * 1.0) / pip_size, 1))
        effective_max_sl_pips = max(50.0, round((atr_dollars * 3.5) / pip_size, 1))
        effective_min_fvg_gap = max(0.40, round(atr_dollars * 0.30, 2))

        # 上位足トレンドフォロー制約（H1上昇中はBUYのみ、H1下降中はSELLのみ、H1中立時は双方向許可）
        allow_buy = (h1_trend != "BEARISH")
        allow_sell = (h1_trend != "BULLISH")

        # 1. セッションフィルター
        active_session = self.get_active_session()
        if not active_session:
            return TradeSignal(
                action="NO_TRADE",
                confidence=0.0,
                suggested_entry_price=current_ask,
                suggested_sl_price=0.0,
                suggested_tp_price=0.0,
                sl_distance_pips=0.0,
                tp_distance_pips=0.0,
                risk_reward_ratio=0.0,
                setup_name="Session_Filter_Wait",
                rationale_ja="休場・流動性過疎時間帯。東京・ロンドン・NYセッション待機中。"
            )

        if df_m5 is None or len(df_m5) < 35:
            return TradeSignal(
                action="NO_TRADE",
                confidence=0.0,
                suggested_entry_price=current_ask,
                suggested_sl_price=0.0,
                suggested_tp_price=0.0,
                sl_distance_pips=0.0,
                tp_distance_pips=0.0,
                risk_reward_ratio=0.0,
                setup_name="Insufficient_Data",
                rationale_ja="M5ローソク足データ数が不足しています。"
            )

        macro_enabled = bool(self.macro_cfg.get("enabled", True))
        active_open_engines = set(market_data.get("active_open_engines") or [])
        self.last_hard_guard_blocked = False

        # =====================================================================
        # 系統 1 (新規・型A): コンフルエンス・マクロモメンタム (FVG不要・上位足順張り)
        # =====================================================================
        if macro_enabled and ("MACRO_MOMENTUM" not in active_open_engines) and macro_state.get("momentum_signal") in ("BUY", "SELL"):
            m_dir = macro_state["momentum_signal"]
            m_src = macro_state.get("momentum_source", "MT5_M1")
            m_detail = macro_state.get("momentum_detail", "")
            htf_ok = (m_dir == "BUY" and allow_buy) or (m_dir == "SELL" and allow_sell)

            if htf_ok:
                macro_sl_mult = float(self.macro_cfg.get("macro_sl_atr_multiplier", 1.7))
                macro_max_sl = max(effective_max_sl_pips, 75.0)
                raw_sl_pips = round((atr_dollars * macro_sl_mult) / pip_size, 1)
                sl_pips = round(max(effective_min_sl_pips, min(macro_max_sl, raw_sl_pips)), 1)

                # H1 + M15 完全一致時はRR 2.2で大きく伸ばす
                full_htf_align = (
                    (m_dir == "BUY" and h1_trend == "BULLISH" and m15_trend == "BULLISH")
                    or (m_dir == "SELL" and h1_trend == "BEARISH" and m15_trend == "BEARISH")
                )
                base_macro_rr = float(self.macro_cfg.get("macro_min_rr", 1.8))
                target_rr = 2.2 if full_htf_align else base_macro_rr
                tp_pips = round(sl_pips * target_rr, 1)
                rr = round(tp_pips / sl_pips, 2)

                entry_px = current_ask if m_dir == "BUY" else current_bid
                sl_price = round(entry_px - (sl_pips * pip_size), 2) if m_dir == "BUY" else round(entry_px + (sl_pips * pip_size), 2)
                tp_price = round(entry_px + (tp_pips * pip_size), 2) if m_dir == "BUY" else round(entry_px - (tp_pips * pip_size), 2)

                htf_boost = (
                    (m_dir == "BUY" and h1_trend == "BULLISH")
                    or (m_dir == "SELL" and h1_trend == "BEARISH")
                    or (m_dir == "BUY" and bool(macro_state.get("is_geopolitical_risk_off")))
                )
                lot_mult = 1.15 if htf_boost else 1.0
                conf = 0.90 if m_src == "TV_WEBHOOK" else 0.86

                return TradeSignal(
                    action=m_dir,
                    confidence=conf,
                    suggested_entry_price=entry_px,
                    suggested_sl_price=sl_price,
                    suggested_tp_price=tp_price,
                    sl_distance_pips=sl_pips,
                    tp_distance_pips=tp_pips,
                    risk_reward_ratio=rr,
                    setup_name=f"MacroA_{active_session}_{m_src}_Momentum_{m_dir}",
                    rationale_ja=(
                        f"[{active_session}/型Aマクロモメンタム] FVG不要の上位足順張り(H1:{h1_trend}, M15:{m15_trend})。"
                        f"{m_detail}。SL: {sl_pips}pips(M5 ATR動的), RR 1:{rr}, ロット倍率:{lot_mult:.2f}x"
                    ),
                    invalidation_level=sl_price,
                    entry_engine="MACRO_MOMENTUM",
                    macro_source=m_src,
                    lot_multiplier=lot_mult,
                )

        # =====================================================================
        # 系統 2 (新規・型B): SMTダイバージェンス (機関の吸収・FVG不要・上位足順張り)
        # =====================================================================
        if macro_enabled and ("SMT_DIVERGENCE" not in active_open_engines) and macro_state.get("smt_signal") in ("BUY", "SELL"):
            s_dir = macro_state["smt_signal"]
            s_src = macro_state.get("smt_source", "MT5_M1")
            s_detail = macro_state.get("smt_detail", "")
            s_swing = macro_state.get("smt_swing_level")
            htf_ok = (s_dir == "BUY" and allow_buy) or (s_dir == "SELL" and allow_sell)

            if htf_ok:
                entry_px = current_ask if s_dir == "BUY" else current_bid
                pad = atr_dollars * 0.40
                if s_dir == "BUY":
                    anchor = float(s_swing) if s_swing is not None else (entry_px - atr_dollars * 1.1)
                    raw_sl_price = anchor - pad
                    raw_sl_pips = round((entry_px - raw_sl_price) / pip_size, 1)
                else:
                    anchor = float(s_swing) if s_swing is not None else (entry_px + atr_dollars * 1.1)
                    raw_sl_price = anchor + pad
                    raw_sl_pips = round((raw_sl_price - entry_px) / pip_size, 1)

                # スイングが極端に浅い場合でも最低SL幅を確保してノイズ狩りを防止
                sl_pips = round(max(effective_min_sl_pips, raw_sl_pips), 1)
                if sl_pips <= effective_max_sl_pips:
                    sl_price = round(entry_px - (sl_pips * pip_size), 2) if s_dir == "BUY" else round(entry_px + (sl_pips * pip_size), 2)
                    smt_rr = float(self.macro_cfg.get("smt_min_rr", 2.0))
                    tp_pips = round(sl_pips * smt_rr, 1)
                    tp_price = round(entry_px + (tp_pips * pip_size), 2) if s_dir == "BUY" else round(entry_px - (tp_pips * pip_size), 2)
                    rr = round(tp_pips / sl_pips, 2)

                    aligned_htf = (s_dir == "BUY" and h1_trend == "BULLISH") or (s_dir == "SELL" and h1_trend == "BEARISH")
                    lot_mult = 1.15 if aligned_htf else 1.0
                    conf = 0.89 if s_src == "TV_WEBHOOK" else 0.85

                    return TradeSignal(
                        action=s_dir,
                        confidence=conf,
                        suggested_entry_price=entry_px,
                        suggested_sl_price=sl_price,
                        suggested_tp_price=tp_price,
                        sl_distance_pips=sl_pips,
                        tp_distance_pips=tp_pips,
                        risk_reward_ratio=rr,
                        setup_name=f"MacroB_{active_session}_{s_src}_SMT_{s_dir}",
                        rationale_ja=(
                            f"[{active_session}/型B SMTダイバージェンス] FVG不要の上位足順張り(H1:{h1_trend})。"
                            f"{s_detail}。SL: {sl_pips}pips, RR 1:{rr}, ロット倍率:{lot_mult:.2f}x"
                        ),
                        invalidation_level=sl_price,
                        entry_engine="SMT_DIVERGENCE",
                        macro_source=s_src,
                        lot_multiplier=lot_mult,
                    )

        # =====================================================================
        # 系統 3 (既存SMC): フラクタル・FVG・EMA20 ＋ マクロ強弱オーバーレイ
        # =====================================================================
        c1 = df_m5.iloc[-2]  # 直前確定足
        c2 = df_m5.iloc[-3]  # 前々足

        # --- SMCトリガー 1: フラクタル・ピボット流動性スイープ ---
        fractal_highs, fractal_lows = self._find_fractals(df_m5, lookback=35)
        all_high_pools = fractal_highs + [h for h in [asia_high, pdh] if h is not None]
        all_low_pools  = fractal_lows  + [l for l in [asia_low, pdl] if l is not None]

        valid_highs = [h for h in all_high_pools if h > current_bid - (atr_dollars * 1.5)]
        valid_lows  = [l for l in all_low_pools  if l < current_ask + (atr_dollars * 1.5)]

        smc_can_open = ("SMC" not in active_open_engines)

        # SELL: 高値流動性スイープ
        if smc_can_open and allow_sell:
            for target_h in sorted(valid_highs, reverse=True)[:3]:
                if (c1['high'] >= target_h or c2['high'] >= target_h) and c1['close'] < target_h:
                    c1_upper_wick = c1['high'] - max(c1['open'], c1['close'])
                    c1_body = abs(c1['close'] - c1['open'])
                    is_single_pinbar = (c1_upper_wick >= c1_body * self.wick_ratio) or (c1['close'] < c1['open'])
                    is_combo_sweep = (c2['high'] >= target_h and c1['close'] < c2['close'] and c1['close'] < c1['open'])

                    if is_single_pinbar or is_combo_sweep:
                        sweep_h = max(c1['high'], c2['high'])
                        sl_price = round(sweep_h + (atr_dollars * (self.atr_multiplier * 0.25)), 2)
                        sl_pips = round((sl_price - current_bid) / pip_size, 1)

                        if effective_min_sl_pips <= sl_pips <= effective_max_sl_pips:
                            tp_pips = round(sl_pips * self.min_rr, 1)
                            tp_price = round(current_bid - (tp_pips * pip_size), 2)
                            rr = round(tp_pips / sl_pips, 2)
                            cand = TradeSignal(
                                action="SELL",
                                confidence=0.88,
                                suggested_entry_price=current_bid,
                                suggested_sl_price=sl_price,
                                suggested_tp_price=tp_price,
                                sl_distance_pips=sl_pips,
                                tp_distance_pips=tp_pips,
                                risk_reward_ratio=rr,
                                setup_name=f"SMC_{active_session}_Fractal_High_Sweep",
                                rationale_ja=f"[{active_session}] フラクタル高値 (${target_h:.2f}) のストップ狩り（上ヒゲ/2本合成反落）を検知。個人買いトラップからの急反落狙い。SL: {sl_pips}pips, RR 1:{rr}",
                                invalidation_level=sweep_h,
                                entry_engine="SMC",
                            )
                            checked = self._apply_macro_overlay(cand, macro_state, current_ask, current_bid, pip_size)
                            if checked:
                                return checked

        # BUY: 安値流動性スイープ
        if smc_can_open and allow_buy:
            for target_l in sorted(valid_lows)[:3]:
                if (c1['low'] <= target_l or c2['low'] <= target_l) and c1['close'] > target_l:
                    c1_lower_wick = min(c1['open'], c1['close']) - c1['low']
                    c1_body = abs(c1['close'] - c1['open'])
                    is_single_pinbar = (c1_lower_wick >= c1_body * self.wick_ratio) or (c1['close'] > c1['open'])
                    is_combo_sweep = (c2['low'] <= target_l and c1['close'] > c2['close'] and c1['close'] > c1['open'])

                    if is_single_pinbar or is_combo_sweep:
                        sweep_l = min(c1['low'], c2['low'])
                        sl_price = round(sweep_l - (atr_dollars * (self.atr_multiplier * 0.25)), 2)
                        sl_pips = round((current_ask - sl_price) / pip_size, 1)

                        if effective_min_sl_pips <= sl_pips <= effective_max_sl_pips:
                            tp_pips = round(sl_pips * self.min_rr, 1)
                            tp_price = round(current_ask + (tp_pips * pip_size), 2)
                            rr = round(tp_pips / sl_pips, 2)
                            cand = TradeSignal(
                                action="BUY",
                                confidence=0.88,
                                suggested_entry_price=current_ask,
                                suggested_sl_price=sl_price,
                                suggested_tp_price=tp_price,
                                sl_distance_pips=sl_pips,
                                tp_distance_pips=tp_pips,
                                risk_reward_ratio=rr,
                                setup_name=f"SMC_{active_session}_Fractal_Low_Sweep",
                                rationale_ja=f"[{active_session}] フラクタル安値 (${target_l:.2f}) のストップ狩り（下ヒゲ/2本合成反発）を検知。個人売りトラップからの急反発狙い。SL: {sl_pips}pips, RR 1:{rr}",
                                invalidation_level=sweep_l,
                                entry_engine="SMC",
                            )
                            checked = self._apply_macro_overlay(cand, macro_state, current_ask, current_bid, pip_size)
                            if checked:
                                return checked

        # --- SMCトリガー 2: ICT Fair Value Gap (FVG / 不均衡ゾーン) リテスト ---
        self._current_min_fvg_gap = effective_min_fvg_gap
        fvg = self._find_recent_fvg(df_m5) if smc_can_open else None
        if fvg:
            if allow_buy and fvg["type"] == "BULLISH_FVG" and (c1['low'] <= fvg["top"]) and (c1['close'] > fvg["bottom"]):
                sl_price = round(fvg["bottom"] - (atr_dollars * 0.3), 2)
                sl_pips = round((current_ask - sl_price) / pip_size, 1)
                if effective_min_sl_pips <= sl_pips <= effective_max_sl_pips:
                    tp_pips = round(sl_pips * self.min_rr, 1)
                    tp_price = round(current_ask + (tp_pips * pip_size), 2)
                    rr = round(tp_pips / sl_pips, 2)
                    cand = TradeSignal(
                        action="BUY",
                        confidence=0.84,
                        suggested_entry_price=current_ask,
                        suggested_sl_price=sl_price,
                        suggested_tp_price=tp_price,
                        sl_distance_pips=sl_pips,
                        tp_distance_pips=tp_pips,
                        risk_reward_ratio=rr,
                        setup_name=f"ICT_{active_session}_Bullish_FVG_Retest",
                        rationale_ja=f"[{active_session}] 大口インパルス波の未埋め不均衡ゾーン (FVG: ${fvg['bottom']:.2f}-${fvg['top']:.2f}) へのプルバック反発を検知。押し目買い。SL: {sl_pips}pips, RR 1:{rr}",
                        invalidation_level=sl_price,
                        entry_engine="SMC",
                    )
                    checked = self._apply_macro_overlay(cand, macro_state, current_ask, current_bid, pip_size)
                    if checked:
                        return checked

            if allow_sell and fvg["type"] == "BEARISH_FVG" and (c1['high'] >= fvg["bottom"]) and (c1['close'] < fvg["top"]):
                sl_price = round(fvg["top"] + (atr_dollars * 0.3), 2)
                sl_pips = round((sl_price - current_bid) / pip_size, 1)
                if effective_min_sl_pips <= sl_pips <= effective_max_sl_pips:
                    tp_pips = round(sl_pips * self.min_rr, 1)
                    tp_price = round(current_bid - (tp_pips * pip_size), 2)
                    rr = round(tp_pips / sl_pips, 2)
                    cand = TradeSignal(
                        action="SELL",
                        confidence=0.84,
                        suggested_entry_price=current_bid,
                        suggested_sl_price=sl_price,
                        suggested_tp_price=tp_price,
                        sl_distance_pips=sl_pips,
                        tp_distance_pips=tp_pips,
                        risk_reward_ratio=rr,
                        setup_name=f"ICT_{active_session}_Bearish_FVG_Retest",
                        rationale_ja=f"[{active_session}] 大口インパルス波の未埋め不均衡ゾーン (FVG: ${fvg['bottom']:.2f}-${fvg['top']:.2f}) への戻り目リジェクションを検知。戻り売り。SL: {sl_pips}pips, RR 1:{rr}",
                        invalidation_level=sl_price,
                        entry_engine="SMC",
                    )
                    checked = self._apply_macro_overlay(cand, macro_state, current_ask, current_bid, pip_size)
                    if checked:
                        return checked

        # --- SMCトリガー 3: トレンドモメンタム EMA20 プルバック反発 ---
        if smc_can_open and len(df_m5) >= 50:
            ema20 = float(df_m5['close'].ewm(span=20, adjust=False).mean().iloc[-2])
            ema50 = float(df_m5['close'].ewm(span=50, adjust=False).mean().iloc[-2])

            if allow_buy and ema20 > ema50 and (c1['low'] <= ema20 * 1.0006) and (c1['close'] > ema20) and (c1['close'] >= c1['open']):
                sl_price = round(min(c1['low'], ema50) - (atr_dollars * 0.3), 2)
                sl_pips = round((current_ask - sl_price) / pip_size, 1)
                if effective_min_sl_pips <= sl_pips <= effective_max_sl_pips:
                    tp_pips = round(sl_pips * self.min_rr, 1)
                    tp_price = round(current_ask + (tp_pips * pip_size), 2)
                    rr = round(tp_pips / sl_pips, 2)
                    cand = TradeSignal(
                        action="BUY",
                        confidence=0.80,
                        suggested_entry_price=current_ask,
                        suggested_sl_price=sl_price,
                        suggested_tp_price=tp_price,
                        sl_distance_pips=sl_pips,
                        tp_distance_pips=tp_pips,
                        risk_reward_ratio=rr,
                        setup_name=f"Trend_{active_session}_EMA20_Bounce_BUY",
                        rationale_ja=f"[{active_session}] M5上昇トレンド推進中（EMA20 > EMA50）。EMA20 (${ema20:.2f}) への押し目反発を検知し順張り押し目買い。SL: {sl_pips}pips, RR 1:{rr}",
                        invalidation_level=sl_price,
                        entry_engine="SMC",
                    )
                    checked = self._apply_macro_overlay(cand, macro_state, current_ask, current_bid, pip_size)
                    if checked:
                        return checked

            if allow_sell and ema20 < ema50 and (c1['high'] >= ema20 * 0.9994) and (c1['close'] < ema20) and (c1['close'] <= c1['open']):
                sl_price = round(max(c1['high'], ema50) + (atr_dollars * 0.3), 2)
                sl_pips = round((sl_price - current_bid) / pip_size, 1)
                if effective_min_sl_pips <= sl_pips <= effective_max_sl_pips:
                    tp_pips = round(sl_pips * self.min_rr, 1)
                    tp_price = round(current_bid - (tp_pips * pip_size), 2)
                    rr = round(tp_pips / sl_pips, 2)
                    cand = TradeSignal(
                        action="SELL",
                        confidence=0.80,
                        suggested_entry_price=current_bid,
                        suggested_sl_price=sl_price,
                        suggested_tp_price=tp_price,
                        sl_distance_pips=sl_pips,
                        tp_distance_pips=tp_pips,
                        risk_reward_ratio=rr,
                        setup_name=f"Trend_{active_session}_EMA20_Reject_SELL",
                        rationale_ja=f"[{active_session}] M5下降トレンド推進中（EMA20 < EMA50）。EMA20 (${ema20:.2f}) への戻り目リジェクションを検知し順張り戻り売り。SL: {sl_pips}pips, RR 1:{rr}",
                        invalidation_level=sl_price,
                        entry_engine="SMC",
                    )
                    checked = self._apply_macro_overlay(cand, macro_state, current_ask, current_bid, pip_size)
                    if checked:
                        return checked

        # 条件不合致時
        nearest_h = min(valid_highs) if valid_highs else 0.0
        nearest_l = max(valid_lows) if valid_lows else 0.0
        m_src = macro_state.get("source", "NONE")
        m_bias = float(macro_state.get("macro_bias_score", 0.0))
        dxy_z = float(macro_state.get("dxy_z", 0.0))
        y_z = float(macro_state.get("yield_z", 0.0))
        return TradeSignal(
            action="NO_TRADE",
            confidence=0.0,
            suggested_entry_price=current_ask,
            suggested_sl_price=0.0,
            suggested_tp_price=0.0,
            sl_distance_pips=0.0,
            tp_distance_pips=0.0,
            risk_reward_ratio=0.0,
            setup_name=f"Scanning_{active_session}",
            rationale_ja=(
                f"[{active_session}] H1:{h1_trend}/M15:{m15_trend} | 先行指標({m_src}: bias={m_bias:+.2f}, DXY={dxy_z:+.2f}, Yield={y_z:+.2f}) | "
                f"型A急変・型B SMT・SMC流動性(${nearest_h:.2f}/${nearest_l:.2f})を並行監視中。"
            ),
            macro_source=m_src,
        )
