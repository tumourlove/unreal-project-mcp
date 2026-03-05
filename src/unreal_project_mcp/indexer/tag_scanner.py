"""Gameplay tag scanner — extracts tags from C++, INI, and data tables."""
from __future__ import annotations

import csv
import logging
import re
import sqlite3
from pathlib import Path

from unreal_project_mcp.db.queries import insert_gameplay_tag

logger = logging.getLogger(__name__)

_TAG_IN_TEXT_RE = re.compile(r'TEXT\(\s*"([A-Za-z][\w]*(?:\.[A-Za-z][\w]*)*)"\s*\)')
_TAG_IN_INI_RE = re.compile(r'Tag="([^"]+)"')

_CPP_DEFINITION_PATTERNS = ["AddNativeGameplayTag"]
_CPP_REQUEST_PATTERNS = ["RequestGameplayTag"]
_CPP_CHECK_PATTERNS = ["HasMatchingGameplayTag", "MatchesTag", "HasTag", "HasAny", "HasAll"]


class TagScanner:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def scan_all(self, content_dir: Path | None = None) -> int:
        count = self.scan_config_tags()
        count += self.scan_cpp_tags()
        if content_dir and content_dir.is_dir():
            count += self.scan_csv_tags(content_dir)
        return count

    def scan_config_tags(self) -> int:
        """Extract gameplay tags from config_entries table."""
        rows = self._conn.execute(
            "SELECT * FROM config_entries WHERE key LIKE '%GameplayTag%'"
        ).fetchall()
        count = 0
        for row in rows:
            value = row["value"] or ""
            for m in _TAG_IN_INI_RE.finditer(value):
                tag = m.group(1)
                if "." in tag:
                    insert_gameplay_tag(
                        self._conn, tag=tag, source_type="ini",
                        usage_kind="definition",
                        file_path=row["file_path"], line=row["line"],
                    )
                    count += 1
        return count

    def scan_cpp_tags(self) -> int:
        """Extract gameplay tags from indexed C++ source via source_fts."""
        count = 0
        for patterns, kind in [
            (_CPP_DEFINITION_PATTERNS, "definition"),
            (_CPP_REQUEST_PATTERNS, "request"),
            (_CPP_CHECK_PATTERNS, "check"),
        ]:
            for pattern in patterns:
                rows = self._conn.execute(
                    'SELECT sf.file_id, sf.line_number, sf.text '
                    'FROM source_fts sf WHERE source_fts MATCH ?',
                    (f'"{pattern}"',),
                ).fetchall()
                for row in rows:
                    text = row["text"] or ""
                    if pattern not in text:
                        continue
                    for m in _TAG_IN_TEXT_RE.finditer(text):
                        tag = m.group(1)
                        if "." in tag:
                            file_row = self._conn.execute(
                                "SELECT path FROM files WHERE id = ?",
                                (row["file_id"],),
                            ).fetchone()
                            insert_gameplay_tag(
                                self._conn, tag=tag, source_type="cpp",
                                usage_kind=kind,
                                file_path=file_row["path"] if file_row else None,
                                line=row["line_number"],
                            )
                            count += 1
        return count

    def scan_csv_tags(self, content_dir: Path) -> int:
        """Scan CSV data tables for gameplay tag columns."""
        count = 0
        for csv_file in content_dir.rglob("*.csv"):
            try:
                with open(csv_file, encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    if not reader.fieldnames:
                        continue
                    tag_cols = [c for c in reader.fieldnames if "tag" in c.lower()]
                    if not tag_cols:
                        continue
                    for row_num, row in enumerate(reader, 2):
                        for col in tag_cols:
                            val = row.get(col, "")
                            if val and "." in val:
                                insert_gameplay_tag(
                                    self._conn, tag=val,
                                    source_type="datatable",
                                    usage_kind="definition",
                                    file_path=str(csv_file), line=row_num,
                                )
                                count += 1
            except Exception:
                logger.warning("Error scanning %s", csv_file, exc_info=True)
        return count
