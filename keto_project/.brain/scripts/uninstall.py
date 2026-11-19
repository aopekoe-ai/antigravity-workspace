#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portable Brain Engine - Clean Eject, Disable/Enable & Restore CLI (uninstall.py)
システムを使いたくなくなった時や一時停止したい時に、成果物コードを一切傷つけず
安全に元の状態へ戻す（または知見をObsidianへアーカイブ退避する）スクリプト。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ACTIVE_BLOCK_PATTERN = re.compile(
    r"<!-- PORTABLE-BRAIN:START -->.*?<!-- PORTABLE-BRAIN:END -->\n?",
    re.DOTALL,
)
DISABLED_STUB = (
    "<!-- PORTABLE-BRAIN:DISABLED "
    "(再開: python .brain/scripts/uninstall.py --enable) -->\n"
)
DISABLED_PATTERN = re.compile(
    r"<!-- PORTABLE-BRAIN:DISABLED[^>]*-->\n?", re.MULTILINE
)


def resolve_brain_dir(target_arg: str) -> Path:
    if target_arg:
        return Path(target_arg).resolve() / ".brain"
    return Path(__file__).resolve().parent.parent


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def encode_backup_name(rel_path: str) -> str:
    normalized = rel_path.replace("\\", "/").lstrip("/")
    return normalized.replace("/", "__") + ".bak"


def cleanup_empty_parents(file_path: Path, stop_at: Path) -> None:
    curr = file_path.parent
    while curr != stop_at and stop_at in curr.parents:
        try:
            if curr.exists() and not any(curr.iterdir()):
                curr.rmdir()
                curr = curr.parent
            else:
                break
        except OSError:
            break


def force_remove_readonly(func: Any, path: str, _: Any) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def strip_claude_brain_hooks(data: Dict[str, Any]) -> Dict[str, Any]:
    """Claude settings.json から Portable Brain のフック定義のみを安全に除去する"""
    hooks_obj = data.get("hooks")
    if not isinstance(hooks_obj, dict):
        return data
    for event_name in list(hooks_obj.keys()):
        groups = hooks_obj.get(event_name, [])
        if isinstance(groups, list):
            filtered = [
                g
                for g in groups
                if ".brain/scripts/checkpoint.py" not in json.dumps(g)
            ]
            if filtered:
                hooks_obj[event_name] = filtered
            else:
                hooks_obj.pop(event_name, None)
    if not hooks_obj:
        data.pop("hooks", None)
    return data


def set_disabled_state(project_root: Path, brain_dir: Path, disable: bool) -> int:
    manifest_path = brain_dir / "manifest.json"
    if not manifest_path.exists():
        print("[!] manifest.json が見つかりません。先に setup_brain.py を実行してください。", file=sys.stderr)
        return 1

    manifest = load_json(manifest_path, {})
    registry = load_json(brain_dir / "ai_registry.json", {"adapters": {}})
    adapters = registry.get("adapters", {})
    tracked_files: Dict[str, Any] = manifest.get("files", {})

    tmpl_text = (brain_dir / "templates" / "adapter_common.md.tmpl").read_text(
        encoding="utf-8"
    )
    claude_tmpl = load_json(brain_dir / "templates" / "claude_hooks.json.tmpl", {})

    for rel_path, meta in tracked_files.items():
        if rel_path.startswith(".brain/"):
            continue
        ai_key = meta.get("ai", "")
        ai_label = adapters.get(ai_key, {}).get("label", ai_key)
        target = project_root / rel_path

        if rel_path == ".agents/hooks.json" and target.exists():
            hooks_data = load_json(target, {})
            if "portable-brain-gate" in hooks_data:
                hooks_data["portable-brain-gate"]["enabled"] = not disable
                save_json(target, hooks_data)
            continue

        if rel_path == ".claude/settings.json" and target.exists():
            cdata = load_json(target, {})
            cdata = strip_claude_brain_hooks(cdata)
            if not disable:
                hooks_obj = cdata.setdefault("hooks", {})
                for ev, groups in claude_tmpl.get("hooks", {}).items():
                    cur: List[Any] = hooks_obj.get(ev, [])
                    cur.extend(groups)
                    hooks_obj[ev] = cur
            save_json(target, cdata)
            continue

        if rel_path in {
            ".agents/rules/brain-adapter.md",
            ".agents/skills/portable-brain/SKILL.md",
        }:
            disabled_path = project_root / (rel_path + ".disabled")
            if disable and target.exists():
                target.replace(disabled_path)
            elif not disable and disabled_path.exists():
                disabled_path.replace(target)
            continue

        if disable and target.exists():
            content = target.read_text(encoding="utf-8")
            updated = ACTIVE_BLOCK_PATTERN.sub(DISABLED_STUB, content)
            target.write_text(updated, encoding="utf-8")
        elif not disable and target.exists():
            block = tmpl_text.replace("{{AI_LABEL}}", ai_label).strip() + "\n"
            content = target.read_text(encoding="utf-8")
            if DISABLED_PATTERN.search(content):
                updated = DISABLED_PATTERN.sub(block, content)
            elif not ACTIVE_BLOCK_PATTERN.search(content):
                updated = content.rstrip() + "\n\n" + block
            else:
                updated = content
            target.write_text(updated, encoding="utf-8")

    manifest["enabled"] = not disable
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_json(manifest_path, manifest)

    if disable:
        print("⏸️  Portable Brain を一時停止しました（コンテキスト消費ゼロ・知見データは保持）。")
        print("   再開するには: python .brain/scripts/uninstall.py --enable")
    else:
        print("▶️  Portable Brain を再開しました！すべての導入済みAIアダプターが有効です。")
    return 0


def restore_and_remove_adapters(project_root: Path, brain_dir: Path) -> None:
    manifest = load_json(brain_dir / "manifest.json", {})
    tracked_files: Dict[str, Any] = manifest.get("files", {})
    backup_dir = brain_dir / ".backups"

    for rel_path, meta in tracked_files.items():
        if rel_path.startswith(".brain/"):
            continue

        mode = meta.get("mode", "created")
        target = project_root / rel_path
        disabled_target = project_root / (rel_path + ".disabled")

        if disabled_target.exists():
            disabled_target.unlink()

        if mode == "created":
            if target.exists():
                target.unlink()
            cleanup_empty_parents(target, project_root)

        elif mode == "json_merged":
            bak_file = backup_dir / encode_backup_name(rel_path)
            if target.exists():
                data = load_json(target, {})
                data.pop("portable-brain-gate", None)
                if data:
                    save_json(target, data)
                elif bak_file.exists():
                    shutil.copy2(bak_file, target)
                else:
                    target.unlink()
                    cleanup_empty_parents(target, project_root)

        elif mode == "claude_json_merged":
            bak_file = backup_dir / encode_backup_name(rel_path)
            if target.exists():
                data = strip_claude_brain_hooks(load_json(target, {}))
                if data:
                    save_json(target, data)
                elif bak_file.exists():
                    shutil.copy2(bak_file, target)
                else:
                    target.unlink()
                    cleanup_empty_parents(target, project_root)

        elif mode == "injected":
            if target.exists():
                content = target.read_text(encoding="utf-8")
                cleaned = ACTIVE_BLOCK_PATTERN.sub("", content)
                cleaned = DISABLED_PATTERN.sub("", cleaned)
                bak_file = backup_dir / encode_backup_name(rel_path)
                if not cleaned.strip() and bak_file.exists():
                    shutil.copy2(bak_file, target)
                else:
                    target.write_text(cleaned.rstrip() + "\n", encoding="utf-8")


def archive_to_obsidian(project_root: Path, brain_dir: Path, custom_vault: str) -> Path:
    registry = load_json(brain_dir / "ai_registry.json", {})
    default_vault = registry.get(
        "obsidian_archive_root",
        r"C:\Obsidian\LLM Folder\04_PortableBrain_Archives",
    )
    vault_base = Path(custom_vault) if custom_vault else Path(default_vault)

    if not custom_vault and not Path(r"C:\Obsidian").exists():
        vault_base = project_root.parent / "_portable_brain_archives"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = vault_base / f"{project_root.name}_{timestamp}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    for item in brain_dir.rglob("*"):
        rel = item.relative_to(brain_dir)
        if any(p in {".backups", "__pycache__", ".hook_state.json"} for p in rel.parts):
            continue
        dest = archive_dir / ".brain" / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    summary_md = (
        f"# Portable Brain Eject Archive: {project_root.name}\n"
        f"- **退避日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **元プロジェクトパス**: `{project_root}`\n"
        f"- **再導入コマンド**:\n"
        f"  ```powershell\n"
        f'  python "{archive_dir / ".brain" / "scripts" / "setup_brain.py"}" --target "{project_root}"\n'
        f"  ```\n"
    )
    (archive_dir / "ARCHIVE_SUMMARY.md").write_text(summary_md, encoding="utf-8")
    return archive_dir


def remove_brain_directory(brain_dir: Path) -> None:
    project_root = brain_dir.parent
    try:
        if Path.cwd().resolve().is_relative_to(brain_dir.resolve()):
            os.chdir(project_root)
    except Exception:
        pass
    shutil.rmtree(brain_dir, onerror=force_remove_readonly)


def show_status(project_root: Path, brain_dir: Path) -> int:
    manifest_path = brain_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"[状態] {project_root.name}: アダプター未配備（コアのみ存在）")
        return 0
    manifest = load_json(manifest_path, {})
    enabled = manifest.get("enabled", True)
    ais = ", ".join(manifest.get("installed_ais", [])) or "なし"
    print(f"=== Portable Brain ステータス ({project_root.name}) ===")
    print(f"  稼働状態   : {'🟢 有効 (ACTIVE)' if enabled else '⏸️ 一時停止中 (DISABLED)'}")
    print(f"  連携済みAI : {ais}")
    print(f"  管理対象数 : {len(manifest.get('files', {}))} ファイル")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Portable Brain 安全リセット・一時停止・Obsidian退避 CLI"
    )
    parser.add_argument("--target", type=str, default="", help="対象プロジェクトのルートパス")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="現在の稼働状態を表示する")
    group.add_argument("--disable", action="store_true", help="システムを一時停止する")
    group.add_argument("--enable", action="store_true", help="一時停止したシステムを再開する")
    group.add_argument(
        "--eject",
        action="store_true",
        help="プロジェクトをプレーンに戻し、知見はObsidianへ安全退避する（推奨）",
    )
    group.add_argument("--purge", action="store_true", help="導入前の状態へ完全リセットする")
    parser.add_argument("--vault-dir", type=str, default="", help="--eject 時の退避先パス指定")

    args = parser.parse_args()
    brain_dir = resolve_brain_dir(args.target)
    project_root = brain_dir.parent

    if not brain_dir.exists():
        print(f"[!] {brain_dir} が存在しません。", file=sys.stderr)
        return 1

    if args.status:
        return show_status(project_root, brain_dir)
    if args.disable:
        return set_disabled_state(project_root, brain_dir, disable=True)
    if args.enable:
        return set_disabled_state(project_root, brain_dir, disable=False)

    if args.eject:
        archive_path = archive_to_obsidian(project_root, brain_dir, args.vault_dir)
        restore_and_remove_adapters(project_root, brain_dir)
        remove_brain_directory(brain_dir)
        print(f"📦 知見・ルール一式を退避しました: {archive_path}")
        print(f"✨ プロジェクト '{project_root.name}' を完全にプレーンな状態へ戻しました（成果物コードは無傷です）。")
        return 0

    if args.purge:
        restore_and_remove_adapters(project_root, brain_dir)
        remove_brain_directory(brain_dir)
        print(f"🧹 Portable Brain を完全削除し、'{project_root.name}' を導入前の状態へ復元しました。")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
