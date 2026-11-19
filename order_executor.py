import MetaTrader5 as mt5
import sys
import config
import mt5_bridge
import bigquery_logger
import requests

# Windowsコンソールの文字化け防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def check_open_positions(symbol=config.DEFAULT_SYMBOL):
    """
    CFO 小資金適応ルール:
    現在のオープンポジション数を取得し、単ポジ限定 (Single Position Policy) を守る
    """
    if not mt5_bridge.initialize_mt5():
        return -1
    
    positions = mt5.positions_get(symbol=symbol)
    mt5.shutdown()
    
    if positions is None:
        return 0
    return len(positions)

def execute_market_order_with_hard_sl(symbol=config.DEFAULT_SYMBOL, action="BUY", volume=0.01, sl_pips=20, tp_pips=40):
    """
    【完全フェールセーフ実発注モジュール】
    注文と同時にブローカーサーバーへハードSLを即時付与して実約定する。
    """
    # 1. 小資金ルール: 単ポジ制限チェック (Single Position Interlock)
    open_count = check_open_positions(symbol)
    if open_count > 0:
        print(f"[CFO GUARD] 既に {symbol} のオープンポジションが {open_count} 件存在します。単ポジルールに基づき新規エントリーをインターロックしました。")
        return False
    
    if not mt5_bridge.initialize_mt5():
        return False

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"[ERROR] {symbol} のシンボル情報が見つかりません。")
        mt5.shutdown()
        return False

    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            print(f"[ERROR] {symbol} を気配値表示に追加できませんでした。")
            mt5.shutdown()
            return False

    # 価格の取得とSL/TPの計算
    point = symbol_info.point
    digits = symbol_info.digits
    
    if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
        pip_size = 0.10  # ゴールドは $0.10 = 1 pip
    else:
        pip_size = point * (10 if digits in [3, 5] else 1)
    
    if action.upper() == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(symbol).ask
        sl = round(price - (sl_pips * pip_size), digits)
        tp = round(price + (tp_pips * pip_size), digits)
    elif action.upper() == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).bid
        sl = round(price + (sl_pips * pip_size), digits)
        tp = round(price - (tp_pips * pip_size), digits)
    else:
        print(f"[ERROR] 不正な売買アクション指定: {action}")
        mt5.shutdown()
        return False

    # ブローカー対応の Filling Mode を自動検出
    # bit 0 (1): SYMBOL_FILLING_FOK -> ORDER_FILLING_FOK (0)
    # bit 1 (2): SYMBOL_FILLING_IOC -> ORDER_FILLING_IOC (1)
    filling_mode = symbol_info.filling_mode
    if filling_mode & 1:
        type_filling = mt5.ORDER_FILLING_FOK
    elif filling_mode & 2:
        type_filling = mt5.ORDER_FILLING_IOC
    else:
        type_filling = mt5.ORDER_FILLING_RETURN

    # MT5 OrderSend リクエスト構造体 (注文時に即時ハードSLを必ず同梱)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 202610,
        "comment": "AI Hedge Fund Fail-Safe Order",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": type_filling,
    }

    print(f"\n[LIVE ORDER ATTEMPT] {symbol} {action} {volume} Lot (現在価格: {price}, ハードSL: {sl}, TP: {tp}) を発注します...")
    
    # 実発注の実行 (AutoTrading がONである必要があります)
    result = mt5.order_send(request)
    mt5.shutdown()
    
    if result is None:
        print(f"[FAIL-SAFE ORDER ERROR] order_send が None を返しました。MT5ターミナル設定を確認してください。")
        return False

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[FAIL-SAFE ORDER ERROR] 発注失敗: {result.comment} (retcode: {result.retcode})")
        return False
    else:
        print(f"🎉 [SUCCESS] ブローカーサーバーへのハードSL付き実約定に成功! 注文番号: #{result.order}, 約定価格: {result.price}")
        
        # BigQuery に約定履歴を記録
        bigquery_logger.log_trade_execution(
            order_id=str(result.order),
            symbol=symbol,
            action=action,
            volume=float(volume),
            entry_price=float(result.price),
            sl_price=float(sl),
            tp_price=float(tp)
        )

        # Discord に実約定速報を送信
        send_trade_execution_discord(
            order_id=str(result.order),
            symbol=symbol,
            action=action,
            volume=float(volume),
            price=float(result.price),
            sl=float(sl),
            tp=float(tp)
        )
        return True

def send_trade_execution_discord(order_id: str, symbol: str, action: str, volume: float, price: float, sl: float, tp: float):
    """実約定時のDiscord速報通知"""
    webhook_url = config.DISCORD_WEBHOOK_URL
    if not webhook_url:
        return

    color = 0x26a69a if action.upper() == "BUY" else 0xef5350
    embed = {
        "title": f"⚡ 【自動約定完了】 {symbol} {action} #{order_id}",
        "color": color,
        "fields": [
            {"name": "売買種別", "value": f"**{action}** ({volume} Lot)", "inline": True},
            {"name": "約定価格", "value": f"`${price:.2f}`", "inline": True},
            {"name": "ハードSL (損切)", "value": f"`${sl:.2f}`", "inline": True},
            {"name": "TP (利確)", "value": f"`${tp:.2f}`", "inline": True},
            {"name": "安全機能", "value": "✅ ブローカーサーバー側ハードSL即時書き込み完了\n✅ CFO単ポジインターロック有効", "inline": False}
        ],
        "footer": {"text": "AI Hedge Fund Execution Engine"}
    }
    try:
        requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
    except Exception as e:
        print(f"[DISCORD TRADE NOTIFY ERROR] {e}")

if __name__ == "__main__":
    print("--- 実発注モジュール単体テスト ---")
    print(f"現在のオープンポジション数: {check_open_positions(config.DEFAULT_SYMBOL)}")
