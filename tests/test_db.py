"""Tests for database schema and query layer."""

import sqlite3
import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db import queries


@pytest.fixture
def conn():
    """Create an in-memory SQLite database with schema initialized."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()


@pytest.fixture
def populated(conn):
    """Seed the database with a module, file, and a few symbols."""
    mod_id = queries.insert_module(
        conn, name="CoreModule", path="/Engine/Source/Runtime/Core",
        module_type="Runtime", build_cs_path="/Engine/Source/Runtime/Core/Core.Build.cs",
    )
    file_id = queries.insert_file(
        conn, path="/Engine/Source/Runtime/Core/Public/Actor.h",
        module_id=mod_id, file_type="header", line_count=500, last_modified=1000.0,
    )
    parent_sym = queries.insert_symbol(
        conn, name="AActor", qualified_name="AActor", kind="class",
        file_id=file_id, line_start=10, line_end=400,
        parent_symbol_id=None, access="public",
        signature="class AActor : public UObject",
        docstring="Base actor class", is_ue_macro=0,
    )
    child_sym = queries.insert_symbol(
        conn, name="GetActorLocation", qualified_name="AActor::GetActorLocation",
        kind="function", file_id=file_id, line_start=50, line_end=55,
        parent_symbol_id=parent_sym, access="public",
        signature="FVector GetActorLocation() const",
        docstring="Returns the location of this actor", is_ue_macro=0,
    )
    return {
        "conn": conn,
        "module_id": mod_id,
        "file_id": file_id,
        "parent_sym_id": parent_sym,
        "child_sym_id": child_sym,
    }


# ─── Schema tests ───────────────────────────────────────────────────────

class TestSchema:
    def test_creates_all_tables(self, conn):
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        expected = {"modules", "files", "symbols", "inheritance",
                    "references", "includes", "symbols_fts",
                    "source_fts", "meta"}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_schema_version(self, conn):
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert row is not None
        assert row[0] == "2"

    def test_creates_v2_tables(self, conn):
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        v2_tables = {
            "config_entries", "config_fts",
            "asset_references", "data_tables",
            "gameplay_tags", "tags_fts",
            "module_dependencies",
            "plugins", "plugin_modules", "plugin_dependencies",
            "log_categories", "replication_entries", "pattern_tags",
        }
        assert v2_tables.issubset(tables), f"Missing tables: {v2_tables - tables}"

    def test_fts_tables_exist(self, conn):
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "symbols_fts" in tables
        assert "source_fts" in tables


# ─── Schema v2 tests ────────────────────────────────────────────────────

class TestSchemaV2:
    def test_creates_v2_tables(self, conn):
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        v2_tables = {
            "config_entries", "config_fts",
            "asset_references", "data_tables",
            "gameplay_tags", "tags_fts",
            "module_dependencies",
            "plugins", "plugin_modules", "plugin_dependencies",
            "log_categories", "replication_entries", "pattern_tags",
        }
        assert v2_tables.issubset(tables), f"Missing tables: {v2_tables - tables}"

    def test_schema_version_is_2(self, conn):
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert row[0] == "2"

    def test_config_fts_trigger_works(self, conn):
        conn.execute(
            "INSERT INTO config_entries (file_path, section, key, value, line) "
            "VALUES ('/Config/DefaultEngine.ini', '/Script/Engine', 'bUseFixedFrameRate', 'True', 10)"
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM config_fts WHERE config_fts MATCH 'bUseFixedFrameRate'"
        ).fetchone()
        assert row is not None

    def test_tags_fts_trigger_works(self, conn):
        conn.execute(
            "INSERT INTO gameplay_tags (tag, source_type, usage_kind, file_path, line) "
            "VALUES ('Ability.Skill.Fireball', 'cpp', 'definition', '/test.cpp', 10)"
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM tags_fts WHERE tags_fts MATCH 'Fireball'"
        ).fetchone()
        assert row is not None


# ─── Insert + query symbol tests ────────────────────────────────────────

class TestSymbolCRUD:
    def test_insert_and_get_symbol_by_id(self, populated):
        sym = queries.get_symbol_by_id(populated["conn"], populated["parent_sym_id"])
        assert sym is not None
        assert sym["name"] == "AActor"
        assert sym["kind"] == "class"

    def test_get_symbol_by_qualified_name(self, populated):
        sym = queries.get_symbol_by_name(populated["conn"], "AActor::GetActorLocation")
        assert sym is not None
        assert sym["name"] == "GetActorLocation"

    def test_get_symbol_by_short_name(self, populated):
        sym = queries.get_symbol_by_name(populated["conn"], "AActor")
        assert sym is not None

    def test_get_symbols_by_name(self, populated):
        results = queries.get_symbols_by_name(populated["conn"], "AActor")
        assert len(results) == 1
        assert results[0]["kind"] == "class"

    def test_get_symbols_by_name_with_kind(self, populated):
        results = queries.get_symbols_by_name(populated["conn"], "AActor", kind="function")
        assert len(results) == 0

    def test_get_symbol_not_found(self, populated):
        assert queries.get_symbol_by_name(populated["conn"], "NonExistent") is None


# ─── FTS symbol search tests ────────────────────────────────────────────

class TestSymbolFTS:
    def test_fts_search_finds_symbol(self, populated):
        results = queries.search_symbols_fts(populated["conn"], "Actor")
        assert len(results) >= 1
        names = [r["name"] for r in results]
        assert "AActor" in names

    def test_fts_search_by_docstring(self, populated):
        results = queries.search_symbols_fts(populated["conn"], "location")
        assert len(results) >= 1

    def test_fts_search_empty(self, populated):
        results = queries.search_symbols_fts(populated["conn"], "zzzznonexistent")
        assert len(results) == 0


# ─── Inheritance tests ───────────────────────────────────────────────────

class TestInheritance:
    def test_insert_and_query_parents(self, populated):
        conn = populated["conn"]
        # Create a base class symbol
        base_id = queries.insert_symbol(
            conn, name="UObject", qualified_name="UObject", kind="class",
            file_id=populated["file_id"], line_start=1, line_end=100,
            parent_symbol_id=None, access="public",
            signature="class UObject", docstring="Base UObject", is_ue_macro=0,
        )
        queries.insert_inheritance(conn, child_id=populated["parent_sym_id"], parent_id=base_id)

        parents = queries.get_inheritance_parents(conn, populated["parent_sym_id"])
        assert len(parents) == 1
        assert parents[0]["name"] == "UObject"

    def test_insert_and_query_children(self, populated):
        conn = populated["conn"]
        base_id = queries.insert_symbol(
            conn, name="UObject", qualified_name="UObject", kind="class",
            file_id=populated["file_id"], line_start=1, line_end=100,
            parent_symbol_id=None, access="public",
            signature="class UObject", docstring="Base UObject", is_ue_macro=0,
        )
        queries.insert_inheritance(conn, child_id=populated["parent_sym_id"], parent_id=base_id)

        children = queries.get_inheritance_children(conn, base_id)
        assert len(children) == 1
        assert children[0]["name"] == "AActor"


# ─── References tests ───────────────────────────────────────────────────

class TestReferences:
    def test_insert_and_query_references_to(self, populated):
        conn = populated["conn"]
        # Create a caller symbol
        caller_id = queries.insert_symbol(
            conn, name="Tick", qualified_name="AMyActor::Tick", kind="function",
            file_id=populated["file_id"], line_start=200, line_end=210,
            parent_symbol_id=None, access="public",
            signature="void Tick(float)", docstring="", is_ue_macro=0,
        )
        queries.insert_reference(
            conn, from_symbol_id=caller_id, to_symbol_id=populated["child_sym_id"],
            ref_kind="call", file_id=populated["file_id"], line=205,
        )

        refs = queries.get_references_to(conn, populated["child_sym_id"])
        assert len(refs) == 1
        assert refs[0]["from_name"] == "Tick"
        assert refs[0]["line"] == 205

    def test_insert_and_query_references_from(self, populated):
        conn = populated["conn"]
        target_id = queries.insert_symbol(
            conn, name="SetActorLocation", qualified_name="AActor::SetActorLocation",
            kind="function", file_id=populated["file_id"],
            line_start=60, line_end=65, parent_symbol_id=populated["parent_sym_id"],
            access="public", signature="void SetActorLocation(FVector)",
            docstring="", is_ue_macro=0,
        )
        queries.insert_reference(
            conn, from_symbol_id=populated["child_sym_id"], to_symbol_id=target_id,
            ref_kind="call", file_id=populated["file_id"], line=52,
        )

        refs = queries.get_references_from(conn, populated["child_sym_id"])
        assert len(refs) == 1
        assert refs[0]["to_name"] == "SetActorLocation"

    def test_references_filter_by_kind(self, populated):
        conn = populated["conn"]
        caller_id = queries.insert_symbol(
            conn, name="Foo", qualified_name="Foo", kind="function",
            file_id=populated["file_id"], line_start=300, line_end=310,
            parent_symbol_id=None, access="public",
            signature="void Foo()", docstring="", is_ue_macro=0,
        )
        queries.insert_reference(
            conn, from_symbol_id=caller_id, to_symbol_id=populated["child_sym_id"],
            ref_kind="call", file_id=populated["file_id"], line=305,
        )
        queries.insert_reference(
            conn, from_symbol_id=caller_id, to_symbol_id=populated["parent_sym_id"],
            ref_kind="type_use", file_id=populated["file_id"], line=301,
        )

        call_refs = queries.get_references_to(conn, populated["child_sym_id"], ref_kind="call")
        assert len(call_refs) == 1

        type_refs = queries.get_references_to(conn, populated["parent_sym_id"], ref_kind="type_use")
        assert len(type_refs) == 1


# ─── Source FTS tests ────────────────────────────────────────────────────

class TestSourceFTS:
    def test_source_fts_search(self, populated):
        conn = populated["conn"]
        # Insert some source lines
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (populated["file_id"], 50, "FVector GetActorLocation() const"),
        )
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (populated["file_id"], 51, "{ return RootComponent->GetComponentLocation(); }"),
        )
        conn.commit()

        results = queries.search_source_fts(conn, "GetActorLocation")
        assert len(results) >= 1
        assert results[0]["line_number"] == 50

    def test_source_fts_scope_filter(self, populated):
        conn = populated["conn"]
        # Add a .cpp file
        cpp_file = queries.insert_file(
            conn, path="/Engine/Source/Runtime/Core/Private/Actor.cpp",
            module_id=populated["module_id"], file_type="source",
            line_count=1000, last_modified=1000.0,
        )
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (cpp_file, 10, "void AActor::BeginPlay()"),
        )
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (populated["file_id"], 15, "virtual void BeginPlay();"),
        )
        conn.commit()

        # Search only headers
        results = queries.search_source_fts(conn, "BeginPlay", scope="header")
        assert len(results) == 1
        assert results[0]["file_id"] == populated["file_id"]


# ─── Module + file query tests ──────────────────────────────────────────

class TestModuleFileQueries:
    def test_get_file_by_path(self, populated):
        f = queries.get_file_by_path(
            populated["conn"], "/Engine/Source/Runtime/Core/Public/Actor.h"
        )
        assert f is not None
        assert f["line_count"] == 500

    def test_get_module_by_name(self, populated):
        m = queries.get_module_by_name(populated["conn"], "CoreModule")
        assert m is not None
        assert m["module_type"] == "Runtime"

    def test_get_symbols_in_module(self, populated):
        syms = queries.get_symbols_in_module(populated["conn"], "CoreModule")
        assert len(syms) >= 2  # AActor + GetActorLocation

    def test_get_module_stats(self, populated):
        stats = queries.get_module_stats(populated["conn"], "CoreModule")
        assert stats is not None
        assert stats["file_count"] == 1
        assert stats["symbol_counts"]["class"] == 1
        assert stats["symbol_counts"]["function"] == 1


# ─── Duplicate module tests ─────────────────────────────────────────────

class TestDuplicateModule:
    def test_duplicate_module_returns_existing_id(self, conn):
        mod_id1 = queries.insert_module(conn, name="TestMod", path="/a", module_type="Runtime")
        mod_id2 = queries.insert_module(conn, name="TestMod", path="/a", module_type="Runtime")
        assert mod_id1 == mod_id2


# ─── V2 Insert tests ────────────────────────────────────────────────────

class TestV2Inserts:
    def test_insert_config_entry(self, conn):
        row_id = queries.insert_config_entry(
            conn, file_path="/Config/DefaultEngine.ini",
            section="/Script/Engine", key="bUseFixedFrameRate",
            value="True", line=10,
        )
        assert row_id > 0
        row = conn.execute("SELECT * FROM config_entries WHERE id = ?", (row_id,)).fetchone()
        assert row is not None
        assert dict(row)["key"] == "bUseFixedFrameRate"

    def test_insert_asset_reference(self, populated):
        conn = populated["conn"]
        row_id = queries.insert_asset_reference(
            conn, symbol_id=populated["parent_sym_id"],
            asset_path="/Game/Meshes/SM_Chair.SM_Chair",
            ref_type="soft_object", file_id=populated["file_id"], line=100,
        )
        assert row_id > 0
        row = conn.execute("SELECT * FROM asset_references WHERE id = ?", (row_id,)).fetchone()
        assert dict(row)["asset_path"] == "/Game/Meshes/SM_Chair.SM_Chair"

    def test_insert_gameplay_tag(self, conn):
        row_id = queries.insert_gameplay_tag(
            conn, tag="Ability.Skill.Fireball",
            source_type="cpp", usage_kind="definition",
            file_path="/Source/MyGame/Abilities.cpp", line=42,
        )
        assert row_id > 0
        row = conn.execute("SELECT * FROM gameplay_tags WHERE id = ?", (row_id,)).fetchone()
        assert dict(row)["tag"] == "Ability.Skill.Fireball"

    def test_insert_gameplay_tag_with_symbol(self, populated):
        conn = populated["conn"]
        row_id = queries.insert_gameplay_tag(
            conn, tag="Combat.Damage.Fire",
            source_type="cpp", usage_kind="usage",
            symbol_id=populated["child_sym_id"],
        )
        assert row_id > 0

    def test_insert_module_dependency(self, populated):
        conn = populated["conn"]
        queries.insert_module_dependency(
            conn, module_id=populated["module_id"],
            dependency_name="Engine", dep_type="public",
        )
        row = conn.execute(
            "SELECT * FROM module_dependencies WHERE module_id = ? AND dependency_name = ?",
            (populated["module_id"], "Engine"),
        ).fetchone()
        assert row is not None
        assert dict(row)["dep_type"] == "public"

    def test_insert_module_dependency_ignore_duplicate(self, populated):
        conn = populated["conn"]
        queries.insert_module_dependency(
            conn, module_id=populated["module_id"],
            dependency_name="Engine", dep_type="public",
        )
        # Should not raise
        queries.insert_module_dependency(
            conn, module_id=populated["module_id"],
            dependency_name="Engine", dep_type="public",
        )

    def test_insert_plugin(self, conn):
        plugin_id = queries.insert_plugin(
            conn, name="MyPlugin", friendly_name="My Plugin",
            description="A test plugin", category="Gameplay",
            version="1.0", can_contain_content=True, is_beta=False,
            file_path="/Plugins/MyPlugin/MyPlugin.uplugin",
        )
        assert plugin_id > 0
        row = conn.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,)).fetchone()
        assert dict(row)["name"] == "MyPlugin"

    def test_insert_plugin_duplicate_returns_existing(self, conn):
        id1 = queries.insert_plugin(
            conn, name="MyPlugin",
            file_path="/Plugins/MyPlugin/MyPlugin.uplugin",
        )
        id2 = queries.insert_plugin(
            conn, name="MyPlugin",
            file_path="/Plugins/MyPlugin/MyPlugin.uplugin",
        )
        assert id1 == id2

    def test_insert_plugin_module(self, conn):
        plugin_id = queries.insert_plugin(
            conn, name="TestPlugin",
            file_path="/Plugins/TestPlugin/TestPlugin.uplugin",
        )
        queries.insert_plugin_module(
            conn, plugin_id=plugin_id, module_name="TestPluginModule",
            module_type="Runtime", loading_phase="Default",
        )
        row = conn.execute(
            "SELECT * FROM plugin_modules WHERE plugin_id = ?", (plugin_id,)
        ).fetchone()
        assert dict(row)["module_name"] == "TestPluginModule"

    def test_insert_plugin_dependency(self, conn):
        plugin_id = queries.insert_plugin(
            conn, name="DepPlugin",
            file_path="/Plugins/DepPlugin/DepPlugin.uplugin",
        )
        queries.insert_plugin_dependency(conn, plugin_id=plugin_id, depends_on="OnlineSubsystem")
        row = conn.execute(
            "SELECT * FROM plugin_dependencies WHERE plugin_id = ?", (plugin_id,)
        ).fetchone()
        assert dict(row)["depends_on"] == "OnlineSubsystem"

    def test_insert_log_category(self, populated):
        conn = populated["conn"]
        queries.insert_log_category(
            conn, name="LogMyGame", file_id=populated["file_id"],
            line=5, verbosity="Log",
        )
        row = conn.execute(
            "SELECT * FROM log_categories WHERE name = ?", ("LogMyGame",)
        ).fetchone()
        assert row is not None
        assert dict(row)["verbosity"] == "Log"

    def test_insert_log_category_ignore_duplicate(self, populated):
        conn = populated["conn"]
        queries.insert_log_category(conn, name="LogDup", file_id=populated["file_id"], line=1)
        # Should not raise
        queries.insert_log_category(conn, name="LogDup", file_id=populated["file_id"], line=2)

    def test_insert_replication_entry(self, populated):
        conn = populated["conn"]
        queries.insert_replication_entry(
            conn, symbol_id=populated["child_sym_id"],
            rep_type="replicated", condition="COND_OwnerOnly",
            callback="OnRep_Location",
        )
        row = conn.execute(
            "SELECT * FROM replication_entries WHERE symbol_id = ?",
            (populated["child_sym_id"],),
        ).fetchone()
        assert dict(row)["rep_type"] == "replicated"
        assert dict(row)["condition"] == "COND_OwnerOnly"

    def test_insert_pattern_tag(self, populated):
        conn = populated["conn"]
        queries.insert_pattern_tag(
            conn, symbol_id=populated["parent_sym_id"],
            tag_kind="singleton", metadata='{"scope": "game"}',
        )
        row = conn.execute(
            "SELECT * FROM pattern_tags WHERE symbol_id = ?",
            (populated["parent_sym_id"],),
        ).fetchone()
        assert dict(row)["tag_kind"] == "singleton"

    def test_insert_data_table(self, populated):
        conn = populated["conn"]
        queries.insert_data_table(
            conn, struct_symbol_id=populated["parent_sym_id"],
            table_path="/Game/Data/DT_Weapons",
            table_name="DT_Weapons",
        )
        row = conn.execute(
            "SELECT * FROM data_tables WHERE struct_symbol_id = ?",
            (populated["parent_sym_id"],),
        ).fetchone()
        assert dict(row)["table_name"] == "DT_Weapons"


# ─── V2 Query tests ─────────────────────────────────────────────────────

class TestV2Queries:
    def test_search_config_fts(self, conn):
        queries.insert_config_entry(
            conn, file_path="/Config/DefaultEngine.ini",
            section="/Script/Engine", key="bUseFixedFrameRate",
            value="True", line=10,
        )
        conn.commit()
        results = queries.search_config_fts(conn, "bUseFixedFrameRate")
        assert len(results) >= 1
        assert results[0]["key"] == "bUseFixedFrameRate"

    def test_get_config_by_key(self, conn):
        queries.insert_config_entry(
            conn, file_path="/Config/DefaultEngine.ini",
            section="/Script/Engine", key="MaxFPS", value="60", line=20,
        )
        queries.insert_config_entry(
            conn, file_path="/Config/DefaultGame.ini",
            section="/Script/Game", key="MaxFPS", value="120", line=5,
        )
        # Without section filter
        results = queries.get_config_by_key(conn, "MaxFPS")
        assert len(results) == 2
        # With section filter
        results = queries.get_config_by_key(conn, "MaxFPS", section="/Script/Engine")
        assert len(results) == 1
        assert results[0]["value"] == "60"

    def test_get_asset_references_by_path(self, populated):
        conn = populated["conn"]
        queries.insert_asset_reference(
            conn, symbol_id=populated["parent_sym_id"],
            asset_path="/Game/Meshes/SM_Chair.SM_Chair",
            ref_type="soft_object", file_id=populated["file_id"], line=100,
        )
        results = queries.get_asset_references_by_path(conn, "SM_Chair")
        assert len(results) >= 1
        assert "SM_Chair" in results[0]["asset_path"]

    def test_get_asset_references_by_symbol(self, populated):
        conn = populated["conn"]
        queries.insert_asset_reference(
            conn, symbol_id=populated["parent_sym_id"],
            asset_path="/Game/Meshes/SM_Table.SM_Table",
            ref_type="hard_object", file_id=populated["file_id"], line=101,
        )
        results = queries.get_asset_references_by_symbol(conn, populated["parent_sym_id"])
        assert len(results) >= 1
        assert results[0]["asset_path"] == "/Game/Meshes/SM_Table.SM_Table"

    def test_search_gameplay_tags_fts(self, conn):
        queries.insert_gameplay_tag(
            conn, tag="Ability.Skill.Fireball",
            source_type="cpp", usage_kind="definition",
            file_path="/Source/test.cpp", line=10,
        )
        conn.commit()
        results = queries.search_gameplay_tags_fts(conn, "Fireball")
        assert len(results) >= 1
        assert results[0]["tag"] == "Ability.Skill.Fireball"

    def test_search_gameplay_tags_fts_with_usage_kind(self, conn):
        queries.insert_gameplay_tag(
            conn, tag="Combat.Damage.Fire",
            source_type="cpp", usage_kind="definition",
            file_path="/Source/a.cpp", line=1,
        )
        queries.insert_gameplay_tag(
            conn, tag="Combat.Damage.Ice",
            source_type="cpp", usage_kind="usage",
            file_path="/Source/b.cpp", line=2,
        )
        conn.commit()
        results = queries.search_gameplay_tags_fts(conn, "Combat", usage_kind="definition")
        tags = [r["tag"] for r in results]
        assert "Combat.Damage.Fire" in tags
        assert "Combat.Damage.Ice" not in tags

    def test_get_module_dependencies(self, populated):
        conn = populated["conn"]
        queries.insert_module_dependency(
            conn, module_id=populated["module_id"],
            dependency_name="Engine", dep_type="public",
        )
        queries.insert_module_dependency(
            conn, module_id=populated["module_id"],
            dependency_name="Slate", dep_type="private",
        )
        results = queries.get_module_dependencies(conn, populated["module_id"])
        assert len(results) == 2

        results = queries.get_module_dependencies(conn, populated["module_id"], dep_type="public")
        assert len(results) == 1
        assert results[0]["dependency_name"] == "Engine"

    def test_get_module_dependents(self, populated):
        conn = populated["conn"]
        queries.insert_module_dependency(
            conn, module_id=populated["module_id"],
            dependency_name="Engine", dep_type="public",
        )
        results = queries.get_module_dependents(conn, "Engine")
        assert len(results) >= 1
        assert results[0]["name"] == "CoreModule"

    def test_get_plugin_by_name(self, conn):
        queries.insert_plugin(
            conn, name="MyPlugin", friendly_name="My Plugin",
            file_path="/Plugins/MyPlugin/MyPlugin.uplugin",
        )
        result = queries.get_plugin_by_name(conn, "MyPlugin")
        assert result is not None
        assert result["friendly_name"] == "My Plugin"

    def test_get_plugin_by_name_not_found(self, conn):
        result = queries.get_plugin_by_name(conn, "NonExistent")
        assert result is None

    def test_get_plugin_modules(self, conn):
        plugin_id = queries.insert_plugin(
            conn, name="TestPlugin",
            file_path="/Plugins/TestPlugin/TestPlugin.uplugin",
        )
        queries.insert_plugin_module(
            conn, plugin_id=plugin_id, module_name="TestMod",
            module_type="Runtime", loading_phase="Default",
        )
        results = queries.get_plugin_modules(conn, plugin_id)
        assert len(results) == 1
        assert results[0]["module_name"] == "TestMod"

    def test_get_plugin_dependencies(self, conn):
        plugin_id = queries.insert_plugin(
            conn, name="DepPlugin",
            file_path="/Plugins/DepPlugin/DepPlugin.uplugin",
        )
        queries.insert_plugin_dependency(conn, plugin_id=plugin_id, depends_on="OnlineSubsystem")
        queries.insert_plugin_dependency(conn, plugin_id=plugin_id, depends_on="Niagara")
        results = queries.get_plugin_dependencies(conn, plugin_id)
        assert len(results) == 2
        dep_names = [r["depends_on"] for r in results]
        assert "OnlineSubsystem" in dep_names

    def test_get_log_category(self, populated):
        conn = populated["conn"]
        queries.insert_log_category(
            conn, name="LogMyGame", file_id=populated["file_id"],
            line=5, verbosity="Log",
        )
        result = queries.get_log_category(conn, "LogMyGame")
        assert result is not None
        assert result["verbosity"] == "Log"
        assert "path" in result  # JOINs files for path

    def test_get_log_category_not_found(self, conn):
        result = queries.get_log_category(conn, "LogNonExistent")
        assert result is None

    def test_get_replication_entries(self, populated):
        conn = populated["conn"]
        queries.insert_replication_entry(
            conn, symbol_id=populated["child_sym_id"],
            rep_type="replicated", condition="COND_OwnerOnly",
        )
        results = queries.get_replication_entries(conn)
        assert len(results) >= 1
        assert results[0]["rep_type"] == "replicated"

    def test_get_replication_entries_by_class(self, populated):
        conn = populated["conn"]
        queries.insert_replication_entry(
            conn, symbol_id=populated["child_sym_id"],
            rep_type="replicated", condition="COND_OwnerOnly",
        )
        # child_sym's parent_symbol_id is parent_sym_id (AActor)
        results = queries.get_replication_entries(conn, class_name="AActor")
        assert len(results) >= 1
        assert results[0]["condition"] == "COND_OwnerOnly"

        # Non-matching class
        results = queries.get_replication_entries(conn, class_name="APawn")
        assert len(results) == 0

    def test_get_pattern_tags(self, populated):
        conn = populated["conn"]
        queries.insert_pattern_tag(
            conn, symbol_id=populated["parent_sym_id"],
            tag_kind="singleton", metadata='{"scope": "game"}',
        )
        queries.insert_pattern_tag(
            conn, symbol_id=populated["child_sym_id"],
            tag_kind="factory",
        )
        results = queries.get_pattern_tags(conn, kind="singleton")
        assert len(results) == 1
        assert results[0]["tag_kind"] == "singleton"

    def test_get_pattern_tags_with_query(self, populated):
        conn = populated["conn"]
        queries.insert_pattern_tag(
            conn, symbol_id=populated["parent_sym_id"],
            tag_kind="singleton",
        )
        results = queries.get_pattern_tags(conn, query="Actor")
        assert len(results) >= 1

    def test_get_data_tables_by_struct(self, populated):
        conn = populated["conn"]
        queries.insert_data_table(
            conn, struct_symbol_id=populated["parent_sym_id"],
            table_path="/Game/Data/DT_Weapons",
            table_name="DT_Weapons",
        )
        queries.insert_data_table(
            conn, struct_symbol_id=populated["parent_sym_id"],
            table_path="/Game/Data/DT_Armor",
            table_name="DT_Armor",
        )
        results = queries.get_data_tables_by_struct(conn, populated["parent_sym_id"])
        assert len(results) == 2
        names = [r["table_name"] for r in results]
        assert "DT_Weapons" in names
        assert "DT_Armor" in names
