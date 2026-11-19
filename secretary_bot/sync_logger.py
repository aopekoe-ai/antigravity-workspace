import os
import sys
from datetime import datetime
from pathlib import Path

# ログ保存先
INBOX_DIR = Path(r"C:\Obsidian\LLM Folder\01_Inbox")
DISCORD_LOG_PATH = INBOX_DIR / "discord_activity_log.md"

def record_activity_for_desktop(instruction: str, plan: str, result: str, project_path: str = ""):
    """
    Discordで実行されたタスクをObsidianログへ記録します。
    （会話自体は --conversation により既存スレッドに直接追記されます）
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title_short = instruction.split('\n')[0][:40].strip()

    try:
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        log_entry = (
            f"\n\n## [{now_str}] Discordからの指示: {title_short}\n"
            f"- **対象プロジェクト**: `{project_path if project_path else '未指定/グローバル'}`\n"
            f"- **ユーザー指示**:\n> {instruction}\n"
            f"- **承認された計画**:\n{plan}\n"
            f"- **Antigravity実行結果・変更ファイル**:\n```text\n{result[:1500]}\n```\n"
            f"- **ステータス**: 完了 (Approved via Discord)\n"
            f"---\n"
        )
        with open(DISCORD_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"活動ログ保存エラー: {e}")

    if project_path and os.path.isdir(project_path):
        snap_path = Path(project_path) / "DECISIONS_SNAPSHOT.md"
        try:
            snap_entry = (
                f"\n\n### [{now_str}] Discord承認タスク: {title_short}\n"
                f"- **指示**: {instruction}\n"
                f"- **実行結果要約**: {result.split(chr(10))[0][:100]}\n"
            )
            with open(snap_path, "a", encoding="utf-8") as f:
                f.write(snap_entry)
        except Exception:
            pass
