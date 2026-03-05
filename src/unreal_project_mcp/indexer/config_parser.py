"""UE config/INI file parser."""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from unreal_project_mcp.db.queries import insert_config_entry

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(r'^\[(.+)\]\s*$')
_KV_RE = re.compile(r'^([+\-\.!]?\w[\w.]*)\s*=\s*(.*?)\s*$')


class ConfigParser:
    """Parser for Unreal Engine .ini config files.

    UE INI format is non-standard and cannot use Python's configparser.
    It supports duplicate keys (array-style ``+Key=Value``), special
    prefixes (``+``, ``-``, ``.``, ``!``), and comments with ``;`` or ``#``.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def index_config_dir(self, config_dir: Path) -> int:
        """Index all .ini files in *config_dir*. Returns entry count."""
        count = 0
        for ini_file in sorted(Path(config_dir).glob("*.ini")):
            try:
                count += self._parse_ini_file(ini_file)
            except Exception:
                logger.warning("Error parsing %s", ini_file, exc_info=True)
        return count

    def _parse_ini_file(self, path: Path) -> int:
        text = path.read_text(encoding="utf-8", errors="replace")
        current_section = ""
        count = 0
        for line_num, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(";") or stripped.startswith("#"):
                continue
            sm = _SECTION_RE.match(stripped)
            if sm:
                current_section = sm.group(1)
                continue
            kvm = _KV_RE.match(stripped)
            if kvm:
                insert_config_entry(
                    self._conn,
                    file_path=str(path),
                    section=current_section,
                    key=kvm.group(1),
                    value=kvm.group(2),
                    line=line_num,
                )
                count += 1
        return count
