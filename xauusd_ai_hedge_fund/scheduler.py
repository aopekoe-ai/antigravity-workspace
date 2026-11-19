import time
import datetime
import client_worker
import config

def start_scheduler():
    """
    起動直後に1回即時実行し、その後毎時00分のローソク足確定時に自動でパイプラインを実行するスケジューラー
    """
    print("==================================================")
    print("🤖 XAU/USD AI Hedge Fund Autonomous Scheduler 起動")
    print(f"対象シンボル: {config.DEFAULT_SYMBOL}")
    print(f"実発注モード: {'【有効 (LIVE AUTO TRADING)】' if config.LIVE_TRADING_ENABLED else '【模擬 (DRY-RUN)】'}")
    print(f"初期ロット: {config.DEFAULT_LOT_SIZE} Lot (CFO小資金モード)")
    print("監視周期: 毎時 00 分 (ローソク足確定トリガー)")
    print("==================================================")

    # 1. 起動時の即時1回実行 (動作確認)
    print("\n[STARTUP] スケジューラー起動を検知しました。初回相場分析を実行します...")
    try:
        client_worker.run_pipeline_cycle(symbol=config.DEFAULT_SYMBOL, dry_run=not config.LIVE_TRADING_ENABLED)
    except Exception as e:
        print(f"[STARTUP ERROR] 初回実行エラー: {e}")

    last_executed_hour = datetime.datetime.now().hour

    print(f"\n[STANDBY] 次のローソク足確定（毎時 00 分）まで待機中... (常時監視稼働中)")

    while True:
        now = datetime.datetime.now()
        
        # 毎時 00 分を検知した際に実行
        if now.minute == 0 and now.hour != last_executed_hour:
            print(f"\n[CRON TRIGGER] 毎時 00 分を検知しました: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            try:
                client_worker.run_pipeline_cycle(symbol=config.DEFAULT_SYMBOL, dry_run=not config.LIVE_TRADING_ENABLED)
                last_executed_hour = now.hour
                print(f"\n[STANDBY] 次のローソク足確定（毎時 00 分）まで待機中...")
            except Exception as e:
                print(f"[CRON ERROR] パイプライン実行エラー: {e}")

        # 10秒ごとに待機
        time.sleep(10)

if __name__ == "__main__":
    start_scheduler()
