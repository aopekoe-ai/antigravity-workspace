#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portable Brain Engine - Web AI Context Packer & Rule Evolution CLI (sync_web.py)
1. --pack  : Grok / ChatGPT 等のWeb系AIに貼るだけの省トークン・コンテキストカプセルを生成＆コピー
2. --learn : ユーザー修正から得た学びを該当モジュールへ重複排除・行数維持で登録し、Obsidian同期も支援
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

QUESTION_MAP: Dict[str, str] = {
    "q01": "questions/q01_intent_and_prd.md",
    "q02": "questions/q02_ooui_and_ia.md",
    "q03": "questions/q03_divergence_lenses.md",
    "q04": "questions/q04_edge_and_states.md",
    "q05": "questions/q05_design_and_code_tokens.md",
    "q06": "questions/q06_critic_rubric.md",
}


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


def extract_learned_rules(md_path: Path) -> List[str]:
    if not md_path.exists():
        return []
    lines = md_path.read_text(encoding="utf-8").splitlines()
    in_section = False
    collected: List[str] = []
    for ln in lines:
        if "[LEARNED_RULES]" in ln or "学習済みプロジェクト固有ルール" in ln:
            in_section = True
            continue
        if in_section:
            if ln.startswith("## "):
                break
            if ln.startswith("- ") and "初期状態" not in ln:
                collected.append(ln)
    return collected


def build_web_capsule(brain_dir: Path, selected_qs: List[str]) -> str:
    """WebチャットAI向けに350トークン前後の高密度コンテキストカプセルを組み立てる"""
    snap = (brain_dir / "DECISIONS_SNAPSHOT.md").read_text(encoding="utf-8")
    task = (brain_dir / "current_task.md").read_text(encoding="utf-8")

    snap_bullets = [ln for ln in snap.splitlines() if ln.startswith("- ")][:6]
    task_bullets = [ln for ln in task.splitlines() if ln.startswith("- ")][:8]

    extra_rules: List[str] = []
    for q_key in selected_qs:
        rel = QUESTION_MAP.get(q_key.lower().strip())
        if rel:
            extra_rules.extend(extract_learned_rules(brain_dir / rel))

    parts = [
        "# Portable Brain Context Capsule (Grok / ChatGPT / Web AI)",
        "以下の思考プロセスで私の次の依頼を実行してください：",
        "1. 【??????OS補完】下記ステートから前提を自動補完し、タスクツリーを更新（重大分岐のみ推奨付き2択質問）。",
        "2. 【カナリー流5段階】①要求整理 → ②OOUI優先度(Primary/Secondary/Tertiary) → ③構造の異なる3案発散と採用根拠 → ④5状態(0件/読込/エラー/長文/破壊操作)込み実装 → ⑤85点基準の自己監査。",
        "",
        "## 確定ステート",
        *(snap_bullets or ["- 初期状態"]),
        "",
        "## 進行中タスク",
        *(task_bullets or ["- 新規依頼待ち"]),
    ]
    if extra_rules:
        parts.extend(["", "## 重点適用ルール", *extra_rules[:6]])

    return "\n".join(parts) + "\n"


def learn_rule(
    brain_dir: Path, rule_text: str, q_target: str, max_learned_items: int = 8
) -> int:
    """指定モジュールの学習セクションに重複排除・件数上限付きでルールを記録する"""
    clean_rule = rule_text.strip().lstrip("- ").strip()
    if not clean_rule:
        print("[!] 空のルールは登録できません。", file=sys.stderr)
        return 1

    if q_target == "snapshot":
        target_path = brain_dir / "DECISIONS_SNAPSHOT.md"
        header_marker = "学習済みプロジェクト固有ルール"
    elif q_target in {"reject", "anti-regression"}:
        target_path = brain_dir / "DECISIONS_SNAPSHOT.md"
        header_marker = "ボツ案・先祖返り禁止リスト"
    else:
        rel = QUESTION_MAP.get(q_target.lower())
        if not rel:
            print(
                f"[!] 無効な対象指定です: {q_target} (q01〜q05, snapshot, または reject)",
                file=sys.stderr,
            )
            return 1
        target_path = brain_dir / rel
        header_marker = "[LEARNED_RULES]"

    lines = target_path.read_text(encoding="utf-8").splitlines()
    out_lines: List[str] = []
    idx = 0
    inserted = False

    while idx < len(lines):
        ln = lines[idx]
        out_lines.append(ln)
        if header_marker in ln and not inserted:
            idx += 1
            # コメント行を維持
            while idx < len(lines) and lines[idx].strip().startswith("<!--"):
                out_lines.append(lines[idx])
                idx += 1
            existing_bullets: List[str] = []
            while idx < len(lines) and not lines[idx].startswith("## "):
                cur = lines[idx]
                if cur.startswith("- ") and "初期状態" not in cur:
                    existing_bullets.append(cur)
                idx += 1

            new_bullet = f"- {clean_rule}"
            # 同一プレフィックス（コロン前）または完全一致があれば上書き置換（圧縮統合）
            prefix = clean_rule.split("：")[0].split(":")[0]
            replaced = False
            updated_bullets: List[str] = []
            for b in existing_bullets:
                b_body = b[2:].strip()
                if b_body == clean_rule or (len(prefix) >= 4 and b_body.startswith(prefix)):
                    if not replaced:
                        updated_bullets.append(new_bullet)
                        replaced = True
                else:
                    updated_bullets.append(b)
            if not replaced:
                updated_bullets.append(new_bullet)

            # 上限を超えた場合は古い項目をローテーション圧縮して肥大化を防止
            if len(updated_bullets) > max_learned_items:
                updated_bullets = updated_bullets[-max_learned_items:]

            out_lines.extend(updated_bullets)
            out_lines.append("")
            inserted = True
            continue
        idx += 1

    target_path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")
    print(f"[✓] 学習ルールを圧縮反映しました -> {target_path.relative_to(brain_dir.parent)}")
    return 0


def sync_to_obsidian_live(project_root: Path, brain_dir: Path) -> None:
    """Obsidian Vault が存在する場合、最新スナップショットを軽量ミラーリングする"""
    obs_root = Path(r"C:\Obsidian\LLM Folder\04_PortableBrain_Archives\Live_Snapshots")
    if not Path(r"C:\Obsidian").exists():
        return
    obs_root.mkdir(parents=True, exist_ok=True)
    dest = obs_root / f"{project_root.name}_DECISIONS.md"
    snap = (brain_dir / "DECISIONS_SNAPSHOT.md").read_text(encoding="utf-8")
    header = f"<!-- Synced from {project_root} at {datetime.now().isoformat(timespec='seconds')} -->\n"
    dest.write_text(header + snap, encoding="utf-8")
    print(f"[✓] Obsidian Vault へ最新決定事項を同期しました: {dest}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grok/Web系AI用コンテキスト出力 ＆ 省トークン学習同期 CLI"
    )
    parser.add_argument("--target", type=str, default="", help="対象プロジェクトパス")
    parser.add_argument(
        "--pack",
        action="store_true",
        help="Grok / ChatGPT 用の省トークン・コンテキストカプセルを生成・コピーする",
    )
    parser.add_argument(
        "--q",
        type=str,
        default="snapshot",
        help="--pack時は含める問い(例: q03,q05)、--learn時は保存先(q01..q05 または snapshot)",
    )
    parser.add_argument(
        "--learn",
        type=str,
        default="",
        help="学習・上書き統合する1行ルールを指定する",
    )
    parser.add_argument(
        "--sync-obsidian",
        action="store_true",
        help="確定仕様スナップショットを Obsidian Vault へ同期する",
    )
    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="クリップボードへのコピーをスキップする",
    )

    args = parser.parse_args()
    brain_dir = (
        Path(args.target).resolve() / ".brain"
        if args.target
        else Path(__file__).resolve().parent.parent
    )
    project_root = brain_dir.parent

    if args.learn:
        rc = learn_rule(brain_dir, args.learn, args.q)
        if rc != 0:
            return rc

    if args.sync_obsidian:
        sync_to_obsidian_live(project_root, brain_dir)

    if args.pack or (not args.learn and not args.sync_obsidian):
        q_list = [x for x in args.q.split(",") if x and x != "snapshot"]
        capsule = build_web_capsule(brain_dir, q_list)
        out_file = brain_dir / "web_bootstrap_prompt.md"
        out_file.write_text(capsule, encoding="utf-8")
        copied = False if args.no_clipboard else copy_to_clipboard(capsule)
        clip_note = "（クリップボードにコピーしました！そのままGrok等へ貼り付け可能）" if copied else ""
        print(f"[✓] Web AI用コンテキストカプセルを生成しました: {out_file} {clip_note}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
