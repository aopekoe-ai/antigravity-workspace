import requests
import json
import datetime
import sys
import config

# Windowsコンソールの文字化け・Unicodeエラー防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def send_test_discord_notification():
    """Discordへシステム開通のテスト通知を送信する"""
    webhook_url = config.DISCORD_WEBHOOK_URL
    
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    embed = {
        "title": "🤖 XAU/USD AI Hedge Fund System - 初期接続テスト成功",
        "description": "システムとDiscord間の通知ラインが正常に開通しました！",
        "color": 3447003,  # Blue color
        "fields": [
            {
                "name": "📡 接続ステータス",
                "value": "🟢 オンライン (正常)",
                "inline": True
            },
            {
                "name": "🔑 FRED API",
                "value": "🟢 登録完了",
                "inline": True
            },
            {
                "name": "⏰ 接続テスト時刻",
                "value": current_time,
                "inline": False
            },
            {
                "name": "📝 次のステップ",
                "value": "GCPプロジェクトの確認と、ローカルMT5 Python Bridgeの実装に進みます。",
                "inline": False
            }
        ],
        "footer": {
            "text": "Multi-Agent AI Hedge Fund Platform v7.0"
        }
    }
    
    payload = {
        "username": "AI Hedge Fund System",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2092/2092663.png",
        "embeds": [embed]
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(webhook_url, data=json.dumps(payload), headers=headers)
        if response.status_code in [200, 204]:
            print("[SUCCESS] Discordへのテストメッセージ送信に成功しました！")
        else:
            print(f"[FAILED] 送信失敗: ステータスコード {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"[ERROR] エラーが発生しました: {e}")

if __name__ == "__main__":
    send_test_discord_notification()
