import MetaTrader5 as mt5
import pandas as pd
import matplotlib.pyplot as plt
import os
import datetime
import sys
import config
import mt5_bridge

# Windowsコンソールの文字化け防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def generate_multi_timeframe_chart(symbol=config.DEFAULT_SYMBOL):
    """
    マルチタイムフレーム(D1, H4, H1, M15)のチャート画像を生成し、一時保存する
    """
    if not mt5_bridge.initialize_mt5():
        return None

    # フォント警告回避のため英語表記
    timeframes = {
        "D1 (Daily)": mt5.TIMEFRAME_D1,
        "H4 (4-Hour)": mt5.TIMEFRAME_H4,
        "H1 (1-Hour)": mt5.TIMEFRAME_H1,
        "M15 (15-Min)": mt5.TIMEFRAME_M15
    }

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"XAU/USD Multi-Timeframe Analysis ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})", fontsize=16)

    axes_flat = axes.flatten()

    for idx, (tf_name, tf_val) in enumerate(timeframes.items()):
        df = mt5_bridge.get_ohlcv_data(symbol=symbol, timeframe=tf_val, count=40)
        ax = axes_flat[idx]

        if df is not None and not df.empty:
            # 簡易ローソク足 & 移動平均線 (20EMA & 89EMA) の描画
            df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
            df['EMA89'] = df['close'].ewm(span=89, adjust=False).mean()

            # ローソク足描画
            up = df[df['close'] >= df['open']]
            down = df[df['close'] < df['open']]

            col_up = '#26a69a'
            col_down = '#ef5350'

            # 陽線
            ax.vlines(up['time'], up['low'], up['high'], color=col_up, linewidth=1)
            ax.vlines(up['time'], up['open'], up['close'], color=col_up, linewidth=4)

            # 陰線
            ax.vlines(down['time'], down['low'], down['high'], color=col_down, linewidth=1)
            ax.vlines(down['time'], down['open'], down['close'], color=col_down, linewidth=4)

            # 移動平均線
            ax.plot(df['time'], df['EMA20'], label='20 EMA', color='#ff9800', linewidth=1.2)
            ax.plot(df['time'], df['EMA89'], label='89 EMA', color='#2196f3', linewidth=1.2)

            ax.set_title(f"Timeframe: {tf_name}")
            ax.legend(loc="upper left")
            ax.grid(True, linestyle='--', alpha=0.5)

    plt.tight_layout()
    
    # 一時画像の保存
    temp_dir = os.path.join(os.path.dirname(__file__), "temp")
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, f"chart_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    
    plt.savefig(file_path, dpi=100)
    plt.close()
    
    mt5.shutdown()
    print(f"[SUCCESS] マルチタイムフレームチャート画像を作成しました: {file_path}")
    return file_path

def cleanup_temp_image(file_path):
    """エフェメラル画像方針に基づき、処理完了後に画像を即時削除する"""
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(f"[CLEANUP] エフェメラル画像ポリシーに基づき画像を削除しました: {file_path}")
        except Exception as e:
            print(f"[WARNING] 画像削除エラー: {e}")

if __name__ == "__main__":
    chart_path = generate_multi_timeframe_chart()
    if chart_path:
        print("[TEST] 画像が存在することを確認中...")
        print(f"存在フラグ: {os.path.exists(chart_path)}")
        
        cleanup_temp_image(chart_path)
        print(f"削除後存在フラグ (0を期待): {os.path.exists(chart_path)}")
