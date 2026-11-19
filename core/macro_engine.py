import math
import time
from typing import Any, Dict, Optional, Set, Tuple

import numpy as np
import pandas as pd

from core.mt5_conn import mt5
from core.webhook_server import MacroWebhookStore


class DualMacroEngine:
    """
    【デュアル・ハイブリッド先行指標エンジン v9.0】
    主系: TradingView Premium Webhook (DXY + US10Y + US02Y + XAUUSD 1分足)
    副系: Exness MT5 M1直結パイプライン (DXY + USDJPY[金利プロキシ] + USOIL + USTEC + XAUUSD)

    機能:
    1. 自動フェイルオーバー: TV無受信時は設定変更ゼロでMT5 M1生データへ自動切替。
    2. 型A (コンフルエンス・マクロモメンタム): DXY単独ノイズを排除し、2市場同時一致＋初動往復ビンタ回避＋追随確認＋飛び乗り防止でFVG不要のトレンド初動エントリーを生成。
    3. 型B (SMTダイバージェンス): DXYとXAUUSDの高安値ズレから大口の吸収を検知し、FVG不要の高勝率押し目/戻りエントリーを生成。
    4. 地政学リスクオフ判定: USOIL↑ ＆ USTEC↓ ＆ USDJPY↓ の同時発生のみゴールド買いブースト（インフレ型原油高のワナを排除）。
    5. マクロバイアス＆反転検知: 既存SMCのソフトガード・ロット強弱（0.75x〜1.25x）および利益確定トレーリングを提供。
    """

    def __init__(self, webhook_store: Optional[MacroWebhookStore], config: Dict[str, Any]):
        self.webhook_store = webhook_store
        self.config = config or {}
        self._selected_symbols: Set[str] = set()
        # MT5側の極端ショック初検知時刻（初動の往復ビンタをやり過ごすクールダウン管理）
        self._mt5_shock_first_seen: Dict[str, float] = {}

    def update_config(self, config: Dict[str, Any]) -> None:
        if config:
            self.config = config

    def _ensure_symbol(self, symbol: str) -> bool:
        if symbol in self._selected_symbols:
            return True
        try:
            if mt5.symbol_select(symbol, True):
                self._selected_symbols.add(symbol)
                return True
        except Exception:
            pass
        return False

    def _get_m1_df(self, symbol: str, count: int = 120) -> Optional[pd.DataFrame]:
        if not self._ensure_symbol(symbol):
            return None
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, count)
            if rates is None or len(rates) < 40:
                return None
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            return df
        except Exception:
            return None

    def _calc_asset_metrics(self, df_m1: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """1分足から3分・5分モメンタムZスコアおよびM5 EMA20相当（M1 EMA100）位置を算出"""
        default = {
            "available": False,
            "z": 0.0,
            "z3": 0.0,
            "z5": 0.0,
            "above_m5_ema20": False,
            "below_m5_ema20": False,
            "close": 0.0,
        }
        if df_m1 is None or len(df_m1) < 40:
            return default

        closes = df_m1["close"].astype(float)
        ret_1m = closes.pct_change().dropna()
        if len(ret_1m) < 25:
            return default

        # 直近34本の確定M1足リターン標準偏差（極小フロア付きでゼロ除算防止）
        vol_slice = ret_1m.iloc[-35:-1] if len(ret_1m) >= 35 else ret_1m.iloc[:-1]
        sigma_1m = float(vol_slice.std())
        if not np.isfinite(sigma_1m) or sigma_1m < 1e-5:
            sigma_1m = 1e-5

        c_now = float(closes.iloc[-1])
        c_3m = float(closes.iloc[-4])
        c_5m = float(closes.iloc[-6])

        r3 = (c_now - c_3m) / c_3m if c_3m != 0 else 0.0
        r5 = (c_now - c_5m) / c_5m if c_5m != 0 else 0.0

        z3 = r3 / (sigma_1m * math.sqrt(3.0))
        z5 = r5 / (sigma_1m * math.sqrt(5.0))

        # 3分・5分が同方向なら強い方を採用、逆方向（往復ヒゲ）なら平均化してノイズ減衰
        if (z3 >= 0 and z5 >= 0) or (z3 <= 0 and z5 <= 0):
            z = z3 if abs(z3) >= abs(z5) else z5
        else:
            z = 0.5 * (z3 + z5)

        z = max(-6.0, min(6.0, float(z)))

        # M5 EMA20 ≒ M1 EMA100（データ本数に応じて調整）
        ema_span = min(100, max(30, len(closes) - 5))
        ema_m5_20 = float(closes.ewm(span=ema_span, adjust=False).mean().iloc[-1])

        return {
            "available": True,
            "z": round(z, 3),
            "z3": round(float(z3), 3),
            "z5": round(float(z5), 3),
            "above_m5_ema20": c_now > ema_m5_20,
            "below_m5_ema20": c_now < ema_m5_20,
            "close": c_now,
        }

    def _detect_mt5_smt(
        self,
        df_dxy: Optional[pd.DataFrame],
        df_xau: Optional[pd.DataFrame],
        atr_m5_dollars: float,
        lookback: int = 35,
    ) -> Tuple[Optional[str], Optional[float], str]:
        """
        型B: DXY と XAUUSD のM1同期データから SMTダイバージェンス（機関投資家の吸収）を検知
        """
        if df_dxy is None or df_xau is None or len(df_dxy) < lookback + 2 or len(df_xau) < lookback + 2:
            return None, None, ""

        # 未確定の現在足(iloc[-1])を除き、確定M1足をタイムスタンプで厳密同期
        dxy_closed = df_dxy.iloc[:-1][["time", "open", "high", "low", "close"]].rename(
            columns={"open": "d_o", "high": "d_h", "low": "d_l", "close": "d_c"}
        )
        xau_closed = df_xau.iloc[:-1][["time", "open", "high", "low", "close"]].rename(
            columns={"open": "x_o", "high": "x_h", "low": "x_l", "close": "x_c"}
        )
        merged = pd.merge(dxy_closed, xau_closed, on="time", how="inner")
        if len(merged) < lookback:
            return None, None, ""

        window = merged.iloc[-lookback:]
        ref = window.iloc[:-8]   # 9〜35分前の基準スイング
        rec = window.iloc[-8:]   # 直近8分間の流動性スイープ帯
        c1 = rec.iloc[-1]        # 最新確定M1足

        dxy_ref_high = float(ref["d_h"].max())
        dxy_ref_low = float(ref["d_l"].min())
        xau_ref_high = float(ref["x_h"].max())
        xau_ref_low = float(ref["x_l"].min())

        dxy_rec_high = float(rec["d_h"].max())
        dxy_rec_low = float(rec["d_l"].min())
        xau_rec_high = float(rec["x_h"].max())
        xau_rec_low = float(rec["x_l"].min())

        xau_ema9 = float(df_xau["close"].astype(float).ewm(span=9, adjust=False).mean().iloc[-1])
        xau_now = float(df_xau["close"].iloc[-1])

        min_div_dollars = max(0.25, atr_m5_dollars * 0.12)
        dxy_rec_range = max(1e-5, dxy_rec_high - dxy_rec_low)

        # --- Bullish SMT (BUY): DXYは高値更新したのに、XAUUSDは安値を割らない（大口の買い吸収） ---
        if dxy_rec_high > dxy_ref_high and xau_rec_low > (xau_ref_low + min_div_dollars):
            dxy_rejecting = (float(c1["d_c"]) < float(c1["d_o"])) or (
                (dxy_rec_high - float(c1["d_c"])) >= dxy_rec_range * 0.30
            )
            xau_turning_up = (float(c1["x_c"]) > float(c1["x_o"])) and (xau_now >= xau_ema9 * 0.9998)
            if dxy_rejecting and xau_turning_up:
                detail = (
                    f"DXY高値更新({dxy_ref_high:.3f}->{dxy_rec_high:.3f})に対し"
                    f"XAUUSD安値切り上げ(${xau_ref_low:.2f}->${xau_rec_low:.2f})＋DXY失速"
                )
                return "BUY", xau_rec_low, detail

        # --- Bearish SMT (SELL): DXYは安値更新したのに、XAUUSDは高値更新できない（大口の売り吸収） ---
        if dxy_rec_low < dxy_ref_low and xau_rec_high < (xau_ref_high - min_div_dollars):
            dxy_bouncing = (float(c1["d_c"]) > float(c1["d_o"])) or (
                (float(c1["d_c"]) - dxy_rec_low) >= dxy_rec_range * 0.30
            )
            xau_turning_down = (float(c1["x_c"]) < float(c1["x_o"])) and (xau_now <= xau_ema9 * 1.0002)
            if dxy_bouncing and xau_turning_down:
                detail = (
                    f"DXY安値更新({dxy_ref_low:.3f}->{dxy_rec_low:.3f})に対し"
                    f"XAUUSD高値切り下げ(${xau_ref_high:.2f}->${xau_rec_high:.2f})＋DXY反発"
                )
                return "SELL", xau_rec_high, detail

        return None, None, ""

    def evaluate_macro_state(
        self,
        df_xau_m1: Optional[pd.DataFrame],
        atr_m5_dollars: float,
    ) -> Dict[str, Any]:
        """
        TradingView主系 ＆ MT5 M1副系のハイブリッド統合評価を実行し、
        戦略エンジン・リスク管理エンジンへ渡すリアルタイム・マクロ状態を返す。
        """
        now_ts = time.time()
        cfg = self.config
        syms = cfg.get("mt5_symbols", {})
        sym_dxy = syms.get("dxy", "DXY")
        sym_jpy = syms.get("yield_proxy", "USDJPY")
        sym_oil = syms.get("oil", "USOIL")
        sym_eq = syms.get("equity", "USTEC")

        tv_sig_ttl = float(cfg.get("tv_signal_ttl_seconds", 300))
        tv_hb_ttl = float(cfg.get("tv_heartbeat_ttl_seconds", 900))
        z_thresh = float(cfg.get("momentum_z_threshold", 1.5))
        cooldown_min = float(cfg.get("momentum_cooldown_min_sec", 45))
        cooldown_max = float(cfg.get("momentum_cooldown_max_sec", 240))
        max_chase_mult = float(cfg.get("max_chase_atr_mult", 1.5))
        smt_lookback = int(cfg.get("smt_lookback_m1", 35))

        # 1. MT5 M1 データを常時取得（副系バックアップ＋追随確認＋飛び乗り防止＋地政学判定）
        df_dxy = self._get_m1_df(sym_dxy, count=120)
        df_jpy = self._get_m1_df(sym_jpy, count=120)
        df_oil = self._get_m1_df(sym_oil, count=60)
        df_eq = self._get_m1_df(sym_eq, count=60)

        m_dxy = self._calc_asset_metrics(df_dxy)
        m_jpy = self._calc_asset_metrics(df_jpy)
        m_oil = self._calc_asset_metrics(df_oil)
        m_eq = self._calc_asset_metrics(df_eq)

        # 2. XAUUSD M1 追随度・飛び乗り防止（Max Chase Guard）算出
        xau_confirm_buy = False
        xau_confirm_sell = False
        chase_blocked_buy = False
        chase_blocked_sell = False
        xau_rec_low_8m = None
        xau_rec_high_8m = None

        if df_xau_m1 is not None and len(df_xau_m1) >= 15:
            x_closes = df_xau_m1["close"].astype(float)
            x_ema9 = float(x_closes.ewm(span=9, adjust=False).mean().iloc[-1])
            x_now = float(x_closes.iloc[-1])
            x_3m_ago = float(x_closes.iloc[-4])
            x_move_3m = x_now - x_3m_ago
            c1 = df_xau_m1.iloc[-2]

            recent_high_5m = float(df_xau_m1["high"].iloc[-6:-1].max())
            recent_low_5m = float(df_xau_m1["low"].iloc[-6:-1].min())
            xau_rec_low_8m = float(df_xau_m1["low"].iloc[-9:-1].min())
            xau_rec_high_8m = float(df_xau_m1["high"].iloc[-9:-1].max())

            # 飛び乗り防止: 直近3分で既に M5 ATR × 1.5 以上飛んでいれば成行追いかけを禁止
            chase_limit = max(1.5, atr_m5_dollars * max_chase_mult)
            chase_blocked_buy = x_move_3m > chase_limit
            chase_blocked_sell = x_move_3m < -chase_limit

            # ゴールド自身が吸収されず同方向へ追随している確認（FVG不要）
            xau_confirm_buy = (
                (x_now >= x_ema9 * 0.9998)
                and (float(c1["close"]) >= float(c1["open"]) or x_now >= recent_high_5m * 0.9999)
                and (x_move_3m > -atr_m5_dollars * 0.25)
            )
            xau_confirm_sell = (
                (x_now <= x_ema9 * 1.0002)
                and (float(c1["close"]) <= float(c1["open"]) or x_now <= recent_low_5m * 1.0001)
                and (x_move_3m < atr_m5_dollars * 0.25)
            )

        # 3. 地政学リスクオフ判定（USOIL↑ かつ USTEC↓ かつ USDJPY↓ のみ有効、インフレ型原油高を排除）
        is_geopolitical_risk_off = (
            m_oil["available"]
            and m_eq["available"]
            and m_jpy["available"]
            and (m_oil["z"] >= 1.2)
            and (m_eq["z"] <= -0.8)
            and (m_jpy["z"] <= -0.8)
        )

        # 4. TradingView Webhook スナップショット参照（主系チェック）
        tv_snap = self.webhook_store.get_snapshot() if self.webhook_store else {}
        tv_hb = tv_snap.get("heartbeat")
        tv_hb_active = bool(
            isinstance(tv_hb, dict)
            and (now_ts - float(tv_hb.get("received_at", 0.0))) <= tv_hb_ttl
        )

        # 5. マクロバイアススコア統合（週末自動検証で最適化されたDXY/金利ウェイトを動的適用）
        w_dxy = float(cfg.get("dxy_weight", 0.45 if tv_hb_active else 0.50))
        w_yield = float(cfg.get("yield_weight", 1.0 - w_dxy))
        if tv_hb_active:
            active_source = "TV_WEBHOOK"
            dxy_z = float(tv_hb.get("dxy_z", 0.0))
            yield_z = float(tv_hb.get("us10y_z", 0.0))
            raw_bias = float(tv_hb.get("bias_score", 0.0))
            if raw_bias == 0.0 and (dxy_z != 0.0 or yield_z != 0.0):
                raw_bias = math.tanh((-w_dxy * dxy_z - w_yield * yield_z) / 2.0)
            if is_geopolitical_risk_off:
                raw_bias = min(1.0, raw_bias + 0.30)
            macro_bias_score = round(max(-1.0, min(1.0, raw_bias)), 3)
            macro_rev_against_buy = (
                bool(tv_hb.get("dxy_above_m5_ema20"))
                and bool(tv_hb.get("us10y_above_m5_ema20"))
                and macro_bias_score <= -0.45
            )
            macro_rev_against_sell = (
                (not bool(tv_hb.get("dxy_above_m5_ema20")))
                and (not bool(tv_hb.get("us10y_above_m5_ema20")))
                and macro_bias_score >= 0.45
            )
        else:
            active_source = "MT5_M1" if (m_dxy["available"] and m_jpy["available"]) else "NONE"
            dxy_z = m_dxy["z"]
            yield_z = m_jpy["z"]  # USDJPYを米金利プロキシとして利用
            geo_boost = 0.35 if is_geopolitical_risk_off else 0.0
            raw_score = math.tanh((-w_dxy * dxy_z - w_yield * yield_z) / 2.0) + geo_boost
            macro_bias_score = round(max(-1.0, min(1.0, raw_score)), 3)
            macro_rev_against_buy = (
                m_dxy["above_m5_ema20"]
                and m_jpy["above_m5_ema20"]
                and macro_bias_score <= -0.45
            )
            macro_rev_against_sell = (
                m_dxy["below_m5_ema20"]
                and m_jpy["below_m5_ema20"]
                and macro_bias_score >= 0.45
            )

        # 6. 型A: コンフルエンス・マクロモメンタム評価（TV優先 → 無ければMT5 M1自動評価）
        momentum_signal: Optional[str] = None
        momentum_source = "NONE"
        momentum_detail = ""
        momentum_waiting_cooldown = False

        tv_mom = tv_snap.get("momentum")
        tv_mom_valid = (
            isinstance(tv_mom, dict)
            and (not bool(tv_mom.get("consumed", False)))
            and (now_ts - float(tv_mom.get("received_at", 0.0))) <= tv_sig_ttl
            and tv_mom.get("direction") in ("BUY", "SELL")
        )

        if tv_mom_valid:
            t_dir = tv_mom["direction"]
            t_dxy_z = float(tv_mom.get("dxy_z", 0.0))
            t_y_z = float(tv_mom.get("us10y_z", 0.0))
            first_seen = float(tv_mom.get("first_seen_at", tv_mom.get("received_at", now_ts)))
            elapsed = now_ts - first_seen
            is_extreme_spike = max(abs(t_dxy_z), abs(t_y_z)) >= 2.4

            if is_extreme_spike and elapsed < cooldown_min:
                momentum_waiting_cooldown = True
            elif elapsed <= cooldown_max:
                if t_dir == "BUY" and xau_confirm_buy and not chase_blocked_buy:
                    momentum_signal = "BUY"
                    momentum_source = "TV_WEBHOOK"
                    momentum_detail = (
                        f"TV主系コンフルエンス急変 (DXY Z={t_dxy_z:+.2f}, US10Y Z={t_y_z:+.2f}) ＋ ゴールド追随確認"
                    )
                elif t_dir == "SELL" and xau_confirm_sell and not chase_blocked_sell:
                    momentum_signal = "SELL"
                    momentum_source = "TV_WEBHOOK"
                    momentum_detail = (
                        f"TV主系コンフルエンス急変 (DXY Z={t_dxy_z:+.2f}, US10Y Z={t_y_z:+.2f}) ＋ ゴールド追随確認"
                    )
        elif m_dxy["available"] and m_jpy["available"]:
            # MT5 M1バックアップによる DXY + USDJPY（米金利プロキシ）同時一致モメンタム判定
            ad, aj = abs(m_dxy["z"]), abs(m_jpy["z"])
            avg_z = 0.5 * (ad + aj)
            min_z = min(ad, aj)
            max_z = max(ad, aj)

            same_bear_usd = (m_dxy["z"] < 0 and m_jpy["z"] < 0)
            same_bull_usd = (m_dxy["z"] > 0 and m_jpy["z"] > 0)
            consensus_met = (
                (ad >= z_thresh and aj >= z_thresh * 0.72)
                or (aj >= z_thresh and ad >= z_thresh * 0.72)
                or (avg_z >= z_thresh and min_z >= z_thresh * 0.60)
            )

            cand_dir = None
            if same_bear_usd and consensus_met:
                cand_dir = "BUY"
            elif same_bull_usd and consensus_met:
                cand_dir = "SELL"

            if cand_dir:
                prev_seen = self._mt5_shock_first_seen.get(cand_dir)
                if prev_seen is None or (now_ts - prev_seen) > cooldown_max:
                    self._mt5_shock_first_seen[cand_dir] = now_ts
                    prev_seen = now_ts

                elapsed = now_ts - prev_seen
                is_extreme_spike = max_z >= 2.4

                # 極端ショック時は45秒の往復ビンタ収束を待機。通常ブレイクアウトは即追随確認へ
                if is_extreme_spike and elapsed < cooldown_min:
                    momentum_waiting_cooldown = True
                elif elapsed <= cooldown_max:
                    if cand_dir == "BUY" and xau_confirm_buy and not chase_blocked_buy:
                        momentum_signal = "BUY"
                        momentum_source = "MT5_M1"
                        geo_tag = " [地政学リスクオフ補強]" if is_geopolitical_risk_off else ""
                        momentum_detail = (
                            f"MT5 M1 2市場同時一致 (DXY Z={m_dxy['z']:+.2f}, USDJPY Z={m_jpy['z']:+.2f}){geo_tag} ＋ XAUUSD追随確認"
                        )
                    elif cand_dir == "SELL" and xau_confirm_sell and not chase_blocked_sell:
                        momentum_signal = "SELL"
                        momentum_source = "MT5_M1"
                        momentum_detail = (
                            f"MT5 M1 2市場同時一致 (DXY Z={m_dxy['z']:+.2f}, USDJPY Z={m_jpy['z']:+.2f}) ＋ XAUUSD追随確認"
                        )
            else:
                # 勢いが消失して一定時間経過したらショック追跡をリセット
                for d_key in list(self._mt5_shock_first_seen.keys()):
                    if (now_ts - self._mt5_shock_first_seen[d_key]) > cooldown_max:
                        del self._mt5_shock_first_seen[d_key]

        # 7. 型B: SMTダイバージェンス評価（TV優先 → 無ければMT5 M1同期データから自動検知）
        smt_signal: Optional[str] = None
        smt_source = "NONE"
        smt_swing_level: Optional[float] = None
        smt_detail = ""

        tv_smt = tv_snap.get("smt")
        tv_smt_valid = (
            isinstance(tv_smt, dict)
            and (not bool(tv_smt.get("consumed", False)))
            and (now_ts - float(tv_smt.get("received_at", 0.0))) <= tv_sig_ttl
            and tv_smt.get("direction") in ("BUY", "SELL")
        )

        if tv_smt_valid:
            s_dir = tv_smt["direction"]
            if s_dir == "BUY" and xau_confirm_buy:
                smt_signal = "BUY"
                smt_source = "TV_WEBHOOK"
                smt_swing_level = xau_rec_low_8m
                smt_detail = tv_smt.get("detail") or "TradingView検知 Bullish SMT (DXY高値更新×XAUUSD安値維持)"
            elif s_dir == "SELL" and xau_confirm_sell:
                smt_signal = "SELL"
                smt_source = "TV_WEBHOOK"
                smt_swing_level = xau_rec_high_8m
                smt_detail = tv_smt.get("detail") or "TradingView検知 Bearish SMT (DXY安値更新×XAUUSD高値切下)"
        else:
            mt5_smt_dir, mt5_smt_lvl, mt5_smt_desc = self._detect_mt5_smt(
                df_dxy=df_dxy,
                df_xau=df_xau_m1,
                atr_m5_dollars=atr_m5_dollars,
                lookback=smt_lookback,
            )
            if mt5_smt_dir:
                smt_signal = mt5_smt_dir
                smt_source = "MT5_M1"
                smt_swing_level = mt5_smt_lvl
                smt_detail = mt5_smt_desc

        return {
            "source": active_source,
            "tv_heartbeat_active": tv_hb_active,
            "dxy_z": round(dxy_z, 3),
            "yield_z": round(yield_z, 3),
            "oil_z": m_oil["z"],
            "equity_z": m_eq["z"],
            "is_geopolitical_risk_off": is_geopolitical_risk_off,
            "macro_bias_score": macro_bias_score,
            "macro_reversed_against_buy": macro_rev_against_buy,
            "macro_reversed_against_sell": macro_rev_against_sell,
            "momentum_signal": momentum_signal,
            "momentum_source": momentum_source,
            "momentum_detail": momentum_detail,
            "momentum_waiting_cooldown": momentum_waiting_cooldown,
            "chase_blocked_buy": chase_blocked_buy,
            "chase_blocked_sell": chase_blocked_sell,
            "smt_signal": smt_signal,
            "smt_source": smt_source,
            "smt_swing_level": smt_swing_level,
            "smt_detail": smt_detail,
        }
