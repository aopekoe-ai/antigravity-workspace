#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portable Brain Engine - Compact-Proof Zero-Amnesia Checkpoint CLI (checkpoint.py)
`/compact`（コンテキスト要約）実行時や長時間中断後の再開時に、確定仕様・ボツ案（先祖返り禁止）・
直近編集ファイル・次の一手を失わせないための自動引き継ぎスクリプト。
- Gitリポジトリの有無に関わらず動作（タイムスタンプ検知 ＋ Git差分ハイブリッド）
- Claude Code (`PreCompact` / `SessionStart[compact]`) 完全対応
- Antigravity (`PreInvocation` での `/compact` ステップ減少自動検知) 完全対応
- Cursor / Windsurf / Grok 向けクリップボード出力対応
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

IGNORE_DIRS = {
    "node_modules",
    ".git",
    ".next",
    "dist",
    "build",
    "out",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".brain",
    ".agents",
    ".claude",
    ".cursor",
    "coverage",
}

RECOVERY_KEYWORDS = (
    "続きやって",
    "さっきの続き",
    "作業を再開",
    "compact後",
    "/checkpoint",
    "状況を復元",
)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_to_clipboard(text: str) -> bool:
    try:
        if os.name == "nt":
            proc = subprocess.run(
                ["clip"],
                input=text.encode("utf-16le"),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return proc.returncode == 0
    except Exception:
        return False
    return False


def detect_recent_files(project_root: Path, hours: float = 24.0, limit: int = 6) -> List[str]:
    """Git非依存：直近N時間以内に更新されたプロジェクト内ファイルを新しい順に取得する"""
    cutoff = time.time() - (hours * 3600.0)
    candidates: List[tuple[float, str]] = []

    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(project_root).parts
        if any(part in IGNORE_DIRS for part in rel_parts):
            continue
        if path.name.endswith(".restore.json") or path.name.endswith(".bak"):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            rel_posix = path.relative_to(project_root).as_posix()
            candidates.append((mtime, rel_posix))

    candidates.sort(key=lambda x: x[0], reverse=True)
    result: List[str] = []
    for mtime, rel_posix in candidates[:limit]:
        ts = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
        result.append(f"`{rel_posix}` ({ts}更新)")
    return result


def detect_git_dirty_files(project_root: Path, limit: int = 6) -> List[str]:
    """Gitリポジトリがある場合のみ補助的に未コミット変更一覧を取得する（無くてもエラーにしない）"""
    if not (project_root / ".git").exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3,
            check=False,
        )
        if proc.returncode != 0:
            return []
        items: List[str] = []
        for raw in proc.stdout.splitlines():
            line = raw.strip()
            if not line or ".brain/" in line or ".agents/" in line or ".claude/" in line:
                continue
            items.append(f"`{line}`")
            if len(items) >= limit:
                break
        return items
    except Exception:
        return []


def extract_section_bullets(text: str, heading_keyword: str, max_items: int = 5) -> List[str]:
    lines = text.splitlines()
    in_sec = False
    out: List[str] = []
    for ln in lines:
        if ln.startswith("## ") and heading_keyword in ln:
            in_sec = True
            continue
        if in_sec:
            if ln.startswith("## "):
                break
            if ln.startswith("- ") and "未登録" not in ln and "初期状態" not in ln:
                out.append(ln)
                if len(out) >= max_items:
                    break
    return out


def build_compact_handover(project_root: Path, brain_dir: Path) -> str:
    """約300〜380トークンの高密度引き継ぎカプセルを生成し compact_handover.md に保存する"""
    snap_path = brain_dir / "DECISIONS_SNAPSHOT.md"
    task_path = brain_dir / "current_task.md"
    rat_path = brain_dir / "workspace" / "latest_rationale.md"

    snap_text = snap_path.read_text(encoding="utf-8") if snap_path.exists() else ""
    task_text = task_path.read_text(encoding="utf-8") if task_path.exists() else ""
    rat_text = rat_path.read_text(encoding="utf-8") if rat_path.exists() else ""

    domain_bullets = extract_section_bullets(snap_text, "プロダクト基本前提", 3)
    constraint_bullets = extract_section_bullets(snap_text, "絶対遵守", 3)
    anti_reg_bullets = extract_section_bullets(snap_text, "ボツ案・先祖返り禁止", 5)
    learned_bullets = extract_section_bullets(snap_text, "学習済みプロジェクト固有", 4)

    # タスクの未完了項目と引き継ぎメモを抽出
    unchecked_tasks = [
        ln for ln in task_text.splitlines() if ln.strip().startswith("- [ ]")
    ][:4]
    handoff_memo = extract_section_bullets(task_text, "Handoff Memo", 3)

    # 直近採用した設計根拠の1行抽出
    adopted_lines = [
        ln for ln in rat_text.splitlines()
        if "最終採用アプローチ" in ln and "未実行" not in ln and "ここに" not in ln
    ][:1]

    recent_files = detect_recent_files(project_root, hours=24.0, limit=5)
    git_dirty = detect_git_dirty_files(project_root, limit=5)

    lines: List[str] = [
        "# 🔄 Post-Compact 強制引き継ぎカプセル（最優先遵守）",
        "※コンテキスト要約文よりも以下の確定事実・禁止事項を最優先し、先祖返りを起こすな。",
        "",
        "## 1. 確定前提・ルール",
        *(domain_bullets[:2] + constraint_bullets[:2] + learned_bullets[:3] or ["- `.brain/DECISIONS_SNAPSHOT.md` 参照"]),
    ]

    if anti_reg_bullets:
        lines.extend(["", "## 2. 🚫 ボツ案・先祖返り禁止リスト（再提案厳禁）", *anti_reg_bullets])

    lines.extend([
        "",
        "## 3. 現在進行中のタスク・次の一手",
        *(handoff_memo + unchecked_tasks or ["- `.brain/current_task.md` を確認して再開"]),
    ])

    if adopted_lines:
        lines.extend(["", "## 4. 直近の設計採用根拠", *adopted_lines])

    file_summary = recent_files or git_dirty
    if file_summary:
        lines.extend([
            "",
            "## 5. 直近編集中のファイル",
            "- " + ", ".join(file_summary[:5]),
        ])

    content = "\n".join(lines).rstrip() + "\n"
    out_path = brain_dir / "workspace" / "compact_handover.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return content


def handle_agy_pre_hook(project_root: Path, brain_dir: Path) -> int:
    """
    Antigravity PreInvocation フック処理:
    - 会話ステップ数 (initialNumSteps) が前回より減少した瞬間（= /compact 実行直後）を自動検知
    - またはユーザーが明示的な再開ワードを投げた瞬間のみ引き継ぎカプセルを1ターン注入
    - 通常ターンは {} を返して追加トークン 0 を維持
    """
    raw_in = ""
    try:
        if not sys.stdin.isatty():
            raw_in = sys.stdin.read()
    except Exception:
        pass

    payload: Dict[str, Any] = {}
    if raw_in.strip():
        try:
            payload = json.loads(raw_in)
        except Exception:
            payload = {}

    conv_id = str(payload.get("conversationId", "default"))
    cur_steps = payload.get("initialNumSteps")
    inv_num = int(payload.get("invocationNum", 1) or 1)
    user_input = str(payload.get("lastUserInput", ""))

    state_file = brain_dir / "workspace" / ".hook_state.json"
    state = load_json(state_file, {"conversations": {}})
    convs: Dict[str, Any] = state.setdefault("conversations", {})

    prev_info = convs.get(conv_id, {})
    prev_steps = prev_info.get("last_steps")

    compact_detected = False
    if isinstance(cur_steps, int) and isinstance(prev_steps, int):
        # ステップ数が前回より減っていれば /compact が実行されたと判定
        if cur_steps < prev_steps:
            compact_detected = True

    keyword_triggered = (
        inv_num == 1 and any(kw in user_input for kw in RECOVERY_KEYWORDS)
    )

    if isinstance(cur_steps, int):
        convs[conv_id] = {
            "last_steps": cur_steps,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        # 古い会話IDが増えすぎないよう最新20件のみ保持
        if len(convs) > 20:
            oldest_keys = list(convs.keys())[:-20]
            for k in oldest_keys:
                convs.pop(k, None)
        save_json(state_file, state)

    if not (compact_detected or keyword_triggered):
        print("{}")
        return 0

    handover = build_compact_handover(project_root, brain_dir)
    out = {"injectSteps": [{"ephemeralMessage": handover}]}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Portable Brain `/compact` ゼロ健忘症・引き継ぎカプセル管理 CLI"
    )
    parser.add_argument("--target", type=str, default="", help="対象プロジェクトパス")
    parser.add_argument(
        "--save",
        action="store_true",
        help="引き継ぎカプセル (.brain/workspace/compact_handover.md) を生成更新する",
    )
    parser.add_argument(
        "--claude-precompact",
        action="store_true",
        help="Claude Code PreCompact フック用（無音で最新状態をファイル退避する）",
    )
    parser.add_argument(
        "--claude-postcompact",
        action="store_true",
        help="Claude Code SessionStart(compact) フック用（圧縮直後に stdout へカプセルを注入）",
    )
    parser.add_argument(
        "--agy-pre",
        action="store_true",
        help="Antigravity PreInvocation フック用（/compact 直後のみ自動注入・通常0tok）",
    )
    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="通常実行時のクリップボードコピーを抑止する",
    )

    args = parser.parse_args()
    brain_dir = (
        Path(args.target).resolve() / ".brain"
        if args.target
        else Path(__file__).resolve().parent.parent
    )
    project_root = brain_dir.parent

    if not brain_dir.exists():
        if args.agy_pre:
            print("{}")
        return 0

    if args.claude_precompact:
        build_compact_handover(project_root, brain_dir)
        # PreCompact では stdout に何も出さないのが Claude Code 公式仕様
        return 0

    if args.claude_postcompact:
        handover_path = brain_dir / "workspace" / "compact_handover.md"
        if handover_path.exists():
            content = handover_path.read_text(encoding="utf-8")
        else:
            content = build_compact_handover(project_root, brain_dir)
        # SessionStart(compact) の stdout は圧縮直後の Claude コンテキストへ直接注入される
        sys.stdout.write(content)
        return 0

    if args.agy_pre:
        return handle_agy_pre_hook(project_root, brain_dir)

    # 手動実行または Cursor / Windsurf / Grok 向けチェックポイント作成
    content = build_compact_handover(project_root, brain_dir)
    copied = False if (args.no_clipboard or args.save) else copy_to_clipboard(content)
    clip_msg = "（クリップボードへコピー済）" if copied else ""
    print(
        f"[✓] `/compact` 引き継ぎカプセルを更新しました: "
        f"{brain_dir / 'workspace' / 'compact_handover.md'} {clip_msg}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
