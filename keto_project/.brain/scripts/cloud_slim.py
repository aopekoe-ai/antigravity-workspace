#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portable Brain Engine - GitHub Cloud Offload & Local Disk Slimmer (cloud_slim.py)
既定の共通クラウド倉庫: https://github.com/aopekoe-ai/AI_brain.git
- マスター (`portable-brain`) は `main` ブランチへ保存
- 各個別プロジェクト（独自origin未設定時）は `projects/<案件名>` ブランチへ自動分離して保存（上書き衝突ゼロ）
- 既存の別GitHubアカウント（sns-news等）と認証が競合しないよう `credential.useHttpPath=true` を自動設定
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_HUB_REPO = "https://github.com/aopekoe-ai/AI_brain.git"

HEAVY_CACHE_DIRS = {
    "node_modules",
    ".next",
    "dist",
    "build",
    "out",
    ".turbo",
    ".parcel-cache",
    ".cache",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
}

DEFAULT_GITIGNORE_ENTRIES = [
    "# Portable Brain Safe Cache Excludes",
    "node_modules/",
    ".next/",
    "dist/",
    "build/",
    "out/",
    ".turbo/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "*.pyc",
    "coverage/",
    ".brain/.backups/",
    ".brain/workspace/.hook_state.json",
]


def force_remove_readonly(func: Any, path: str, _: Any) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def sanitize_branch_segment(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    return cleaned or "unnamed-project"


def load_default_hub_repo(project_root: Path) -> str:
    reg_path = project_root / ".brain" / "ai_registry.json"
    if reg_path.exists():
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            url = str(data.get("default_github_repo", "")).strip()
            if url:
                return url
        except Exception:
            pass
    return DEFAULT_HUB_REPO


def format_bytes(num_bytes: int) -> str:
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024.0 or unit == "GB":
            return f"{val:.2f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.2f} GB"


def dir_size(path: Path) -> int:
    """高速なディレクトリ再帰サイズ集計 (os.scandir 使用)"""
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0

    total = 0
    try:
        with os.scandir(str(path)) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += dir_size(Path(entry.path))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def get_project_last_active_mtime(project_root: Path) -> Tuple[float, str]:
    """
    プロジェクト内の『実ソースコード』の最新更新日時を取得する。
    キャッシュ・ビルド成果物・Git・自動アダプター（CLAUDE.md等）は除外して純粋な開発放置日数を判定。
    """
    max_mtime = 0.0
    newest_file = ""
    ignore_files = {"CLAUDE.md", ".cursorrules", "AGENTS.md", "DECISIONS_SNAPSHOT.md"}
    ignore_dir_names = set(HEAVY_CACHE_DIRS) | {".git", ".brain", ".agents", ".claude", ".cursor", "public"}

    try:
        with os.scandir(str(project_root)) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in ignore_dir_names:
                        continue
                    mt, nf = get_project_last_active_mtime(Path(entry.path))
                    if mt > max_mtime:
                        max_mtime = mt
                        newest_file = nf
                elif entry.is_file(follow_symlinks=False):
                    if entry.name in ignore_files:
                        continue
                    try:
                        mt = entry.stat().st_mtime
                        if mt > max_mtime:
                            max_mtime = mt
                            newest_file = entry.path
                    except OSError:
                        pass
    except OSError:
        pass
    return max_mtime, newest_file


def check_weekly_maintenance(
    scratch_dir: Path,
    interval_days: float = 7.0,
    dormant_days_threshold: float = 14.0,
    force: bool = False,
) -> Dict[str, Any]:
    """
    常駐プロセスなし・週1回起動時のみ超軽量に実行する自動容量診断。
    - 前回のチェックから interval_days (既定7日) 経過していなければ 0.01 秒で何もしない (skipped)
    - 経過していた場合のみ、放置されているプロジェクトを走査して容量削減提案または自動退避リストを返す
    """
    state_file = scratch_dir / ".brain_maintenance_state.json"
    now = datetime.now().timestamp()

    if not force and state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            last_run = float(data.get("last_run", 0))
            elapsed_days = (now - last_run) / 86400.0
            if elapsed_days < interval_days:
                return {
                    "status": "skipped",
                    "reason": f"前回チェックから {elapsed_days:.1f} 日経過（次回予定: {interval_days - elapsed_days:.1f} 日後）",
                    "last_run": data.get("last_run_iso", ""),
                    "stale_projects": [],
                }
        except Exception:
            pass

    stale_projects: List[Dict[str, Any]] = []
    if scratch_dir.exists():
        for entry in scratch_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if entry.name == "portable-brain":
                continue
            if (entry / "RESTORATION_CARD.md").exists():
                continue  # すでにGitHubへ退避済み

            mt, nf = get_project_last_active_mtime(entry)
            dormant_days = (now - mt) / 86400.0 if mt > 0 else 999.0
            if dormant_days >= dormant_days_threshold:
                sz = dir_size(entry)
                stale_projects.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "dormant_days": round(dormant_days, 1),
                        "size_bytes": sz,
                        "size_human": format_bytes(sz),
                        "newest_file": Path(nf).name if nf else "none",
                    }
                )

    # タイムスタンプ更新
    try:
        state_file.write_text(
            json.dumps(
                {
                    "last_run": now,
                    "last_run_iso": datetime.now().isoformat(),
                    "checked_count": len(stale_projects),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    return {
        "status": "executed",
        "timestamp": datetime.now().isoformat(),
        "stale_projects": stale_projects,
    }


def analyze_project_storage(project_root: Path) -> Dict[str, Any]:
    cache_paths: List[Tuple[Path, int]] = []
    seen_cache_roots: List[Path] = []

    for item in project_root.rglob("*"):
        if not item.is_dir():
            continue
        if any(parent in seen_cache_roots for parent in item.parents):
            continue
        if item.name in HEAVY_CACHE_DIRS:
            sz = dir_size(item)
            cache_paths.append((item, sz))
            seen_cache_roots.append(item)

    backups_dir = project_root / ".brain" / ".backups"
    if backups_dir.exists():
        cache_paths.append((backups_dir, dir_size(backups_dir)))

    total_bytes = dir_size(project_root)
    git_bytes = dir_size(project_root / ".git")
    brain_bytes = dir_size(project_root / ".brain")
    reclaimable_bytes = sum(sz for _, sz in cache_paths)
    core_bytes = max(0, total_bytes - git_bytes - reclaimable_bytes)

    return {
        "total_bytes": total_bytes,
        "reclaimable_bytes": reclaimable_bytes,
        "git_bytes": git_bytes,
        "brain_bytes": brain_bytes,
        "core_bytes": core_bytes,
        "cache_paths": cache_paths,
    }


def print_analysis(project_root: Path, stats: Dict[str, Any]) -> None:
    total = stats["total_bytes"]
    reclaim = stats["reclaimable_bytes"]
    after_slim = max(0, total - reclaim)
    hub_repo = load_default_hub_repo(project_root)
    target_branch = (
        "main"
        if project_root.name == "portable-brain"
        else f"projects/{sanitize_branch_segment(project_root.name)}"
    )
    print(f"=== ディスク容量診断 [{project_root.name}] ===")
    print(f"  📦 現在の合計サイズ         : {format_bytes(total)}")
    print(f"  🧹 削減可能キャッシュ合計   : {format_bytes(reclaim)}")
    print(f"  🗂️  Git履歴 (.git)           : {format_bytes(stats['git_bytes'])}")
    print(f"  💎 コア資産 (コード+.brain) : {format_bytes(stats['core_bytes'])} (内 .brain: {format_bytes(stats['brain_bytes'])})")
    print(f"  ☁️  既定クラウド退避先       : {hub_repo} [{target_branch}]")
    print(f"  👉 --slim 実行後の予測サイズ: {format_bytes(after_slim)}")
    print("  👉 --offload 実行後のサイズ : 約 2.00 KB (復元カードのみ)")


def clean_heavy_caches(project_root: Path) -> int:
    stats = analyze_project_storage(project_root)
    freed = 0
    for cpath, sz in stats["cache_paths"]:
        if cpath.exists():
            shutil.rmtree(cpath, onerror=force_remove_readonly)
            freed += sz
    hook_state = project_root / ".brain" / "workspace" / ".hook_state.json"
    if hook_state.exists():
        freed += hook_state.stat().st_size
        hook_state.unlink()
    return freed


def run_git(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def ensure_safe_gitignore(project_root: Path) -> None:
    gi_path = project_root / ".gitignore"
    existing = gi_path.read_text(encoding="utf-8") if gi_path.exists() else ""
    missing = [
        entry
        for entry in DEFAULT_GITIGNORE_ENTRIES
        if not entry.startswith("#") and entry.rstrip("/") not in existing
    ]
    if missing:
        block = "\n".join(["", "# Portable Brain Auto-Ignore (Heavy Caches)", *missing, ""])
        gi_path.write_text(existing.rstrip() + "\n" + block.lstrip("\n"), encoding="utf-8")


def resolve_target_remote_and_branch(
    project_root: Path, explicit_remote: str, explicit_branch: str
) -> Tuple[str, str]:
    """
    リモートURLと保存先ブランチを自動解決する:
    - 独自リポジトリが既に設定されていればそれを尊重
    - 未設定または共通ハブ (`AI_brain.git`) を使う場合:
      * `portable-brain` 本体 -> `main`
      * その他の各プロジェクト -> `projects/<案件名>` に自動分離（1つのリポジトリで全案件を衝突なく保管）
    """
    hub_repo = load_default_hub_repo(project_root)
    cur_remote = ""
    if (project_root / ".git").exists():
        cur_remote = run_git(project_root, "remote", "get-url", "origin").stdout.strip()

    remote_url = explicit_remote or cur_remote or hub_repo

    if explicit_branch:
        target_branch = explicit_branch
    else:
        norm_remote = remote_url.replace("\\", "/").rstrip("/").lower()
        norm_hub = hub_repo.replace("\\", "/").rstrip("/").lower()
        is_shared_hub = (
            norm_remote == norm_hub
            or norm_remote.endswith("/ai_brain.git")
            or norm_remote.endswith(":aopekoe-ai/ai_brain.git")
        )
        if is_shared_hub and project_root.name != "portable-brain":
            target_branch = f"projects/{sanitize_branch_segment(project_root.name)}"
        elif (project_root / ".git").exists():
            existing_br = run_git(project_root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            target_branch = existing_br if (existing_br and existing_br != "HEAD") else "main"
        else:
            target_branch = "main"

    return remote_url, target_branch


def sync_project_to_github(
    project_root: Path, explicit_remote: str, explicit_branch: str
) -> Tuple[bool, str, str, str]:
    """
    プロジェクトのコードと .brain を GitHub へ確実にPushする。
    戻り値: (成功フラグ, remote_url, branch_name, head_commit_sha)
    """
    ensure_safe_gitignore(project_root)
    remote_url, target_branch = resolve_target_remote_and_branch(
        project_root, explicit_remote, explicit_branch
    )

    if not (project_root / ".git").exists():
        init_res = run_git(project_root, "init", "-b", target_branch)
        if init_res.returncode != 0:
            run_git(project_root, "init")
            run_git(project_root, "checkout", "-B", target_branch)
    else:
        cur_br = run_git(project_root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if cur_br != target_branch:
            run_git(project_root, "checkout", "-B", target_branch)

    # 同一PC内の複数GitHubアカウント（例: sns-news と aopekoe-ai）の認証競合を防ぐ
    run_git(project_root, "config", "credential.useHttpPath", "true")

    if not run_git(project_root, "config", "user.name").stdout.strip():
        run_git(project_root, "config", "user.name", "aopekoe-ai")
    if not run_git(project_root, "config", "user.email").stdout.strip():
        run_git(project_root, "config", "user.email", "aopekoe-ai@users.noreply.github.com")

    cur_remote = run_git(project_root, "remote", "get-url", "origin").stdout.strip()
    if cur_remote:
        if cur_remote != remote_url:
            run_git(project_root, "remote", "set-url", "origin", remote_url)
    else:
        run_git(project_root, "remote", "add", "origin", remote_url)

    ckpt_script = project_root / ".brain" / "scripts" / "checkpoint.py"
    if ckpt_script.exists():
        subprocess.run(
            [sys.executable, str(ckpt_script), "--save", "--no-clipboard"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    run_git(project_root, "add", "-A")
    dirty = run_git(project_root, "status", "--porcelain").stdout.strip()
    has_head = run_git(project_root, "rev-parse", "--verify", "HEAD").returncode == 0
    if dirty or not has_head:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_res = run_git(
            project_root,
            "commit",
            "--allow-empty",
            "-m",
            f"chore(portable-brain): sync {project_root.name} ({ts})",
        )
        if commit_res.returncode != 0:
            print(f"[!] git commit に失敗しました:\n{commit_res.stderr}", file=sys.stderr)
            return False, remote_url, target_branch, ""

    push_res = run_git(project_root, "push", "-u", "origin", f"HEAD:refs/heads/{target_branch}")
    if push_res.returncode != 0:
        print(
            f"[!] リモート ({remote_url} [{target_branch}]) への git push に失敗したため、"
            f"安全装置によりローカル削除を中止しました:\n{push_res.stderr.strip()}\n"
            f"💡 ヒント: 初回のみ GitHub 側で `{remote_url}` が作成済みか、および `aopekoe-ai` アカウントの認証をご確認ください。",
            file=sys.stderr,
        )
        return False, remote_url, target_branch, ""

    still_dirty = run_git(project_root, "status", "--porcelain").stdout.strip()
    if still_dirty:
        print("[!] 未コミットの変更が残っているためローカル退避を中止しました。", file=sys.stderr)
        return False, remote_url, target_branch, ""

    head_sha = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    return True, remote_url, target_branch, head_sha


def write_restore_cards(
    project_root: Path, remote_url: str, branch: str, sha: str, stubs_dir: str
) -> Path:
    snap_path = project_root / ".brain" / "DECISIONS_SNAPSHOT.md"
    task_path = project_root / ".brain" / "current_task.md"
    snap_lines = (
        [ln for ln in snap_path.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")][:5]
        if snap_path.exists()
        else []
    )
    task_lines = (
        [ln for ln in task_path.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")][:5]
        if task_path.exists()
        else []
    )

    stub_parent = Path(stubs_dir).resolve() if stubs_dir else project_root.parent
    stub_parent.mkdir(parents=True, exist_ok=True)
    card_path = stub_parent / f"{project_root.name}.restore.json"

    master_slim = Path(
        r"C:\Users\user\.gemini\antigravity\scratch\portable-brain\.brain\scripts\cloud_slim.py"
    )
    script_hint = str(master_slim) if master_slim.exists() else "cloud_slim.py"

    card_data = {
        "project_name": project_root.name,
        "original_path": str(project_root),
        "remote_url": remote_url,
        "branch": branch,
        "commit_sha": sha,
        "offloaded_at": datetime.now().isoformat(timespec="seconds"),
        "decisions_preview": snap_lines,
        "tasks_preview": task_lines,
        "restore_command": f'python "{script_hint}" --restore "{card_path}"',
    }
    card_path.write_text(
        json.dumps(card_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # --stubs-dir 未指定の実運用時かつ Obsidian Vault が存在する場合は一覧閲覧用の Markdown カードも自動保存
    if not stubs_dir and Path(r"C:\Obsidian").exists():
        obs_dir = Path(r"C:\Obsidian\LLM Folder\04_PortableBrain_Archives\Cloud_Offloaded")
        obs_dir.mkdir(parents=True, exist_ok=True)
        obs_md = (
            f"# ☁️ Cloud Offloaded: {project_root.name}\n"
            f"- **退避日時**: {card_data['offloaded_at']}\n"
            f"- **GitHub Remote**: `{remote_url}` (`{branch}` @ `{sha[:8]}`)\n"
            f"- **元のローカル場所**: `{project_root}`\n\n"
            f"## ワンコマンド高速復元（Shallow Clone）\n"
            f"```powershell\n{card_data['restore_command']}\n```\n"
        )
        (obs_dir / f"{project_root.name}.md").write_text(obs_md, encoding="utf-8")
        shutil.copy2(card_path, obs_dir / f"{project_root.name}.restore.json")

    return card_path


def resolve_restore_card(query: str) -> Path | None:
    p = Path(query)
    if p.exists() and p.is_file():
        return p.resolve()
    candidates = [
        Path.cwd() / f"{query}.restore.json",
        Path(r"C:\Users\user\.gemini\antigravity\scratch") / f"{query}.restore.json",
        Path(r"C:\Obsidian\LLM Folder\04_PortableBrain_Archives\Cloud_Offloaded")
        / f"{query}.restore.json",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


def restore_from_cloud(query: str, target_override: str, full_history: bool) -> int:
    card_path = resolve_restore_card(query)
    if not card_path:
        print(f"[!] 復元カードが見つかりません: {query}", file=sys.stderr)
        return 1

    card = json.loads(card_path.read_text(encoding="utf-8"))
    dest = Path(target_override).resolve() if target_override else Path(card["original_path"])
    if dest.exists() and any(dest.iterdir()):
        print(f"[!] 復元先ディレクトリが既に存在し空ではありません: {dest}", file=sys.stderr)
        return 1

    remote_url = card["remote_url"]
    branch = card.get("branch", "main")
    clone_cmd = [
        "git",
        "-c",
        "credential.useHttpPath=true",
        "clone",
    ]
    if not full_history:
        clone_cmd.extend(["--depth", "1", "--single-branch"])
    clone_cmd.extend(["--branch", branch, remote_url, str(dest)])

    res = subprocess.run(clone_cmd, capture_output=True, text=True, encoding="utf-8", check=False)
    if res.returncode != 0:
        fallback_cmd = (
            ["git", "-c", "credential.useHttpPath=true", "clone"]
            + ([] if full_history else ["--depth", "1"])
            + [remote_url, str(dest)]
        )
        res = subprocess.run(
            fallback_cmd, capture_output=True, text=True, encoding="utf-8", check=False
        )
        if res.returncode != 0:
            print(f"[!] git clone に失敗しました:\n{res.stderr}", file=sys.stderr)
            return 1

    setup_py = dest / ".brain" / "scripts" / "setup_brain.py"
    if setup_py.exists():
        subprocess.run(
            [sys.executable, str(setup_py), "--no-clipboard"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if "04_PortableBrain_Archives" not in str(card_path) and card_path.exists():
        card_path.unlink()

    print(f"✨ クラウドからの高速復元が完了しました！ -> {dest} (branch: {branch})")
    print(f"   サイズ: {format_bytes(dir_size(dest))} (Shallow Clone 省容量モード)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Portable Brain GitHubクラウド退避 ＆ ローカル容量削減 CLI (既定: {DEFAULT_HUB_REPO})"
    )
    parser.add_argument("--target", type=str, default="", help="対象プロジェクトパス")
    parser.add_argument(
        "--remote",
        type=str,
        default="",
        help=f"GitHub リポジトリURL（省略時は既定の {DEFAULT_HUB_REPO} を自動使用）",
    )
    parser.add_argument(
        "--branch",
        type=str,
        default="",
        help="Push/Clone対象ブランチ名（省略時は portable-brain=main、他案件=projects/<案件名> に自動分離）",
    )
    parser.add_argument("--stubs-dir", type=str, default="", help="--offload 時の復元カード保存先")
    parser.add_argument("--full-history", action="store_true", help="--restore 時に全Git履歴を取得する")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--analyze", action="store_true", help="ローカル容量の内訳と削減可能サイズを診断する")
    group.add_argument("--clean-cache", action="store_true", help="GitHub不要で重量キャッシュ(node_modules等)のみ削除する")
    group.add_argument("--slim", action="store_true", help="GitHubへPush後、重量キャッシュを削除して95〜99%軽量化する")
    group.add_argument("--offload", action="store_true", help="GitHubへ全保存後、ローカル本体を削除し2KB復元カード化する")
    group.add_argument("--restore", type=str, metavar="CARD_OR_NAME", help="復元カードまたは案件名からローカルへ復元する")
    group.add_argument("--check-weekly", action="store_true", help="週1回起動時用の超軽量放置判定（7日未経過なら即座にスキップ）")
    group.add_argument("--auto-sweep", action="store_true", help="14日以上放置されたプロジェクトを自動でGitHub退避・復元カード化する")
    parser.add_argument("--force", action="store_true", help="インターバルチェックを無視して強制実行する")
    parser.add_argument("--days", type=float, default=14.0, help="放置判定日数（既定: 14日）")

    args = parser.parse_args()

    if args.restore:
        return restore_from_cloud(args.restore, args.target, args.full_history)

    project_root = (
        Path(args.target).resolve()
        if args.target
        else Path(__file__).resolve().parent.parent.parent
    )
    if not project_root.exists():
        print(f"[!] 対象プロジェクトが存在しません: {project_root}", file=sys.stderr)
        return 1

    if args.analyze:
        print_analysis(project_root, analyze_project_storage(project_root))
        return 0

    if args.clean_cache:
        freed = clean_heavy_caches(project_root)
        print(f"🧹 キャッシュ削除完了！ 解放サイズ: {format_bytes(freed)}")
        return 0

    if args.slim:
        before = dir_size(project_root)
        ok, remote_url, used_branch, _ = sync_project_to_github(
            project_root, args.remote, args.branch
        )
        if not ok:
            return 1
        clean_heavy_caches(project_root)
        run_git(project_root, "gc", "--prune=now", "--quiet")
        after = dir_size(project_root)
        print(f"☁️  GitHub 同期完了: {remote_url} (ブランチ: {used_branch})")
        print(f"✨ スリム化完了！ {format_bytes(before)} -> {format_bytes(after)} (解放: {format_bytes(max(0, before - after))})")
        return 0

    if args.offload:
        before = dir_size(project_root)
        clean_heavy_caches(project_root)
        ok, remote_url, used_branch, sha = sync_project_to_github(
            project_root, args.remote, args.branch
        )
        if not ok:
            return 1
        card_path = write_restore_cards(project_root, remote_url, used_branch, sha, args.stubs_dir)

        try:
            if Path.cwd().resolve().is_relative_to(project_root.resolve()):
                os.chdir(project_root.parent)
        except Exception:
            pass

        shutil.rmtree(project_root, onerror=force_remove_readonly)
        print(f"☁️  GitHub 完全退避完了！ ({remote_url} [{used_branch}] @ {sha[:8]})")
        print(f"🪪 復元カードを作成しました: {card_path} (解放容量: {format_bytes(before)})")
        print(f'   再開時は: python "{Path(__file__).name}" --restore "{card_path}"')
        return 0

    scratch_dir = project_root if project_root.name != "portable-brain" else project_root.parent

    if args.check_weekly:
        res = check_weekly_maintenance(scratch_dir, dormant_days_threshold=args.days, force=args.force)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.auto_sweep:
        res = check_weekly_maintenance(scratch_dir, dormant_days_threshold=args.days, force=args.force)
        if res.get("status") == "skipped":
            print(f"⏸️  {res.get('reason')}")
            return 0
        stale_list = res.get("stale_projects", [])
        if not stale_list:
            print("✅ 放置されているプロジェクトはありません（ディスククリーン）")
            return 0
        print(f"🧹 放置プロジェクト検出: {len(stale_list)} 件の自動退避を開始します...")
        for proj in stale_list:
            p_path = Path(proj["path"])
            print(f"▶ [{proj['name']}] 放置日数: {proj['dormant_days']}日, サイズ: {proj['size_human']} -> GitHub退避中...")
            before = dir_size(p_path)
            clean_heavy_caches(p_path)
            ok, remote_url, used_branch, sha = sync_project_to_github(p_path)
            if ok:
                card = write_restore_cards(p_path, remote_url, used_branch, sha)
                shutil.rmtree(p_path, onerror=force_remove_readonly)
                print(f"   ✓ 退避完了・復元カード化: {card.name} (解放: {format_bytes(before)})")
            else:
                print(f"   ✕ Push失敗のため安全停止しました: {proj['name']}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
