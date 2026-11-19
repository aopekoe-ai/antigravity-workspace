#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portable Brain Engine - Universal AI Onboarding & Setup CLI (setup_brain.py)
各AIサービス（Antigravity, Claude Code [+Compact Hooks], Cursor, Windsurf, Codex, Grok/Web等）の
アダプター設定をワンコマンドで安全に配備・追加登録するスクリプト。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

MARKER_START = "<!-- PORTABLE-BRAIN:START -->"
MARKER_END = "<!-- PORTABLE-BRAIN:END -->"
DISABLED_PATTERN = re.compile(
    r"<!-- PORTABLE-BRAIN:DISABLED[^>]*-->\n?", re.MULTILINE
)
ACTIVE_BLOCK_PATTERN = re.compile(
    r"<!-- PORTABLE-BRAIN:START -->.*?<!-- PORTABLE-BRAIN:END -->\n?",
    re.DOTALL,
)


def resolve_source_brain_dir() -> Path:
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


def ensure_backup(project_root: Path, brain_dir: Path, rel_path: str) -> None:
    target_file = project_root / rel_path
    if not target_file.exists():
        return
    backup_dir = brain_dir / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / encode_backup_name(rel_path)
    if not backup_file.exists():
        shutil.copy2(target_file, backup_file)


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
        elif sys.platform == "darwin":
            proc = subprocess.run(
                ["pbcopy"], input=text.encode("utf-8"), check=False
            )
            return proc.returncode == 0
    except Exception:
        return False
    return False


def deploy_brain_core_if_needed(source_brain: Path, target_root: Path) -> Path:
    target_brain = target_root / ".brain"
    if source_brain.resolve() == target_brain.resolve():
        return target_brain

    target_root.mkdir(parents=True, exist_ok=True)
    skip_names = {
        ".backups",
        "manifest.json",
        "__pycache__",
        "web_bootstrap_prompt.md",
        ".hook_state.json",
    }

    for item in source_brain.rglob("*"):
        rel = item.relative_to(source_brain)
        if any(part in skip_names for part in rel.parts):
            continue
        dest = target_brain / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            if dest.exists() and rel.as_posix() in {
                "DECISIONS_SNAPSHOT.md",
                "current_task.md",
            }:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    print(f"[✓] コアエンジンを配備しました: {target_brain}")
    return target_brain


def render_common_adapter(brain_dir: Path, ai_label: str) -> str:
    tmpl_path = brain_dir / "templates" / "adapter_common.md.tmpl"
    tmpl = tmpl_path.read_text(encoding="utf-8")
    return tmpl.replace("{{AI_LABEL}}", ai_label).strip() + "\n"


def install_markdown_adapter(
    project_root: Path,
    brain_dir: Path,
    manifest: Dict[str, Any],
    rel_path: str,
    ai_key: str,
    ai_label: str,
) -> None:
    target_path = project_root / rel_path
    block = render_common_adapter(brain_dir, ai_label)
    tracked_files: Dict[str, Any] = manifest.setdefault("files", {})

    if not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(block, encoding="utf-8")
        tracked_files[rel_path] = {
            "ai": ai_key,
            "mode": "created",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        return

    if rel_path not in tracked_files:
        ensure_backup(project_root, brain_dir, rel_path)
        mode = "injected"
    else:
        mode = tracked_files[rel_path].get("mode", "injected")

    existing = target_path.read_text(encoding="utf-8")
    existing = DISABLED_PATTERN.sub("", existing)

    if ACTIVE_BLOCK_PATTERN.search(existing):
        updated = ACTIVE_BLOCK_PATTERN.sub(block, existing)
    else:
        sep = (
            ""
            if (not existing or existing.endswith("\n\n"))
            else ("\n" if existing.endswith("\n") else "\n\n")
        )
        updated = existing + sep + block

    target_path.write_text(updated, encoding="utf-8")
    tracked_files[rel_path] = {
        "ai": ai_key,
        "mode": mode,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def merge_claude_hooks_config(existing: Dict[str, Any], tmpl: Dict[str, Any]) -> Dict[str, Any]:
    """既存の .claude/settings.json 設定を壊さずに PreCompact / SessionStart(compact) をマージする"""
    hooks_obj = existing.setdefault("hooks", {})
    tmpl_hooks = tmpl.get("hooks", {})
    for event_name, new_groups in tmpl_hooks.items():
        cur_groups: List[Any] = hooks_obj.get(event_name, [])
        # 既存の Portable Brain エントリを一旦除去して重複を防止
        filtered = [
            g
            for g in cur_groups
            if ".brain/scripts/checkpoint.py" not in json.dumps(g)
        ]
        filtered.extend(new_groups)
        hooks_obj[event_name] = filtered
    return existing


def install_claude_bundle(
    project_root: Path,
    brain_dir: Path,
    manifest: Dict[str, Any],
    ai_label: str,
) -> None:
    """Claude Code 用の CLAUDE.md + /compact 自動引き継ぎフック (.claude/settings.json) を配備する"""
    tracked_files: Dict[str, Any] = manifest.setdefault("files", {})

    # 1) CLAUDE.md
    install_markdown_adapter(
        project_root, brain_dir, manifest, "CLAUDE.md", "claude", ai_label
    )

    # 2) .claude/settings.json
    settings_rel = ".claude/settings.json"
    settings_target = project_root / settings_rel
    claude_tmpl = load_json(
        brain_dir / "templates" / "claude_hooks.json.tmpl", {}
    )

    if not settings_target.exists():
        save_json(settings_target, claude_tmpl)
        tracked_files[settings_rel] = {
            "ai": "claude",
            "mode": "created",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    else:
        if settings_rel not in tracked_files:
            ensure_backup(project_root, brain_dir, settings_rel)
            mode = "claude_json_merged"
        else:
            mode = tracked_files[settings_rel].get("mode", "claude_json_merged")
        cur_data = load_json(settings_target, {})
        merged = merge_claude_hooks_config(cur_data, claude_tmpl)
        save_json(settings_target, merged)
        tracked_files[settings_rel] = {
            "ai": "claude",
            "mode": mode,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }


def install_antigravity_bundle(
    project_root: Path,
    brain_dir: Path,
    manifest: Dict[str, Any],
    ai_label: str,
) -> None:
    tracked_files: Dict[str, Any] = manifest.setdefault("files", {})

    rule_rel = ".agents/rules/brain-adapter.md"
    disabled_rule = project_root / (rule_rel + ".disabled")
    if disabled_rule.exists():
        disabled_rule.unlink()
    install_markdown_adapter(
        project_root, brain_dir, manifest, rule_rel, "antigravity", ai_label
    )

    skill_rel = ".agents/skills/portable-brain/SKILL.md"
    disabled_skill = project_root / (skill_rel + ".disabled")
    if disabled_skill.exists():
        disabled_skill.unlink()
    skill_target = project_root / skill_rel
    skill_tmpl = (brain_dir / "templates" / "antigravity_skill.md.tmpl").read_text(
        encoding="utf-8"
    )
    if skill_target.exists() and skill_rel not in tracked_files:
        ensure_backup(project_root, brain_dir, skill_rel)
        skill_mode = "injected"
    else:
        skill_mode = tracked_files.get(skill_rel, {}).get("mode", "created")
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    skill_target.write_text(skill_tmpl, encoding="utf-8")
    tracked_files[skill_rel] = {
        "ai": "antigravity",
        "mode": skill_mode,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

    hooks_rel = ".agents/hooks.json"
    hooks_target = project_root / hooks_rel
    hooks_tmpl = load_json(
        brain_dir / "templates" / "antigravity_hooks.json.tmpl", {}
    )
    if not hooks_target.exists():
        save_json(hooks_target, hooks_tmpl)
        tracked_files[hooks_rel] = {
            "ai": "antigravity",
            "mode": "created",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    else:
        if hooks_rel not in tracked_files:
            ensure_backup(project_root, brain_dir, hooks_rel)
            hooks_mode = "json_merged"
        else:
            hooks_mode = tracked_files[hooks_rel].get("mode", "json_merged")
        current_hooks = load_json(hooks_target, {})
        current_hooks.update(hooks_tmpl)
        save_json(hooks_target, current_hooks)
        tracked_files[hooks_rel] = {
            "ai": "antigravity",
            "mode": hooks_mode,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }


def generate_web_bootstrap(
    project_root: Path,
    brain_dir: Path,
    manifest: Dict[str, Any],
    use_clipboard: bool,
) -> bool:
    snapshot_text = (brain_dir / "DECISIONS_SNAPSHOT.md").read_text(encoding="utf-8")
    task_text = (brain_dir / "current_task.md").read_text(encoding="utf-8")

    snap_lines = [ln for ln in snapshot_text.splitlines() if ln.startswith("- ")][:6]
    task_lines = [ln for ln in task_text.splitlines() if ln.startswith("- ")][:8]

    web_prompt = (
        "# Portable Brain Bootstrap (Grok / ChatGPT / Web AI用)\n"
        "以下の共通思考プロトコルに従って私の依頼を実行してください：\n"
        "1. 【前提補完 & /compact耐性】下記の現在ステートとボツ案リストを最優先遵守し、不足前提を自力補完してタスク分解する（重大分岐のみ推奨付き2択質問）。\n"
        "2. 【5段階思考】いきなり最終案を出さず、①要求整理 → ②OOUI情報優先度(Primary/Secondary/Tertiary) → "
        "③異なる探索軸での3案発散と比較根拠 → ④境界値(0件/読込中/エラー/長文)込みの本実装 → ⑤自己監査(85点基準)の順で出力する。\n\n"
        "## 現在のプロジェクト前提\n"
        + ("\n".join(snap_lines) if snap_lines else "- 初期状態")
        + "\n\n## 現在のタスク進行状態\n"
        + ("\n".join(task_lines) if task_lines else "- 新規依頼待ち")
        + "\n"
    )

    rel_path = ".brain/web_bootstrap_prompt.md"
    out_path = project_root / rel_path
    out_path.write_text(web_prompt, encoding="utf-8")
    manifest.setdefault("files", {})[rel_path] = {
        "ai": "web",
        "mode": "created",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if use_clipboard:
        return copy_to_clipboard(web_prompt)
    return False


def configure_local_git_exclude(project_root: Path) -> None:
    """チーム開発等で .gitignore を汚さずローカルのGit管理から .brain 等を隠したい場合の設定"""
    exclude_file = project_root / ".git" / "info" / "exclude"
    if not exclude_file.parent.exists():
        return
    existing = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
    marker = "# PORTABLE-BRAIN-LOCAL-EXCLUDE"
    if marker in existing:
        return
    block = (
        f"\n{marker}\n"
        ".brain/\n"
        ".agents/rules/brain-adapter.md*\n"
        ".agents/skills/portable-brain/\n"
    )
    exclude_file.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
    print("[✓] .git/info/exclude にローカル除外ルールを登録しました。")


def detect_default_ais(project_root: Path) -> List[str]:
    detected: List[str] = ["antigravity", "web"]
    if (project_root / "CLAUDE.md").exists() or (project_root / ".claude").exists():
        detected.append("claude")
    if (project_root / ".cursorrules").exists() or (project_root / ".cursor").exists():
        detected.append("cursor")
    if (project_root / ".windsurfrules").exists():
        detected.append("windsurf")
    if (project_root / "AGENTS.md").exists():
        detected.append("codex")
    if len(detected) == 2:
        detected.append("claude")
    return detected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Portable Brain Engine セットアップ & 新AIオンボーディング CLI"
    )
    parser.add_argument("--target", type=str, default="", help="導入先プロジェクトのルートパス")
    parser.add_argument(
        "--add-ai",
        nargs="+",
        default=[],
        help="有効化するAI名（antigravity claude cursor windsurf codex copilot cline web または all）",
    )
    parser.add_argument("--register-ai", type=str, default="", help="新AIサービス名をレジストリへ登録する")
    parser.add_argument("--config-path", type=str, default="", help="--register-ai 時の設定ファイル相対パス")
    parser.add_argument("--label", type=str, default="", help="--register-ai 時の表示ラベル名")
    parser.add_argument("--list", action="store_true", help="登録済みAIサービス一覧と導入状態を表示する")
    parser.add_argument("--git-exclude", action="store_true", help=".git/info/exclude で .brain をローカル除外する")
    parser.add_argument("--no-clipboard", action="store_true", help="クリップボードコピーを抑止する")

    args = parser.parse_args()
    source_brain = resolve_source_brain_dir()

    if args.target:
        project_root = Path(args.target).resolve()
        brain_dir = deploy_brain_core_if_needed(source_brain, project_root)
    else:
        project_root = source_brain.parent
        brain_dir = source_brain

    registry_path = brain_dir / "ai_registry.json"
    manifest_path = brain_dir / "manifest.json"
    registry = load_json(registry_path, {"adapters": {}})
    adapters: Dict[str, Any] = registry.setdefault("adapters", {})
    manifest = load_json(
        manifest_path,
        {
            "installed_at": datetime.now().isoformat(timespec="seconds"),
            "enabled": True,
            "installed_ais": [],
            "files": {},
        },
    )

    if args.register_ai:
        ai_key = args.register_ai.strip().lower()
        if not args.config_path:
            print("[!] --register-ai を使う場合は --config-path <相対パス> を指定してください。", file=sys.stderr)
            return 1
        rel_cfg = args.config_path.replace("\\", "/").lstrip("/")
        adapters[ai_key] = {
            "label": args.label or f"{args.register_ai} Custom Agent",
            "type": "markdown_marker",
            "files": [rel_cfg],
        }
        save_json(registry_path, registry)
        print(f"[✓] 新AIサービス '{ai_key}' ({rel_cfg}) をレジストリに登録しました。")
        if ai_key not in args.add_ai:
            args.add_ai.append(ai_key)

    if args.list:
        installed_set = set(manifest.get("installed_ais", []))
        state_str = "有効 (ACTIVE)" if manifest.get("enabled", True) else "一時停止中 (DISABLED)"
        print(f"=== Portable Brain 導入状態 [{project_root.name}] : {state_str} ===")
        for key, spec in adapters.items():
            mark = "✅ 導入済" if key in installed_set else "⬜ 未導入"
            files_str = ", ".join(spec.get("files", []))
            print(f"  - {key:<12} [{mark}] : {spec.get('label')} -> {files_str}")
        return 0

    requested = [x.lower() for x in args.add_ai]
    if not requested:
        requested = detect_default_ais(project_root)
    elif "all" in requested:
        requested = list(adapters.keys())

    unknown = [x for x in requested if x not in adapters]
    if unknown:
        print(
            f"[!] 未登録のAI指定があります: {', '.join(unknown)}\n"
            f"    新サービスを追加する場合は --register-ai <名前> --config-path <設定パス> を指定してください。",
            file=sys.stderr,
        )
        return 1

    installed_ais = set(manifest.get("installed_ais", []))

    for ai_key in requested:
        spec = adapters[ai_key]
        ai_type = spec.get("type", "markdown_marker")
        ai_label = spec.get("label", ai_key)

        if ai_type == "antigravity_bundle":
            install_antigravity_bundle(project_root, brain_dir, manifest, ai_label)
            print(f"[✓] {ai_label}: .agents/ (Rule + Skill + Compact/Verify Hooks) を配備しました。")
        elif ai_type == "claude_bundle":
            install_claude_bundle(project_root, brain_dir, manifest, ai_label)
            print(f"[✓] {ai_label}: CLAUDE.md + .claude/settings.json (/compact 自動引き継ぎフック) を配備しました。")
        elif ai_type == "web_snippet":
            copied_clip = generate_web_bootstrap(
                project_root, brain_dir, manifest, not args.no_clipboard
            )
            clip_msg = "（クリップボードへコピー済）" if copied_clip else ""
            print(f"[✓] {ai_label}: .brain/web_bootstrap_prompt.md を生成しました{clip_msg}。")
        else:
            for rel_file in spec.get("files", []):
                install_markdown_adapter(
                    project_root, brain_dir, manifest, rel_file, ai_key, ai_label
                )
                print(f"[✓] {ai_label}: {rel_file} を設定しました。")

        installed_ais.add(ai_key)

    if args.git_exclude:
        configure_local_git_exclude(project_root)

    manifest["enabled"] = True
    manifest["installed_ais"] = sorted(installed_ais)
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_json(manifest_path, manifest)

    print(f"\n✨ セットアップ完了！対象プロジェクト: {project_root}")
    print("   ・`/compact` 自動引き継ぎ: 有効")
    print("   ・GitHub容量スリム化     : `python .brain/scripts/cloud_slim.py --analyze`")
    print("   ・元に戻す               : `python .brain/scripts/uninstall.py --disable | --eject | --purge`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
