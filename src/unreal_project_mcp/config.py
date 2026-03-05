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


def _detect_project_root() -> Path | None:
    """Detect the UE project root directory from UE_PROJECT_PATH.

    Walks up from UE_PROJECT_PATH to find the project root:
    - If path ends with 'Source', returns the parent
    - If path contains 'Source' in its parts, returns the parent of that segment
    - If path itself contains a .uproject file, returns it directly
    - Fallback: returns the path as-is
    - Returns None if UE_PROJECT_PATH is not set
    """
    if not UE_PROJECT_PATH:
        return None
    p = Path(UE_PROJECT_PATH)
    # If the last component is "Source", go up one level
    if p.name == "Source":
        return p.parent
    # If "Source" appears somewhere in parts, find parent of that segment
    parts = p.parts
    for i, part in enumerate(parts):
        if part == "Source":
            return Path(*parts[:i])
    # If the path itself has a .uproject file, use it directly
    if p.is_dir():
        for f in p.iterdir():
            if f.suffix == ".uproject":
                return p
    # Fallback: return the path directly
    return p


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
