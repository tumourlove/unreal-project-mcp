"""End-to-end test: index fixtures, query via server tools."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from unreal_project_mcp.db.schema import init_db
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
