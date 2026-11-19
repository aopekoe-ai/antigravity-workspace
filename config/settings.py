import os
import json
from pathlib import Path

# プロジェクトルートディレクトリ
BASE_DIR = Path(__file__).resolve().parent.parent

# 設定ファイル
PARAMS_FILE = BASE_DIR / "config" / "strategy_params.json"

# Google Cloud Platform 設定
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "xauusd-ai-fund")
GCP_REGION = os.getenv("GCP_REGION", "asia-northeast1")
GCP_VERTEX_LOCATION = os.getenv("GCP_VERTEX_LOCATION", "us-central1")
VERTEX_MODEL_NAME = os.getenv("VERTEX_MODEL_NAME", "gemini-2.5-flash")

# FRED API Key (米連邦準備銀行)
FRED_API_KEY = os.getenv("FRED_API_KEY", "509548acea13a9fa6cc1d6ae7e50f117")

# Discord Webhook & Bot Token
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1556945137257680907/CzP5QETlItJvdLr1zyLFSfPeFJJO_M9x2RnD0zcPDKRgqtNY0e_bCSafNkRvW7pY_GW4"
)
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# MT5 口座切り替え用（未指定の場合はMT5端末で現在開いているアクティブ口座を使用）
MT5_LOGIN = os.getenv("MT5_LOGIN", None)
MT5_PASSWORD = os.getenv("MT5_PASSWORD", None)
MT5_SERVER = os.getenv("MT5_SERVER", None)
MT5_PATH = os.getenv("MT5_PATH", None)

# ログディレクトリ
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def load_strategy_params():
    """戦略パラメータを動的に読み込む（相場変化時にファイルを書き換えるだけで即反映）"""
    if PARAMS_FILE.exists():
        with open(PARAMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
