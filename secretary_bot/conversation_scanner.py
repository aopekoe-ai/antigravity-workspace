import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple

# WindowsコンソールでのUnicodeEncodeError防止
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

DB_PATH = Path(r"C:\Users\user\.gemini\antigravity\conversation_summaries.db")

def get_sidebar_conversations(days_threshold: int = 7) -> Tuple[List[Dict[str, Any]], int]:
    """
    Antigravityの左サイドバー「Conversations」に並んでいる正規スレッドをそのまま取得し、
    直近 days_threshold 日以内に更新があった『アクティブな会話』と『休眠中の会話数』を返します。
    """
    if not DB_PATH.exists():
        return [], 0

    uri = f"file:{DB_PATH.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()

        # UIに表示される会話のみを対象（CLIの一時タスクやネストされたサブエージェントは除外）
        query = """
        SELECT conversation_id, title, preview, step_count, last_modified_time, project_id
        FROM conversation_summaries
        WHERE (source IS NULL OR source != 'CORTEX_TRAJECTORY_SOURCE_CLI')
          AND (parent_conversation_id IS NULL OR parent_conversation_id = '')
        ORDER BY last_modified_time DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"Error querying conversation_summaries.db: {e}")
        return [], 0

    active_conversations = []
    inactive_count = 0
    jst = timezone(timedelta(hours=9))
    cutoff_utc = datetime.now(timezone.utc) - timedelta(days=days_threshold)

    for row in rows:
        cid, title, preview, step_count, modified_str, project_id = row

        # 表示用のタイトル解決（title が空の場合は preview の先頭行を使用）
        display_title = title.strip() if title else ""
        if not display_title and preview:
            display_title = preview.split('\n')[0].strip()
        if not display_title:
            display_title = "無題の会話"

        # 日時判定（UTC -> JST）
        is_active = False
        dt_display = modified_str
        try:
            clean_time_str = modified_str.split('.')[0]
            if '+' in modified_str:
                tz_part = '+' + modified_str.split('+')[1]
                dt_obj = datetime.fromisoformat(clean_time_str + tz_part)
            elif 'Z' in modified_str:
                dt_obj = datetime.fromisoformat(clean_time_str + "+00:00")
            else:
                dt_obj = datetime.fromisoformat(clean_time_str).replace(tzinfo=timezone.utc)

            # 7日以内かどうか判定
            if dt_obj >= cutoff_utc:
                is_active = True

            dt_jst = dt_obj.astimezone(jst)
            now_jst = datetime.now(jst)
            delta = now_jst - dt_jst

            if delta.days == 0:
                dt_display = f"今日 {dt_jst.strftime('%H:%M')}"
            elif delta.days == 1:
                dt_display = f"昨日 {dt_jst.strftime('%H:%M')}"
            elif delta.days < 7:
                dt_display = f"{delta.days}日前"
            else:
                # 30日以上なら〇mo
                months = delta.days // 30
                dt_display = f"{months}ヶ月前" if months > 0 else f"{delta.days}日前"
        except Exception:
            pass

        if is_active:
            active_conversations.append({
                "id": cid,
                "short_id": cid[:8],
                "title": display_title,
                "preview": preview.split('\n')[0][:60] if preview else "",
                "step_count": step_count,
                "last_modified_display": dt_display,
                "project_id": project_id
            })
        else:
            inactive_count += 1

    return active_conversations, inactive_count

if __name__ == "__main__":
    actives, inactives = get_sidebar_conversations(days_threshold=7)
    print(f"=== Antigravity Conversations (1週間以内: {len(actives)}件 / 休眠: {inactives}件) ===")
    for c in actives:
        print(f"• {c['title']} ({c['last_modified_display']}) - Steps: {c['step_count']}")
