from core.mt5_conn import mt5
import pandas as pd
import numpy as np
import datetime
from typing import Dict, Any, Optional

class MarketDataEngine:
    """
    MT5からの正確なマルチタイムフレームデータ取得（M1/M5/M15/H1/D1）
    および数理特徴量（ATR, 流動性プール高安, MTFトレンド）算出エンジン
    """
    def __init__(self, symbol: str = "XAUUSD"):
        self.symbol = symbol

    def get_rates_df(self, timeframe: int, count: int = 100) -> Optional[pd.DataFrame]:
        """指定時間足のOHLCVを取得してDataFrame化"""
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Average True Range (ATR) を算出（ドル建て）"""
        if df is None or len(df) < period + 1:
            return 2.0  # フォールバック値（$2.0 = 20pips）
        high = df['high']
        low = df['low']
        close_prev = df['close'].shift(1)
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr_series = tr.rolling(window=period).mean()
        return float(atr_series.iloc[-1])

    def _detect_ema_trend(self, df: Optional[pd.DataFrame]) -> tuple[str, float, float]:
        """EMA20/EMA50の並びと傾きからトレンド方向（BULLISH / BEARISH / NEUTRAL）を判定"""
        if df is None or len(df) < 50:
            return "NEUTRAL", 0.0, 0.0
        s_ema20 = df['close'].ewm(span=20, adjust=False).mean()
        s_ema50 = df['close'].ewm(span=50, adjust=False).mean()
        ema20 = float(s_ema20.iloc[-2])
        ema50 = float(s_ema50.iloc[-2])
        prev_ema20 = float(s_ema20.iloc[-3])

        if ema20 > ema50 and ema20 >= prev_ema20:
            return "BULLISH", ema20, ema50
        elif ema20 < ema50 and ema20 <= prev_ema20:
            return "BEARISH", ema20, ema50
        return "NEUTRAL", ema20, ema50

    def get_market_state(self, atr_period: int = 14) -> Optional[Dict[str, Any]]:
        """
        現在のマーケット状態（価格、スプレッド、ATR、セッション高安、流動性ライン、M1〜H1データ）を一括算出
        """
        symbol_info = mt5.symbol_info(self.symbol)
        tick = mt5.symbol_info_tick(self.symbol)
        if not symbol_info or not tick:
            return None

        # ゴールドのpipサイズ計算（XAUUSDは $0.10 = 1 pip）
        pip_size = 0.10 if ("XAU" in self.symbol.upper() or "GOLD" in self.symbol.upper()) else (symbol_info.point * 10)
        spread_pips = round((tick.ask - tick.bid) / pip_size, 1)

        # M1足（先行指標同期・SMT・飛び乗り防止用）、M5足、M15足、H1足、D1足の取得
        df_m1 = self.get_rates_df(mt5.TIMEFRAME_M1, count=120)
        df_m5 = self.get_rates_df(mt5.TIMEFRAME_M5, count=120)
        df_m15 = self.get_rates_df(mt5.TIMEFRAME_M15, count=100)
        df_h1 = self.get_rates_df(mt5.TIMEFRAME_H1, count=100)
        df_d1 = self.get_rates_df(mt5.TIMEFRAME_D1, count=10)

        atr_m5 = self.calculate_atr(df_m5, period=atr_period) if df_m5 is not None else 1.2
        atr_m15 = self.calculate_atr(df_m15, period=atr_period) if df_m15 is not None else 2.0
        atr_h1 = self.calculate_atr(df_h1, period=atr_period) if df_h1 is not None else 5.0

        # アジアセッション（JST 09:00〜15:00 / UTC 00:00〜06:00）の高値・安値を算出
        asia_high = None
        asia_low = None
        if df_m15 is not None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            today_utc_date = now_utc.date()
            asia_candles = df_m15[
                (df_m15['time'].dt.date == today_utc_date) &
                (df_m15['time'].dt.hour >= 0) &
                (df_m15['time'].dt.hour < 6)
            ]
            if len(asia_candles) > 0:
                asia_high = float(asia_candles['high'].max())
                asia_low = float(asia_candles['low'].min())

        # H1 ＆ M15 マルチタイムフレーム（MTF）トレンド判定
        h1_trend, h1_ema20, h1_ema50 = self._detect_ema_trend(df_h1)
        m15_trend, m15_ema20, m15_ema50 = self._detect_ema_trend(df_m15)

        # 前日高値・前日安値（PDH / PDL）
        pdh = float(df_d1['high'].iloc[-2]) if df_d1 is not None and len(df_d1) >= 2 else None
        pdl = float(df_d1['low'].iloc[-2]) if df_d1 is not None and len(df_d1) >= 2 else None

        return {
            "symbol": self.symbol,
            "current_ask": float(tick.ask),
            "current_bid": float(tick.bid),
            "spread_pips": spread_pips,
            "pip_size": pip_size,
            "digits": symbol_info.digits,
            "atr_m5_pips": round(atr_m5 / pip_size, 1),
            "atr_m15_pips": round(atr_m15 / pip_size, 1),
            "atr_h1_pips": round(atr_h1 / pip_size, 1),
            "atr_m5_dollars": atr_m5,
            "atr_m15_dollars": atr_m15,
            "asia_high": asia_high,
            "asia_low": asia_low,
            "h1_trend": h1_trend,
            "h1_ema20": h1_ema20,
            "h1_ema50": h1_ema50,
            "m15_trend": m15_trend,
            "m15_ema20": m15_ema20,
            "m15_ema50": m15_ema50,
            "pdh": pdh,
            "pdl": pdl,
            "df_m1": df_m1,
            "df_m5": df_m5,
            "df_m15": df_m15,
            "df_h1": df_h1
        }
