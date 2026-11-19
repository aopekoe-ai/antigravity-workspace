import socket
s = socket.socket()
s.settimeout(5)
try:
    s.connect(("mt5-server", 18812))
    print("[SOCKET] CONNECT OK!")
except Exception as e:
    print("[SOCKET] CONNECT ERROR:", e)
finally:
    s.close()
