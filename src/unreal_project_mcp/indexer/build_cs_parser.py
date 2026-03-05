"""Build.cs dependency extractor."""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from unreal_project_mcp.db.queries import insert_module_dependency

logger = logging.getLogger(__name__)

_ADD_RANGE_RE = re.compile(
    r'(Public|Private|DynamicallyLoaded)(?:Dependency)?ModuleNames\s*\.\s*AddRange\s*\([^{]*\{([^}]*)\}',
    re.DOTALL,
)
_ADD_SINGLE_RE = re.compile(
    r'(Public|Private|DynamicallyLoaded)(?:Dependency)?ModuleNames\s*\.\s*Add\s*\(\s*"(\w+)"',
)
_QUOTED_RE = re.compile(r'"(\w+)"')


def _dep_type(prefix: str) -> str:
    return {"Public": "public", "Private": "private", "DynamicallyLoaded": "dynamic"}.get(prefix, "public")


class BuildCsParser:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def parse_build_cs(self, path: Path, module_id: int) -> int:
        """Parse a .Build.cs file and insert module dependencies.

        Returns the number of dependencies extracted.
        """
        text = path.read_text(encoding="utf-8", errors="replace")
        count = 0
        for m in _ADD_RANGE_RE.finditer(text):
            dt = _dep_type(m.group(1))
            for qm in _QUOTED_RE.finditer(m.group(2)):
                insert_module_dependency(self._conn, module_id=module_id, dependency_name=qm.group(1), dep_type=dt)
                count += 1
        for m in _ADD_SINGLE_RE.finditer(text):
            insert_module_dependency(self._conn, module_id=module_id, dependency_name=m.group(2), dep_type=_dep_type(m.group(1)))
            count += 1
        logger.debug("Parsed %s: %d dependencies", path.name, count)
        return count
