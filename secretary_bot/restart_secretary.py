import os
import sys
import time
import subprocess
from pathlib import Path

# WindowsコンソールでのUnicodeEncodeError (CP932) 防止
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = Path(__file__).parent.resolve()
SECRETARY_SCRIPT = BASE_DIR / "secretary.py"

# 本物のPython実行ファイルパス
REAL_PYTHON = r"C:\Users\user\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not os.path.exists(REAL_PYTHON):
    REAL_PYTHON = sys.executable

def kill_running_secretary():
    current_pid = os.getpid()
    print("既存の secretary.py プロセスを検索しています...")
    try:
        ps_script = (
            f"Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*secretary.py*' -and $_.ProcessId -ne {current_pid} }} | "
            f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force; Write-Host 'Stopped PID:' $_.ProcessId }}"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, encoding='utf-8', errors='replace')
        out = res.stdout.strip()
        if out:
            print(out)
        else:
            print("実行中の既存 secretary.py はありません。")
    except Exception as e:
        print(f"停止処理中に例外: {e}")

def start_new_secretary():
    print(f"最新の secretary.py を起動中: {SECRETARY_SCRIPT}")
    try:
        creation_flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        p = subprocess.Popen(
            [REAL_PYTHON, str(SECRETARY_SCRIPT)],
            cwd=str(BASE_DIR),
            creationflags=creation_flags
        )
        print(f"[OK] 再起動完了！ (新PID: {p.pid})")
    except Exception as e:
        print(f"起動エラー: {e}")

def main():
    print("==================================================")
    print("  Antigravity Secretary Bot 再起動マネージャー")
    print("==================================================")
    kill_running_secretary()
    time.sleep(1.0)
    start_new_secretary()

if __name__ == "__main__":
    main()
