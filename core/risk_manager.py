from core.mt5_conn import mt5
import datetime
from typing import Dict, Any, Tuple, Optional, Set, List

class InstitutionalRiskManager:
    """
    ヘッジファンド基準の資金管理 ＆ ドローダウン防御エンジン v9.1
    - 3系統ロジック別1ポジション（全体で最大3ポジション）の順張りピラミッディング対応
    - 両建て（逆方向ポジション）および同一ロジック重複（ナンピン）の厳格ブロック
    - 既存ポジションの建値移動（フリーロール）判定による追加ロットの同時リスク自動調整
    - 全保有ポジション個別の建値自動移動（Break-Even）＆ マクロ反転トレーリング
    """
    def __init__(self, risk_params: Dict[str, Any]):
        self.risk_per_trade_pct = risk_params.get("risk_per_trade_percent", 1.5)
        self.max_daily_dd_pct = risk_params.get("max_daily_drawdown_percent", 3.0)
        self.min_lot = risk_params.get("min_lot_size", 0.01)
        self.max_lot = risk_params.get("max_lot_size", 0.50)
        self.max_positions = int(risk_params.get("max_concurrent_positions", 3))
        self.enforce_single_pos = risk_params.get("enforce_single_position", False)

        self.daily_start_balance = None
        self.current_day = None
        # ticket(str) -> entry_engine(str) のオンメモリ補助マップ
        self.ticket_engine_map: Dict[str, str] = {}

    def register_position_engine(self, order_id: Any, entry_engine: str):
        if order_id:
            self.ticket_engine_map[str(order_id)] = str(entry_engine)

    def _infer_position_engine(self, pos: Any) -> str:
        ticket_str = str(getattr(pos, "ticket", ""))
        if ticket_str in self.ticket_engine_map:
            return self.ticket_engine_map[ticket_str]
        comment = str(getattr(pos, "comment", "") or "").upper()
        if "MACRO_MOMENTUM" in comment:
            return "MACRO_MOMENTUM"
        if "SMT_DIVERGENCE" in comment or "SMT" in comment:
            return "SMT_DIVERGENCE"
        return "SMC"

    def get_open_engines(self, symbol: str) -> Set[str]:
        """現在保有中のポジションが属するエンジン一覧を返す"""
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return set()
        return {self._infer_position_engine(p) for p in positions}

    def check_can_open_position(
        self,
        symbol: str,
        action: str,
        entry_engine: str,
    ) -> Tuple[bool, str, float]:
        """
        3系統ロジック別1ポジション（最大3ポジション）の発注可否 ＆ ピラミッディング倍率を判定
        Returns: (allowed: bool, reason: str, pyramid_lot_scale: float)
        """
        positions = mt5.positions_get(symbol=symbol)
        if not positions or len(positions) == 0:
            return True, "新規1ポジション目許可", 1.0

        if len(positions) >= self.max_positions:
            return False, f"最大同時保有数 ({len(positions)}/{self.max_positions}ポジ) に到達済みのため見送り", 0.0

        unprotected_count = 0
        for pos in positions:
            pos_dir = "BUY" if pos.type == 0 else "SELL"
            pos_eng = self._infer_position_engine(pos)
            open_px = float(pos.price_open)
            cur_sl = float(pos.sl)

            # 1. 逆方向（両建て）の禁止
            if pos_dir != action:
                return False, f"逆方向ポジション ({pos_dir} #{pos.ticket} [{pos_eng}]) 保有中のため両建てブロック", 0.0

            # 2. 同一ロジックの重複（ナンピン）禁止
            if pos_eng == entry_engine:
                return False, f"同一ロジック ({entry_engine} #{pos.ticket}) で既に保有中のため重複ブロック", 0.0

            # 3. 建値移動（Break-Even）完了済みか判定
            is_protected = (
                (pos.type == 0 and cur_sl >= open_px)
                or (pos.type == 1 and cur_sl > 0.0 and cur_sl <= open_px)
            )
            if not is_protected:
                unprotected_count += 1

        # 既存ポジションがすべて建値移動済み（リスクゼロのフリーロール状態）なら1.0倍、未保護があれば0.80倍に調整
        pyramid_scale = 1.0 if unprotected_count == 0 else 0.80
        reason = (
            f"順張りピラミッディング許可 ({len(positions) + 1}/{self.max_positions}ポジ目, "
            f"エンジン:{entry_engine}, 未保護建玉:{unprotected_count} -> ロット係数:{pyramid_scale:.2f}x)"
        )
        return True, reason, pyramid_scale

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

        # max_daily_dd_pct が 0 または未設定の場合は日次停止をスキップ（上限なし）
        if self.max_daily_dd_pct is not None and self.max_daily_dd_pct > 0:
            if loss_pct >= self.max_daily_dd_pct:
                return False, f"日次最大ドローダウン限界突破 (-{loss_pct:.2f}% >= -{self.max_daily_dd_pct}%). 本日の取引を完全停止。"
        return True, "Normal"

    def has_open_positions(self, symbol: str) -> bool:
        """未決済建玉の有無を判定"""
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

        safe_mult = max(0.40, min(1.35, float(lot_multiplier)))
        risk_amount_jpy = equity * (self.risk_per_trade_pct / 100.0) * safe_mult

        pip_value_per_001_lot = 15.0
        calculated_lot = (risk_amount_jpy / (sl_distance_pips * (pip_value_per_001_lot / 0.01)))

        # max_lot が 0 または未設定の場合は上限なし（100.0 Lot）
        effective_max = self.max_lot if (self.max_lot and self.max_lot > 0) else 100.0
        rounded_lot = round(max(self.min_lot, min(effective_max, calculated_lot)), 2)
        return rounded_lot

    def apply_break_even_protection(
        self,
        symbol: str,
        pip_size: float = 0.10,
        be_trigger_rr: float = 1.15,
    ) -> Optional[str]:
        """
        【複数ポジション完全対応・反発ノイズ耐性強化】建値移動 (Break-Even) 自動スライド
        保有中の全ポジションを個別に監視し、未実現利益が「初期SL幅 × be_trigger_rr（標準1.15倍、最低30pips）」
        に達した時点でSLを「建値 + 2.5pips」へ引き上げる。微益撤退が多発した場合は be_trigger_rr が自動拡大する。
        """
        positions = mt5.positions_get(symbol=symbol)
        if not positions or len(positions) == 0:
            return None

        triggered_logs: List[str] = []
        be_buffer_dollars = 2.5 * pip_size
        eff_rr = max(0.95, float(be_trigger_rr or 1.15))

        for pos in positions:
            ticket = pos.ticket
            pos_type = pos.type  # 0: BUY, 1: SELL
            open_price = float(pos.price_open)
            current_price = float(pos.price_current)
            current_sl = float(pos.sl)

            if current_sl > 0:
                initial_sl_dist = abs(open_price - current_sl)
            else:
                initial_sl_dist = 30.0 * pip_size

            be_trigger_dollars = max(30.0 * pip_size, initial_sl_dist * eff_rr)

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
                        triggered_logs.append(f"BUY #{ticket} RR1:{eff_rr:.2f}到達による建値移動完了 (SL -> ${new_sl:.2f})")
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
                        triggered_logs.append(f"SELL #{ticket} RR1:{eff_rr:.2f}到達による建値移動完了 (SL -> ${new_sl:.2f})")

        return " | ".join(triggered_logs) if triggered_logs else None

    def apply_macro_trailing_protection(
        self,
        symbol: str,
        pip_size: float,
        macro_state: Optional[Dict[str, Any]],
        atr_m5_dollars: float,
        trail_atr_mult: float = 1.15,
    ) -> Optional[str]:
        """
        【複数ポジション完全対応・トレール反発刈り防止】マクロ反転トレーリング防御
        含み益が十分（最低35pips または 1.35×M5 ATR）に乗った状態で先行指標が反転した際、
        現在価格から「最低18pips または trail_atr_mult×M5 ATR」の呼吸幅（クッション）を残してSLを追従させる。
        トレール直後の反発で微益決済されるケースが多い場合、自己最適化により trail_atr_mult が自動で広がる。
        """
        if not macro_state:
            return None

        positions = mt5.positions_get(symbol=symbol)
        if not positions or len(positions) == 0:
            return None

        triggered_logs: List[str] = []
        eff_mult = max(0.75, float(trail_atr_mult or 1.15))
        min_profit_dollars = max(35.0 * pip_size, atr_m5_dollars * 1.35)
        trail_offset = max(18.0 * pip_size, atr_m5_dollars * eff_mult)

        for pos in positions:
            ticket = pos.ticket
            pos_type = pos.type  # 0: BUY, 1: SELL
            open_price = float(pos.price_open)
            current_price = float(pos.price_current)
            current_sl = float(pos.sl)

            if pos_type == 0 and macro_state.get("macro_reversed_against_buy"):
                profit_dollars = current_price - open_price
                if profit_dollars >= min_profit_dollars:
                    new_sl = round(current_price - trail_offset, 2)
                    if new_sl > open_price + (8.0 * pip_size) and (current_sl == 0.0 or new_sl > current_sl + (2.0 * pip_size)):
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": new_sl,
                            "tp": float(pos.tp)
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            triggered_logs.append(f"BUY #{ticket} マクロ反転トレーリング (幅:{eff_mult:.2f}xATR, SL -> ${new_sl:.2f})")

            elif pos_type == 1 and macro_state.get("macro_reversed_against_sell"):
                profit_dollars = open_price - current_price
                if profit_dollars >= min_profit_dollars:
                    new_sl = round(current_price + trail_offset, 2)
                    if new_sl < open_price - (8.0 * pip_size) and (current_sl == 0.0 or new_sl < current_sl - (2.0 * pip_size)):
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": new_sl,
                            "tp": float(pos.tp)
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            triggered_logs.append(f"SELL #{ticket} マクロ反転トレーリング (幅:{eff_mult:.2f}xATR, SL -> ${new_sl:.2f})")

        return " | ".join(triggered_logs) if triggered_logs else None
