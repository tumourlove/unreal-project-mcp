"""Tests for Build.cs dependency parser."""
import sqlite3
from pathlib import Path

import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db import queries
from unreal_project_mcp.indexer.build_cs_parser import BuildCsParser

FIXTURES = Path(__file__).parent / "fixtures" / "sample_build_cs"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


class TestBuildCsParser:
    def test_extracts_public_dependencies(self, conn):
        mod_id = queries.insert_module(conn, name="MyGame", path="/Source/MyGame", module_type="GameModule")
        BuildCsParser(conn).parse_build_cs(FIXTURES / "MyGame.Build.cs", mod_id)
        conn.commit()
        deps = queries.get_module_dependencies(conn, mod_id, dep_type="public")
        names = {d["dependency_name"] for d in deps}
        assert "Core" in names and "Engine" in names and "InputCore" in names

    def test_extracts_private_dependencies(self, conn):
        mod_id = queries.insert_module(conn, name="MyGame", path="/Source/MyGame", module_type="GameModule")
        BuildCsParser(conn).parse_build_cs(FIXTURES / "MyGame.Build.cs", mod_id)
        conn.commit()
        deps = queries.get_module_dependencies(conn, mod_id, dep_type="private")
        names = {d["dependency_name"] for d in deps}
        assert "Slate" in names and "GameplayTags" in names

    def test_extracts_dynamic_dependencies(self, conn):
        mod_id = queries.insert_module(conn, name="MyGame", path="/Source/MyGame", module_type="GameModule")
        BuildCsParser(conn).parse_build_cs(FIXTURES / "MyGame.Build.cs", mod_id)
        conn.commit()
        deps = queries.get_module_dependencies(conn, mod_id, dep_type="dynamic")
        names = {d["dependency_name"] for d in deps}
        assert "OnlineSubsystem" in names

    def test_total_dependency_count(self, conn):
        mod_id = queries.insert_module(conn, name="MyGame", path="/Source/MyGame", module_type="GameModule")
        BuildCsParser(conn).parse_build_cs(FIXTURES / "MyGame.Build.cs", mod_id)
        conn.commit()
        all_deps = queries.get_module_dependencies(conn, mod_id)
        assert len(all_deps) == 9  # 4 public + 4 private + 1 dynamic
