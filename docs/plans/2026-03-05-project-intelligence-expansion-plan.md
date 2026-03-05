# Project Intelligence Expansion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand unreal-project-mcp from C++ source intelligence to full UE project intelligence with 10 new MCP tools, 9 new DB tables, and 5 new indexer modules.

**Architecture:** New indexer modules parse non-C++ files (INI, .Build.cs, .uplugin, CSV). Extended C++ parser extracts replication markers, asset paths, and log categories. All data lands in SQLite alongside existing tables. Pipeline orchestrates new indexers in phases. Each feature gets a dedicated MCP tool.

**Tech Stack:** Python 3.11+, SQLite + FTS5, tree-sitter-cpp, regex parsers for non-C++ files, `mcp` SDK

**Design doc:** `docs/plans/2026-03-05-project-intelligence-expansion-design.md`

---

## Phase 1: Foundation (Schema v2 + Config Auto-Detection)

### Task 1: Project Root Auto-Detection

**Files:**
- Modify: `src/unreal_project_mcp/config.py`
- Test: `tests/test_config.py`

**Step 1: Write failing tests**

Add to `tests/test_config.py`:

```python
class TestDetectProjectRoot:
    def test_from_source_subdir(self, tmp_path):
        """UE_PROJECT_PATH pointing to Source/ should detect parent as root."""
        root = tmp_path / "MyGame"
        root.mkdir()
        (root / "MyGame.uproject").write_text("{}")
        (root / "Source").mkdir()
        (root / "Config").mkdir()
        source_dir = root / "Source"
        with patch.dict(os.environ, {"UE_PROJECT_PATH": str(source_dir), "UE_PROJECT_NAME": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            result = cfg._detect_project_root()
            assert result == root

    def test_from_project_root_directly(self, tmp_path):
        """UE_PROJECT_PATH pointing to project root (with .uproject) should work."""
        root = tmp_path / "MyGame"
        root.mkdir()
        (root / "MyGame.uproject").write_text("{}")
        (root / "Source").mkdir()
        with patch.dict(os.environ, {"UE_PROJECT_PATH": str(root), "UE_PROJECT_NAME": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            result = cfg._detect_project_root()
            assert result == root

    def test_subdirs_exposed(self, tmp_path):
        """PROJECT_ROOT should expose SOURCE_DIR, CONFIG_DIR, CONTENT_DIR, PLUGINS_DIR."""
        root = tmp_path / "MyGame"
        root.mkdir()
        (root / "MyGame.uproject").write_text("{}")
        for d in ("Source", "Config", "Content", "Plugins"):
            (root / d).mkdir()
        with patch.dict(os.environ, {"UE_PROJECT_PATH": str(root / "Source"), "UE_PROJECT_NAME": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            root_result = cfg._detect_project_root()
            assert root_result is not None
            assert (root_result / "Source").is_dir()
            assert (root_result / "Config").is_dir()
            assert (root_result / "Content").is_dir()
            assert (root_result / "Plugins").is_dir()

    def test_no_project_path_returns_none(self):
        with patch.dict(os.environ, {"UE_PROJECT_PATH": "", "UE_PROJECT_NAME": ""}):
            import importlib
            import unreal_project_mcp.config as cfg
            importlib.reload(cfg)
            assert cfg._detect_project_root() is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py::TestDetectProjectRoot -v`
Expected: FAIL — `_detect_project_root` does not exist

**Step 3: Implement project root detection**

In `src/unreal_project_mcp/config.py`, add:

```python
def _detect_project_root() -> Path | None:
    """Auto-detect UE project root from UE_PROJECT_PATH.

    If path contains Source/, walk up to the parent.
    If path contains a .uproject file, use it directly.
    Returns None if UE_PROJECT_PATH is not set.
    """
    if not UE_PROJECT_PATH:
        return None
    p = Path(UE_PROJECT_PATH)

    # If path IS or ends with Source, go up one level
    if p.name == "Source":
        candidate = p.parent
        if any(f.suffix == ".uproject" for f in candidate.iterdir() if f.is_file()):
            return candidate
        return candidate  # Still use parent even without .uproject

    # If path contains Source/ somewhere, find the parent of Source
    parts = p.parts
    for i, part in enumerate(parts):
        if part == "Source" and i > 0:
            candidate = Path(*parts[:i])
            return candidate

    # Check if this IS the project root (has .uproject)
    if p.is_dir() and any(f.suffix == ".uproject" for f in p.iterdir() if f.is_file()):
        return p

    # Fallback: use the path directly
    return p
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py::TestDetectProjectRoot -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/unreal_project_mcp/config.py tests/test_config.py
git commit -m "feat: add project root auto-detection from UE_PROJECT_PATH"
```

---

### Task 2: Schema v2 — New Tables

**Files:**
- Modify: `src/unreal_project_mcp/db/schema.py`
- Test: `tests/test_db.py`

**Step 1: Write failing test**

Add to `tests/test_db.py`:

```python
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
            "SELECT * FROM config_fts WHERE config_fts MATCH 'FixedFrameRate'"
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::TestSchemaV2 -v`
Expected: FAIL — tables don't exist

**Step 3: Add v2 tables to schema.py**

In `src/unreal_project_mcp/db/schema.py`, update `SCHEMA_VERSION = 2` and append to `_DDL`:

```sql
-- v2 tables ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS config_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,
    section     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT,
    line        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_config_section_key ON config_entries(section, key);

CREATE VIRTUAL TABLE IF NOT EXISTS config_fts USING fts5(
    section, key, value,
    content=config_entries, content_rowid=id
);

CREATE TABLE IF NOT EXISTS asset_references (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id   INTEGER REFERENCES symbols(id),
    asset_path  TEXT NOT NULL,
    ref_type    TEXT NOT NULL,
    file_id     INTEGER REFERENCES files(id),
    line        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_asset_refs_path ON asset_references(asset_path);
CREATE INDEX IF NOT EXISTS idx_asset_refs_symbol ON asset_references(symbol_id);

CREATE TABLE IF NOT EXISTS data_tables (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    struct_symbol_id  INTEGER REFERENCES symbols(id),
    table_path        TEXT,
    table_name        TEXT
);

CREATE TABLE IF NOT EXISTS gameplay_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tag         TEXT NOT NULL,
    source_type TEXT NOT NULL,
    usage_kind  TEXT NOT NULL,
    symbol_id   INTEGER REFERENCES symbols(id),
    file_path   TEXT,
    line        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON gameplay_tags(tag);
CREATE INDEX IF NOT EXISTS idx_tags_kind ON gameplay_tags(usage_kind);

CREATE VIRTUAL TABLE IF NOT EXISTS tags_fts USING fts5(
    tag, content=gameplay_tags, content_rowid=id
);

CREATE TABLE IF NOT EXISTS module_dependencies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id       INTEGER NOT NULL REFERENCES modules(id),
    dependency_name TEXT NOT NULL,
    dep_type        TEXT NOT NULL,
    UNIQUE(module_id, dependency_name, dep_type)
);

CREATE TABLE IF NOT EXISTS plugins (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    friendly_name       TEXT,
    description         TEXT,
    category            TEXT,
    version             TEXT,
    can_contain_content INTEGER DEFAULT 0,
    is_beta             INTEGER DEFAULT 0,
    file_path           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plugin_modules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id     INTEGER NOT NULL REFERENCES plugins(id),
    module_name   TEXT NOT NULL,
    module_type   TEXT,
    loading_phase TEXT
);

CREATE TABLE IF NOT EXISTS plugin_dependencies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id   INTEGER NOT NULL REFERENCES plugins(id),
    depends_on  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS log_categories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    file_id   INTEGER REFERENCES files(id),
    line      INTEGER,
    verbosity TEXT
);

CREATE TABLE IF NOT EXISTS replication_entries (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id),
    rep_type  TEXT NOT NULL,
    condition TEXT,
    callback  TEXT
);
CREATE INDEX IF NOT EXISTS idx_rep_type ON replication_entries(rep_type);

CREATE TABLE IF NOT EXISTS pattern_tags (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id),
    tag_kind  TEXT NOT NULL,
    metadata  TEXT
);
CREATE INDEX IF NOT EXISTS idx_pattern_tags_kind ON pattern_tags(tag_kind);
```

Append to `_TRIGGERS`:

```sql
CREATE TRIGGER IF NOT EXISTS config_ai AFTER INSERT ON config_entries BEGIN
    INSERT INTO config_fts(rowid, section, key, value)
    VALUES (new.id, new.section, new.key, new.value);
END;

CREATE TRIGGER IF NOT EXISTS config_ad AFTER DELETE ON config_entries BEGIN
    INSERT INTO config_fts(config_fts, rowid, section, key, value)
    VALUES ('delete', old.id, old.section, old.key, old.value);
END;

CREATE TRIGGER IF NOT EXISTS tags_ai AFTER INSERT ON gameplay_tags BEGIN
    INSERT INTO tags_fts(rowid, tag) VALUES (new.id, new.tag);
END;

CREATE TRIGGER IF NOT EXISTS tags_ad AFTER DELETE ON gameplay_tags BEGIN
    INSERT INTO tags_fts(tags_fts, rowid, tag)
    VALUES ('delete', old.id, old.tag);
END;
```

Update `SCHEMA_VERSION = 2`.

Also fix `tests/test_db.py::TestSchema::test_schema_version` to expect `"2"`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/unreal_project_mcp/db/schema.py tests/test_db.py
git commit -m "feat: add schema v2 with 9 new tables for project intelligence"
```

---

### Task 3: Query Helpers for New Tables

**Files:**
- Modify: `src/unreal_project_mcp/db/queries.py`
- Test: `tests/test_db.py`

**Step 1: Write failing tests**

Add to `tests/test_db.py`:

```python
class TestV2Inserts:
    def test_insert_config_entry(self, conn):
        queries.insert_config_entry(
            conn, file_path="/Config/DefaultEngine.ini",
            section="/Script/Engine", key="bUseFixedFrameRate",
            value="True", line=10,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM config_entries").fetchone()
        assert row is not None
        assert dict(row)["key"] == "bUseFixedFrameRate"

    def test_insert_asset_reference(self, populated):
        conn = populated["conn"]
        queries.insert_asset_reference(
            conn, symbol_id=populated["child_sym_id"],
            asset_path="/Game/Blueprints/BP_Weapon",
            ref_type="LoadObject", file_id=populated["file_id"], line=55,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM asset_references").fetchone()
        assert dict(row)["asset_path"] == "/Game/Blueprints/BP_Weapon"

    def test_insert_gameplay_tag(self, conn):
        queries.insert_gameplay_tag(
            conn, tag="Ability.Skill.Fireball",
            source_type="cpp", usage_kind="definition",
            symbol_id=None, file_path="/test.cpp", line=50,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM gameplay_tags").fetchone()
        assert dict(row)["tag"] == "Ability.Skill.Fireball"

    def test_insert_module_dependency(self, populated):
        conn = populated["conn"]
        queries.insert_module_dependency(
            conn, module_id=populated["module_id"],
            dependency_name="Engine", dep_type="public",
        )
        conn.commit()
        row = conn.execute("SELECT * FROM module_dependencies").fetchone()
        assert dict(row)["dependency_name"] == "Engine"

    def test_insert_plugin(self, conn):
        plugin_id = queries.insert_plugin(
            conn, name="MyPlugin", friendly_name="My Plugin",
            description="A plugin", category="Gameplay",
            version="1.0", can_contain_content=True,
            is_beta=False, file_path="/Plugins/MyPlugin/MyPlugin.uplugin",
        )
        conn.commit()
        assert plugin_id > 0

    def test_insert_plugin_module(self, conn):
        plugin_id = queries.insert_plugin(
            conn, name="TestPlugin", file_path="/test.uplugin",
        )
        queries.insert_plugin_module(
            conn, plugin_id=plugin_id, module_name="TestModule",
            module_type="Runtime", loading_phase="Default",
        )
        conn.commit()
        row = conn.execute("SELECT * FROM plugin_modules").fetchone()
        assert dict(row)["module_name"] == "TestModule"

    def test_insert_plugin_dependency(self, conn):
        plugin_id = queries.insert_plugin(
            conn, name="DepPlugin", file_path="/test.uplugin",
        )
        queries.insert_plugin_dependency(
            conn, plugin_id=plugin_id, depends_on="OtherPlugin",
        )
        conn.commit()
        row = conn.execute("SELECT * FROM plugin_dependencies").fetchone()
        assert dict(row)["depends_on"] == "OtherPlugin"

    def test_insert_log_category(self, populated):
        conn = populated["conn"]
        queries.insert_log_category(
            conn, name="LogMyGame",
            file_id=populated["file_id"], line=5, verbosity="Warning",
        )
        conn.commit()
        row = conn.execute("SELECT * FROM log_categories").fetchone()
        assert dict(row)["name"] == "LogMyGame"

    def test_insert_replication_entry(self, populated):
        conn = populated["conn"]
        queries.insert_replication_entry(
            conn, symbol_id=populated["child_sym_id"],
            rep_type="Server", condition=None, callback=None,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM replication_entries").fetchone()
        assert dict(row)["rep_type"] == "Server"

    def test_insert_pattern_tag(self, populated):
        conn = populated["conn"]
        queries.insert_pattern_tag(
            conn, symbol_id=populated["parent_sym_id"],
            tag_kind="subsystem", metadata='{"type": "WorldSubsystem"}',
        )
        conn.commit()
        row = conn.execute("SELECT * FROM pattern_tags").fetchone()
        assert dict(row)["tag_kind"] == "subsystem"

    def test_insert_data_table(self, populated):
        conn = populated["conn"]
        queries.insert_data_table(
            conn, struct_symbol_id=populated["parent_sym_id"],
            table_path="/Game/Data/DT_Weapons", table_name="DT_Weapons",
        )
        conn.commit()
        row = conn.execute("SELECT * FROM data_tables").fetchone()
        assert dict(row)["table_name"] == "DT_Weapons"


class TestV2Queries:
    def test_search_config_fts(self, conn):
        queries.insert_config_entry(
            conn, file_path="/Config/DefaultEngine.ini",
            section="/Script/Engine.GameEngine",
            key="bUseFixedFrameRate", value="True", line=10,
        )
        conn.commit()
        results = queries.search_config_fts(conn, "FixedFrameRate")
        assert len(results) >= 1

    def test_get_config_by_key(self, conn):
        queries.insert_config_entry(
            conn, file_path="/Config/DefaultEngine.ini",
            section="/Script/Engine", key="MaxFPS", value="60", line=20,
        )
        conn.commit()
        results = queries.get_config_by_key(conn, "MaxFPS")
        assert len(results) == 1
        assert results[0]["value"] == "60"

    def test_get_config_by_key_and_section(self, conn):
        queries.insert_config_entry(
            conn, file_path="/a.ini", section="/Script/A", key="Foo", value="1", line=1,
        )
        queries.insert_config_entry(
            conn, file_path="/b.ini", section="/Script/B", key="Foo", value="2", line=1,
        )
        conn.commit()
        results = queries.get_config_by_key(conn, "Foo", section="/Script/A")
        assert len(results) == 1
        assert results[0]["value"] == "1"

    def test_get_asset_references_by_path(self, populated):
        conn = populated["conn"]
        queries.insert_asset_reference(
            conn, symbol_id=populated["child_sym_id"],
            asset_path="/Game/BP/BP_Weapon", ref_type="LoadObject",
            file_id=populated["file_id"], line=55,
        )
        conn.commit()
        results = queries.get_asset_references_by_path(conn, "/Game/BP/BP_Weapon")
        assert len(results) == 1

    def test_get_asset_references_by_symbol(self, populated):
        conn = populated["conn"]
        queries.insert_asset_reference(
            conn, symbol_id=populated["child_sym_id"],
            asset_path="/Game/BP/BP_Shield", ref_type="FSoftObjectPath",
            file_id=populated["file_id"], line=60,
        )
        conn.commit()
        results = queries.get_asset_references_by_symbol(conn, populated["child_sym_id"])
        assert len(results) == 1

    def test_search_gameplay_tags_fts(self, conn):
        queries.insert_gameplay_tag(
            conn, tag="Ability.Skill.Fireball",
            source_type="cpp", usage_kind="definition",
            file_path="/test.cpp", line=10,
        )
        conn.commit()
        results = queries.search_gameplay_tags_fts(conn, "Fireball")
        assert len(results) >= 1

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
        conn.commit()
        results = queries.get_module_dependencies(conn, populated["module_id"])
        assert len(results) == 2
        dep_names = {r["dependency_name"] for r in results}
        assert dep_names == {"Engine", "Slate"}

    def test_get_module_dependents(self, populated):
        conn = populated["conn"]
        queries.insert_module_dependency(
            conn, module_id=populated["module_id"],
            dependency_name="Engine", dep_type="public",
        )
        conn.commit()
        results = queries.get_module_dependents(conn, "Engine")
        assert len(results) >= 1

    def test_get_plugin_by_name(self, conn):
        queries.insert_plugin(
            conn, name="MyPlugin", friendly_name="My Plugin",
            description="Test", file_path="/test.uplugin",
        )
        conn.commit()
        result = queries.get_plugin_by_name(conn, "MyPlugin")
        assert result is not None
        assert result["friendly_name"] == "My Plugin"

    def test_get_plugin_modules(self, conn):
        pid = queries.insert_plugin(conn, name="P1", file_path="/p.uplugin")
        queries.insert_plugin_module(conn, plugin_id=pid, module_name="M1", module_type="Runtime")
        conn.commit()
        results = queries.get_plugin_modules(conn, pid)
        assert len(results) == 1

    def test_get_plugin_dependencies(self, conn):
        pid = queries.insert_plugin(conn, name="P2", file_path="/p.uplugin")
        queries.insert_plugin_dependency(conn, plugin_id=pid, depends_on="Core")
        conn.commit()
        results = queries.get_plugin_dependencies(conn, pid)
        assert len(results) == 1

    def test_get_replication_entries_by_class(self, populated):
        conn = populated["conn"]
        queries.insert_replication_entry(
            conn, symbol_id=populated["child_sym_id"],
            rep_type="Server",
        )
        conn.commit()
        results = queries.get_replication_entries(conn, class_name="AActor")
        assert len(results) >= 1

    def test_get_all_replication_entries(self, populated):
        conn = populated["conn"]
        queries.insert_replication_entry(
            conn, symbol_id=populated["child_sym_id"],
            rep_type="Client",
        )
        conn.commit()
        results = queries.get_replication_entries(conn)
        assert len(results) >= 1

    def test_get_pattern_tags_by_kind(self, populated):
        conn = populated["conn"]
        queries.insert_pattern_tag(
            conn, symbol_id=populated["parent_sym_id"],
            tag_kind="subsystem",
        )
        conn.commit()
        results = queries.get_pattern_tags(conn, kind="subsystem")
        assert len(results) == 1

    def test_get_log_category(self, populated):
        conn = populated["conn"]
        queries.insert_log_category(
            conn, name="LogMyGame",
            file_id=populated["file_id"], line=5, verbosity="Warning",
        )
        conn.commit()
        result = queries.get_log_category(conn, "LogMyGame")
        assert result is not None
        assert result["verbosity"] == "Warning"

    def test_get_data_tables_by_struct(self, populated):
        conn = populated["conn"]
        queries.insert_data_table(
            conn, struct_symbol_id=populated["parent_sym_id"],
            table_path="/Game/DT_Test", table_name="DT_Test",
        )
        conn.commit()
        results = queries.get_data_tables_by_struct(conn, populated["parent_sym_id"])
        assert len(results) == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::TestV2Inserts tests/test_db.py::TestV2Queries -v`
Expected: FAIL — functions don't exist

**Step 3: Implement all insert/query helpers**

Add to `src/unreal_project_mcp/db/queries.py`:

```python
# ── v2 Insert helpers ───────────────────────────────────────────────────

def insert_config_entry(
    conn: sqlite3.Connection, *, file_path: str, section: str,
    key: str, value: str | None, line: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO config_entries (file_path, section, key, value, line) "
        "VALUES (?, ?, ?, ?, ?)",
        (file_path, section, key, value, line),
    )
    return cur.lastrowid


def insert_asset_reference(
    conn: sqlite3.Connection, *, symbol_id: int | None,
    asset_path: str, ref_type: str, file_id: int, line: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO asset_references (symbol_id, asset_path, ref_type, file_id, line) "
        "VALUES (?, ?, ?, ?, ?)",
        (symbol_id, asset_path, ref_type, file_id, line),
    )
    return cur.lastrowid


def insert_gameplay_tag(
    conn: sqlite3.Connection, *, tag: str, source_type: str,
    usage_kind: str, symbol_id: int | None = None,
    file_path: str | None = None, line: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO gameplay_tags (tag, source_type, usage_kind, symbol_id, file_path, line) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tag, source_type, usage_kind, symbol_id, file_path, line),
    )
    return cur.lastrowid


def insert_module_dependency(
    conn: sqlite3.Connection, *, module_id: int,
    dependency_name: str, dep_type: str,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO module_dependencies (module_id, dependency_name, dep_type) "
        "VALUES (?, ?, ?)",
        (module_id, dependency_name, dep_type),
    )


def insert_plugin(
    conn: sqlite3.Connection, *, name: str,
    friendly_name: str | None = None, description: str | None = None,
    category: str | None = None, version: str | None = None,
    can_contain_content: bool = False, is_beta: bool = False,
    file_path: str,
) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO plugins "
        "(name, friendly_name, description, category, version, can_contain_content, is_beta, file_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, friendly_name, description, category, version,
         1 if can_contain_content else 0, 1 if is_beta else 0, file_path),
    )
    if cur.lastrowid and cur.rowcount > 0:
        return cur.lastrowid
    row = conn.execute("SELECT id FROM plugins WHERE name = ?", (name,)).fetchone()
    return row[0]


def insert_plugin_module(
    conn: sqlite3.Connection, *, plugin_id: int,
    module_name: str, module_type: str | None = None,
    loading_phase: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO plugin_modules (plugin_id, module_name, module_type, loading_phase) "
        "VALUES (?, ?, ?, ?)",
        (plugin_id, module_name, module_type, loading_phase),
    )


def insert_plugin_dependency(
    conn: sqlite3.Connection, *, plugin_id: int, depends_on: str,
) -> None:
    conn.execute(
        "INSERT INTO plugin_dependencies (plugin_id, depends_on) VALUES (?, ?)",
        (plugin_id, depends_on),
    )


def insert_log_category(
    conn: sqlite3.Connection, *, name: str,
    file_id: int | None = None, line: int | None = None,
    verbosity: str | None = None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO log_categories (name, file_id, line, verbosity) "
        "VALUES (?, ?, ?, ?)",
        (name, file_id, line, verbosity),
    )


def insert_replication_entry(
    conn: sqlite3.Connection, *, symbol_id: int,
    rep_type: str, condition: str | None = None,
    callback: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO replication_entries (symbol_id, rep_type, condition, callback) "
        "VALUES (?, ?, ?, ?)",
        (symbol_id, rep_type, condition, callback),
    )


def insert_pattern_tag(
    conn: sqlite3.Connection, *, symbol_id: int,
    tag_kind: str, metadata: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO pattern_tags (symbol_id, tag_kind, metadata) "
        "VALUES (?, ?, ?)",
        (symbol_id, tag_kind, metadata),
    )


def insert_data_table(
    conn: sqlite3.Connection, *, struct_symbol_id: int,
    table_path: str | None = None, table_name: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO data_tables (struct_symbol_id, table_path, table_name) "
        "VALUES (?, ?, ?)",
        (struct_symbol_id, table_path, table_name),
    )


# ── v2 Query helpers ───────────────────────────────────────────────────

def search_config_fts(
    conn: sqlite3.Connection, query: str, limit: int = 20,
) -> list[dict]:
    fts_query = _escape_fts(query)
    rows = conn.execute(
        "SELECT c.* FROM config_fts f "
        "JOIN config_entries c ON c.id = f.rowid "
        "WHERE config_fts MATCH ? "
        "ORDER BY bm25(config_fts) LIMIT ?",
        (fts_query, limit),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_config_by_key(
    conn: sqlite3.Connection, key: str, section: str | None = None,
) -> list[dict]:
    if section:
        rows = conn.execute(
            "SELECT * FROM config_entries WHERE key = ? AND section = ?",
            (key, section),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM config_entries WHERE key = ?", (key,),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_asset_references_by_path(
    conn: sqlite3.Connection, asset_path: str, limit: int = 50,
) -> list[dict]:
    rows = conn.execute(
        "SELECT ar.*, s.name AS symbol_name, s.qualified_name, f.path "
        "FROM asset_references ar "
        "LEFT JOIN symbols s ON s.id = ar.symbol_id "
        "LEFT JOIN files f ON f.id = ar.file_id "
        "WHERE ar.asset_path LIKE ? LIMIT ?",
        (f"%{asset_path}%", limit),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_asset_references_by_symbol(
    conn: sqlite3.Connection, symbol_id: int, limit: int = 50,
) -> list[dict]:
    rows = conn.execute(
        "SELECT ar.*, f.path FROM asset_references ar "
        "LEFT JOIN files f ON f.id = ar.file_id "
        "WHERE ar.symbol_id = ? LIMIT ?",
        (symbol_id, limit),
    ).fetchall()
    return _rows_to_dicts(rows)


def search_gameplay_tags_fts(
    conn: sqlite3.Connection, query: str, usage_kind: str | None = None,
    limit: int = 50,
) -> list[dict]:
    fts_query = _escape_fts(query)
    if usage_kind:
        rows = conn.execute(
            "SELECT g.* FROM tags_fts f "
            "JOIN gameplay_tags g ON g.id = f.rowid "
            "WHERE tags_fts MATCH ? AND g.usage_kind = ? "
            "ORDER BY bm25(tags_fts) LIMIT ?",
            (fts_query, usage_kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT g.* FROM tags_fts f "
            "JOIN gameplay_tags g ON g.id = f.rowid "
            "WHERE tags_fts MATCH ? "
            "ORDER BY bm25(tags_fts) LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_module_dependencies(
    conn: sqlite3.Connection, module_id: int,
    dep_type: str | None = None,
) -> list[dict]:
    if dep_type:
        rows = conn.execute(
            "SELECT * FROM module_dependencies WHERE module_id = ? AND dep_type = ?",
            (module_id, dep_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM module_dependencies WHERE module_id = ?",
            (module_id,),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_module_dependents(
    conn: sqlite3.Connection, dependency_name: str,
) -> list[dict]:
    rows = conn.execute(
        "SELECT md.*, m.name AS module_name FROM module_dependencies md "
        "JOIN modules m ON m.id = md.module_id "
        "WHERE md.dependency_name = ?",
        (dependency_name,),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_plugin_by_name(
    conn: sqlite3.Connection, name: str,
) -> dict | None:
    row = conn.execute(
        "SELECT * FROM plugins WHERE name = ?", (name,),
    ).fetchone()
    return _row_to_dict(row)


def get_plugin_modules(
    conn: sqlite3.Connection, plugin_id: int,
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM plugin_modules WHERE plugin_id = ?", (plugin_id,),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_plugin_dependencies(
    conn: sqlite3.Connection, plugin_id: int,
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM plugin_dependencies WHERE plugin_id = ?", (plugin_id,),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_log_category(
    conn: sqlite3.Connection, name: str,
) -> dict | None:
    row = conn.execute(
        "SELECT lc.*, f.path FROM log_categories lc "
        "LEFT JOIN files f ON f.id = lc.file_id "
        "WHERE lc.name = ?",
        (name,),
    ).fetchone()
    return _row_to_dict(row)


def get_replication_entries(
    conn: sqlite3.Connection, class_name: str | None = None,
    limit: int = 100,
) -> list[dict]:
    if class_name:
        rows = conn.execute(
            "SELECT re.*, s.name AS symbol_name, s.qualified_name, "
            "s.parent_symbol_id, f.path "
            "FROM replication_entries re "
            "JOIN symbols s ON s.id = re.symbol_id "
            "LEFT JOIN files f ON f.id = s.file_id "
            "WHERE s.parent_symbol_id IN "
            "  (SELECT id FROM symbols WHERE name = ? AND kind IN ('class', 'struct')) "
            "LIMIT ?",
            (class_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT re.*, s.name AS symbol_name, s.qualified_name, "
            "s.parent_symbol_id, f.path "
            "FROM replication_entries re "
            "JOIN symbols s ON s.id = re.symbol_id "
            "LEFT JOIN files f ON f.id = s.file_id "
            "LIMIT ?",
            (limit,),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_pattern_tags(
    conn: sqlite3.Connection, kind: str | None = None,
    query: str | None = None, limit: int = 100,
) -> list[dict]:
    sql = (
        "SELECT pt.*, s.name AS symbol_name, s.qualified_name, f.path "
        "FROM pattern_tags pt "
        "JOIN symbols s ON s.id = pt.symbol_id "
        "LEFT JOIN files f ON f.id = s.file_id "
    )
    conditions: list[str] = []
    params: list = []
    if kind:
        conditions.append("pt.tag_kind = ?")
        params.append(kind)
    if query:
        conditions.append("s.name LIKE ?")
        params.append(f"%{query}%")
    if conditions:
        sql += "WHERE " + " AND ".join(conditions) + " "
    sql += "LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def get_data_tables_by_struct(
    conn: sqlite3.Connection, struct_symbol_id: int,
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM data_tables WHERE struct_symbol_id = ?",
        (struct_symbol_id,),
    ).fetchall()
    return _rows_to_dicts(rows)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/unreal_project_mcp/db/queries.py tests/test_db.py
git commit -m "feat: add insert/query helpers for all v2 tables"
```

---

## Phase 2: Config/INI Indexer + Tools

### Task 4: Config Parser

**Files:**
- Create: `src/unreal_project_mcp/indexer/config_parser.py`
- Create: `tests/test_config_parser.py`
- Create: `tests/fixtures/sample_config/DefaultEngine.ini`
- Create: `tests/fixtures/sample_config/DefaultGame.ini`

**Step 1: Create fixture files**

`tests/fixtures/sample_config/DefaultEngine.ini`:
```ini
[/Script/Engine.Engine]
bUseFixedFrameRate=True
FixedFrameRate=60.000000

[/Script/Engine.RendererSettings]
r.DefaultFeature.AutoExposure=False
+ConsoleVariables=sg.ShadowQuality=3

[/Script/Engine.GameMapsSettings]
GameDefaultMap=/Game/Maps/MainMenu
```

`tests/fixtures/sample_config/DefaultGame.ini`:
```ini
[/Script/UnrealEd.ProjectPackagingSettings]
+MapsToCook=(FilePath="/Game/Maps/Level01")
+MapsToCook=(FilePath="/Game/Maps/Level02")

[/Script/GameplayTags.GameplayTagsSettings]
+GameplayTagList=(Tag="Ability.Skill.Fireball",DevComment="")
+GameplayTagList=(Tag="Ability.Skill.IceBlast",DevComment="")
+GameplayTagList=(Tag="Status.Buff.Shield",DevComment="")
```

**Step 2: Write failing tests**

`tests/test_config_parser.py`:
```python
"""Tests for UE config/INI parser."""

import sqlite3
from pathlib import Path

import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.indexer.config_parser import ConfigParser

FIXTURES = Path(__file__).parent / "fixtures" / "sample_config"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


class TestConfigParser:
    def test_parses_sections(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        rows = conn.execute(
            "SELECT DISTINCT section FROM config_entries"
        ).fetchall()
        sections = {r[0] for r in rows}
        assert "/Script/Engine.Engine" in sections
        assert "/Script/Engine.RendererSettings" in sections

    def test_parses_key_value_pairs(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM config_entries WHERE key = 'bUseFixedFrameRate'"
        ).fetchone()
        assert row is not None
        assert dict(row)["value"] == "True"

    def test_parses_array_additions(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM config_entries WHERE key LIKE '+MapsToCook%'"
        ).fetchall()
        assert len(rows) >= 2

    def test_parses_gameplay_tag_entries(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM config_entries WHERE key LIKE '+GameplayTagList%'"
        ).fetchall()
        assert len(rows) >= 3

    def test_fts_search_works(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM config_fts WHERE config_fts MATCH 'FixedFrameRate'"
        ).fetchone()
        assert rows is not None

    def test_preserves_line_numbers(self, conn):
        parser = ConfigParser(conn)
        parser.index_config_dir(FIXTURES)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM config_entries WHERE key = 'bUseFixedFrameRate'"
        ).fetchone()
        assert dict(row)["line"] > 0
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_parser.py -v`
Expected: FAIL — module doesn't exist

**Step 4: Implement config parser**

`src/unreal_project_mcp/indexer/config_parser.py`:
```python
"""UE config/INI file parser.

Handles Unreal's non-standard INI format: duplicate keys, +/- prefixes,
array-style additions. Inserts into config_entries + config_fts.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from unreal_project_mcp.db.queries import insert_config_entry

logger = logging.getLogger(__name__)

_SECTION_RE = re.compile(r'^\[(.+)\]\s*$')
_KV_RE = re.compile(r'^([+\-\.!]?\w[\w.]*)\s*=\s*(.*?)\s*$')


class ConfigParser:
    """Parses UE .ini files and stores entries in the database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def index_config_dir(self, config_dir: Path) -> int:
        """Index all .ini files in the given directory. Returns entry count."""
        config_dir = Path(config_dir)
        count = 0
        for ini_file in sorted(config_dir.glob("*.ini")):
            try:
                count += self._parse_ini_file(ini_file)
            except Exception:
                logger.warning("Error parsing %s", ini_file, exc_info=True)
        return count

    def _parse_ini_file(self, path: Path) -> int:
        """Parse a single .ini file. Returns entry count."""
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        current_section = ""
        count = 0

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith(";") or stripped.startswith("#"):
                continue

            # Section header
            sm = _SECTION_RE.match(stripped)
            if sm:
                current_section = sm.group(1)
                continue

            # Key=Value pair
            kvm = _KV_RE.match(stripped)
            if kvm:
                key = kvm.group(1)
                value = kvm.group(2)
                insert_config_entry(
                    self._conn,
                    file_path=str(path),
                    section=current_section,
                    key=key,
                    value=value,
                    line=line_num,
                )
                count += 1

        return count
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_parser.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/unreal_project_mcp/indexer/config_parser.py tests/test_config_parser.py tests/fixtures/sample_config/
git commit -m "feat: add config/INI parser with FTS indexing"
```

---

### Task 5: Build.cs Parser

**Files:**
- Create: `src/unreal_project_mcp/indexer/build_cs_parser.py`
- Create: `tests/test_build_cs_parser.py`
- Create: `tests/fixtures/sample_build_cs/MyGame.Build.cs`

**Step 1: Create fixture**

`tests/fixtures/sample_build_cs/MyGame.Build.cs`:
```csharp
using UnrealBuildTool;

public class MyGame : ModuleRules
{
    public MyGame(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[] {
            "Core",
            "CoreUObject",
            "Engine",
            "InputCore"
        });

        PrivateDependencyModuleNames.AddRange(new string[] {
            "Slate",
            "SlateCore",
            "UMG"
        });

        PrivateDependencyModuleNames.Add("GameplayTags");

        DynamicallyLoadedModuleNames.Add("OnlineSubsystem");
    }
}
```

**Step 2: Write failing tests**

`tests/test_build_cs_parser.py`:
```python
"""Tests for Build.cs dependency parser."""

import sqlite3
from pathlib import Path

import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db import queries
from unreal_project_mcp.indexer.build_cs_parser import BuildCsParser

FIXTURES = Path(__file__).parent / "fixtures" / "sample_build_cs"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


class TestBuildCsParser:
    def test_extracts_public_dependencies(self, conn):
        mod_id = queries.insert_module(conn, name="MyGame", path="/Source/MyGame", module_type="GameModule")
        parser = BuildCsParser(conn)
        parser.parse_build_cs(FIXTURES / "MyGame.Build.cs", mod_id)
        conn.commit()
        deps = queries.get_module_dependencies(conn, mod_id, dep_type="public")
        dep_names = {d["dependency_name"] for d in deps}
        assert "Core" in dep_names
        assert "Engine" in dep_names
        assert "InputCore" in dep_names

    def test_extracts_private_dependencies(self, conn):
        mod_id = queries.insert_module(conn, name="MyGame", path="/Source/MyGame", module_type="GameModule")
        parser = BuildCsParser(conn)
        parser.parse_build_cs(FIXTURES / "MyGame.Build.cs", mod_id)
        conn.commit()
        deps = queries.get_module_dependencies(conn, mod_id, dep_type="private")
        dep_names = {d["dependency_name"] for d in deps}
        assert "Slate" in dep_names
        assert "GameplayTags" in dep_names

    def test_extracts_dynamic_dependencies(self, conn):
        mod_id = queries.insert_module(conn, name="MyGame", path="/Source/MyGame", module_type="GameModule")
        parser = BuildCsParser(conn)
        parser.parse_build_cs(FIXTURES / "MyGame.Build.cs", mod_id)
        conn.commit()
        deps = queries.get_module_dependencies(conn, mod_id, dep_type="dynamic")
        dep_names = {d["dependency_name"] for d in deps}
        assert "OnlineSubsystem" in dep_names

    def test_total_dependency_count(self, conn):
        mod_id = queries.insert_module(conn, name="MyGame", path="/Source/MyGame", module_type="GameModule")
        parser = BuildCsParser(conn)
        parser.parse_build_cs(FIXTURES / "MyGame.Build.cs", mod_id)
        conn.commit()
        all_deps = queries.get_module_dependencies(conn, mod_id)
        assert len(all_deps) == 9  # 4 public + 4 private + 1 dynamic
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_build_cs_parser.py -v`
Expected: FAIL

**Step 4: Implement**

`src/unreal_project_mcp/indexer/build_cs_parser.py`:
```python
"""Build.cs dependency extractor.

Regex-based extraction of module dependency lists from UE .Build.cs files.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from unreal_project_mcp.db.queries import insert_module_dependency

logger = logging.getLogger(__name__)

_DEP_TYPE_MAP = {
    "PublicDependencyModuleNames": "public",
    "PrivateDependencyModuleNames": "private",
    "DynamicallyLoadedModuleNames": "dynamic",
}

# Match: VarName.AddRange(new string[] { "A", "B" }) or VarName.Add("A")
_ADD_RANGE_RE = re.compile(
    r'(Public|Private|DynamicallyLoaded)DependencyModuleNames\s*\.\s*AddRange\s*\('
    r'[^{]*\{([^}]*)\}',
    re.DOTALL,
)
_ADD_SINGLE_RE = re.compile(
    r'(Public|Private|DynamicallyLoaded)DependencyModuleNames\s*\.\s*Add\s*\(\s*"(\w+)"',
)
_QUOTED_RE = re.compile(r'"(\w+)"')


class BuildCsParser:
    """Parses .Build.cs files to extract module dependencies."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def parse_build_cs(self, path: Path, module_id: int) -> int:
        """Parse a .Build.cs file and insert dependencies. Returns count."""
        text = path.read_text(encoding="utf-8", errors="replace")
        count = 0

        # AddRange calls
        for m in _ADD_RANGE_RE.finditer(text):
            prefix = m.group(1)
            dep_type = _dep_type_from_prefix(prefix)
            block = m.group(2)
            for qm in _QUOTED_RE.finditer(block):
                insert_module_dependency(
                    self._conn,
                    module_id=module_id,
                    dependency_name=qm.group(1),
                    dep_type=dep_type,
                )
                count += 1

        # Single Add calls
        for m in _ADD_SINGLE_RE.finditer(text):
            prefix = m.group(1)
            dep_type = _dep_type_from_prefix(prefix)
            dep_name = m.group(2)
            insert_module_dependency(
                self._conn,
                module_id=module_id,
                dependency_name=dep_name,
                dep_type=dep_type,
            )
            count += 1

        return count


def _dep_type_from_prefix(prefix: str) -> str:
    mapping = {
        "Public": "public",
        "Private": "private",
        "DynamicallyLoaded": "dynamic",
    }
    return mapping.get(prefix, "public")
```

**Step 5: Run tests, commit**

Run: `uv run pytest tests/test_build_cs_parser.py -v`

```bash
git add src/unreal_project_mcp/indexer/build_cs_parser.py tests/test_build_cs_parser.py tests/fixtures/sample_build_cs/
git commit -m "feat: add Build.cs dependency parser"
```

---

### Task 6: Plugin Parser

**Files:**
- Create: `src/unreal_project_mcp/indexer/plugin_parser.py`
- Create: `tests/test_plugin_parser.py`
- Create: `tests/fixtures/sample_plugins/MyPlugin.uplugin`

**Step 1: Create fixture**

`tests/fixtures/sample_plugins/MyPlugin.uplugin`:
```json
{
    "FileVersion": 3,
    "FriendlyName": "My Awesome Plugin",
    "Description": "A test plugin for development",
    "Category": "Gameplay",
    "VersionName": "1.0",
    "bCanContainContent": true,
    "bIsBetaVersion": false,
    "Modules": [
        {
            "Name": "MyPluginRuntime",
            "Type": "Runtime",
            "LoadingPhase": "Default"
        },
        {
            "Name": "MyPluginEditor",
            "Type": "Editor",
            "LoadingPhase": "PostEngineInit"
        }
    ],
    "Plugins": [
        {
            "Name": "GameplayAbilities",
            "Enabled": true
        },
        {
            "Name": "OnlineSubsystem",
            "Enabled": true
        }
    ]
}
```

**Step 2: Write failing tests**

`tests/test_plugin_parser.py`:
```python
"""Tests for .uplugin parser."""

import sqlite3
from pathlib import Path

import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db import queries
from unreal_project_mcp.indexer.plugin_parser import PluginParser

FIXTURES = Path(__file__).parent / "fixtures" / "sample_plugins"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


class TestPluginParser:
    def test_parses_plugin_metadata(self, conn):
        parser = PluginParser(conn)
        parser.parse_uplugin(FIXTURES / "MyPlugin.uplugin")
        conn.commit()
        plugin = queries.get_plugin_by_name(conn, "MyPlugin")
        assert plugin is not None
        assert plugin["friendly_name"] == "My Awesome Plugin"
        assert plugin["category"] == "Gameplay"

    def test_parses_modules(self, conn):
        parser = PluginParser(conn)
        parser.parse_uplugin(FIXTURES / "MyPlugin.uplugin")
        conn.commit()
        plugin = queries.get_plugin_by_name(conn, "MyPlugin")
        modules = queries.get_plugin_modules(conn, plugin["id"])
        assert len(modules) == 2
        names = {m["module_name"] for m in modules}
        assert names == {"MyPluginRuntime", "MyPluginEditor"}

    def test_parses_dependencies(self, conn):
        parser = PluginParser(conn)
        parser.parse_uplugin(FIXTURES / "MyPlugin.uplugin")
        conn.commit()
        plugin = queries.get_plugin_by_name(conn, "MyPlugin")
        deps = queries.get_plugin_dependencies(conn, plugin["id"])
        dep_names = {d["depends_on"] for d in deps}
        assert "GameplayAbilities" in dep_names
        assert "OnlineSubsystem" in dep_names

    def test_index_plugins_dir(self, conn):
        parser = PluginParser(conn)
        count = parser.index_plugins_dir(FIXTURES)
        conn.commit()
        assert count >= 1
```

**Step 3: Run tests to verify fail, then implement**

`src/unreal_project_mcp/indexer/plugin_parser.py`:
```python
"""Plugin descriptor (.uplugin) parser."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from unreal_project_mcp.db.queries import (
    insert_plugin,
    insert_plugin_dependency,
    insert_plugin_module,
)

logger = logging.getLogger(__name__)


class PluginParser:
    """Parses .uplugin JSON files and stores plugin metadata."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def index_plugins_dir(self, plugins_dir: Path) -> int:
        """Walk a Plugins/ directory and parse all .uplugin files. Returns count."""
        plugins_dir = Path(plugins_dir)
        count = 0
        for uplugin in sorted(plugins_dir.rglob("*.uplugin")):
            try:
                self.parse_uplugin(uplugin)
                count += 1
            except Exception:
                logger.warning("Error parsing %s", uplugin, exc_info=True)
        return count

    def parse_uplugin(self, path: Path) -> None:
        """Parse a single .uplugin file."""
        text = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(text)

        plugin_name = path.stem
        plugin_id = insert_plugin(
            self._conn,
            name=plugin_name,
            friendly_name=data.get("FriendlyName"),
            description=data.get("Description"),
            category=data.get("Category"),
            version=data.get("VersionName"),
            can_contain_content=data.get("bCanContainContent", False),
            is_beta=data.get("bIsBetaVersion", False),
            file_path=str(path),
        )

        for mod in data.get("Modules", []):
            insert_plugin_module(
                self._conn,
                plugin_id=plugin_id,
                module_name=mod.get("Name", ""),
                module_type=mod.get("Type"),
                loading_phase=mod.get("LoadingPhase"),
            )

        for dep in data.get("Plugins", []):
            if dep.get("Enabled", False):
                insert_plugin_dependency(
                    self._conn,
                    plugin_id=plugin_id,
                    depends_on=dep.get("Name", ""),
                )
```

**Step 4: Run tests, commit**

Run: `uv run pytest tests/test_plugin_parser.py -v`

```bash
git add src/unreal_project_mcp/indexer/plugin_parser.py tests/test_plugin_parser.py tests/fixtures/sample_plugins/
git commit -m "feat: add .uplugin plugin parser"
```

---

## Phase 3: C++ Parser Extensions

### Task 7: Replication Marker Extraction

**Files:**
- Modify: `src/unreal_project_mcp/indexer/cpp_parser.py`
- Test: `tests/test_cpp_parser.py`
- Create: `tests/fixtures/sample_project_source/ReplicatedActor.h`

**Step 1: Create fixture**

`tests/fixtures/sample_project_source/ReplicatedActor.h`:
```cpp
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ReplicatedActor.generated.h"

UCLASS()
class YOURPROJECT_API AReplicatedActor : public AActor
{
    GENERATED_BODY()

public:
    UFUNCTION(Server, Reliable)
    void ServerFireWeapon(FVector Direction);

    UFUNCTION(Client, Unreliable)
    void ClientPlayHitEffect(FVector Location);

    UFUNCTION(NetMulticast, Reliable)
    void MulticastOnDeath();

    UPROPERTY(Replicated)
    float Health;

    UPROPERTY(ReplicatedUsing=OnRep_Ammo)
    int32 Ammo;

    UFUNCTION()
    void OnRep_Ammo();
};
```

**Step 2: Write failing tests**

Add to `tests/test_cpp_parser.py` (or create a new section):

```python
class TestReplicationExtraction:
    def test_extracts_server_rpc(self):
        parser = CppParser()
        result = parser.parse_file(FIXTURES / "ReplicatedActor.h")
        server_funcs = [s for s in result.symbols
                        if s.name == "ServerFireWeapon"]
        assert len(server_funcs) == 1
        assert server_funcs[0].ue_specifiers is not None
        assert "Server" in server_funcs[0].ue_specifiers

    def test_extracts_client_rpc(self):
        parser = CppParser()
        result = parser.parse_file(FIXTURES / "ReplicatedActor.h")
        client_funcs = [s for s in result.symbols
                        if s.name == "ClientPlayHitEffect"]
        assert len(client_funcs) == 1
        assert "Client" in client_funcs[0].ue_specifiers

    def test_extracts_multicast_rpc(self):
        parser = CppParser()
        result = parser.parse_file(FIXTURES / "ReplicatedActor.h")
        mc_funcs = [s for s in result.symbols
                    if s.name == "MulticastOnDeath"]
        assert len(mc_funcs) == 1
        assert "NetMulticast" in mc_funcs[0].ue_specifiers

    def test_extracts_replicated_property(self):
        parser = CppParser()
        result = parser.parse_file(FIXTURES / "ReplicatedActor.h")
        health = [s for s in result.symbols if s.name == "Health"]
        assert len(health) == 1
        assert "Replicated" in health[0].ue_specifiers

    def test_extracts_replicated_using(self):
        parser = CppParser()
        result = parser.parse_file(FIXTURES / "ReplicatedActor.h")
        ammo = [s for s in result.symbols if s.name == "Ammo"]
        assert len(ammo) == 1
        assert "ReplicatedUsing" in ammo[0].ue_specifiers
        assert ammo[0].rep_notify_func == "OnRep_Ammo"
```

**Step 3: Implement**

Add to `ParsedSymbol` dataclass in `cpp_parser.py`:
```python
ue_specifiers: list[str] = field(default_factory=list)
rep_notify_func: str | None = None
```

When extracting UE macro arguments (in `_try_get_ue_macro` and `_try_get_ue_macro_field`), also capture the macro's argument text. Then when creating `ParsedSymbol`, parse the argument text for replication keywords:

- If the argument text contains `Server`, `Client`, `NetMulticast` → add to `ue_specifiers`
- If it contains `Replicated` → add `"Replicated"` to `ue_specifiers`
- If it contains `ReplicatedUsing=X` → add `"ReplicatedUsing"` to `ue_specifiers`, set `rep_notify_func = X`

The macro argument text is available from the `call_expression` node's `argument_list` child.

Modify `_try_get_ue_macro` to return `(macro_name, macro_args_text)` tuple instead of just `macro_name`. Thread the args text through to symbol creation.

**Step 4: Run tests, commit**

Run: `uv run pytest tests/test_cpp_parser.py::TestReplicationExtraction -v`

```bash
git add src/unreal_project_mcp/indexer/cpp_parser.py tests/test_cpp_parser.py tests/fixtures/sample_project_source/ReplicatedActor.h
git commit -m "feat: extract replication markers from UFUNCTION/UPROPERTY specifiers"
```

---

### Task 8: Asset Path + Log Category Extraction in Reference Builder

**Files:**
- Modify: `src/unreal_project_mcp/indexer/reference_builder.py`
- Create: `tests/fixtures/sample_project_source/AssetLoader.cpp`

**Step 1: Create fixture**

`tests/fixtures/sample_project_source/AssetLoader.cpp`:
```cpp
#include "AssetLoader.h"

DEFINE_LOG_CATEGORY(LogAssetLoader);

void UAssetLoader::LoadWeapon()
{
    static ConstructorHelpers::FObjectFinder<UBlueprint> WeaponBP(
        TEXT("/Game/Blueprints/BP_Weapon"));

    FSoftObjectPath ShieldPath(TEXT("/Game/Blueprints/BP_Shield.BP_Shield_C"));

    UObject* Loaded = LoadObject<UStaticMesh>(
        nullptr, TEXT("/Game/Meshes/SM_Cube"));

    UE_LOG(LogAssetLoader, Warning, TEXT("Loading weapon blueprint"));
}
```

Also create `tests/fixtures/sample_project_source/AssetLoader.h`:
```cpp
#pragma once

#include "CoreMinimal.h"
#include "AssetLoader.generated.h"

DECLARE_LOG_CATEGORY_EXTERN(LogAssetLoader, Warning, All);

UCLASS()
class UAssetLoader : public UObject
{
    GENERATED_BODY()
public:
    void LoadWeapon();
};
```

**Step 2: Write failing tests for asset extraction and log categories**

These tests should verify that after running the full pipeline on the expanded fixtures:
- `asset_references` table contains entries for the three asset paths
- `log_categories` table contains `LogAssetLoader`

Add to `tests/test_pipeline.py`:

```python
class TestAssetAndLogExtraction:
    def test_extracts_asset_references(self, indexed_db):
        db, _ = indexed_db
        rows = db.execute("SELECT * FROM asset_references").fetchall()
        paths = {dict(r)["asset_path"] for r in rows}
        assert "/Game/Blueprints/BP_Weapon" in paths or any("BP_Weapon" in p for p in paths)

    def test_extracts_log_categories(self, indexed_db):
        db, _ = indexed_db
        rows = db.execute("SELECT * FROM log_categories").fetchall()
        names = {dict(r)["name"] for r in rows}
        assert "LogAssetLoader" in names
```

**Step 3: Implement**

In `reference_builder.py`, add two new extraction methods called during `extract_references`:

```python
_ASSET_PATH_RE = re.compile(r'TEXT\(\s*"(/(?:Game|Script|Engine)/[^"]+)"\s*\)')
_LOG_DECL_RE = re.compile(r'DECLARE_LOG_CATEGORY_EXTERN\s*\(\s*(\w+)')
_LOG_DEF_RE = re.compile(r'DEFINE_LOG_CATEGORY\s*\(\s*(\w+)')
_CONSTRUCTOR_HELPER_RE = re.compile(r'ConstructorHelpers::F\w+\s*<[^>]+>\s*\w+\s*\(\s*TEXT\(\s*"(/[^"]+)"')
_LOAD_OBJECT_RE = re.compile(r'LoadObject\s*<[^>]+>\s*\([^,]*,\s*TEXT\(\s*"(/[^"]+)"')
_SOFT_PATH_RE = re.compile(r'FSoftObjectPath\s*\(\s*TEXT\(\s*"(/[^"]+)"')
```

`extract_asset_references(self, source_text, func_node, caller_id, file_id)`:
- Regex scan the function body text for asset path patterns
- For each match, determine `ref_type` and insert into `asset_references`

`extract_log_categories(self, source_text, file_id)`:
- Scan full file for `DECLARE_LOG_CATEGORY_EXTERN` and `DEFINE_LOG_CATEGORY`
- Insert into `log_categories`

**Step 4: Run tests, commit**

Run: `uv run pytest tests/test_pipeline.py::TestAssetAndLogExtraction -v`

```bash
git add src/unreal_project_mcp/indexer/reference_builder.py tests/fixtures/sample_project_source/AssetLoader.* tests/test_pipeline.py
git commit -m "feat: extract asset path references and log categories from C++ source"
```

---

## Phase 4: Pipeline Integration

### Task 9: Extended Pipeline

**Files:**
- Modify: `src/unreal_project_mcp/indexer/pipeline.py`
- Modify: `src/unreal_project_mcp/config.py` (use `_detect_project_root`)
- Test: `tests/test_pipeline.py`

**Step 1: Write failing test**

Add to `tests/test_pipeline.py`:

```python
class TestExpandedPipeline:
    def test_indexes_config_files(self, db, tmp_path):
        """Pipeline should index Config/*.ini files."""
        root = tmp_path / "MyGame"
        root.mkdir()
        (root / "MyGame.uproject").write_text("{}")
        src = root / "Source" / "MyGame"
        src.mkdir(parents=True)
        (src / "Test.h").write_text("#pragma once\nclass ATestActor {};\n")
        cfg = root / "Config"
        cfg.mkdir()
        (cfg / "DefaultEngine.ini").write_text(
            "[/Script/Engine]\nbUseFixed=True\n"
        )

        pipeline = IndexingPipeline(db)
        stats = pipeline.index_project(root)

        rows = db.execute("SELECT COUNT(*) FROM config_entries").fetchone()
        assert rows[0] >= 1

    def test_indexes_build_cs(self, db, tmp_path):
        """Pipeline should parse .Build.cs files for dependencies."""
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
        """Pipeline should parse .uplugin files."""
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
```

**Step 2: Implement pipeline extensions**

In `pipeline.py`, after existing C++ indexing in `index_project()`:

```python
# Phase 2: Non-C++ indexing
project_root = _detect_project_root_from(project_path)
if project_root:
    config_dir = project_root / "Config"
    if config_dir.is_dir():
        from unreal_project_mcp.indexer.config_parser import ConfigParser
        config_parser = ConfigParser(self._conn)
        config_parser.index_config_dir(config_dir)

    # Build.cs files
    from unreal_project_mcp.indexer.build_cs_parser import BuildCsParser
    build_parser = BuildCsParser(self._conn)
    # For each module, find its .Build.cs
    for mod_path, mod_name, mod_type in modules:
        for build_cs in mod_path.parent.glob("*.Build.cs"):
            mod = get_module_by_name(self._conn, mod_name)
            if mod:
                build_parser.parse_build_cs(build_cs, mod["id"])

    plugins_dir = project_root / "Plugins"
    if plugins_dir.is_dir():
        from unreal_project_mcp.indexer.plugin_parser import PluginParser
        plugin_parser = PluginParser(self._conn)
        plugin_parser.index_plugins_dir(plugins_dir)

self._conn.commit()
```

Add a helper `_detect_project_root_from(path)` that does the same logic as `config.py._detect_project_root()` but takes a path argument directly (since pipeline receives the path as a parameter, not from env var).

**Step 3: Run tests, commit**

Run: `uv run pytest tests/test_pipeline.py::TestExpandedPipeline -v`

```bash
git add src/unreal_project_mcp/indexer/pipeline.py src/unreal_project_mcp/config.py tests/test_pipeline.py
git commit -m "feat: expand pipeline to index config, Build.cs, and plugins"
```

---

### Task 10: Replication + Data Table Pipeline Integration

**Files:**
- Modify: `src/unreal_project_mcp/indexer/pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write failing tests**

```python
class TestReplicationAndDataTablePipeline:
    def test_inserts_replication_entries(self, indexed_db):
        db, _ = indexed_db
        rows = db.execute("SELECT COUNT(*) FROM replication_entries").fetchone()
        # ReplicatedActor.h has 3 RPCs + 2 replicated properties = 5
        assert rows[0] >= 3

    def test_detects_data_table_structs(self, db, tmp_path):
        src = tmp_path / "Source" / "MyGame"
        src.mkdir(parents=True)
        (src / "WeaponData.h").write_text(
            '#pragma once\n#include "Engine/DataTable.h"\n'
            'USTRUCT()\nstruct FWeaponDataRow : public FTableRowBase\n'
            '{\n    GENERATED_BODY()\n    float Damage;\n};\n'
        )
        pipeline = IndexingPipeline(db)
        pipeline.index_project(tmp_path)
        rows = db.execute("SELECT COUNT(*) FROM data_tables").fetchone()
        assert rows[0] >= 1
```

**Step 2: Implement**

In `pipeline.py._finalize()`, after inheritance resolution:
1. Iterate symbols with `ue_specifiers` containing replication markers → insert into `replication_entries`
2. Query inheritance for structs inheriting `FTableRowBase` → insert into `data_tables`

The replication data comes from `ParsedSymbol.ue_specifiers` which was added in Task 7. The pipeline needs to store these during `_index_cpp_file` and process them in `_finalize`.

**Step 3: Run tests, commit**

```bash
git add src/unreal_project_mcp/indexer/pipeline.py tests/test_pipeline.py
git commit -m "feat: integrate replication entries and data table detection into pipeline"
```

---

## Phase 5: Tag Scanner + Pattern Tagger

### Task 11: Tag Scanner

**Files:**
- Create: `src/unreal_project_mcp/indexer/tag_scanner.py`
- Create: `tests/test_tag_scanner.py`

**Step 1: Write failing tests**

`tests/test_tag_scanner.py`:
```python
"""Tests for gameplay tag scanner."""

import sqlite3
from pathlib import Path

import pytest

from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db import queries
from unreal_project_mcp.indexer.tag_scanner import TagScanner

FIXTURES_CONFIG = Path(__file__).parent / "fixtures" / "sample_config"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


class TestTagScannerFromConfig:
    def test_extracts_tags_from_ini(self, conn):
        # Seed config_entries with gameplay tag data
        queries.insert_config_entry(
            conn, file_path="/Config/DefaultGame.ini",
            section="/Script/GameplayTags.GameplayTagsSettings",
            key='+GameplayTagList',
            value='(Tag="Ability.Skill.Fireball",DevComment="")',
            line=10,
        )
        conn.commit()
        scanner = TagScanner(conn)
        scanner.scan_config_tags()
        conn.commit()
        rows = conn.execute("SELECT * FROM gameplay_tags").fetchall()
        tags = {dict(r)["tag"] for r in rows}
        assert "Ability.Skill.Fireball" in tags


class TestTagScannerFromCpp:
    def test_extracts_native_tag_definitions(self, conn):
        # Seed source_fts with C++ code containing tag definitions
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.cpp", module_id=mod_id, file_type="source", line_count=10)
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (file_id, 5, 'AddNativeGameplayTag(TEXT("Ability.Skill.Fireball"))'),
        )
        conn.commit()
        scanner = TagScanner(conn)
        scanner.scan_cpp_tags()
        conn.commit()
        rows = conn.execute("SELECT * FROM gameplay_tags WHERE usage_kind = 'definition'").fetchall()
        assert len(rows) >= 1

    def test_extracts_tag_requests(self, conn):
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.cpp", module_id=mod_id, file_type="source", line_count=10)
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (file_id, 10, 'FGameplayTag Tag = RequestGameplayTag(FName(TEXT("Status.Buff.Shield")))'),
        )
        conn.commit()
        scanner = TagScanner(conn)
        scanner.scan_cpp_tags()
        conn.commit()
        rows = conn.execute("SELECT * FROM gameplay_tags WHERE usage_kind = 'request'").fetchall()
        assert len(rows) >= 1
```

**Step 2: Implement**

`src/unreal_project_mcp/indexer/tag_scanner.py`:
```python
"""Gameplay tag scanner — extracts tags from C++, INI, and data tables."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from unreal_project_mcp.db.queries import insert_gameplay_tag

logger = logging.getLogger(__name__)

_TAG_IN_TEXT_RE = re.compile(r'TEXT\(\s*"([A-Za-z][\w.]*(?:\.[A-Za-z][\w.]*)*)"\s*\)')
_TAG_IN_INI_RE = re.compile(r'Tag="([^"]+)"')

_CPP_DEFINITION_PATTERNS = ["AddNativeGameplayTag"]
_CPP_REQUEST_PATTERNS = ["RequestGameplayTag"]
_CPP_CHECK_PATTERNS = ["HasMatchingGameplayTag", "MatchesTag", "HasTag", "HasAny", "HasAll"]


class TagScanner:
    """Scans multiple sources for gameplay tag usage."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def scan_all(self, content_dir: Path | None = None) -> int:
        count = 0
        count += self.scan_config_tags()
        count += self.scan_cpp_tags()
        if content_dir and content_dir.is_dir():
            count += self.scan_csv_tags(content_dir)
        return count

    def scan_config_tags(self) -> int:
        """Extract gameplay tags from config_entries."""
        rows = self._conn.execute(
            "SELECT * FROM config_entries WHERE key LIKE '%GameplayTag%'"
        ).fetchall()
        count = 0
        for row in rows:
            value = row["value"] or ""
            for m in _TAG_IN_INI_RE.finditer(value):
                tag = m.group(1)
                if "." in tag:  # gameplay tags are dot-separated
                    insert_gameplay_tag(
                        self._conn, tag=tag, source_type="ini",
                        usage_kind="definition",
                        file_path=row["file_path"], line=row["line"],
                    )
                    count += 1
        return count

    def scan_cpp_tags(self) -> int:
        """Extract gameplay tags from indexed C++ source (source_fts)."""
        count = 0

        for pattern_list, usage_kind in [
            (_CPP_DEFINITION_PATTERNS, "definition"),
            (_CPP_REQUEST_PATTERNS, "request"),
            (_CPP_CHECK_PATTERNS, "check"),
        ]:
            for pattern in pattern_list:
                rows = self._conn.execute(
                    "SELECT sf.file_id, sf.line_number, sf.text "
                    "FROM source_fts sf WHERE source_fts MATCH ?",
                    (f'"{pattern}"',),
                ).fetchall()
                for row in rows:
                    text = row["text"] or ""
                    if pattern not in text:
                        continue
                    for m in _TAG_IN_TEXT_RE.finditer(text):
                        tag = m.group(1)
                        if "." in tag:
                            file_row = self._conn.execute(
                                "SELECT path FROM files WHERE id = ?",
                                (row["file_id"],),
                            ).fetchone()
                            file_path = file_row["path"] if file_row else None
                            insert_gameplay_tag(
                                self._conn, tag=tag, source_type="cpp",
                                usage_kind=usage_kind,
                                file_path=file_path,
                                line=row["line_number"],
                            )
                            count += 1
        return count

    def scan_csv_tags(self, content_dir: Path) -> int:
        """Scan CSV data tables for gameplay tag columns."""
        import csv
        count = 0
        for csv_file in content_dir.rglob("*.csv"):
            try:
                with open(csv_file, encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    if not reader.fieldnames:
                        continue
                    tag_cols = [c for c in reader.fieldnames
                                if "tag" in c.lower() or "Tag" in c]
                    if not tag_cols:
                        continue
                    for row_num, row in enumerate(reader, 2):
                        for col in tag_cols:
                            val = row.get(col, "")
                            if val and "." in val:
                                insert_gameplay_tag(
                                    self._conn, tag=val,
                                    source_type="datatable",
                                    usage_kind="definition",
                                    file_path=str(csv_file),
                                    line=row_num,
                                )
                                count += 1
            except Exception:
                logger.warning("Error scanning %s", csv_file, exc_info=True)
        return count
```

**Step 3: Run tests, commit**

Run: `uv run pytest tests/test_tag_scanner.py -v`

```bash
git add src/unreal_project_mcp/indexer/tag_scanner.py tests/test_tag_scanner.py
git commit -m "feat: add gameplay tag scanner for C++, INI, and CSV sources"
```

---

### Task 12: Pattern Tagger

**Files:**
- Create: `src/unreal_project_mcp/indexer/pattern_tagger.py`
- Create: `tests/test_pattern_tagger.py`

**Step 1: Write failing tests**

`tests/test_pattern_tagger.py`:
```python
"""Tests for pattern tagger (subsystems, anim notifies, console commands)."""

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

        tagger = PatternTagger(conn)
        tagger.tag_subsystems()
        conn.commit()

        tags = queries.get_pattern_tags(conn, kind="subsystem")
        assert len(tags) == 1
        assert tags[0]["symbol_name"] == "UMyWorldSubsystem"


class TestConsoleCommandTagging:
    def test_tags_console_commands(self, conn):
        mod_id = queries.insert_module(conn, name="Test", path="/test", module_type="GameModule")
        file_id = queries.insert_file(conn, path="/test.cpp", module_id=mod_id, file_type="source", line_count=50)
        conn.execute(
            "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
            (file_id, 10,
             'IConsoleManager::Get().RegisterConsoleCommand(TEXT("my.debug.cmd"), TEXT("Debug help"))'),
        )
        conn.commit()

        tagger = PatternTagger(conn)
        tagger.tag_console_commands()
        conn.commit()

        tags = queries.get_pattern_tags(conn, kind="console_command")
        assert len(tags) >= 1
```

**Step 2: Implement**

`src/unreal_project_mcp/indexer/pattern_tagger.py`:
```python
"""Pattern tagger — tags subsystems, anim notifies, and console commands."""

from __future__ import annotations

import json
import logging
import re
import sqlite3

from unreal_project_mcp.db.queries import (
    get_inheritance_children,
    insert_pattern_tag,
)

logger = logging.getLogger(__name__)

_SUBSYSTEM_BASES = {
    "UGameInstanceSubsystem": "GameInstance",
    "UWorldSubsystem": "World",
    "ULocalPlayerSubsystem": "LocalPlayer",
    "UEngineSubsystem": "Engine",
}

_ANIM_NOTIFY_BASES = {"UAnimNotify", "UAnimNotifyState"}

_CONSOLE_CMD_RE = re.compile(r'RegisterConsoleCommand\s*\(\s*TEXT\(\s*"([^"]+)"')


class PatternTagger:
    """Post-indexing pass that tags symbols matching known UE patterns."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def tag_all(self) -> int:
        count = 0
        count += self.tag_subsystems()
        count += self.tag_anim_notifies()
        count += self.tag_console_commands()
        return count

    def tag_subsystems(self) -> int:
        count = 0
        for base_name, subsystem_type in _SUBSYSTEM_BASES.items():
            row = self._conn.execute(
                "SELECT id FROM symbols WHERE name = ? AND kind IN ('class', 'struct')",
                (base_name,),
            ).fetchone()
            if not row:
                continue
            children = get_inheritance_children(self._conn, row[0])
            for child in children:
                insert_pattern_tag(
                    self._conn, symbol_id=child["id"],
                    tag_kind="subsystem",
                    metadata=json.dumps({"type": subsystem_type}),
                )
                count += 1
        return count

    def tag_anim_notifies(self) -> int:
        count = 0
        for base_name in _ANIM_NOTIFY_BASES:
            row = self._conn.execute(
                "SELECT id FROM symbols WHERE name = ? AND kind IN ('class', 'struct')",
                (base_name,),
            ).fetchone()
            if not row:
                continue
            children = get_inheritance_children(self._conn, row[0])
            for child in children:
                insert_pattern_tag(
                    self._conn, symbol_id=child["id"],
                    tag_kind="anim_notify",
                )
                count += 1
        return count

    def tag_console_commands(self) -> int:
        count = 0
        rows = self._conn.execute(
            "SELECT sf.file_id, sf.line_number, sf.text "
            "FROM source_fts sf WHERE source_fts MATCH '\"RegisterConsoleCommand\"'"
        ).fetchall()

        for row in rows:
            text = row["text"] or ""
            for m in _CONSOLE_CMD_RE.finditer(text):
                cmd_name = m.group(1)
                # Find the enclosing function symbol to attach the tag to
                file_id = row["file_id"]
                line = row["line_number"]
                sym = self._conn.execute(
                    "SELECT id FROM symbols WHERE file_id = ? AND line_start <= ? AND line_end >= ? "
                    "AND kind = 'function' ORDER BY (line_end - line_start) ASC LIMIT 1",
                    (file_id, line, line),
                ).fetchone()
                if sym:
                    insert_pattern_tag(
                        self._conn, symbol_id=sym[0],
                        tag_kind="console_command",
                        metadata=json.dumps({"command": cmd_name}),
                    )
                    count += 1
        return count
```

**Step 3: Run tests, commit**

Run: `uv run pytest tests/test_pattern_tagger.py -v`

```bash
git add src/unreal_project_mcp/indexer/pattern_tagger.py tests/test_pattern_tagger.py
git commit -m "feat: add pattern tagger for subsystems, anim notifies, console commands"
```

---

### Task 13: Wire Tag Scanner + Pattern Tagger into Pipeline

**Files:**
- Modify: `src/unreal_project_mcp/indexer/pipeline.py`

**Step 1: Add to `_finalize()` after existing finalization**

```python
# Phase 4: Post-index passes
from unreal_project_mcp.indexer.tag_scanner import TagScanner
tag_scanner = TagScanner(self._conn)
tag_scanner.scan_all(content_dir=content_dir)

from unreal_project_mcp.indexer.pattern_tagger import PatternTagger
tagger = PatternTagger(self._conn)
tagger.tag_all()

self._conn.commit()
```

The `content_dir` needs to be threaded through from `index_project` to `_finalize`. Store it as `self._content_dir` during `index_project`.

**Step 2: Run full test suite**

Run: `uv run pytest -v`

**Step 3: Commit**

```bash
git add src/unreal_project_mcp/indexer/pipeline.py
git commit -m "feat: wire tag scanner and pattern tagger into pipeline finalize"
```

---

## Phase 6: MCP Tool Handlers

### Task 14: Config Tools (get_config_values, search_config)

**Files:**
- Modify: `src/unreal_project_mcp/server.py`
- Test: `tests/test_server.py`

**Step 1: Add tool handlers to server.py**

```python
@mcp.tool()
def get_config_values(key: str, section: str = "") -> str:
    """Look up config/INI values by key name. Cross-references with UPROPERTY(Config) symbols."""
    conn = _get_conn()
    results = get_config_by_key(conn, key, section=section or None)
    if not results:
        return f"No config entries found for key '{key}'."
    lines = []
    for r in results:
        lines.append(f"[{r['section']}] {r['key']} = {r['value']}")
        lines.append(f"  {_short_path(r['file_path'])}:{r['line']}")
    # Cross-reference with C++ symbols
    sym_results = get_symbols_by_name(conn, key)
    config_syms = [s for s in sym_results if s.get("is_ue_macro")]
    if config_syms:
        lines.append("\nC++ declaration:")
        for s in config_syms:
            fp = _get_file_path(conn, s["file_id"])
            lines.append(f"  {s['signature']} ({_short_path(fp)}:{s['line_start']})")
    return "\n".join(lines)


@mcp.tool()
def search_config(query: str, limit: int = 20) -> str:
    """Full-text search across all project config/INI files."""
    conn = _get_conn()
    results = search_config_fts(conn, query, limit=limit)
    if not results:
        return f"No config entries found for '{query}'."
    lines = []
    for r in results:
        lines.append(f"[{r['section']}] {r['key']} = {r['value']}")
        lines.append(f"  {_short_path(r['file_path'])}:{r['line']}")
    return "\n".join(lines)
```

Add the necessary imports from `queries.py`.

**Step 2: Run existing tests to check nothing is broken, commit**

Run: `uv run pytest tests/test_server.py -v`

```bash
git add src/unreal_project_mcp/server.py
git commit -m "feat: add get_config_values and search_config MCP tools"
```

---

### Task 15: Asset + Data Table Tools

Add to `server.py`:

```python
@mcp.tool()
def find_asset_references(asset_path: str = "", symbol: str = "") -> str:
    """Find C++ code that references assets by path, or assets referenced by a symbol."""
    ...

@mcp.tool()
def find_data_table_schema(name: str) -> str:
    """Show the FTableRowBase struct definition and linked data table for a data table schema."""
    ...
```

Commit: `feat: add find_asset_references and find_data_table_schema MCP tools`

---

### Task 16: Gameplay Tags + Module Dependencies + Plugin Info Tools

Add to `server.py`:

```python
@mcp.tool()
def search_gameplay_tags(query: str, usage_kind: str = "") -> str:
    """Search gameplay tag definitions, requests, and checks across the project."""
    ...

@mcp.tool()
def get_module_dependencies(module_name: str, direction: str = "both") -> str:
    """Show Build.cs dependency graph for a module (dependencies, dependents, or both)."""
    ...

@mcp.tool()
def get_plugin_info(plugin_name: str) -> str:
    """Show plugin metadata, modules, and dependencies."""
    ...
```

Commit: `feat: add gameplay tags, module dependencies, and plugin info MCP tools`

---

### Task 17: Log Sites + Replication Map + Pattern Tags Tools

Add to `server.py`:

```python
@mcp.tool()
def find_log_sites(category: str, limit: int = 50) -> str:
    """Find log category declaration and all UE_LOG usage sites."""
    ...

@mcp.tool()
def get_replication_map(class_name: str = "") -> str:
    """Show Server/Client/NetMulticast RPCs and replicated properties."""
    ...

@mcp.tool()
def search_project_tags(kind: str = "", query: str = "") -> str:
    """Search pattern tags: subsystems, anim_notify, console_command."""
    ...
```

Commit: `feat: add log sites, replication map, and pattern tags MCP tools`

---

## Phase 7: Integration + Cleanup

### Task 18: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Update:
- Tool count from 7 to 17
- Add new tables to DB section
- Update project structure with new files
- Update environment variable docs (note auto-detection)

Commit: `docs: update CLAUDE.md with v2 project intelligence features`

---

### Task 19: Full Integration Test

**Files:**
- Modify: `tests/test_e2e.py`

Create a comprehensive fixture that includes all file types:
- C++ files with replication, asset refs, log categories
- Config/INI with gameplay tags
- .Build.cs with dependencies
- .uplugin with modules and deps
- CSV data table with tag column

Run the full pipeline, then query each of the 10 new tools to verify they return non-empty results.

Commit: `test: add full integration test for all 17 MCP tools`

---

### Task 20: Run Full Suite + Final Commit

Run: `uv run pytest -v`
Expected: ALL PASS

```bash
git add -A
git commit -m "feat: complete project intelligence expansion v2"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| 1: Foundation | 1-3 | Schema v2, project root detection, all query helpers |
| 2: Non-C++ Indexers | 4-6 | Config parser, Build.cs parser, Plugin parser |
| 3: C++ Extensions | 7-8 | Replication markers, asset paths, log categories |
| 4: Pipeline | 9-10 | All indexers wired into pipeline |
| 5: Post-Index | 11-13 | Tag scanner, pattern tagger, pipeline integration |
| 6: MCP Tools | 14-17 | All 10 new tool handlers |
| 7: Cleanup | 18-20 | Docs, integration tests, final verification |

**Total: 20 tasks across 7 phases. Each task is independently testable and committable.**
