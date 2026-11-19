#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portable Brain Engine - Token Budget & Deliverable Quality Gate (verify_gate.py)
1. 省トークン監視: .brain 内のナレッジ・状態ファイルが行数上限を超えて肥大化していないか検査
2. 品質ガードレール: UI/コード内の放置プレースホルダー、alt属性漏れ、直書きカラー等を機械検査
3. Antigravity Hook対応: --agy-hook 指定時は JSON入出力プロトコルで動作（問題なければ0トークン）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

HEX_COLOR_RE = re.compile(r"(?<![&\w])#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
IMG_NO_ALT_RE = re.compile(r"<img\b(?![^>]*\balt=)[^>]*>", re.IGNORECASE)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def estimate_tokens(text: str) -> int:
    """日英混在テキストの概算トークン数を算出する"""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    return int(ascii_chars * 0.28 + non_ascii * 0.65)


def check_token_budgets(
    brain_dir: Path, config: Dict[str, Any]
) -> Tuple[List[str], int]:
    """ナレッジファイル群の行数上限をチェックし、常駐部分の推定トークン数を返す"""
    errors: List[str] = []
    budgets: Dict[str, int] = config.get("line_budgets", {})

    for rel_path, max_lines in budgets.items():
        fpath = brain_dir / rel_path
        if not fpath.exists():
            continue
        lines = fpath.read_text(encoding="utf-8").splitlines()
        if len(lines) > max_lines:
            errors.append(
                f"[TOKEN_BUDGET_OVER] .brain/{rel_path} ({len(lines)}/{max_lines}行): "
                "追記による肥大化を検知しました。既存ルールと抽象化・統合して行数を圧縮してください。"
            )

    # 常時参照される INDEX.md + アダプター1枚の概算トークン計測
    always_on_tokens = 0
    index_path = brain_dir / "questions" / "INDEX.md"
    tmpl_path = brain_dir / "templates" / "adapter_common.md.tmpl"
    if index_path.exists():
        always_on_tokens += estimate_tokens(index_path.read_text(encoding="utf-8"))
    if tmpl_path.exists():
        always_on_tokens += estimate_tokens(tmpl_path.read_text(encoding="utf-8"))

    return errors, always_on_tokens


def check_project_code(
    project_root: Path, config: Dict[str, Any]
) -> Tuple[List[str], List[str]]:
    """対象拡張子のUI/ソースコードを機械スキャンする"""
    errors: List[str] = []
    warnings: List[str] = []
    code_cfg = config.get("code_checks", {})
    if not code_cfg.get("enabled", True):
        return errors, warnings

    exts = set(code_cfg.get("target_extensions", []))
    ignore_dirs = set(code_cfg.get("ignore_dirs", [])) | {"tests", ".backups"}
    forbidden_texts: List[str] = code_cfg.get("forbid_placeholder_text", [])
    warn_hex: bool = code_cfg.get("warn_hardcoded_hex_in_components", True)
    warn_alt: bool = code_cfg.get("warn_img_without_alt", True)

    for path in project_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        rel_parts = path.relative_to(project_root).parts
        if any(part in ignore_dirs for part in rel_parts):
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        rel_str = path.relative_to(project_root).as_posix()

        for bad_phrase in forbidden_texts:
            if bad_phrase in content:
                errors.append(
                    f"[FORBIDDEN_PLACEHOLDER] {rel_str}: 未完成プレースホルダー '{bad_phrase}' が残っています。"
                )

        if warn_alt and path.suffix.lower() in {".tsx", ".jsx", ".html", ".vue", ".svelte"}:
            if IMG_NO_ALT_RE.search(content):
                warnings.append(
                    f"[A11Y_IMG_ALT] {rel_str}: alt属性のない <img> タグが検出されました。"
                )

        if warn_hex and path.suffix.lower() in {".tsx", ".jsx", ".vue", ".svelte"}:
            matches = HEX_COLOR_RE.findall(content)
            if matches:
                sample = ", ".join(sorted(set(matches))[:3])
                warnings.append(
                    f"[DESIGN_TOKEN_HEX] {rel_str}: 直書きカラー ({sample}) を検出。デザイントークンへの置換を推奨します。"
                )

    return errors, warnings


def run_agy_hook_mode(brain_dir: Path, project_root: Path, config: Dict[str, Any]) -> int:
    """Antigravity PostInvocation Hook 契約に従い JSON を標準出力へ返す"""
    try:
        if not sys.stdin.isatty():
            _ = sys.stdin.read()
    except Exception:
        pass

    budget_errors, _ = check_token_budgets(brain_dir, config)
    code_errors, _ = check_project_code(project_root, config)
    all_errors = budget_errors + code_errors

    if not all_errors:
        # 問題なし：完全空オブジェクトを返してトークン消費ゼロを維持
        print("{}")
        return 0

    msg = (
        "【Portable Brain 自動検証アラート】以下の規約違反を修正してください:\n"
        + "\n".join(f"- {e}" for e in all_errors[:5])
    )
    payload = {"injectSteps": [{"ephemeralMessage": msg}]}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Portable Brain 省トークン上限 ＆ コード品質機械検査ゲート"
    )
    parser.add_argument(
        "--target",
        type=str,
        default="",
        help="検査対象プロジェクトのルートパス",
    )
    parser.add_argument(
        "--agy-hook",
        action="store_true",
        help="Antigravity Lifecycle Hook (PostInvocation) JSONモードで実行する",
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="警告(Warning)も終了コード1として扱う",
    )

    args = parser.parse_args()
    brain_dir = (
        Path(args.target).resolve() / ".brain"
        if args.target
        else Path(__file__).resolve().parent.parent
    )
    project_root = brain_dir.parent
    config = load_json(brain_dir / "gate_config.json", {})

    if args.agy_hook:
        return run_agy_hook_mode(brain_dir, project_root, config)

    budget_errors, base_tokens = check_token_budgets(brain_dir, config)
    code_errors, code_warnings = check_project_code(project_root, config)
    all_errors = budget_errors + code_errors

    print(f"=== Portable Brain Verify Gate [{project_root.name}] ===")
    print(f"  📊 常駐インデックス＋アダプター推定消費: 約 {base_tokens} tokens (超軽量維持)")

    if code_warnings:
        print(f"  ⚠️  警告 ({len(code_warnings)}件):")
        for w in code_warnings:
            print(f"     - {w}")

    if all_errors:
        print(f"  ❌ エラー ({len(all_errors)}件):")
        for e in all_errors:
            print(f"     - {e}")
        return 1

    if args.strict_warnings and code_warnings:
        return 1

    print("  ✅ すべての省トークン上限チェック ＆ 品質ゲートを通過しました！")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
