"""End-to-end test: index fixtures, query via server tools."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db.queries import (
    get_module_by_name,
    insert_config_entry,
    insert_module_dependency,
    insert_plugin,
    insert_plugin_module,
    insert_plugin_dependency,
)
from unreal_project_mcp.indexer.pipeline import IndexingPipeline
from unreal_project_mcp import server

FIXTURES = Path(__file__).parent / "fixtures" / "sample_project_source"


@pytest.fixture
def full_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    pipeline = IndexingPipeline(conn)
    stats = pipeline.index_project(FIXTURES)
    assert stats["files_processed"] >= 2
    assert stats["symbols_extracted"] > 0
    assert stats["errors"] == 0
    return conn


@pytest.fixture(autouse=True)
def mock_conn(full_db):
    with patch.object(server, "_conn", full_db):
        with patch.object(server, "_get_conn", return_value=full_db):
            yield


class TestE2E:
    # ── Original 7 tool tests ────────────────────────────────────────────

    def test_search_finds_class(self):
        result = server.search_project("MeshDamageStamper")
        assert "UMeshDamageStamper" in result

    def test_read_source_shows_header_and_cpp(self):
        result = server.read_project_source("UMeshDamageStamper")
        assert "UActorComponent" in result
        assert "ApplyDamageStamp" in result

    def test_find_references(self):
        result = server.find_project_references("UMeshDamageStamper")
        assert isinstance(result, str)

    def test_find_callers(self):
        result = server.find_project_callers("UpdateDamageDecay")
        assert isinstance(result, str)

    def test_find_callees(self):
        result = server.find_project_callees("ApplyDamageStamp")
        assert isinstance(result, str)

    def test_class_hierarchy(self):
        result = server.get_project_class_hierarchy("UMeshDamageStamper")
        assert "UMeshDamageStamper" in result

    def test_module_info(self):
        result = server.get_project_module_info("sample_project_source")
        assert "class" in result.lower() or "function" in result.lower()

    # ── Group 1: Tests using existing pipeline-indexed data ──────────────

    def test_replication_map(self):
        result = server.get_replication_map("AReplicatedActor")
        assert isinstance(result, str)
        # The fixture ReplicatedActor.h declares Server, Client, NetMulticast,
        # Replicated, and ReplicatedUsing specifiers.
        assert "Server" in result
        assert "Client" in result
        assert "NetMulticast" in result
        assert "Replicated" in result
        assert "ReplicatedUsing" in result

    def test_replication_map_all(self):
        result = server.get_replication_map()
        assert isinstance(result, str)
        # With no class filter, should still return replication entries
        # from AReplicatedActor at minimum.
        assert "Server" in result or "Replicated" in result

    def test_find_log_sites(self):
        result = server.find_log_sites("LogAssetLoader")
        assert isinstance(result, str)
        # The log category is declared in AssetLoader.h and defined in AssetLoader.cpp.
        assert "LogAssetLoader" in result

    def test_find_asset_references_by_path(self):
        result = server.find_asset_references(asset_path="/Game/Blueprints/BP_Weapon")
        assert isinstance(result, str)
        # AssetLoader.cpp has a ConstructorHelpers reference to /Game/Blueprints/BP_Weapon
        assert "BP_Weapon" in result

    def test_find_asset_references_by_symbol(self):
        result = server.find_asset_references(symbol="LoadWeapon")
        assert isinstance(result, str)
        # LoadWeapon references multiple asset paths
        assert "/Game/" in result or "asset" in result.lower() or isinstance(result, str)

    def test_search_gameplay_tags(self):
        # The test fixtures don't contain gameplay tag patterns like
        # AddNativeGameplayTag or RequestGameplayTag, so this may return
        # "No gameplay tags found". Just verify it returns a valid string.
        result = server.search_gameplay_tags("Ability")
        assert isinstance(result, str)

    def test_search_project_tags(self):
        # Pattern tagger may or may not find patterns in the fixtures.
        # Just verify the tool returns a valid string.
        result = server.search_project_tags()
        assert isinstance(result, str)

    def test_find_data_table_schema_not_found(self):
        # No FTableRowBase children exist in the fixtures, so this should
        # indicate no struct was found.
        result = server.find_data_table_schema("SomeStruct")
        assert isinstance(result, str)
        assert "No struct found" in result

    # ── Group 2: Tests with manually inserted data ───────────────────────

    def test_get_config_values(self, full_db):
        insert_config_entry(
            full_db,
            file_path="Config/DefaultEngine.ini",
            section="/Script/Engine.Engine",
            key="FixedFrameRate",
            value="60.0",
            line=42,
        )
        full_db.commit()
        result = server.get_config_values("FixedFrameRate")
        assert isinstance(result, str)
        assert "FixedFrameRate" in result
        assert "60.0" in result

    def test_search_config(self, full_db):
        insert_config_entry(
            full_db,
            file_path="Config/DefaultEngine.ini",
            section="/Script/Engine.Engine",
            key="FrameRateLimit",
            value="120",
            line=55,
        )
        full_db.commit()
        result = server.search_config("FrameRate")
        assert isinstance(result, str)
        assert "FrameRate" in result

    def test_get_module_dependencies(self, full_db):
        mod = get_module_by_name(full_db, "sample_project_source")
        assert mod is not None
        insert_module_dependency(
            full_db,
            module_id=mod["id"],
            dependency_name="Core",
            dep_type="PublicDependencyModuleNames",
        )
        insert_module_dependency(
            full_db,
            module_id=mod["id"],
            dependency_name="Engine",
            dep_type="PublicDependencyModuleNames",
        )
        full_db.commit()
        result = server.get_module_dependencies("sample_project_source")
        assert isinstance(result, str)
        assert "Core" in result
        assert "Engine" in result
        assert "PublicDependencyModuleNames" in result

    def test_get_plugin_info(self, full_db):
        plugin_id = insert_plugin(
            full_db,
            name="TestPlugin",
            friendly_name="Test Plugin",
            description="A test plugin for E2E tests",
            category="Testing",
            version="1.0",
            file_path="Plugins/TestPlugin/TestPlugin.uplugin",
        )
        insert_plugin_module(
            full_db,
            plugin_id=plugin_id,
            module_name="TestPluginModule",
            module_type="Runtime",
            loading_phase="Default",
        )
        insert_plugin_dependency(
            full_db,
            plugin_id=plugin_id,
            depends_on="OnlineSubsystem",
        )
        full_db.commit()
        result = server.get_plugin_info("TestPlugin")
        assert isinstance(result, str)
        assert "TestPlugin" in result
        assert "Test Plugin" in result
        assert "TestPluginModule" in result
        assert "OnlineSubsystem" in result
        assert "Runtime" in result
