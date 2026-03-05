"""Tests for gameplay tag scanner."""
import sqlite3
from pathlib import Path
import pytest
from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db import queries
from unreal_project_mcp.indexer.tag_scanner import TagScanner


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


class TestTagScannerFromConfig:
    def test_extracts_tags_from_ini(self, conn):
        queries.insert_config_entry(
            conn, file_path="/Config/DefaultGame.ini",
            section="/Script/GameplayTags.GameplayTagsSettings",
            key="+GameplayTagList",
            value='(Tag="Ability.Skill.Fireball",DevComment="")',
            line=10,
        )
        conn.commit()
        scanner = TagScanner(conn)
        scanner.scan_config_tags()
        conn.commit()
        rows = conn.execute("SELECT * FROM gameplay_tags").fetchall()
        tags = {dict(r)["tag"] for r in rows}
        assert "Ability.Skill.Fireball" in tags

    def test_multiple_tags(self, conn):
        for i, tag in enumerate(["Ability.A", "Ability.B", "Status.C"]):
            queries.insert_config_entry(
                conn, file_path="/Config/test.ini",
                section="/Script/GameplayTags", key="+GameplayTagList",
                value=f'(Tag="{tag}")', line=i + 1,
            )
        conn.commit()
        count = TagScanner(conn).scan_config_tags()
        conn.commit()
        assert count == 3


class TestTagScannerFromCpp:
    def test_extracts_native_tag_definitions(self, conn):
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.cpp", module_id=mod_id, file_type="source", line_count=10)
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (file_id, 5, 'AddNativeGameplayTag(TEXT("Ability.Skill.Fireball"))'),
        )
        conn.commit()
        TagScanner(conn).scan_cpp_tags()
        conn.commit()
        rows = conn.execute("SELECT * FROM gameplay_tags WHERE usage_kind = 'definition'").fetchall()
        assert len(rows) >= 1

    def test_extracts_tag_requests(self, conn):
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.cpp", module_id=mod_id, file_type="source", line_count=10)
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (file_id, 10, 'RequestGameplayTag(FName(TEXT("Status.Buff.Shield")))'),
        )
        conn.commit()
        TagScanner(conn).scan_cpp_tags()
        conn.commit()
        rows = conn.execute("SELECT * FROM gameplay_tags WHERE usage_kind = 'request'").fetchall()
        assert len(rows) >= 1


class TestTagScannerFromCsv:
    def test_extracts_tags_from_csv(self, conn, tmp_path):
        csv_file = tmp_path / "DT_Abilities.csv"
        csv_file.write_text("Name,GameplayTag,Damage\nFireball,Ability.Skill.Fireball,100\n")
        count = TagScanner(conn).scan_csv_tags(tmp_path)
        conn.commit()
        assert count == 1
        rows = conn.execute("SELECT * FROM gameplay_tags").fetchall()
        assert dict(rows[0])["tag"] == "Ability.Skill.Fireball"
