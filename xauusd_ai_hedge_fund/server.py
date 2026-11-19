from fastapi import FastAPI, BackgroundTasks, HTTPException
from schemas import MarketAnalysisPayload, CommitteeDecision
import agent_committee
import bigquery_logger
import discord_notifier
import datetime

app = FastAPI(
    title="XAU/USD AI Hedge Fund System Orchestrator",
    version="7.0.0",
    description="Multi-Agent Autonomous Quantitative Trading Platform API"
)

@app.get("/")
def health_check():
    return {
        "status": "healthy",
        "system": "Multi-Agent Autonomous XAU/USD Quantitative Trading Platform",
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.post("/api/analyze", response_model=CommitteeDecision)
def analyze_market(payload: MarketAnalysisPayload, background_tasks: BackgroundTasks):
    """
    マーケット分析リクエストを受信し、合議体判定 ＆ ログ記録 ＆ Discord通知を実行する
    """
    # 1. Tier 1 クオンツ ＆ Tier 2 AI Multi-Agent 合議体判定
    decision = agent_committee.evaluate_market_committee(payload)

    # 2. バックグラウンドで非同期に BigQuery ログ保存 ＆ Discord 通知
    background_tasks.add_task(bigquery_logger.log_agent_decision, decision)
    background_tasks.add_task(discord_notifier.send_discord_decision_alert, decision, payload.current_price)

    return decision

@app.post("/api/log-trade")
def log_trade(order_id: str, symbol: str, action: str, volume: float, entry_price: float, sl_price: float, tp_price: float, background_tasks: BackgroundTasks):
    """
    約定履歴を BigQuery に記録
    """
    background_tasks.add_task(
        bigquery_logger.log_trade_execution,
        order_id, symbol, action, volume, entry_price, sl_price, tp_price
    )
    return {"status": "queued"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=True)
