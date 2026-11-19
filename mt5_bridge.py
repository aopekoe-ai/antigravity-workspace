import MetaTrader5 as mt5
import pandas as pd
import datetime
import sys
import config

# Windowsコンソールの文字化け・Unicodeエラー防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def initialize_mt5():
    """MT5への接続を初期化する"""
    if not mt5.initialize():
        print(f"[ERROR] MT5の初期化に失敗しました。エラーコード: {mt5.last_error()}")
        return False
    print("[SUCCESS] MT5への接続に成功しました！")
    return True

def get_ohlcv_data(symbol=config.DEFAULT_SYMBOL, timeframe=mt5.TIMEFRAME_H1, count=100):
    """指定したシンボルとタイムフレームのローソク足データを取得する"""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        # シンボル名の揺れに対応 (例: XAUUSD, XAUUSD.a, GOLD等)
        print(f"[WARNING] {symbol} のデータ取得に失敗しました。Symbolリストを確認します。")
        return None
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

if __name__ == "__main__":
    if initialize_mt5():
        # ゴールド (XAUUSD) のH1足データを試しに取得
        symbol = config.DEFAULT_SYMBOL
        df_h1 = get_ohlcv_data(symbol=symbol, timeframe=mt5.TIMEFRAME_H1, count=5)
        
        if df_h1 is not None:
            print(f"\n📊 【{symbol} H1足 直近データ取得成功】")
            print(df_h1[['time', 'open', 'high', 'low', 'close', 'tick_volume']])
        else:
            # ブローカーの利用可能なシンボル名を表示
            symbols = mt5.symbols_get()
            print("\n利用可能なゴールド関連シンボルの候補:")
            for s in symbols:
                if "XAU" in s.name.upper() or "GOLD" in s.name.upper():
                    print(f" - {s.name}")
        
        mt5.shutdown()
