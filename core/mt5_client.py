from core.mt5_conn import mt5
import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List


class RobustMT5Client:
    """
    VPS環境での24時間常時稼働に耐えうる堅牢なMT5クライアント v9.2
    - 自動再接続・ブローカー/口座のリアルタイム切替（画面からの証券会社変更に完全対応）
    - ブローカー別シンボル名の自動検出（XAUUSD/GOLD, DXY/USDX, USOIL/WTI 等）
    - ダッシュボードからの個別決済・全決済（Panic Close）・一括建値ロック機能
    """
    def __init__(
        self,
        symbol: str = "XAUUSD",
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None,
        broker_config_path: Optional[Path] = None,
    ):
        self.symbol = symbol
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self.broker_config_path = broker_config_path or (Path(__file__).resolve().parent.parent / "config" / "broker_account.json")
        self._load_saved_broker_override()

    def _load_saved_broker_override(self) -> None:
        """画面から保存された証券会社・口座設定があれば優先ロード"""
        try:
            if self.broker_config_path.exists():
                with open(self.broker_config_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("login"):
                    self.login = int(d["login"])
                if d.get("password"):
                    self.password = str(d["password"])
                if d.get("server"):
                    self.server = str(d["server"])
                if d.get("symbol"):
                    self.symbol = str(d["symbol"])
        except Exception as e:
            print(f"[MT5 WARN] broker_account.json 読込スキップ: {e}")

    def save_broker_override(self, login: int, password: str, server: str, symbol: str) -> None:
        try:
            self.broker_config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "login": int(login),
                "password": str(password),
                "server": str(server),
                "symbol": str(symbol),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            tmp = self.broker_config_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.broker_config_path)
            os.chmod(self.broker_config_path, 0o600)
        except Exception as e:
            print(f"[MT5 WARN] broker_account.json 保存失敗: {e}")

    def connect(self, max_retries: int = 20, retry_delay: float = 3.0) -> bool:
        """MT5との接続確立"""
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
                        print(f"[MT5 INFO] アカウント切り替え実行: #{acc.login} -> #{self.login} ({self.server})")
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

    def switch_account_live(
        self,
        login: int,
        password: str,
        server: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        ダッシュボードから証券会社・MT5口座をリアルタイムに切り替え、接続検証とシンボル自動検出を行う
        """
        try:
            mt5.initialize()
            ok = mt5.login(login=int(login), password=str(password), server=str(server))
            if not ok:
                err = mt5.last_error()
                return {"success": False, "error": f"MT5ログイン失敗: {err} (口座番号・パスワード・サーバー名を確認してください)"}

            acc = mt5.account_info()
            if not acc or int(acc.login) != int(login):
                return {"success": False, "error": "ログイン後の口座情報確認に失敗しました。"}

            detected = self.auto_detect_broker_symbols()
            target_sym = symbol.strip() if (symbol and symbol.strip()) else detected.get("gold", self.symbol)

            self.login = int(login)
            self.password = str(password)
            self.server = str(server)
            self.symbol = target_sym
            self.ensure_symbol_selected()
            self.save_broker_override(self.login, self.password, self.server, self.symbol)

            trade_mode = "REAL" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL else "DEMO"
            return {
                "success": True,
                "login": int(acc.login),
                "server": str(acc.server),
                "company": str(getattr(acc, "company", "")),
                "currency": str(getattr(acc, "currency", "JPY")),
                "balance": float(acc.balance),
                "equity": float(acc.equity),
                "trade_mode": trade_mode,
                "trade_allowed": bool(acc.trade_allowed),
                "active_symbol": self.symbol,
                "detected_symbols": detected,
            }
        except Exception as e:
            return {"success": False, "error": f"口座切替エラー: {e}"}

    def auto_detect_broker_symbols(self) -> Dict[str, str]:
        """接続中ブローカーの全提供銘柄からゴールドおよび先行指標5銘柄の正式シンボル名を自動検出"""
        result = {
            "gold": self.symbol or "XAUUSD",
            "dxy": "DXY",
            "yield_proxy": "USDJPY",
            "oil": "USOIL",
            "equity": "USTEC",
            "aud": "AUDUSD",
        }
        try:
            all_syms = mt5.symbols_get()
            if not all_syms:
                return result
            names = [str(s.name) for s in all_syms]
            names_set = set(names)

            def _pick(candidates: List[str], default_val: str) -> str:
                for c in candidates:
                    if c in names_set:
                        return c
                for c in candidates:
                    for n in names:
                        if n.upper().startswith(c.upper()):
                            return n
                return default_val

            result["gold"] = _pick(["XAUUSD", "GOLD", "XAUUSDm", "XAUUSD.a", "XAUUSDc"], result["gold"])
            result["dxy"] = _pick(["DXY", "USDX", "DXYm", "USDINDEX", "DX"], result["dxy"])
            result["yield_proxy"] = _pick(["USDJPY", "USDJPYm", "USDJPY.a", "USDJPYc"], result["yield_proxy"])
            result["oil"] = _pick(["USOIL", "WTI", "XTIUSD", "USOILm", "CL", "UKOIL"], result["oil"])
            result["equity"] = _pick(["USTEC", "NAS100", "US100", "USTECm", "NDX", "US30"], result["equity"])
            result["aud"] = _pick(["AUDUSD", "AUDUSDm", "AUDUSD.a", "AUDUSDc"], result["aud"])
        except Exception:
            pass
        return result

    def get_broker_info(self) -> Dict[str, Any]:
        """現在の接続口座・ブローカー詳細情報を取得"""
        acc = mt5.account_info()
        if not acc:
            return {
                "connected": False,
                "login": self.login,
                "server": self.server,
                "symbol": self.symbol,
            }
        return {
            "connected": True,
            "login": int(acc.login),
            "server": str(acc.server),
            "company": str(getattr(acc, "company", "Exness")),
            "currency": str(getattr(acc, "currency", "JPY")),
            "balance": float(acc.balance),
            "equity": float(acc.equity),
            "profit": float(acc.profit),
            "margin_free": float(acc.margin_free),
            "leverage": int(getattr(acc, "leverage", 0)),
            "trade_mode": "REAL" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL else "DEMO",
            "trade_allowed": bool(acc.trade_allowed),
            "symbol": self.symbol,
        }

    def get_open_positions_detail(self, ticket_engine_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """保有中の全ポジション詳細（エンジン名・建値ロック状態・含み損益）をリストで返す"""
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return []
        t_map = ticket_engine_map or {}
        out: List[Dict[str, Any]] = []
        for p in positions:
            t_str = str(p.ticket)
            comm = str(getattr(p, "comment", "") or "")
            eng = t_map.get(t_str)
            if not eng:
                cu = comm.upper()
                if "MACRO_MOMENTUM" in cu:
                    eng = "MACRO_MOMENTUM"
                elif "SMT" in cu:
                    eng = "SMT_DIVERGENCE"
                else:
                    eng = "SMC"
            act = "BUY" if p.type == 0 else "SELL"
            open_px = float(p.price_open)
            cur_px = float(p.price_current)
            cur_sl = float(p.sl)
            cur_tp = float(p.tp)
            is_be = (p.type == 0 and cur_sl >= open_px) or (p.type == 1 and cur_sl > 0 and cur_sl <= open_px)
            pips_pnl = round(((cur_px - open_px) if p.type == 0 else (open_px - cur_px)) / 0.10, 1)
            out.append({
                "ticket": int(p.ticket),
                "symbol": str(p.symbol),
                "action": act,
                "engine": eng,
                "volume": float(p.volume),
                "price_open": round(open_px, 2),
                "price_current": round(cur_px, 2),
                "sl": round(cur_sl, 2),
                "tp": round(cur_tp, 2),
                "profit_jpy": round(float(p.profit), 0),
                "pips": pips_pnl,
                "is_be_locked": is_be,
                "comment": comm,
            })
        return out

    def close_position_by_ticket(self, ticket: int) -> Dict[str, Any]:
        """指定チケットのポジションを成行決済"""
        positions = mt5.positions_get(ticket=int(ticket))
        if not positions:
            return {"success": False, "error": f"ポジション #{ticket} が見つかりません"}
        pos = positions[0]
        sym = str(pos.symbol)
        sym_info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if not sym_info or not tick:
            return {"success": False, "error": "シンボル情報が取得できません"}

        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        close_px = tick.bid if pos.type == 0 else tick.ask
        filling = self.get_filling_mode(sym_info)

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": int(pos.ticket),
            "symbol": sym,
            "volume": float(pos.volume),
            "type": close_type,
            "price": close_px,
            "deviation": 30,
            "magic": 202611,
            "comment": "Dashboard Manual Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            return {"success": True, "ticket": int(ticket), "close_price": float(res.price)}
        err = res.comment if res else "No response"
        return {"success": False, "error": f"決済失敗: {err}"}

    def close_all_positions(self) -> Dict[str, Any]:
        """保有中の全ポジションを一括成行決済（緊急パニッククローズ）"""
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return {"success": True, "closed_count": 0, "message": "保有ポジションはありません"}
        closed = 0
        errors = []
        for p in positions:
            r = self.close_position_by_ticket(int(p.ticket))
            if r.get("success"):
                closed += 1
            else:
                errors.append(r.get("error", ""))
        return {"success": len(errors) == 0, "closed_count": closed, "errors": errors}

    def lock_break_even_all(self, pip_size: float = 0.10) -> Dict[str, Any]:
        """現在含み益が出ている全ポジションのSLを即座に『建値 + 1.5pips』へ手動ロック"""
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return {"success": True, "locked_count": 0, "message": "保有ポジションはありません"}
        locked = 0
        buf = 1.5 * pip_size
        for pos in positions:
            open_px = float(pos.price_open)
            cur_px = float(pos.price_current)
            cur_sl = float(pos.sl)
            if pos.type == 0 and (cur_px - open_px) > buf * 2:
                new_sl = round(open_px + buf, 2)
                if cur_sl < new_sl or cur_sl == 0.0:
                    req = {"action": mt5.TRADE_ACTION_SLTP, "position": int(pos.ticket), "symbol": str(pos.symbol), "sl": new_sl, "tp": float(pos.tp)}
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        locked += 1
            elif pos.type == 1 and (open_px - cur_px) > buf * 2:
                new_sl = round(open_px - buf, 2)
                if cur_sl > new_sl or cur_sl == 0.0:
                    req = {"action": mt5.TRADE_ACTION_SLTP, "position": int(pos.ticket), "symbol": str(pos.symbol), "sl": new_sl, "tp": float(pos.tp)}
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        locked += 1
        return {"success": True, "locked_count": locked}

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
