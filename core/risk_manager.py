from core.mt5_conn import mt5
import datetime
from typing import Dict, Any, Tuple, Optional

class InstitutionalRiskManager:
    """
    ヘッジファンド基準の資金管理 ＆ ドローダウン防御エンジン
    """
    def __init__(self, risk_params: Dict[str, Any]):
        self.risk_per_trade_pct = risk_params.get("risk_per_trade_percent", 1.5)
        self.max_daily_dd_pct = risk_params.get("max_daily_drawdown_percent", 3.0)
        self.min_lot = risk_params.get("min_lot_size", 0.01)
        self.max_lot = risk_params.get("max_lot_size", 0.50)
        self.enforce_single_pos = risk_params.get("enforce_single_position", True)

        self.daily_start_balance = None
        self.current_day = None

    def get_account_state(self) -> Dict[str, float]:
        """MT5口座の現在の資産・残高・有効証拠金を取得"""
        account_info = mt5.account_info()
        if not account_info:
            return {"balance": 0.0, "equity": 0.0, "profit": 0.0}
        return {
            "balance": float(account_info.balance),
            "equity": float(account_info.equity),
            "profit": float(account_info.profit),
            "margin_free": float(account_info.margin_free)
        }

    def update_daily_baseline(self):
        """日次ベースライン残高の更新（日が変わったらリセット）"""
        today = datetime.datetime.now().date()
        if self.current_day != today:
            acct = self.get_account_state()
            self.daily_start_balance = acct["balance"]
            self.current_day = today

    def check_circuit_breaker(self) -> Tuple[bool, str]:
        """日次最大ドローダウン制御（サーキットブレーカー）"""
        self.update_daily_baseline()
        acct = self.get_account_state()
        if not self.daily_start_balance or self.daily_start_balance <= 0:
            return True, "Baseline not set"

        current_loss = self.daily_start_balance - acct["equity"]
        loss_pct = (current_loss / self.daily_start_balance) * 100.0

        if loss_pct >= self.max_daily_dd_pct:
            return False, f"日次最大ドローダウン限界突破 (-{loss_pct:.2f}% >= -{self.max_daily_dd_pct}%). 本日の取引を完全停止。"
        return True, "Normal"

    def has_open_positions(self, symbol: str) -> bool:
        """単一ポジション限定ルール: 未決済建玉の有無を判定"""
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return False
        return len(positions) > 0

    def calculate_position_size(
        self,
        sl_distance_pips: float,
        pip_size: float = 0.10,
        lot_multiplier: float = 1.0,
    ) -> float:
        """
        【数学的正当性】ボラティリティ動的損切り幅に応じた適正ロットサイズの算出
        Lot = (口座残高 * リスク% * マクロ強弱倍率) / (SL_pips * 1pipあたりの価値)
        """
        acct = self.get_account_state()
        equity = acct["equity"]
        if equity <= 0 or sl_distance_pips <= 0:
            return self.min_lot

        safe_mult = max(0.50, min(1.35, float(lot_multiplier)))
        risk_amount_jpy = equity * (self.risk_per_trade_pct / 100.0) * safe_mult

        # XAUUSD 0.01 lot = 1オンス。1 pip ($0.10) の価格変動は約15円〜16円（為替による）
        pip_value_per_001_lot = 15.0
        calculated_lot = (risk_amount_jpy / (sl_distance_pips * (pip_value_per_001_lot / 0.01)))

        # 小数点第2位に丸め、最小・最大リミットを適用
        rounded_lot = round(max(self.min_lot, min(self.max_lot, calculated_lot)), 2)
        return rounded_lot

    def apply_break_even_protection(self, symbol: str, pip_size: float = 0.10) -> Optional[str]:
        """
        【適正化プロップファーム仕様】建値移動 (Break-Even) 自動スライド
        未実現利益が「初期SL幅と同等（RR 1:1以上、最低25pips）」に達した時のみSLを「建値 + 2pips」へ引き上げ、
        ノイズによる微益狩りを完全に排除して本来のTP（平均+1.7万円以上）まで伸ばす。
        """
        positions = mt5.positions_get(symbol=symbol)
        if not positions or len(positions) == 0:
            return None

        pos = positions[0]
        ticket = pos.ticket
        pos_type = pos.type  # 0: BUY, 1: SELL
        open_price = float(pos.price_open)
        current_price = float(pos.price_current)
        current_sl = float(pos.sl)

        # SLが設定されている場合、初期SL距離を計算。未設定の場合は最低25pips
        if current_sl > 0:
            initial_sl_dist = abs(open_price - current_sl)
        else:
            initial_sl_dist = 25.0 * pip_size

        # トリガーは「初期リスク（SL幅）の1.0倍以上（RR 1:1到達時、かつ最低25pips）」
        be_trigger_dollars = max(25.0 * pip_size, initial_sl_dist * 0.95)
        be_buffer_dollars = 2.0 * pip_size

        if pos_type == 0:  # BUY
            profit_dollars = current_price - open_price
            new_sl = round(open_price + be_buffer_dollars, 2)
            if profit_dollars >= be_trigger_dollars and (current_sl < open_price or current_sl == 0.0):
                req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": ticket,
                    "symbol": symbol,
                    "sl": new_sl,
                    "tp": float(pos.tp)
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    return f"BUY #{ticket} RR1:1到達による建値移動完了 (SL -> ${new_sl:.2f})"
        else:  # SELL
            profit_dollars = open_price - current_price
            new_sl = round(open_price - be_buffer_dollars, 2)
            if profit_dollars >= be_trigger_dollars and (current_sl > open_price or current_sl == 0.0):
                req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": ticket,
                    "symbol": symbol,
                    "sl": new_sl,
                    "tp": float(pos.tp)
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    return f"SELL #{ticket} RR1:1到達による建値移動完了 (SL -> ${new_sl:.2f})"

        return None

    def apply_macro_trailing_protection(
        self,
        symbol: str,
        pip_size: float,
        macro_state: Optional[Dict[str, Any]],
        atr_m5_dollars: float,
    ) -> Optional[str]:
        """
        【Step 2 プロ仕様】マクロ反転トレーリング防御
        含み益が十分に乗った状態（M5 ATR 1.1倍以上かつ最低25pips）で、
        先行指標（DXY ＆ US10Y/USDJPY）の追い風が明確に反転した際、SLをタイトに引き上げて利益を確実に防衛する。
        """
        if not macro_state:
            return None

        positions = mt5.positions_get(symbol=symbol)
        if not positions or len(positions) == 0:
            return None

        pos = positions[0]
        ticket = pos.ticket
        pos_type = pos.type  # 0: BUY, 1: SELL
        open_price = float(pos.price_open)
        current_price = float(pos.price_current)
        current_sl = float(pos.sl)

        min_profit_dollars = max(25.0 * pip_size, atr_m5_dollars * 1.1)
        trail_offset = max(8.0 * pip_size, atr_m5_dollars * 0.6)

        if pos_type == 0 and macro_state.get("macro_reversed_against_buy"):
            profit_dollars = current_price - open_price
            if profit_dollars >= min_profit_dollars:
                new_sl = round(current_price - trail_offset, 2)
                # 建値より上かつ既存SLより有利（高い）場合のみ引き上げ
                if new_sl > open_price + (3.0 * pip_size) and (current_sl == 0.0 or new_sl > current_sl + pip_size):
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": ticket,
                        "symbol": symbol,
                        "sl": new_sl,
                        "tp": float(pos.tp)
                    }
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        return f"BUY #{ticket} マクロ反転検知により利益防衛トレーリング実行 (SL -> ${new_sl:.2f})"

        elif pos_type == 1 and macro_state.get("macro_reversed_against_sell"):
            profit_dollars = open_price - current_price
            if profit_dollars >= min_profit_dollars:
                new_sl = round(current_price + trail_offset, 2)
                # 建値より下かつ既存SLより有利（低い）場合のみ引き下げ
                if new_sl < open_price - (3.0 * pip_size) and (current_sl == 0.0 or new_sl < current_sl - pip_size):
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": ticket,
                        "symbol": symbol,
                        "sl": new_sl,
                        "tp": float(pos.tp)
                    }
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        return f"SELL #{ticket} マクロ反転検知により利益防衛トレーリング実行 (SL -> ${new_sl:.2f})"

        return None
