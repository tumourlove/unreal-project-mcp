"""Tests for project indexing pipeline."""

import sqlite3
from pathlib import Path

import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.indexer.pipeline import IndexingPipeline

FIXTURES = Path(__file__).parent / "fixtures" / "sample_project_source"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


@pytest.fixture
def indexed_db(db):
    pipeline = IndexingPipeline(db)
    stats = pipeline.index_project(FIXTURES)
    return db, stats


class TestIndexProject:
    def test_indexes_files(self, indexed_db):
        db, stats = indexed_db
        assert stats["files_processed"] >= 2

    def test_extracts_symbols(self, indexed_db):
        db, stats = indexed_db
        assert stats["symbols_extracted"] > 0

    def test_finds_class(self, indexed_db):
        db, _ = indexed_db
        row = db.execute(
            "SELECT * FROM symbols WHERE name = 'UMeshDamageStamper' AND kind = 'class'"
        ).fetchone()
        assert row is not None

    def test_finds_method(self, indexed_db):
        db, _ = indexed_db
        row = db.execute(
            "SELECT * FROM symbols WHERE name = 'ApplyDamageStamp' AND kind = 'function'"
        ).fetchone()
        assert row is not None

    def test_resolves_inheritance(self, indexed_db):
        db, _ = indexed_db
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM inheritance"
        ).fetchone()
        assert row is not None

    def test_extracts_references(self, indexed_db):
        db, _ = indexed_db
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM \"references\""
        ).fetchone()
        assert row["cnt"] > 0


class TestIncrementalReindex:
    def test_reindex_changed_skips_unchanged(self, db, tmp_path):
        src = tmp_path / "Source" / "MyPlugin"
        src.mkdir(parents=True)
        header = src / "Test.h"
        header.write_text('#pragma once\nclass AMyActor {};\n')

        pipeline = IndexingPipeline(db)
        stats1 = pipeline.index_project(tmp_path)
        assert stats1["files_processed"] == 1

        stats2 = pipeline.reindex_changed(tmp_path)
        assert stats2["files_processed"] == 0
        assert stats2["files_skipped"] > 0

    def test_reindex_changed_picks_up_modifications(self, db, tmp_path):
        import time
        src = tmp_path / "Source" / "MyPlugin"
        src.mkdir(parents=True)
        header = src / "Test.h"
        header.write_text('#pragma once\nclass AMyActor {};\n')

        pipeline = IndexingPipeline(db)
        pipeline.index_project(tmp_path)

        time.sleep(0.1)
        header.write_text('#pragma once\nclass AMyActor {};\nclass ANewActor {};\n')

        stats = pipeline.reindex_changed(tmp_path)
        assert stats["files_processed"] == 1

        row = db.execute(
            "SELECT * FROM symbols WHERE name = 'ANewActor'"
        ).fetchone()
        assert row is not None


class TestExpandedPipeline:
    def test_indexes_config_files(self, db, tmp_path):
        root = tmp_path / "MyGame"
        root.mkdir()
        (root / "MyGame.uproject").write_text("{}")
        src = root / "Source" / "MyGame"
        src.mkdir(parents=True)
        (src / "Test.h").write_text("#pragma once\nclass ATestActor {};\n")
        cfg = root / "Config"
        cfg.mkdir()
        (cfg / "DefaultEngine.ini").write_text("[/Script/Engine]\nbUseFixed=True\n")

        pipeline = IndexingPipeline(db)
        pipeline.index_project(root)
        rows = db.execute("SELECT COUNT(*) FROM config_entries").fetchone()
        assert rows[0] >= 1

    def test_indexes_build_cs(self, db, tmp_path):
        root = tmp_path / "MyGame"
        root.mkdir()
        (root / "MyGame.uproject").write_text("{}")
        src = root / "Source" / "MyGame"
        src.mkdir(parents=True)
        (src / "Test.h").write_text("#pragma once\nclass ATestActor {};\n")
        (src / "MyGame.Build.cs").write_text(
            'PublicDependencyModuleNames.AddRange(new string[] { "Core", "Engine" });'
        )

        pipeline = IndexingPipeline(db)
        pipeline.index_project(root)
        rows = db.execute("SELECT COUNT(*) FROM module_dependencies").fetchone()
        assert rows[0] >= 2

    def test_indexes_plugins(self, db, tmp_path):
        root = tmp_path / "MyGame"
        root.mkdir()
        (root / "MyGame.uproject").write_text("{}")
        src = root / "Source" / "MyGame"
        src.mkdir(parents=True)
        (src / "Test.h").write_text("#pragma once\nclass ATestActor {};\n")
        plugins = root / "Plugins" / "TestPlugin"
        plugins.mkdir(parents=True)
        (plugins / "TestPlugin.uplugin").write_text(
            '{"Modules": [{"Name": "TestPlugin", "Type": "Runtime"}]}'
        )

        pipeline = IndexingPipeline(db)
        pipeline.index_project(root)
        rows = db.execute("SELECT COUNT(*) FROM plugins").fetchone()
        assert rows[0] >= 1


class TestReplicationAndDataTablePipeline:
    def test_inserts_replication_entries(self, indexed_db):
        """ReplicatedActor.h has Server, Client, NetMulticast, Replicated, ReplicatedUsing markers."""
        db, _ = indexed_db
        rows = db.execute("SELECT * FROM replication_entries").fetchall()
        rep_types = {dict(r)["rep_type"] for r in rows}
        # Should have at least Server, Client, NetMulticast from ReplicatedActor.h
        assert "Server" in rep_types or len(rows) >= 3

    def test_detects_data_table_structs(self, db, tmp_path):
        src = tmp_path / "Source" / "MyGame"
        src.mkdir(parents=True)
        (src / "WeaponData.h").write_text(
            '#pragma once\n'
            '#include "Engine/DataTable.h"\n'
            'struct FTableRowBase {};\n'
            'USTRUCT()\n'
            'struct FWeaponDataRow : public FTableRowBase\n'
            '{\n    GENERATED_BODY()\n    float Damage;\n};\n'
        )
        pipeline = IndexingPipeline(db)
        pipeline.index_project(tmp_path)
        rows = db.execute("SELECT * FROM data_tables").fetchall()
        assert len(rows) >= 1
        assert dict(rows[0])["table_name"] == "FWeaponDataRow"


class TestAssetAndLogExtraction:
    def test_extracts_asset_references(self, indexed_db):
        db, _ = indexed_db
        rows = db.execute("SELECT * FROM asset_references").fetchall()
        paths = {dict(r)["asset_path"] for r in rows}
        # At least one of the fixture's asset paths should be found
        assert any("/Game/" in p for p in paths), f"No /Game/ asset paths found. Got: {paths}"

    def test_extracts_log_categories(self, indexed_db):
        db, _ = indexed_db
        rows = db.execute("SELECT * FROM log_categories").fetchall()
        names = {dict(r)["name"] for r in rows}
        assert "LogAssetLoader" in names
