import os
import json
import datetime
import config
import requests

STATE_FILE = os.path.join(os.path.dirname(__file__), "system_state.json")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "consecutive_abstains": 0,
        "last_trade_time": None,
        "total_trades": 0
    }

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[STATE ERROR] {e}")

def update_opportunity_metrics(action: str):
    """
    トレード頻度と見送り連続回数を追跡し、機会損失アラートを監視する
    """
    state = load_state()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if action in ["TACTICAL_A_MARKET", "TACTICAL_B_PENDING"]:
        state["consecutive_abstains"] = 0
        state["last_trade_time"] = now_str
        state["total_trades"] = state.get("total_trades", 0) + 1
        save_state(state)
        return state["consecutive_abstains"], False
    else:
        state["consecutive_abstains"] = state.get("consecutive_abstains", 0) + 1
        save_state(state)
        
        # 12回連続 (半日以上) トレード機会がない場合、アラートを発報
        need_alert = False
        if state["consecutive_abstains"] in [12, 24, 48]:
            need_alert = True
            send_opportunity_alert(state["consecutive_abstains"], state.get("last_trade_time"))

        return state["consecutive_abstains"], need_alert

def send_opportunity_alert(abstain_count: int, last_trade_time: str):
    """
    トレード機会減少を検知した際の Discord 機会損失監視アラート
    """
    webhook_url = config.DISCORD_WEBHOOK_URL
    if not webhook_url:
        return

    embed = {
        "title": "👁️ 【トレード機会 ＆ 機会損失監視アラート】",
        "description": f"直近 **{abstain_count} 回連続** でエントリーが見送られています（監視中）。",
        "color": 0xff9800, # Orange
        "fields": [
            {"name": "前回エントリー日時", "value": f"`{last_trade_time or '未記録'}`", "inline": True},
            {"name": "連続見送り回数", "value": f"`{abstain_count} サイクル`", "inline": True},
            {"name": "💡 AIプロデューサーからの適応指示", "value": "> 機会損失（トレード機会不足）を防ぐため、高ボラ時の大きなブレイクだけでなく、**「レンジ境界線での反発（Mean Reversion）」や「動的MA（89EMA等）への押し目指値（Tactical B）」** を積極的に模索するようAIパラメータの柔軟性を引き上げます。", "inline": False}
        ],
        "footer": {"text": "Trade Frequency & Opportunity Guard Engine"}
    }
    try:
        requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)
        print(f"[OPPORTUNITY ALERT] トレード機会監視アラートをDiscordへ送信しました ({abstain_count}回連続見送り)")
    except Exception as e:
        print(f"[OPPORTUNITY NOTIFY ERROR] {e}")
