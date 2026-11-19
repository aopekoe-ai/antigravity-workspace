# Enable AutoTrading in /tmp/common.ini and /tmp/terminal.ini
for p in ["/tmp/common.ini", "/tmp/terminal.ini"]:
    try:
        with open(p, "rb") as f:
            text = f.read().decode("utf-16le", errors="ignore")
        if "[Experts]" not in text:
            text += "\r\n[Experts]\r\nAllowDllImport=1\r\nEnabled=1\r\nAccount=0\r\nProfile=0\r\n"
            with open(p, "wb") as f:
                f.write(text.encode("utf-16le"))
            print(f"Updated {p}")
        else:
            print(f"Already configured: {p}")
    except Exception as e:
        print(f"Error {p}: {e}")
