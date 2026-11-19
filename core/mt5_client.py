from core.mt5_conn import mt5
import time
from typing import Optional, Dict, Any

class RobustMT5Client:
    """
    VPS環境での24時間常時稼働に耐えうる堅牢なMT5クライアント（自動再接続・アカウント切替・ハードSL執行）
    """
    def __init__(
        self,
        symbol: str = "XAUUSD",
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None
    ):
        self.symbol = symbol
        self.login = login
        self.password = password
        self.server = server
        self.path = path

    def connect(self, max_retries: int = 20, retry_delay: float = 3.0) -> bool:
        """MT5との接続確立（起動中インスタンスへのアタッチ または 指定アカウントでの初期化）"""
        for attempt in range(1, max_retries + 1):
            try:
                success = mt5.initialize()
                if not success and (self.login and self.password and self.server):
                    init_kwargs = {
                        "login": int(self.login),
                        "password": str(self.password),
                        "server": str(self.server)
                    }
                    if self.path:
                        init_kwargs["path"] = self.path
                    success = mt5.initialize(**init_kwargs)

                if success:
                    acc = mt5.account_info()
                    if acc and self.login and acc.login != int(self.login):
                        print(f"[MT5 INFO] アカウント切り替え実行: #{acc.login} -> #{self.login}")
                        if not mt5.login(login=int(self.login), password=str(self.password), server=str(self.server)):
                            print(f"[MT5 LOGIN FAILED] 口座 #{self.login} へのログイン失敗: {mt5.last_error()}")
                            time.sleep(retry_delay)
                            continue
                        acc = mt5.account_info()

                    if acc:
                        trade_mode = "REAL(リアル)" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL else "DEMO(デモ)"
                        print(f"[MT5 CONNECTED] 口座: #{acc.login} ({acc.server}) [{trade_mode}] 残高: ¥{acc.balance:,.0f} 取引権限: {acc.trade_allowed}")
                        return True
                    else:
                        print(f"[MT5 WARNING] 口座情報取得待ち... (試行 {attempt}/{max_retries})")
            except Exception as e:
                print(f"[MT5 EXCEPTION] 接続例外 (試行 {attempt}/{max_retries}): {e}")

            time.sleep(retry_delay)
        return False

    def disconnect(self):
        """MT5接続の安全な終了"""
        try:
            mt5.shutdown()
        except Exception:
            pass

    def ensure_symbol_selected(self) -> bool:
        """シンボルが気配値表示で利用可能か確認"""
        symbol_info = mt5.symbol_info(self.symbol)
        if not symbol_info:
            return False
        if not symbol_info.visible:
            return mt5.symbol_select(self.symbol, True)
        return True

    def get_filling_mode(self, symbol_info) -> int:
        """Exness等のブローカー別 filling_mode の動的判定"""
        filling_mode = symbol_info.filling_mode
        if filling_mode & 1:  # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        elif filling_mode & 2:  # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        else:
            return mt5.ORDER_FILLING_RETURN

    def execute_order(
        self,
        action: str,
        volume: float,
        price: float,
        sl_price: float,
        tp_price: float,
        order_kind: str = "MARKET",
        comment: str = "v9:SMC"
    ) -> Optional[Dict[str, Any]]:
        """
        【完全フェールセーフ】ブローカーサーバーへハードSL/TPとエンジン識別コメントを同時に書き込む注文執行
        """
        if not self.ensure_symbol_selected():
            print(f"[MT5 ERROR] シンボル {self.symbol} の選択に失敗しました。")
            return None

        symbol_info = mt5.symbol_info(self.symbol)
        type_filling = self.get_filling_mode(symbol_info)
        digits = symbol_info.digits

        if action.upper() == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            deal_price = mt5.symbol_info_tick(self.symbol).ask
        elif action.upper() == "SELL":
            order_type = mt5.ORDER_TYPE_SELL
            deal_price = mt5.symbol_info_tick(self.symbol).bid
        else:
            print(f"[MT5 ERROR] 未対応のアクション: {action}")
            return None

        sl = round(sl_price, digits)
        tp = round(tp_price, digits)
        safe_comment = str(comment or "v9:SMC")[:31]

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": float(volume),
            "type": order_type,
            "price": deal_price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 202611,
            "comment": safe_comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": type_filling,
        }

        print(f"[ORDER SENDING] {self.symbol} {action} {volume} Lot @ {deal_price:.2f} (SL: {sl:.2f}, TP: {tp:.2f}, Engine: {safe_comment})")
        result = mt5.order_send(request)

        if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
            err_msg = result.comment if result else "No response"
            retcode = result.retcode if result else -1
            print(f"[MT5 ORDER FAILED] 約定失敗: {err_msg} (retcode: {retcode})")
            return None

        print(f"🎉 [MT5 ORDER SUCCESS] 約定完了! 注文番号: #{result.order}, 約定価格: {result.price:.2f} ({safe_comment})")
        return {
            "order_id": str(result.order),
            "symbol": self.symbol,
            "action": action,
            "volume": float(volume),
            "price": float(result.price),
            "sl": float(sl),
            "tp": float(tp),
            "comment": safe_comment
        }
