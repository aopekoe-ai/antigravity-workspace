import os
import sys
from google.cloud import bigquery
from google.api_core.exceptions import Conflict
import config

# Windowsコンソールの文字化け防止
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def setup_bigquery_tables():
    """
    GCP BigQuery に統一データベース (データセット & テーブル群) を自動構築する
    """
    project_id = config.GCP_PROJECT_ID
    dataset_id = f"{project_id}.trading_system"
    
    print(f"[INFO] GCP プロジェクト: {project_id} へ接続中...")
    client = bigquery.Client(project=project_id)
    
    # 1. データセットの作成 (無料枠内: 10GBストレージ)
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = "asia-northeast1"  # 東京リージョン
    try:
        dataset = client.create_dataset(dataset, timeout=30)
        print(f"[SUCCESS] BigQuery データセットを作成しました: {dataset_id}")
    except Conflict:
        print(f"[INFO] データセットは既に存在します: {dataset_id}")
    except Exception as e:
        print(f"[ERROR] データセット作成失敗: {e}")
        return False

    # 2. テーブル定義 (OHLCV, Agent Logs, Trade History)
    tables = {
        "ohlcv_data": [
            bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("timeframe", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("open", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("high", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("low", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("close", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("volume", "INT64", mode="NULLABLE"),
        ],
        "agent_logs": [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("agent_name", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("signal", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("confidence", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("reasoning_json", "STRING", mode="NULLABLE"),
        ],
        "trade_history": [
            bigquery.SchemaField("order_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("action", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("volume", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("entry_price", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("sl_price", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("tp_price", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
        ]
    }

    # 3. 各テーブルの作成
    for table_name, schema in tables.items():
        table_ref = f"{dataset_id}.{table_name}"
        table = bigquery.Table(table_ref, schema=schema)
        try:
            table = client.create_table(table)
            print(f"[SUCCESS] テーブルを作成しました: {table_name}")
        except Conflict:
            print(f"[INFO] テーブルは既に存在します: {table_name}")
        except Exception as e:
            print(f"[ERROR] テーブル {table_name} の作成失敗: {e}")

    print("\n🎉 [COMPLETED] BigQuery データベースの自動構築が完了しました！")
    return True

if __name__ == "__main__":
    setup_bigquery_tables()
