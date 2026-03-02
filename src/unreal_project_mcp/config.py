"""Configuration for unreal-project-mcp."""

import os
import re
from pathlib import Path

DB_DIR = Path(os.environ.get("UNREAL_PROJECT_MCP_DB_DIR", os.path.expanduser("~/.unreal-project-mcp")))
UE_PROJECT_PATH = os.environ.get("UE_PROJECT_PATH", "")
UE_PROJECT_NAME = os.environ.get("UE_PROJECT_NAME", "")


def _detect_project_name() -> str:
    """Detect project name from UE_PROJECT_NAME env var or .uproject file."""
    if UE_PROJECT_NAME:
        return UE_PROJECT_NAME
    if UE_PROJECT_PATH:
        p = Path(UE_PROJECT_PATH)
        for f in p.iterdir():
            if f.suffix == ".uproject":
                return f.stem
    return "unknown"


def _project_root() -> str:
    """Return the project root prefix for path shortening."""
    if not UE_PROJECT_PATH:
        return ""
    return str(Path(UE_PROJECT_PATH)) + os.sep


def get_db_path() -> Path:
    """Return the path to the SQLite database, creating the directory if needed."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    project_name = _detect_project_name()
    return DB_DIR / f"{project_name}.db"
