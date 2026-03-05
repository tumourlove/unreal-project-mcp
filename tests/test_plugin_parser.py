"""Tests for .uplugin parser."""
import sqlite3
from pathlib import Path

import pytest

from unreal_project_mcp.db import queries
from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.indexer.plugin_parser import PluginParser

FIXTURES = Path(__file__).parent / "fixtures" / "sample_plugins"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


class TestPluginParser:
    def test_parses_plugin_metadata(self, conn):
        PluginParser(conn).parse_uplugin(FIXTURES / "MyPlugin.uplugin")
        conn.commit()
        p = queries.get_plugin_by_name(conn, "MyPlugin")
        assert p is not None
        assert p["friendly_name"] == "My Awesome Plugin"
        assert p["description"] == "A test plugin for development"
        assert p["category"] == "Gameplay"
        assert p["version"] == "1.0"

    def test_parses_modules(self, conn):
        PluginParser(conn).parse_uplugin(FIXTURES / "MyPlugin.uplugin")
        conn.commit()
        p = queries.get_plugin_by_name(conn, "MyPlugin")
        modules = queries.get_plugin_modules(conn, p["id"])
        assert len(modules) == 2
        names = {m["module_name"] for m in modules}
        assert names == {"MyPluginRuntime", "MyPluginEditor"}

    def test_parses_dependencies(self, conn):
        PluginParser(conn).parse_uplugin(FIXTURES / "MyPlugin.uplugin")
        conn.commit()
        p = queries.get_plugin_by_name(conn, "MyPlugin")
        deps = queries.get_plugin_dependencies(conn, p["id"])
        names = {d["depends_on"] for d in deps}
        assert "GameplayAbilities" in names
        assert "OnlineSubsystem" in names

    def test_index_plugins_dir(self, conn):
        count = PluginParser(conn).index_plugins_dir(FIXTURES)
        conn.commit()
        assert count >= 1
