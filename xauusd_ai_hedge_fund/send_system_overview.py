import requests
import json
import datetime
import sys
import config

# Windowsコンソールの文字化け防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def send_full_system_overview():
    """
    システム概要および全トレードロジックをDiscordへ公式レポートとして送信する
    """
    webhook_url = config.DISCORD_WEBHOOK_URL
    if not webhook_url:
        print("[ERROR] DISCORD_WEBHOOK_URL が設定されていません。")
        return

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    embed_main = {
        "title": "📋 【XAU/USD AI Hedge Fund System 総合アーキテクチャ & ロジック概要】",
        "description": "自律型AIクオンツヘッジファンドプラットフォーム (v7.0 Master Edition) の全体仕様・ロジック体系の公式概要書です。",
        "color": 0x00e676,  # Emerald Green
        "fields": [
            {
                "name": "🎯 コアコンセプト",
                "value": "• **マルチアセット抽象化**: XAU/USDから為替・暗号資産へ無改修展開可能な設計。\n• **2段階ハイブリッド判定**: Tier 1 高速クオンツ判定 ✕ Tier 2 8大専門AI合議体 (Gemini 2.5 Flash)。\n• **完全フェールセーフ**: 発注と同時にブローカー（Exness）サーバーへハードSL（損切り）を即時設定。",
                "inline": False
            },
            {
                "name": "⚙️ 高度アナリティクス & 特殊機能",
                "value": "• **動的最適MA探索 (Best-Fit MA)**: 時間足ごとに直近で最も意識され反発しているMA（例: 89EMA）をリアルタイム特定。\n• **動的ローリングアノマリー**: 直近3ヶ月の相関変化を最重視（原油・金利・ドルの最新レジーム適応）。\n• **エフェメラル画像解析**: チャート画像はAI解析後に即時物理削除（PC容量消費ゼロ）。\n• **トレード機会監視 (Opportunity Guard)**: 連続見送りを監視し、低ボラティリティ時もサポレジ反発（Mean Reversion）を積極模索。",
                "inline": False
            }
        ]
    }

    embed_agents = {
        "title": "🤖 8大専門AIエージェント合議体 (Decision Committee)",
        "color": 0x7c4dff,  # Deep Purple
        "fields": [
            {"name": "1. Technical Analyst", "value": "ダウ理論、EMAパーフェクトオーダー、動的MA、サポレジ反発を評価", "inline": True},
            {"name": "2. Macro & Lead-Lag", "value": "米実質金利(TIPS)、DXY、先行指標Top 5の動的追跡", "inline": True},
            {"name": "3. Contrarian Sentiment", "value": "OANDAリテール比率の極端な偏りから大口ストップ狩りを逆張り予測", "inline": True},
            {"name": "4. Discovery Architect", "value": "ロンドン/NYセッションアノマリー、SMC（オーダーブロック）分析", "inline": True},
            {"name": "5. Devil's Advocate", "value": "「なぜ負けるか」を徹底反証し、ダマシ・飛び乗りを強力にブロック", "inline": True},
            {"name": "6. CFO & Exit Guard", "value": "小資金モード（単一ポジション限定・タイトSL 15〜25pips）による絶対的資金保護", "inline": True},
            {"name": "7. Orchestrator", "value": "全エージェント意見を統合し、最終確信度と発注アクションを決定", "inline": True},
            {"name": "8. AI Producer", "value": "機関投資家の最新手法を監視し、システム改善案をユーザーへ提案", "inline": True}
        ]
    }

    embed_rules = {
        "title": "🛡️ 口座運用 & リスク管理ルール (Micro Account Mode)",
        "color": 0xff5722,  # Deep Orange
        "fields": [
            {"name": "取引ロット", "value": "`0.01 Lot`（小資金3万円口座等に対応）", "inline": True},
            {"name": "単一ポジション厳守", "value": "同時保有は最大1ポジションのみ。ナンピン・追撃は完全禁止。", "inline": True},
            {"name": "執行モード", "value": "MT5 実発注モード有効（自動約定・自動損切り管理）", "inline": True}
        ],
        "footer": {"text": f"XAU/USD AI Hedge Fund System v7.0 • 送信日時: {now_str}"}
    }

    payload = {
        "username": "AI Hedge Fund Architecture",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2092/2092663.png",
        "embeds": [embed_main, embed_agents, embed_rules]
    }

    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        if res.status_code in [200, 204]:
            print("[SUCCESS] システム概要とロジック解説をDiscordへ送信しました！")
        else:
            print(f"[FAILED] 送信失敗: {res.status_code}, 内容: {res.text}")
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    send_full_system_overview()
