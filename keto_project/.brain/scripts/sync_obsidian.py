#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portable Brain Engine - Obsidian Vault Two-Way Sync CLI (sync_obsidian.py)
Gemini Notebook (NotebookLM) にはアップロードせず、Obsidian Vault (C:\\Obsidian\\LLM Folder)
との間でのみ「省トークン双方向連携」を行う専用スクリプト。

1. --push-archive : 長大な議論・ボツ案・詳細仕様をローカル(.brain)からObsidian外部アーカイブへオフロード
2. --mirror-state : 現在の確定仕様 (DECISIONS_SNAPSHOT.md) の最新状態を 01_Inbox / Projects へ軽量同期
3. --pull-search   : Obsidian内の全プロジェクト知見からピンポイントで数行だけを検索・抽出（トークン浪費ゼロ）
4. --pull-import   : Obsidianで見つかった重要ルールを .brain/questions/ の該当モジュールへ1行圧縮取り込み
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_VAULT_ROOT = Path(r"C:\Obsidian\LLM Folder")


def resolve_vault_root(custom_path: str = "") -> Path:
    if custom_path:
        return Path(custom_path).resolve()
    return DEFAULT_VAULT_ROOT


def estimate_tokens(text: str) -> int:
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    return int(ascii_chars * 0.28 + non_ascii * 0.65)


def push_archive_to_obsidian(project_root: Path, brain_dir: Path, vault_root: Path) -> Path | None:
    """
    ローカルの .brain の長大化を防ぐため、詳細な設計根拠や過去の決定事項を
    Obsidian Vault の '02_Projects/<プロジェクト名>/Brain_Archives/' へ日付付きで保管する。
    """
    if not vault_root.exists():
        print(f"[!] Obsidian Vault が見つかりません: {vault_root}", file=sys.stderr)
        return None

    dest_dir = vault_root / "02_Projects" / project_root.name / "Brain_Archives"
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_file = dest_dir / f"brain_state_{timestamp}.md"

    snap_file = brain_dir / "DECISIONS_SNAPSHOT.md"
    task_file = brain_dir / "current_task.md"
    rat_file = brain_dir / "workspace" / "latest_rationale.md"

    snap_text = snap_file.read_text(encoding="utf-8") if snap_file.exists() else ""
    task_text = task_file.read_text(encoding="utf-8") if task_file.exists() else ""
    rat_text = rat_file.read_text(encoding="utf-8") if rat_file.exists() else ""

    md_content = (
        f"---\n"
        f"project: \"{project_root.name}\"\n"
        f"archived_at: \"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\"\n"
        f"tags:\n"
        f"  - portable-brain/archive\n"
        f"  - project/{project_root.name}\n"
        f"---\n\n"
        f"# 🧠 Portable Brain Archive: {project_root.name}\n"
        f"- **保管元パス**: `{project_root}`\n"
        f"- **保管日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"---\n\n"
        f"## 1. 確定仕様スナップショット\n\n{snap_text}\n\n"
        f"---\n\n"
        f"## 2. タスク進行状態\n\n{task_text}\n\n"
        f"---\n\n"
        f"## 3. 直近の設計・思考根拠\n\n{rat_text}\n"
    )

    archive_file.write_text(md_content, encoding="utf-8")
    print(f"[✓] Obsidian Vault へ詳細アーカイブを保存しました: {archive_file}")
    return archive_file


def mirror_state_to_obsidian(project_root: Path, brain_dir: Path, vault_root: Path) -> Path | None:
    """
    最新の確定仕様（DECISIONS_SNAPSHOT.md）を、Obsidian の
    '01_Inbox/auto_decisions_latest.md' および '02_Projects/<プロジェクト名>/DECISIONS_SNAPSHOT.md'
    へ自動ミラーリングする。
    """
    if not vault_root.exists():
        return None

    snap_file = brain_dir / "DECISIONS_SNAPSHOT.md"
    if not snap_file.exists():
        return None

    snap_text = snap_file.read_text(encoding="utf-8")

    # 1) プロジェクト個別フォルダへミラー
    proj_dir = vault_root / "02_Projects" / project_root.name
    proj_dir.mkdir(parents=True, exist_ok=True)
    proj_dest = proj_dir / "DECISIONS_SNAPSHOT.md"
    proj_dest.write_text(snap_text, encoding="utf-8")

    # 2) 01_Inbox/auto_decisions_latest.md にも最新プロジェクトとして同期
    inbox_dest = vault_root / "01_Inbox" / "auto_decisions_latest.md"
    inbox_dest.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"<!-- Synced by Portable Brain from {project_root.name} at "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} -->\n"
    )
    inbox_dest.write_text(header + snap_text, encoding="utf-8")

    print(f"[✓] Obsidian 側の確定仕様を更新しました: {proj_dest}")
    return proj_dest


def search_obsidian_knowledge(
    vault_root: Path, keyword: str, context_lines: int = 2, max_results: int = 5
) -> List[Dict[str, Any]]:
    """
    Obsidian Vault 内の全Markdownファイルから、指定キーワードに合致する箇所を
    前後2行のコンテキスト付きでピンポイント抽出する（巨大ファイルを丸読みせずトークン極小）。
    """
    if not vault_root.exists():
        print(f"[!] Obsidian Vault が見つかりません: {vault_root}", file=sys.stderr)
        return []

    search_dirs = [
        vault_root / "01_Inbox",
        vault_root / "02_Projects",
        vault_root / "04_Outputs",
        vault_root / "Antigravity スキル一覧",
    ]

    target_files: List[Path] = []
    for sdir in search_dirs:
        if sdir.exists():
            target_files.extend(sdir.rglob("*.md"))

    matches: List[Dict[str, Any]] = []
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)

    for fpath in target_files:
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        for idx, line in enumerate(lines):
            if pattern.search(line):
                start = max(0, idx - context_lines)
                end = min(len(lines), idx + context_lines + 1)
                context_snippet = "\n".join(
                    f"  {lines[i]}" if i != idx else f"> {lines[i]}"
                    for i in range(start, end)
                )
                rel_path = fpath.relative_to(vault_root).as_posix()
                matches.append({
                    "file": rel_path,
                    "line_number": idx + 1,
                    "match_line": line.strip(),
                    "snippet": context_snippet,
                })
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break

    return matches


def import_rule_to_brain(brain_dir: Path, rule_text: str, q_target: str) -> bool:
    """Obsidianから見つかった有益な知見を .brain の該当問いファイルへ1行上書き圧縮登録する"""
    sync_web_py = brain_dir / "scripts" / "sync_web.py"
    if not sync_web_py.exists():
        return False
    import subprocess
    res = subprocess.run(
        [sys.executable, str(sync_web_py), "--learn", rule_text, "--q", q_target, "--no-clipboard"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return res.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Portable Brain - Obsidian Vault 専用省トークン双方向同期 CLI"
    )
    parser.add_argument("--target", type=str, default="", help="対象プロジェクトパス")
    parser.add_argument("--vault", type=str, default="", help="Obsidian Vaultルートパス（既定: C:\\Obsidian\\LLM Folder）")
    parser.add_argument(
        "--push-archive",
        action="store_true",
        help="詳細な思考履歴・ボツ案を Obsidian (02_Projects) へアーカイブ退避する",
    )
    parser.add_argument(
        "--mirror-state",
        action="store_true",
        help="最新の確定仕様 (DECISIONS_SNAPSHOT.md) を Obsidian 側へミラーリングする",
    )
    parser.add_argument(
        "--search",
        type=str,
        default="",
        metavar="KEYWORD",
        help="Obsidian Vault から過去知見をピンポイント検索する（省トークン抽出）",
    )
    parser.add_argument(
        "--import-rule",
        type=str,
        default="",
        metavar="RULE_TEXT",
        help="検索した知見を .brain へ1行圧縮取り込みする（--q と併用）",
    )
    parser.add_argument(
        "--q",
        type=str,
        default="snapshot",
        help="--import-rule 時の反映先 (q01..q05 または snapshot/reject)",
    )

    args = parser.parse_args()
    brain_dir = (
        Path(args.target).resolve() / ".brain"
        if args.target
        else Path(__file__).resolve().parent.parent
    )
    project_root = brain_dir.parent
    vault_root = resolve_vault_root(args.vault)

    executed = False

    if args.push_archive:
        push_archive_to_obsidian(project_root, brain_dir, vault_root)
        executed = True

    if args.mirror_state:
        mirror_state_to_obsidian(project_root, brain_dir, vault_root)
        executed = True

    if args.import_rule:
        ok = import_rule_to_brain(brain_dir, args.import_rule, args.q)
        if ok:
            print(f"[✓] Obsidian の知見を .brain へ取り込みました: {args.import_rule}")
        executed = True

    if args.search:
        results = search_obsidian_knowledge(vault_root, args.search)
        print(f"=== Obsidian 知見ピンポイント検索結果: '{args.search}' ===")
        if not results:
            print("  一致するナレッジは見つかりませんでした。")
        else:
            total_tok = 0
            for r in results:
                tok = estimate_tokens(r["snippet"])
                total_tok += tok
                print(f"\n📄 [{r['file']} : L{r['line_number']}] (約 {tok} tok)")
                print(r["snippet"])
            print(f"\n📊 取得合計トークン: 約 {total_tok} tok （ファイル丸読みせず極小抽出完了）")
        executed = True

    if not executed:
        # デフォルト動作: 最新ステートのミラー同期
        mirror_state_to_obsidian(project_root, brain_dir, vault_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
