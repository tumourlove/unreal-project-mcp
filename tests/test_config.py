"""Tests for project config."""

import os
from pathlib import Path
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


class TestDetectProjectRoot:
    def test_from_source_subdir(self):
        """UE_PROJECT_PATH ending in Source/ should return the parent."""
        with patch.dict(os.environ, {"UE_PROJECT_PATH": "/tmp/MyGame/Source", "UE_PROJECT_NAME": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            result = cfg._detect_project_root()
            assert result is not None
            assert str(result) == str(Path("/tmp/MyGame"))

    def test_from_project_root_directly(self, tmp_path):
        """UE_PROJECT_PATH with a .uproject file should return it directly."""
        proj_dir = tmp_path / "MyGame"
        proj_dir.mkdir()
        (proj_dir / "MyGame.uproject").write_text("{}")
        with patch.dict(os.environ, {"UE_PROJECT_PATH": str(proj_dir), "UE_PROJECT_NAME": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            result = cfg._detect_project_root()
            assert result is not None
            assert result == proj_dir

    def test_subdirs_exposed(self, tmp_path):
        """Config/, Content/, Plugins/ should be findable from detected root."""
        proj_dir = tmp_path / "MyGame"
        source_dir = proj_dir / "Source"
        source_dir.mkdir(parents=True)
        (proj_dir / "Config").mkdir()
        (proj_dir / "Content").mkdir()
        (proj_dir / "Plugins").mkdir()
        with patch.dict(os.environ, {"UE_PROJECT_PATH": str(source_dir), "UE_PROJECT_NAME": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            root = cfg._detect_project_root()
            assert root is not None
            assert (root / "Config").is_dir()
            assert (root / "Content").is_dir()
            assert (root / "Plugins").is_dir()

    def test_no_project_path_returns_none(self):
        """Empty UE_PROJECT_PATH should return None."""
        with patch.dict(os.environ, {"UE_PROJECT_PATH": "", "UE_PROJECT_NAME": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            assert cfg._detect_project_root() is None


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
