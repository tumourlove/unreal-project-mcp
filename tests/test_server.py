"""Tests for MCP server tools."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.indexer.pipeline import IndexingPipeline
from unreal_project_mcp import server

FIXTURES = Path(__file__).parent / "fixtures" / "sample_project_source"


@pytest.fixture
def populated_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    pipeline = IndexingPipeline(conn)
    pipeline.index_project(FIXTURES)
    return conn


@pytest.fixture(autouse=True)
def mock_conn(populated_db):
    with patch.object(server, "_conn", populated_db):
        with patch.object(server, "_get_conn", return_value=populated_db):
            yield


class TestSearchProject:
    def test_finds_class_by_name(self):
        result = server.search_project("MeshDamageStamper")
        assert "MeshDamageStamper" in result

    def test_finds_method(self):
        result = server.search_project("ApplyDamageStamp")
        assert "ApplyDamageStamp" in result


class TestReadProjectSource:
    def test_reads_class(self):
        result = server.read_project_source("UMeshDamageStamper")
        assert "UMeshDamageStamper" in result
        assert "UActorComponent" in result

    def test_reads_function(self):
        result = server.read_project_source("ApplyDamageStamp")
        assert "ApplyDamageStamp" in result


class TestFindProjectCallers:
    def test_finds_callers(self):
        result = server.find_project_callers("UpdateDamageDecay")
        assert isinstance(result, str)


class TestFindProjectCallees:
    def test_finds_callees(self):
        result = server.find_project_callees("ApplyDamageStamp")
        assert isinstance(result, str)


class TestGetProjectClassHierarchy:
    def test_shows_hierarchy(self):
        result = server.get_project_class_hierarchy("UMeshDamageStamper")
        assert "UMeshDamageStamper" in result


class TestGetProjectModuleInfo:
    def test_shows_module_stats(self):
        result = server.get_project_module_info("sample_project_source")
        assert "sample_project_source" in result
