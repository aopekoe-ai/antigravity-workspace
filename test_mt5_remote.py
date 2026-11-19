from mt5linux_updated import MetaTrader5
import sys

print("[TEST] Connecting to mt5-server:18812...")
mt5 = MetaTrader5(host="mt5-server", port=18812)
print("[TEST] Connected. Initializing with credentials...")
res = mt5.initialize(login=277984494, password="aA!24861793", server="Exness-MT5Trial5")
print("[TEST] Initialize result:", res)
if not res:
    print("[TEST] Last error:", mt5.last_error())
terminal = mt5.terminal_info()
print("[TEST] Terminal info:", terminal)
acc = mt5.account_info()
print("[TEST] Account info:", acc)
if acc:
    print(f"[TEST SUCCESS] 口座: {acc.login}, 残高: {acc.balance}, 有効証拠金: {acc.equity}")
rates = mt5.copy_rates_from_pos("XAUUSD", 15, 0, 5)
print("[TEST] Rates sample:", rates)
