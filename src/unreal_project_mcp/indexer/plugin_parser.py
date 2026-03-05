"""Plugin descriptor (.uplugin) parser."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from unreal_project_mcp.db.queries import (
    insert_plugin,
    insert_plugin_dependency,
    insert_plugin_module,
)

logger = logging.getLogger(__name__)


class PluginParser:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def index_plugins_dir(self, plugins_dir: Path) -> int:
        """Recursively find and parse all .uplugin files under *plugins_dir*.

        Returns the number of plugins successfully indexed.
        """
        count = 0
        for uplugin in sorted(Path(plugins_dir).rglob("*.uplugin")):
            try:
                self.parse_uplugin(uplugin)
                count += 1
            except Exception:
                logger.warning("Error parsing %s", uplugin, exc_info=True)
        return count

    def parse_uplugin(self, path: Path) -> None:
        """Parse a single .uplugin JSON file and insert into the database."""
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))

        plugin_id = insert_plugin(
            self._conn,
            name=path.stem,
            friendly_name=data.get("FriendlyName"),
            description=data.get("Description"),
            category=data.get("Category"),
            version=data.get("VersionName"),
            can_contain_content=data.get("bCanContainContent", False),
            is_beta=data.get("bIsBetaVersion", False),
            file_path=str(path),
        )

        for mod in data.get("Modules", []):
            insert_plugin_module(
                self._conn,
                plugin_id=plugin_id,
                module_name=mod.get("Name", ""),
                module_type=mod.get("Type"),
                loading_phase=mod.get("LoadingPhase"),
            )

        for dep in data.get("Plugins", []):
            if dep.get("Enabled", False):
                insert_plugin_dependency(
                    self._conn,
                    plugin_id=plugin_id,
                    depends_on=dep.get("Name", ""),
                )
