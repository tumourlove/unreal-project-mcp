"""Tests for project config."""

import os
from unittest.mock import patch

import pytest


class TestDetectProjectName:
    def test_from_env_var(self):
        with patch.dict(os.environ, {"UE_PROJECT_NAME": "Leviathan", "UE_PROJECT_PATH": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            assert cfg._detect_project_name() == "Leviathan"

    def test_from_uproject_file(self, tmp_path):
        proj_dir = tmp_path / "MyGame"
        proj_dir.mkdir()
        (proj_dir / "MyGame.uproject").write_text("{}")
        with patch.dict(os.environ, {"UE_PROJECT_NAME": "", "UE_PROJECT_PATH": str(proj_dir)}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            assert cfg._detect_project_name() == "MyGame"

    def test_fallback_unknown(self):
        with patch.dict(os.environ, {"UE_PROJECT_NAME": "", "UE_PROJECT_PATH": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            assert cfg._detect_project_name() == "unknown"


class TestGetDbPath:
    def test_returns_path_with_project_name(self, tmp_path):
        with patch.dict(os.environ, {
            "UNREAL_PROJECT_MCP_DB_DIR": str(tmp_path),
            "UE_PROJECT_NAME": "TestProj",
            "UE_PROJECT_PATH": "",
        }):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            db_path = cfg.get_db_path()
            assert db_path.name == "TestProj.db"
            assert db_path.parent == tmp_path
