"""Tests for pattern tagger."""
import sqlite3
import pytest
from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db import queries
from unreal_project_mcp.indexer.pattern_tagger import PatternTagger


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


class TestSubsystemTagging:
    def test_tags_world_subsystem(self, conn):
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.h", module_id=mod_id, file_type="header", line_count=50)
        base_id = queries.insert_symbol(
            conn, name="UWorldSubsystem", qualified_name="UWorldSubsystem",
            kind="class", file_id=file_id, line_start=1, line_end=10,
            parent_symbol_id=None, access="public", signature="", docstring="",
        )
        child_id = queries.insert_symbol(
            conn, name="UMyWorldSubsystem", qualified_name="UMyWorldSubsystem",
            kind="class", file_id=file_id, line_start=20, line_end=40,
            parent_symbol_id=None, access="public", signature="", docstring="",
        )
        queries.insert_inheritance(conn, child_id=child_id, parent_id=base_id)
        conn.commit()
        PatternTagger(conn).tag_subsystems()
        conn.commit()
        tags = queries.get_pattern_tags(conn, kind="subsystem")
        assert len(tags) == 1
        assert tags[0]["symbol_name"] == "UMyWorldSubsystem"


class TestAnimNotifyTagging:
    def test_tags_anim_notify(self, conn):
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.h", module_id=mod_id, file_type="header", line_count=50)
        base_id = queries.insert_symbol(
            conn, name="UAnimNotify", qualified_name="UAnimNotify",
            kind="class", file_id=file_id, line_start=1, line_end=10,
            parent_symbol_id=None, access="public", signature="", docstring="",
        )
        child_id = queries.insert_symbol(
            conn, name="UAnimNotify_Attack", qualified_name="UAnimNotify_Attack",
            kind="class", file_id=file_id, line_start=20, line_end=40,
            parent_symbol_id=None, access="public", signature="", docstring="",
        )
        queries.insert_inheritance(conn, child_id=child_id, parent_id=base_id)
        conn.commit()
        PatternTagger(conn).tag_anim_notifies()
        conn.commit()
        tags = queries.get_pattern_tags(conn, kind="anim_notify")
        assert len(tags) == 1
        assert tags[0]["symbol_name"] == "UAnimNotify_Attack"


class TestConsoleCommandTagging:
    def test_tags_console_commands(self, conn):
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.cpp", module_id=mod_id, file_type="source", line_count=50)
        # Create a function that contains the console command registration
        func_id = queries.insert_symbol(
            conn, name="RegisterCommands", qualified_name="RegisterCommands",
            kind="function", file_id=file_id, line_start=5, line_end=15,
            parent_symbol_id=None, access="public", signature="void RegisterCommands()", docstring="",
        )
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (file_id, 10,
             'IConsoleManager::Get().RegisterConsoleCommand(TEXT("my.debug.cmd"), TEXT("Help"))'),
        )
        conn.commit()
        PatternTagger(conn).tag_console_commands()
        conn.commit()
        tags = queries.get_pattern_tags(conn, kind="console_command")
        assert len(tags) >= 1


class TestTagAll:
    def test_tag_all_returns_total(self, conn):
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.h", module_id=mod_id, file_type="header", line_count=50)
        base_id = queries.insert_symbol(
            conn, name="UEngineSubsystem", qualified_name="UEngineSubsystem",
            kind="class", file_id=file_id, line_start=1, line_end=10,
            parent_symbol_id=None, access="public", signature="", docstring="",
        )
        child_id = queries.insert_symbol(
            conn, name="UMyEngineSubsystem", qualified_name="UMyEngineSubsystem",
            kind="class", file_id=file_id, line_start=20, line_end=40,
            parent_symbol_id=None, access="public", signature="", docstring="",
        )
        queries.insert_inheritance(conn, child_id=child_id, parent_id=base_id)
        conn.commit()
        count = PatternTagger(conn).tag_all()
        conn.commit()
        assert count >= 1
