import datetime
import json
from google.cloud import bigquery
import config
from schemas import CommitteeDecision, CandleData

client = bigquery.Client(project=config.GCP_PROJECT_ID)

def log_agent_decision(decision: CommitteeDecision):
    """
    合議体の最終判定ログを BigQuery (trading_system.agent_logs) に非同期・安全書き込み
    """
    table_id = f"{config.GCP_PROJECT_ID}.trading_system.agent_logs"
    
    row_to_insert = [
        {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "symbol": decision.symbol,
            "agent_name": "Orchestrator_Committee",
            "signal": f"{decision.action}_{decision.direction}",
            "confidence": float(decision.final_confidence),
            "reasoning_json": json.dumps({
                "regime": decision.regime,
                "executive_summary_ja": decision.executive_summary_ja,
                "devils_advocate": decision.devils_advocate_objection,
                "cfo_risk_approval": decision.cfo_risk_approval,
                "producer_advice_ja": decision.producer_advice_ja,
                "agent_verdicts": [v.model_dump() for v in decision.agent_verdicts]
            }, ensure_ascii=False)
        }
    ]
    
    try:
        errors = client.insert_rows_json(table_id, row_to_insert)
        if not errors:
            print(f"[BIGQUERY LOG SUCCESS] agent_logs に判定ログを書き込みました: {decision.action}")
        else:
            print(f"[BIGQUERY LOG WARNING] agent_logs 書き込みエラー: {errors}")
    except Exception as e:
        print(f"[BIGQUERY LOG ERROR] {e}")

def log_trade_execution(order_id: str, symbol: str, action: str, volume: float, entry_price: float, sl_price: float, tp_price: float):
    """
    約定したトレード履歴を BigQuery (trading_system.trade_history) に保存
    """
    table_id = f"{config.GCP_PROJECT_ID}.trading_system.trade_history"
    row = [
        {
            "order_id": str(order_id),
            "symbol": symbol,
            "action": action,
            "volume": float(volume),
            "entry_price": float(entry_price),
            "sl_price": float(sl_price),
            "tp_price": float(tp_price),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    ]
    try:
        errors = client.insert_rows_json(table_id, row)
        if not errors:
            print(f"[BIGQUERY TRADE LOG] trade_history に約定を記録しました: #{order_id}")
        else:
            print(f"[BIGQUERY TRADE WARNING] {errors}")
    except Exception as e:
        print(f"[BIGQUERY TRADE ERROR] {e}")
