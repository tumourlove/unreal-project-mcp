"""Pattern tagger — tags subsystems, anim notifies, and console commands."""
from __future__ import annotations

import json
import logging
import re
import sqlite3

from unreal_project_mcp.db.queries import get_inheritance_children, insert_pattern_tag

logger = logging.getLogger(__name__)

_SUBSYSTEM_BASES = {
    "UGameInstanceSubsystem": "GameInstance",
    "UWorldSubsystem": "World",
    "ULocalPlayerSubsystem": "LocalPlayer",
    "UEngineSubsystem": "Engine",
}
_ANIM_NOTIFY_BASES = {"UAnimNotify", "UAnimNotifyState"}
_CONSOLE_CMD_RE = re.compile(r'RegisterConsoleCommand\s*\(\s*TEXT\(\s*"([^"]+)"')


class PatternTagger:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def tag_all(self) -> int:
        """Run all taggers and return the total number of tags created."""
        return self.tag_subsystems() + self.tag_anim_notifies() + self.tag_console_commands()

    def tag_subsystems(self) -> int:
        """Tag classes that inherit from known UE subsystem base classes."""
        count = 0
        for base_name, sub_type in _SUBSYSTEM_BASES.items():
            row = self._conn.execute(
                "SELECT id FROM symbols WHERE name = ? AND kind IN ('class', 'struct')",
                (base_name,),
            ).fetchone()
            if not row:
                continue
            for child in get_inheritance_children(self._conn, row[0]):
                insert_pattern_tag(
                    self._conn,
                    symbol_id=child["id"],
                    tag_kind="subsystem",
                    metadata=json.dumps({"type": sub_type}),
                )
                count += 1
        return count

    def tag_anim_notifies(self) -> int:
        """Tag classes that inherit from UAnimNotify or UAnimNotifyState."""
        count = 0
        for base_name in _ANIM_NOTIFY_BASES:
            row = self._conn.execute(
                "SELECT id FROM symbols WHERE name = ? AND kind IN ('class', 'struct')",
                (base_name,),
            ).fetchone()
            if not row:
                continue
            for child in get_inheritance_children(self._conn, row[0]):
                insert_pattern_tag(
                    self._conn,
                    symbol_id=child["id"],
                    tag_kind="anim_notify",
                )
                count += 1
        return count

    def tag_console_commands(self) -> int:
        """Tag functions that register console commands via RegisterConsoleCommand."""
        count = 0
        rows = self._conn.execute(
            "SELECT sf.file_id, sf.line_number, sf.text "
            "FROM source_fts sf WHERE source_fts MATCH '\"RegisterConsoleCommand\"'",
        ).fetchall()
        for row in rows:
            text = row["text"] or ""
            for m in _CONSOLE_CMD_RE.finditer(text):
                cmd_name = m.group(1)
                sym = self._conn.execute(
                    "SELECT id FROM symbols WHERE file_id = ? AND line_start <= ? AND line_end >= ? "
                    "AND kind = 'function' ORDER BY (line_end - line_start) ASC LIMIT 1",
                    (row["file_id"], row["line_number"], row["line_number"]),
                ).fetchone()
                if sym:
                    insert_pattern_tag(
                        self._conn,
                        symbol_id=sym[0],
                        tag_kind="console_command",
                        metadata=json.dumps({"command": cmd_name}),
                    )
                    count += 1
        return count
