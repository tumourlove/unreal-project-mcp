"""Tests for UE config/INI parser."""
import sqlite3
from pathlib import Path
import pytest
from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.indexer.config_parser import ConfigParser

FIXTURES = Path(__file__).parent / "fixtures" / "sample_config"

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c

class TestConfigParser:
    def test_parses_sections(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        rows = conn.execute("SELECT DISTINCT section FROM config_entries").fetchall()
        sections = {r[0] for r in rows}
        assert "/Script/Engine.Engine" in sections
        assert "/Script/Engine.RendererSettings" in sections

    def test_parses_key_value_pairs(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        row = conn.execute("SELECT * FROM config_entries WHERE key = 'bUseFixedFrameRate'").fetchone()
        assert row is not None
        assert dict(row)["value"] == "True"

    def test_parses_array_additions(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        rows = conn.execute("SELECT * FROM config_entries WHERE key LIKE '+MapsToCook%'").fetchall()
        assert len(rows) >= 2

    def test_parses_gameplay_tag_entries(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        rows = conn.execute("SELECT * FROM config_entries WHERE key LIKE '+GameplayTagList%'").fetchall()
        assert len(rows) >= 3

    def test_fts_search_works(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        row = conn.execute("SELECT * FROM config_fts WHERE config_fts MATCH '\"bUseFixedFrameRate\"'").fetchone()
        assert row is not None

    def test_preserves_line_numbers(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        row = conn.execute("SELECT * FROM config_entries WHERE key = 'bUseFixedFrameRate'").fetchone()
        assert dict(row)["line"] > 0
