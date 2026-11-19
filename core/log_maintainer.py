import datetime
import gzip
import json
import os
from pathlib import Path
from typing import Any, Dict, List


class LogMaintainer:
    """
    【長期24時間自律稼働用 ログ・ストレージ保全エンジン】
    - trade_journal.json の肥大化防止（直近300件＋OPEN建玉のみアクティブ保持、古い履歴は月次gzip圧縮アーカイブ）
    - learning_journal.md のローテーション（256KB超過時に古い教訓をgzip退避し直近90日分を維持）
    - 一時ファイル（*.tmp）の自動クリーンアップ
    """

    def __init__(self, log_dir: Path, max_active_closed_trades: int = 300, max_learning_kb: int = 256):
        self.log_dir = Path(log_dir)
        self.archive_dir = self.log_dir / "archive"
        self.journal_file = self.log_dir / "trade_journal.json"
        self.learning_file = self.log_dir / "learning_journal.md"
        self.max_active_closed_trades = max_active_closed_trades
        self.max_learning_bytes = max_learning_kb * 1024

    def run_maintenance(self) -> Dict[str, Any]:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        archived_trades = self._rotate_trade_journal()
        rotated_learning = self._rotate_learning_journal()
        cleaned_tmp = self._clean_temp_files()

        summary = {
            "archived_trades": archived_trades,
            "rotated_learning": rotated_learning,
            "cleaned_tmp_files": cleaned_tmp,
        }
        if archived_trades > 0 or rotated_learning or cleaned_tmp > 0:
            print(
                f"🧹 [LOG MAINTENANCE] アーカイブ退避トレード: {archived_trades}件, "
                f"学習ログ圧縮: {rotated_learning}, 一時ファイル掃除: {cleaned_tmp}件"
            )
        return summary

    def _rotate_trade_journal(self) -> int:
        if not self.journal_file.exists():
            return 0
        try:
            with open(self.journal_file, "r", encoding="utf-8") as f:
                records: List[Dict[str, Any]] = json.load(f)
            if not isinstance(records, list):
                return 0
        except Exception:
            return 0

        open_recs = [r for r in records if r.get("status") == "OPEN"]
        closed_recs = [r for r in records if r.get("status") != "OPEN"]

        if len(closed_recs) <= self.max_active_closed_trades:
            return 0

        to_archive = closed_recs[: len(closed_recs) - self.max_active_closed_trades]
        to_keep = closed_recs[len(closed_recs) - self.max_active_closed_trades :]

        ym = datetime.datetime.now().strftime("%Y%m")
        arch_path = self.archive_dir / f"trade_journal_{ym}.json.gz"

        existing_arch: List[Dict[str, Any]] = []
        if arch_path.exists():
            try:
                with gzip.open(arch_path, "rt", encoding="utf-8") as gf:
                    existing_arch = json.load(gf)
            except Exception:
                existing_arch = []

        seen_ids = {str(r.get("order_id")) for r in existing_arch if r.get("order_id")}
        for r in to_archive:
            oid = str(r.get("order_id", ""))
            if not oid or oid not in seen_ids:
                existing_arch.append(r)
                if oid:
                    seen_ids.add(oid)

        try:
            with gzip.open(arch_path, "wt", encoding="utf-8") as gf:
                json.dump(existing_arch, gf, ensure_ascii=False, indent=2)

            active_records = to_keep + open_recs
            tmp_file = self.journal_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(active_records, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.journal_file)
            return len(to_archive)
        except Exception as e:
            print(f"[LOG MAINTENANCE WARN] trade_journal rotation skipped: {e}")
            return 0

    def _rotate_learning_journal(self) -> bool:
        if not self.learning_file.exists():
            return False
        try:
            size = self.learning_file.stat().st_size
            if size <= self.max_learning_bytes:
                return False

            text = self.learning_file.read_text(encoding="utf-8")
            sections = text.split("\n### 📅 ")
            if len(sections) <= 30:
                return False

            header = sections[0]
            older_sections = sections[1:-30]
            recent_sections = sections[-30:]

            ym = datetime.datetime.now().strftime("%Y%m")
            arch_md = self.archive_dir / f"learning_journal_{ym}.md.gz"
            arch_content = "\n### 📅 ".join(older_sections) + "\n"

            existing_text = ""
            if arch_md.exists():
                try:
                    with gzip.open(arch_md, "rt", encoding="utf-8") as gf:
                        existing_text = gf.read()
                except Exception:
                    existing_text = ""

            with gzip.open(arch_md, "wt", encoding="utf-8") as gf:
                gf.write(existing_text + arch_content)

            new_active_text = header + "\n### 📅 " + "\n### 📅 ".join(recent_sections)
            self.learning_file.write_text(new_active_text, encoding="utf-8")
            return True
        except Exception as e:
            print(f"[LOG MAINTENANCE WARN] learning_journal rotation skipped: {e}")
            return False

    def _clean_temp_files(self) -> int:
        count = 0
        now_ts = datetime.datetime.now().timestamp()
        try:
            for p in self.log_dir.glob("*.tmp"):
                if (now_ts - p.stat().st_mtime) > 300:
                    p.unlink(missing_ok=True)
                    count += 1
        except Exception:
            pass
        return count
