import os
import json
from pathlib import Path
from typing import Dict, Any

# プロジェクトルートディレクトリ
BASE_DIR = Path(__file__).resolve().parent.parent

# 設定ファイル
PARAMS_FILE = BASE_DIR / "config" / "strategy_params.json"

# Google Cloud Platform 設定
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "xauusd-ai-fund")
GCP_REGION = os.getenv("GCP_REGION", "asia-northeast1")
GCP_VERTEX_LOCATION = os.getenv("GCP_VERTEX_LOCATION", "us-central1")
VERTEX_MODEL_NAME = os.getenv("VERTEX_MODEL_NAME", "gemini-2.5-flash")

# FRED API Key (米連邦準備銀行・予備)
FRED_API_KEY = os.getenv("FRED_API_KEY", "509548acea13a9fa6cc1d6ae7e50f117")

# TradingView Webhook & ダッシュボード認証設定
TV_WEBHOOK_TOKEN = os.getenv("TV_WEBHOOK_TOKEN", "")
TV_WEBHOOK_PORT = int(os.getenv("TV_WEBHOOK_PORT", "8000"))
DASHBOARD_KEY = os.getenv("DASHBOARD_KEY", "") or TV_WEBHOOK_TOKEN
VPS_PUBLIC_HOST = os.getenv("VPS_PUBLIC_HOST", "155.133.7.59")

# Discord Webhook & Bot Token
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1556945137257680907/CzP5QETlItJvdLr1zyLFSfPeFJJO_M9x2RnD0zcPDKRgqtNY0e_bCSafNkRvW7pY_GW4"
)
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# MT5 口座切り替え用
MT5_LOGIN = os.getenv("MT5_LOGIN", None)
MT5_PASSWORD = os.getenv("MT5_PASSWORD", None)
MT5_SERVER = os.getenv("MT5_SERVER", None)
MT5_PATH = os.getenv("MT5_PATH", None)

# ログディレクトリ
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_dashboard_url() -> str:
    """Discordレポート等に掲載するスマホワンタップ用ダッシュボードURLを生成"""
    key = DASHBOARD_KEY
    if key:
        return f"http://{VPS_PUBLIC_HOST}/dashboard?key={key}"
    return f"http://{VPS_PUBLIC_HOST}/dashboard"


def load_strategy_params() -> Dict[str, Any]:
    """戦略パラメータを動的に読み込む"""
    if PARAMS_FILE.exists():
        try:
            with open(PARAMS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_strategy_params(params: Dict[str, Any]) -> bool:
    """ダッシュボードから変更された戦略パラメータをアトミック保存"""
    try:
        tmp = PARAMS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PARAMS_FILE)
        return True
    except Exception as e:
        print(f"[SETTINGS ERROR] save_strategy_params failed: {e}")
        return False
