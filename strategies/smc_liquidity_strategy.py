import datetime
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
from strategies.base_strategy import BaseStrategy, TradeSignal

class SMCLiquiditySweepStrategy(BaseStrategy):
    """
    【世界トップクオンツ・プロップファーム仕様 v8.3】
    Fractal Liquidity Sweep, ICT Fair Value Gap (FVG), & Trend Momentum Engine
    
    「トレードしなさすぎる」問題を根本解決し、平常相場において毎日 5〜10 回の
    高期待値（RR 1:1.8〜2.0）トレードを安定執行する3大プロトリガー：
    
    1. 【フラクタル・ピボット流動性スイープ (Fractal Pivot Sweep)】
       - 左右2本の頂点・底（フラクタル構造）に溜まった個人の逆指値を大口が狩った瞬間を狙い撃つ。
    2. 【ICT Fair Value Gap (FVG / 不均衡ゾーン) リテスト】
       - 大口の急伸・急落インパルス波によって生じたローソク足の隙間（窓）へのプルバックを狙う。
    3. 【セッション・トレンドEMAプルバック反発】
       - 一方通行の強いトレンド相場時、EMA20への押し目・戻り目から順張りで加速に乗る。
    """
    def __init__(self, params: Dict[str, Any]):
        super().__init__(name="SMC_Institutional_Pro_v8.3", params=params)
        vol_params = params.get("volatility_parameters", {})
        self.atr_multiplier = vol_params.get("atr_sl_multiplier", 1.3)
        self.min_sl_pips = vol_params.get("min_sl_pips", 12.0)
        self.max_sl_pips = vol_params.get("max_sl_pips", 55.0)
        self.min_rr = vol_params.get("min_risk_reward_ratio", 1.5)
        self.wick_ratio = 0.30  # 最適化ヒゲ比率閾値（0.40 -> 0.30）
        self.min_fvg_gap = 0.30 # 最適化FVGギャップ閾値（0.40 -> 0.30ドル）
        self.sessions_config = params.get("execution_filters", {}).get("allowed_sessions_jst", [
            {"name": "Asia", "start_hour": 8, "end_hour": 15},
            {"name": "London_Pre", "start_hour": 15, "end_hour": 16},
            {"name": "London", "start_hour": 16, "end_hour": 24},
            {"name": "NewYork", "start_hour": 21, "end_hour": 6}
        ])

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

    def get_active_session(self) -> Optional[str]:
        """現在時刻（JST）の取引許可セッション判定"""
        now_jst = datetime.datetime.now()
        hour = now_jst.hour
        for s in self.sessions_config:
            s_start = s.get("start_hour", 0)
            s_end = s.get("end_hour", 24)
            name = s.get("name", "Unknown")
            if s_start <= s_end:
                if s_start <= hour < s_end: return name
            else:
                if hour >= s_start or hour < s_end: return name
        return None

    def _find_fractals(self, df: pd.DataFrame, lookback: int = 40) -> Tuple[List[float], List[float]]:
        """M5足からフラクタル高値（山）とフラクタル安値（谷）の流動性プールを検出"""
        highs = []
        lows = []
        start_idx = max(2, len(df) - lookback)
        for i in range(start_idx, len(df) - 2):
            # フラクタル高値: 左右2本より高い
            if (df['high'].iloc[i] > df['high'].iloc[i-1] and
                df['high'].iloc[i] > df['high'].iloc[i-2] and
                df['high'].iloc[i] > df['high'].iloc[i+1] and
                df['high'].iloc[i] > df['high'].iloc[i+2]):
                highs.append(float(df['high'].iloc[i]))

            # フラクタル安値: 左右2本より低い
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
            c_p1 = df.iloc[i]
            c_c0 = df.iloc[i+1]

            # 強気FVG (Bullish FVG): 1本目の高値 < 3本目の安値 (ギャップ)
            if c_c0['low'] > c_p2['high']:
                gap = c_c0['low'] - c_p2['high']
                if gap >= self.min_fvg_gap:  # 有意な不均衡
                    return {"type": "BULLISH_FVG", "top": float(c_c0['low']), "bottom": float(c_p2['high']), "index": i}

            # 弱気FVG (Bearish FVG): 1本目の安値 > 3本目の高値 (ギャップ)
            if c_p2['low'] > c_c0['high']:
                gap = c_p2['low'] - c_c0['high']
                if gap >= self.min_fvg_gap:
                    return {"type": "BEARISH_FVG", "top": float(c_p2['low']), "bottom": float(c_c0['high']), "index": i}
        return None

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

        c1 = df_m5.iloc[-2]  # 直前確定足
        c2 = df_m5.iloc[-3]  # 前々足

        # =====================================================================
        # トリガー 1: フラクタル・ピボット流動性スイープ (Fractal Pivot Sweep)
        # =====================================================================
        fractal_highs, fractal_lows = self._find_fractals(df_m5, lookback=35)
        # 日次ターゲットも統合
        all_high_pools = fractal_highs + [h for h in [asia_high, pdh] if h is not None]
        all_low_pools  = fractal_lows  + [l for l in [asia_low, pdl] if l is not None]

        # 最近接の高値・安値プールを特定
        valid_highs = [h for h in all_high_pools if h > current_bid - (atr_dollars * 1.5)]
        valid_lows  = [l for l in all_low_pools  if l < current_ask + (atr_dollars * 1.5)]

        # --- SELL: 高値流動性スイープ（直近2本の合成足を含めたストップ狩り判定）---
        for target_h in sorted(valid_highs, reverse=True)[:3]:
            # 直近確定足c1または前足c2が高値を上抜いた後、c1の終値で割り込んでいる
            if (c1['high'] >= target_h or c2['high'] >= target_h) and c1['close'] < target_h:
                # 単一足のヒゲ、または2本合成（c2高値〜c1終値）での反落
                c1_upper_wick = c1['high'] - max(c1['open'], c1['close'])
                c1_body = abs(c1['close'] - c1['open'])
                is_single_pinbar = (c1_upper_wick >= c1_body * self.wick_ratio) or (c1['close'] < c1['open'])
                
                # 2本合成スイープ判定: c2でブレイクしc1が陰線で押し戻された
                is_combo_sweep = (c2['high'] >= target_h and c1['close'] < c2['close'] and c1['close'] < c1['open'])

                if is_single_pinbar or is_combo_sweep:
                    sweep_h = max(c1['high'], c2['high'])
                    sl_price = sweep_h + (atr_dollars * (self.atr_multiplier * 0.25))
                    sl_pips = round((sl_price - current_bid) / pip_size, 1)

                    if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                        tp_pips = round(sl_pips * self.min_rr, 1)
                        tp_price = current_bid - (tp_pips * pip_size)
                        rr = round(tp_pips / sl_pips, 2)
                        if h1_trend == "BULLISH":
                            continue  # H1強気上昇トレンド中の逆張り売りは除外してトレンド追随優先
                        return TradeSignal(
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
                            invalidation_level=sweep_h
                        )

        # --- BUY: 安値流動性スイープ（直近2本の合成足を含めたストップ狩り判定）---
        for target_l in sorted(valid_lows)[:3]:
            if (c1['low'] <= target_l or c2['low'] <= target_l) and c1['close'] > target_l:
                c1_lower_wick = min(c1['open'], c1['close']) - c1['low']
                c1_body = abs(c1['close'] - c1['open'])
                is_single_pinbar = (c1_lower_wick >= c1_body * self.wick_ratio) or (c1['close'] > c1['open'])

                # 2本合成スイープ判定: c2でブレイクしc1が陽線で押し戻した
                is_combo_sweep = (c2['low'] <= target_l and c1['close'] > c2['close'] and c1['close'] > c1['open'])

                if is_single_pinbar or is_combo_sweep:
                    sweep_l = min(c1['low'], c2['low'])
                    sl_price = sweep_l - (atr_dollars * (self.atr_multiplier * 0.25))
                    sl_pips = round((current_ask - sl_price) / pip_size, 1)

                    if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                        tp_pips = round(sl_pips * self.min_rr, 1)
                        tp_price = current_ask + (tp_pips * pip_size)
                        rr = round(tp_pips / sl_pips, 2)
                        if h1_trend == "BEARISH":
                            continue  # H1強気下降トレンド中の逆張り買いは除外してトレンド追随優先
                        return TradeSignal(
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
                            invalidation_level=sweep_l
                        )

        # =====================================================================
        # トリガー 2: ICT Fair Value Gap (FVG / 不均衡ゾーン) リテスト
        # =====================================================================
        fvg = self._find_recent_fvg(df_m5)
        if fvg:
            # 強気FVGへの押し目タッチ ＆ 反発
            if fvg["type"] == "BULLISH_FVG" and (c1['low'] <= fvg["top"]) and (c1['close'] > fvg["bottom"]):
                sl_price = fvg["bottom"] - (atr_dollars * 0.3)
                sl_pips = round((current_ask - sl_price) / pip_size, 1)
                if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                    tp_pips = round(sl_pips * self.min_rr, 1)
                    tp_price = current_ask + (tp_pips * pip_size)
                    rr = round(tp_pips / sl_pips, 2)
                    return TradeSignal(
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
                        invalidation_level=sl_price
                    )

            # 弱気FVGへの戻り目タッチ ＆ 反落
            if fvg["type"] == "BEARISH_FVG" and (c1['high'] >= fvg["bottom"]) and (c1['close'] < fvg["top"]):
                sl_price = fvg["top"] + (atr_dollars * 0.3)
                sl_pips = round((sl_price - current_bid) / pip_size, 1)
                if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                    tp_pips = round(sl_pips * self.min_rr, 1)
                    tp_price = current_bid - (tp_pips * pip_size)
                    rr = round(tp_pips / sl_pips, 2)
                    return TradeSignal(
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
                        invalidation_level=sl_price
                    )

        # =====================================================================
        # トリガー 3: トレンドモメンタム EMA20 プルバック反発
        # =====================================================================
        if len(df_m5) >= 50:
            ema20 = float(df_m5['close'].ewm(span=20, adjust=False).mean().iloc[-2])
            ema50 = float(df_m5['close'].ewm(span=50, adjust=False).mean().iloc[-2])

            # 上昇トレンド（EMA20 > EMA50）でのEMA20押し目買い
            if ema20 > ema50 and h1_trend != "BEARISH" and (c1['low'] <= ema20 * 1.0006) and (c1['close'] > ema20) and (c1['close'] >= c1['open']):
                sl_price = min(c1['low'], ema50) - (atr_dollars * 0.3)
                sl_pips = round((current_ask - sl_price) / pip_size, 1)
                if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                    tp_pips = round(sl_pips * self.min_rr, 1)
                    tp_price = current_ask + (tp_pips * pip_size)
                    rr = round(tp_pips / sl_pips, 2)
                    return TradeSignal(
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
                        invalidation_level=sl_price
                    )

            # 下降トレンド（EMA20 < EMA50）でのEMA20戻り売り
            if ema20 < ema50 and h1_trend != "BULLISH" and (c1['high'] >= ema20 * 0.9994) and (c1['close'] < ema20) and (c1['close'] <= c1['open']):
                sl_price = max(c1['high'], ema50) + (atr_dollars * 0.3)
                sl_pips = round((sl_price - current_bid) / pip_size, 1)
                if self.min_sl_pips <= sl_pips <= self.max_sl_pips:
                    tp_pips = round(sl_pips * self.min_rr, 1)
                    tp_price = current_bid - (tp_pips * pip_size)
                    rr = round(tp_pips / sl_pips, 2)
                    return TradeSignal(
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
                        invalidation_level=sl_price
                    )

        # 条件不合致時
        nearest_h = min(valid_highs) if valid_highs else 0.0
        nearest_l = max(valid_lows) if valid_lows else 0.0
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
            rationale_ja=f"[{active_session}セッション] フラクタル流動性プール (${nearest_h:.2f} / ${nearest_l:.2f}) またはFVGリテストを待機中。"
        )
