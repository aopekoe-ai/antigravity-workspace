import os
import sys
import time

MT5_HOST = os.getenv("MT5_HOST", None)
MT5_PORT = int(os.getenv("MT5_PORT", "18812"))

if MT5_HOST:
    print(f"[MT5 CONN] Connecting to remote MT5 Server at {MT5_HOST}:{MT5_PORT}...")
    connected = False
    for attempt in range(1, 31):
        try:
            try:
                from mt5linux_updated import MetaTrader5
                mt5 = MetaTrader5(host=MT5_HOST, port=MT5_PORT)
            except ImportError:
                from mt5linux import MetaTrader5
                mt5 = MetaTrader5(host=MT5_HOST, port=MT5_PORT)
            connected = True
            print(f"[MT5 CONN] Connected to {MT5_HOST}:{MT5_PORT} successfully!")
            break
        except Exception as e:
            print(f"[MT5 CONN WAIT] 試行 {attempt}/30 接続待機中 ({e})... 2秒後再試行")
            time.sleep(2.0)
    if not connected:
        raise ConnectionError(f"Failed to connect to MT5 server at {MT5_HOST}:{MT5_PORT}")
else:
    import MetaTrader5 as mt5
