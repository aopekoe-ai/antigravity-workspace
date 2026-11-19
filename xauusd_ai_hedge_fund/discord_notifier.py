import requests
import json
import datetime
import config
from schemas import CommitteeDecision

def send_discord_decision_alert(decision: CommitteeDecision, current_price: float):
    """
    合議体の判定結果をDiscordへリッチ通知（埋め込みメッセージ）送信する
    """
    webhook_url = config.DISCORD_WEBHOOK_URL
    if not webhook_url:
        return

    # 色設定: BUY (緑: 0x26a69a), SELL (赤: 0xef5350), ABSTAIN (グレー/黄: 0xffa726)
    if decision.direction == "BUY":
        color = 0x26a69a
        status_icon = "🟢 [BUY シグナル]"
    elif decision.direction == "SELL":
        color = 0xef5350
        status_icon = "🔴 [SELL シグナル]"
    else:
        color = 0xffa726
        status_icon = "⚪ [見送り (ABSTAIN)]"

    fields = [
        {"name": "🎯 アクション判定", "value": f"**{decision.action}** ({status_icon})", "inline": True},
        {"name": "📈 相場レジーム", "value": f"`{decision.regime}`", "inline": True},
        {"name": "🔥 総合確信度", "value": f"**{decision.final_confidence * 100:.1f}%**", "inline": True},
        {"name": "💵 現在価格", "value": f"`${current_price:.2f}`", "inline": True},
        {"name": "🛡️ 推奨SL / TP", "value": f"SL: `{decision.suggested_sl_pips} pips` / TP: `{decision.suggested_tp_pips} pips`", "inline": True},
        {"name": "💼 CFO資金管理", "value": f"承認: `{'✅ 承認' if decision.cfo_risk_approval else '⛔ 不承認'}` (Lot: `{decision.cfo_lot_size}`)", "inline": True},
        {"name": "📝 合議体エグゼクティブ解説", "value": decision.executive_summary_ja, "inline": False},
        {"name": "😈 デビルズアドボケート (リスク反論)", "value": f"> {decision.devils_advocate_objection}", "inline": False},
    ]

    if decision.producer_advice_ja:
        fields.append({
            "name": "🎬 AIプロデューサーからの改善・助言",
            "value": f"> {decision.producer_advice_ja}",
            "inline": False
        })

    embed = {
        "title": f"🤖 XAU/USD AI合議体 定時分析レポート ({decision.symbol})",
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"Multi-Agent AI Hedge Fund Platform v7.0 • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
    }

    payload = {
        "username": "AI Hedge Fund Committee",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2092/2092663.png",
        "embeds": [embed]
    }

    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        if res.status_code in [200, 204]:
            print("[DISCORD SUCCESS] 合議体分析アラートを送信しました！")
        else:
            print(f"[DISCORD FAILED] ステータス: {res.status_code}, 内容: {res.text}")
    except Exception as e:
        print(f"[DISCORD ERROR] {e}")

def send_flash_spike_alert(symbol: str, pips_move: float, cause_news: str, ai_guidance: str):
    """
    ⚡ 突発ボラティリティスパイク速報アラート
    """
    webhook_url = config.DISCORD_WEBHOOK_URL
    embed = {
        "title": f"⚡ 【突発ボラティリティ急変検知】 {symbol}",
        "color": 0xe91e63, # Magenta
        "fields": [
            {"name": "急変動幅", "value": f"`{pips_move:+.1f} pips`", "inline": True},
            {"name": "原因ニュース / イベント", "value": cause_news, "inline": False},
            {"name": "AIトレード判断 & 飛び乗り防止", "value": f"> {ai_guidance}", "inline": False}
        ],
        "footer": {"text": "Flash Spike Protection Engine"}
    }
    requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
