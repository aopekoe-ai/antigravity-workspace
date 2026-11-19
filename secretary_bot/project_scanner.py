import os
import time
from pathlib import Path
from typing import List, Dict, Any

def get_active_projects(base_dirs: List[str], days_threshold: int = 7) -> List[Dict[str, Any]]:
    """
    直近 days_threshold 日以内に更新されたプロジェクトのみを抽出する超軽量スキャナー。
    ファイル内容を無駄にメモリへ読み込まず、mtime（タイムスタンプ）で超高速判定します。
    """
    active_projects = []
    now = time.time()
    cutoff_time = now - (days_threshold * 86400)
    seen_paths = set()

    for base_dir in base_dirs:
        base_path = Path(base_dir)
        if not base_path.exists():
            continue

        candidates = []
        # base_dir の直下にサブディレクトリがある場合は、それらをプロジェクト候補とする
        try:
            subdirs = [Path(entry.path) for entry in os.scandir(base_path) if entry.is_dir() and not entry.name.startswith(('.', '_'))]
            if subdirs:
                candidates.extend(subdirs)
            else:
                # サブディレクトリがなければ base_path 自体をプロジェクトとする
                candidates.append(base_path)
        except PermissionError:
            continue

        for proj_path in candidates:
            resolved_str = str(proj_path.resolve())
            if resolved_str in seen_paths:
                continue

            latest_mtime = 0
            latest_file = None
            recent_files = []

            try:
                for root, dirs, files in os.walk(proj_path):
                    # 巨大ディレクトリや無視対象を除外
                    dirs[:] = [d for d in dirs if not d.startswith(('.', 'node_modules', 'dist', 'build', '.git', '__pycache__'))]
                    
                    # 階層の深さを制限
                    rel = Path(root).relative_to(proj_path)
                    if len(rel.parts) > 3:
                        continue

                    for file in files:
                        if file.startswith('.'):
                            continue
                        fpath = os.path.join(root, file)
                        try:
                            mtime = os.path.getmtime(fpath)
                            if mtime > latest_mtime:
                                latest_mtime = mtime
                                latest_file = fpath
                            if mtime > cutoff_time:
                                recent_files.append((fpath, mtime))
                        except (OSError, PermissionError):
                            continue
            except Exception:
                continue

            # 7日以内に更新があった場合のみ追加
            if latest_mtime >= cutoff_time and recent_files:
                seen_paths.add(resolved_str)
                summary_info = extract_project_summary(proj_path, recent_files)

                active_projects.append({
                    "name": proj_path.name,
                    "path": str(proj_path),
                    "latest_mtime": latest_mtime,
                    "latest_file": latest_file,
                    "recent_file_count": len(recent_files),
                    "summary": summary_info
                })

    active_projects.sort(key=lambda x: x["latest_mtime"], reverse=True)
    return active_projects

def extract_project_summary(proj_path: Path, recent_files: List[tuple]) -> Dict[str, Any]:
    """
    プロジェクトの直近の更新点や未完了タスクを最小限のトークン/メモリでピンポイント抽出。
    """
    decisions = []
    uncompleted_tasks = []

    decision_files = [
        proj_path / "DECISIONS_SNAPSHOT.md",
        proj_path / "auto_decisions_latest.md"
    ]

    for df in decision_files:
        if df.exists():
            try:
                with open(df, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = [line.strip() for line in f.readlines() if line.strip()]
                    for line in lines[:15]:
                        if line.startswith(('-', '*', '#')):
                            decisions.append(line)
                break
            except Exception:
                pass

    for fpath, _ in sorted(recent_files, key=lambda x: x[1], reverse=True)[:3]:
        if fpath.endswith('.md'):
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped.startswith('- [ ]'):
                            uncompleted_tasks.append(stripped[5:].strip())
                            if len(uncompleted_tasks) >= 3:
                                break
            except Exception:
                pass
        if len(uncompleted_tasks) >= 3:
            break

    return {
        "decisions": decisions[:5],
        "tasks": uncompleted_tasks[:3]
    }
