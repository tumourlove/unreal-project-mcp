"""SQLite schema for unreal-source-mcp."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

_DDL = """
-- Core tables ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS modules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL,
    module_type TEXT NOT NULL,
    build_cs_path TEXT,
    UNIQUE(name, path)
);

CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT NOT NULL UNIQUE,
    module_id     INTEGER REFERENCES modules(id),
    file_type     TEXT NOT NULL,
    line_count    INTEGER NOT NULL DEFAULT 0,
    last_modified REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS symbols (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    qualified_name   TEXT NOT NULL,
    kind             TEXT NOT NULL,
    file_id          INTEGER REFERENCES files(id),
    line_start       INTEGER,
    line_end         INTEGER,
    parent_symbol_id INTEGER REFERENCES symbols(id),
    access           TEXT,
    signature        TEXT,
    docstring        TEXT,
    is_ue_macro      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_symbols_name            ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_qualified_name  ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbols_kind            ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_file_id         ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_parent          ON symbols(parent_symbol_id);

CREATE TABLE IF NOT EXISTS inheritance (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id  INTEGER NOT NULL REFERENCES symbols(id),
    parent_id INTEGER NOT NULL REFERENCES symbols(id),
    UNIQUE(child_id, parent_id)
);

CREATE TABLE IF NOT EXISTS "references" (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    from_symbol_id INTEGER NOT NULL REFERENCES symbols(id),
    to_symbol_id   INTEGER NOT NULL REFERENCES symbols(id),
    ref_kind       TEXT NOT NULL,
    file_id        INTEGER REFERENCES files(id),
    line           INTEGER
);

CREATE INDEX IF NOT EXISTS idx_refs_from ON "references"(from_symbol_id);
CREATE INDEX IF NOT EXISTS idx_refs_to   ON "references"(to_symbol_id);
CREATE INDEX IF NOT EXISTS idx_refs_kind ON "references"(ref_kind);

CREATE TABLE IF NOT EXISTS includes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id       INTEGER NOT NULL REFERENCES files(id),
    included_path TEXT NOT NULL,
    line          INTEGER
);

-- FTS5 virtual tables --------------------------------------------------------

CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    qualified_name,
    docstring,
    content=symbols,
    content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS source_fts USING fts5(
    file_id UNINDEXED,
    line_number UNINDEXED,
    text
);

-- Meta table -----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- v2 tables ------------------------------------------------------------------

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
"""

_TRIGGERS = """
-- Keep symbols_fts in sync with symbols table

CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, qualified_name, docstring)
    VALUES (new.id, new.name, new.qualified_name, new.docstring);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, qualified_name, docstring)
    VALUES ('delete', old.id, old.name, old.qualified_name, old.docstring);
END;

-- Keep config_fts in sync with config_entries table

CREATE TRIGGER IF NOT EXISTS config_ai AFTER INSERT ON config_entries BEGIN
    INSERT INTO config_fts(rowid, section, key, value)
    VALUES (new.id, new.section, new.key, new.value);
END;

CREATE TRIGGER IF NOT EXISTS config_ad AFTER DELETE ON config_entries BEGIN
    INSERT INTO config_fts(config_fts, rowid, section, key, value)
    VALUES ('delete', old.id, old.section, old.key, old.value);
END;

-- Keep tags_fts in sync with gameplay_tags table

CREATE TRIGGER IF NOT EXISTS tags_ai AFTER INSERT ON gameplay_tags BEGIN
    INSERT INTO tags_fts(rowid, tag) VALUES (new.id, new.tag);
END;

CREATE TRIGGER IF NOT EXISTS tags_ad AFTER DELETE ON gameplay_tags BEGIN
    INSERT INTO tags_fts(tags_fts, rowid, tag)
    VALUES ('delete', old.id, old.tag);
END;
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, FTS virtual tables, and triggers.

    Sets schema_version in meta table.
    """
    conn.executescript(_DDL)
    conn.executescript(_TRIGGERS)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
