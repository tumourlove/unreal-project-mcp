"""Insert and query helpers for the unreal-source-mcp database."""

from __future__ import annotations

import re
import sqlite3

# SQL table name — quoted to avoid any keyword conflicts
_REFS_TABLE = '"references"'


# ── Helpers ──────────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def _escape_fts(query: str) -> str:
    """Prepare a user query for FTS5 MATCH.

    Strips special FTS characters, replaces :: with space,
    wraps each token in quotes with trailing * for prefix matching.
    """
    # Replace :: with space (common in C++ qualified names)
    q = query.replace("::", " ")
    # Strip FTS5 special chars
    q = re.sub(r'[^\w\s]', '', q)
    tokens = q.split()
    if not tokens:
        return '""'
    return " ".join(f'"{t}"*' for t in tokens)


# ── Insert helpers ───────────────────────────────────────────────────────

def insert_module(
    conn: sqlite3.Connection, *, name: str, path: str,
    module_type: str, build_cs_path: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO modules (name, path, module_type, build_cs_path) "
        "VALUES (?, ?, ?, ?)",
        (name, path, module_type, build_cs_path),
    )
    if cur.lastrowid and cur.rowcount > 0:
        return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM modules WHERE name = ? AND path = ?", (name, path)
    ).fetchone()
    return row[0]


def insert_file(
    conn: sqlite3.Connection, *, path: str, module_id: int,
    file_type: str, line_count: int, last_modified: float = 0.0,
) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO files (path, module_id, file_type, line_count, last_modified) "
        "VALUES (?, ?, ?, ?, ?)",
        (path, module_id, file_type, line_count, last_modified),
    )
    if cur.lastrowid and cur.rowcount > 0:
        return cur.lastrowid
    row = conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
    return row[0]


def insert_symbol(
    conn: sqlite3.Connection, *, name: str, qualified_name: str,
    kind: str, file_id: int, line_start: int, line_end: int,
    parent_symbol_id: int | None, access: str | None,
    signature: str | None, docstring: str | None, is_ue_macro: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO symbols (name, qualified_name, kind, file_id, line_start, "
        "line_end, parent_symbol_id, access, signature, docstring, is_ue_macro) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, qualified_name, kind, file_id, line_start, line_end,
         parent_symbol_id, access, signature, docstring, is_ue_macro),
    )
    return cur.lastrowid


def insert_inheritance(
    conn: sqlite3.Connection, *, child_id: int, parent_id: int,
) -> None:
    conn.execute(
        "INSERT INTO inheritance (child_id, parent_id) VALUES (?, ?)",
        (child_id, parent_id),
    )


def insert_reference(
    conn: sqlite3.Connection, *, from_symbol_id: int, to_symbol_id: int,
    ref_kind: str, file_id: int, line: int,
) -> None:
    conn.execute(
        f"INSERT INTO {_REFS_TABLE} (from_symbol_id, to_symbol_id, ref_kind, file_id, line) "
        "VALUES (?, ?, ?, ?, ?)",
        (from_symbol_id, to_symbol_id, ref_kind, file_id, line),
    )


def insert_include(
    conn: sqlite3.Connection, *, file_id: int, included_path: str, line: int,
) -> None:
    conn.execute(
        "INSERT INTO includes (file_id, included_path, line) VALUES (?, ?, ?)",
        (file_id, included_path, line),
    )


# ── Query helpers ────────────────────────────────────────────────────────

def get_symbol_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    """Exact match on qualified_name first, then fall back to name.

    Prefers multi-line definitions over single-line forward declarations.
    """
    row = conn.execute(
        "SELECT * FROM symbols WHERE qualified_name = ? "
        "ORDER BY (line_end > line_start) DESC LIMIT 1",
        (name,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM symbols WHERE name = ? "
            "ORDER BY (line_end > line_start) DESC LIMIT 1",
            (name,),
        ).fetchone()
    return _row_to_dict(row)


def get_symbol_by_id(conn: sqlite3.Connection, symbol_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM symbols WHERE id = ?", (symbol_id,)
    ).fetchone()
    return _row_to_dict(row)


def get_symbols_by_name(
    conn: sqlite3.Connection, name: str, kind: str | None = None,
) -> list[dict]:
    """Find symbols by name, with definitions sorted before forward declarations."""
    if kind:
        rows = conn.execute(
            "SELECT * FROM symbols WHERE name = ? AND kind = ? "
            "ORDER BY (line_end > line_start) DESC",
            (name, kind),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM symbols WHERE name = ? "
            "ORDER BY (line_end > line_start) DESC",
            (name,),
        ).fetchall()
    return _rows_to_dicts(rows)


def search_symbols_fts(
    conn: sqlite3.Connection, query: str, limit: int = 20,
) -> list[dict]:
    fts_query = _escape_fts(query)
    rows = conn.execute(
        "SELECT s.* FROM symbols_fts f "
        "JOIN symbols s ON s.id = f.rowid "
        "WHERE symbols_fts MATCH ? "
        "ORDER BY bm25(symbols_fts) "
        "LIMIT ?",
        (fts_query, limit),
    ).fetchall()
    return _rows_to_dicts(rows)


def search_source_fts(
    conn: sqlite3.Connection, query: str, limit: int = 20, scope: str = "all",
) -> list[dict]:
    """Search source text via FTS5.

    scope: 'all', 'header', 'source' -- filters by files.file_type.
    """
    fts_query = _escape_fts(query)
    if scope == "all":
        rows = conn.execute(
            "SELECT f.file_id, f.line_number, f.text "
            "FROM source_fts f "
            "WHERE source_fts MATCH ? "
            "ORDER BY bm25(source_fts) "
            "LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT sf.file_id, sf.line_number, sf.text "
            "FROM source_fts sf "
            "JOIN files fi ON fi.id = sf.file_id "
            "WHERE source_fts MATCH ? AND fi.file_type = ? "
            "ORDER BY bm25(source_fts) "
            "LIMIT ?",
            (fts_query, scope, limit),
        ).fetchall()
    return _rows_to_dicts(rows)


def search_symbols_fts_filtered(
    conn: sqlite3.Connection, query: str, limit: int = 20,
    kind: str | None = None, module: str | None = None, path_filter: str | None = None,
) -> list[dict]:
    """FTS symbol search with optional kind, module, and path filters."""
    fts_query = _escape_fts(query)
    sql = (
        "SELECT s.* FROM symbols_fts f "
        "JOIN symbols s ON s.id = f.rowid "
    )
    conditions = ["symbols_fts MATCH ?"]
    params: list = [fts_query]

    if module or path_filter:
        sql += "JOIN files fi ON fi.id = s.file_id "
    if module:
        sql += "JOIN modules m ON m.id = fi.module_id "
        conditions.append("m.name = ?")
        params.append(module)
    if kind:
        conditions.append("s.kind = ?")
        params.append(kind)
    if path_filter:
        conditions.append("fi.path LIKE ?")
        params.append(f"%{path_filter}%")

    sql += "WHERE " + " AND ".join(conditions)
    sql += " ORDER BY bm25(symbols_fts) LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def search_source_fts_filtered(
    conn: sqlite3.Connection, query: str, limit: int = 20, scope: str = "all",
    module: str | None = None, path_filter: str | None = None,
) -> list[dict]:
    """FTS source search with optional module and path filters."""
    fts_query = _escape_fts(query)

    if scope == "all" and not module and not path_filter:
        # Fast path — no joins needed (same as original search_source_fts)
        rows = conn.execute(
            "SELECT f.file_id, f.line_number, f.text "
            "FROM source_fts f "
            "WHERE source_fts MATCH ? "
            "ORDER BY bm25(source_fts) LIMIT ?",
            (fts_query, limit),
        ).fetchall()
        return _rows_to_dicts(rows)

    sql = (
        "SELECT sf.file_id, sf.line_number, sf.text "
        "FROM source_fts sf "
        "JOIN files fi ON fi.id = sf.file_id "
    )
    conditions: list[str] = ["source_fts MATCH ?"]
    params: list = [fts_query]

    if module:
        sql += "JOIN modules m ON m.id = fi.module_id "
        conditions.append("m.name = ?")
        params.append(module)
    if scope != "all":
        conditions.append("fi.file_type = ?")
        params.append(scope)
    if path_filter:
        conditions.append("fi.path LIKE ?")
        params.append(f"%{path_filter}%")

    sql += "WHERE " + " AND ".join(conditions)
    sql += " ORDER BY bm25(source_fts) LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def get_source_chunks(
    conn: sqlite3.Connection, keyword: str, scope: str = "all", limit: int = 500,
) -> list[dict]:
    """Fetch source_fts chunks containing a keyword (for post-filtering).

    Uses FTS to narrow candidates, returns raw text for regex/substring matching.
    """
    fts_query = _escape_fts(keyword)
    if scope == "all":
        rows = conn.execute(
            "SELECT f.file_id, f.line_number, f.text "
            "FROM source_fts f "
            "WHERE source_fts MATCH ? "
            "LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT sf.file_id, sf.line_number, sf.text "
            "FROM source_fts sf "
            "JOIN files fi ON fi.id = sf.file_id "
            "WHERE source_fts MATCH ? AND fi.file_type = ? "
            "LIMIT ?",
            (fts_query, scope, limit),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_file_by_id(conn: sqlite3.Connection, file_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _row_to_dict(row)


def get_file_by_path(conn: sqlite3.Connection, path: str) -> dict | None:
    row = conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
    return _row_to_dict(row)


def find_file_by_suffix(conn: sqlite3.Connection, suffix: str) -> dict | None:
    """Find a file whose path ends with the given suffix."""
    row = conn.execute(
        "SELECT * FROM files WHERE path LIKE ? LIMIT 1",
        (f"%{suffix}",),
    ).fetchone()
    return _row_to_dict(row)


def get_module_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM modules WHERE name = ?", (name,)).fetchone()
    return _row_to_dict(row)


def get_inheritance_parents(conn: sqlite3.Connection, child_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT s.* FROM inheritance i "
        "JOIN symbols s ON s.id = i.parent_id "
        "WHERE i.child_id = ?",
        (child_id,),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_inheritance_children(conn: sqlite3.Connection, parent_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT s.* FROM inheritance i "
        "JOIN symbols s ON s.id = i.child_id "
        "WHERE i.parent_id = ?",
        (parent_id,),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_references_to(
    conn: sqlite3.Connection, symbol_id: int,
    ref_kind: str | None = None, limit: int = 50,
) -> list[dict]:
    """Get references pointing TO this symbol, with from_name and path."""
    if ref_kind:
        rows = conn.execute(
            f"SELECT r.*, s.name AS from_name, f.path "
            f"FROM {_REFS_TABLE} r "
            f"JOIN symbols s ON s.id = r.from_symbol_id "
            f"JOIN files f ON f.id = r.file_id "
            f"WHERE r.to_symbol_id = ? AND r.ref_kind = ? "
            f"LIMIT ?",
            (symbol_id, ref_kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT r.*, s.name AS from_name, f.path "
            f"FROM {_REFS_TABLE} r "
            f"JOIN symbols s ON s.id = r.from_symbol_id "
            f"JOIN files f ON f.id = r.file_id "
            f"WHERE r.to_symbol_id = ? "
            f"LIMIT ?",
            (symbol_id, limit),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_references_from(
    conn: sqlite3.Connection, symbol_id: int,
    ref_kind: str | None = None, limit: int = 50,
) -> list[dict]:
    """Get references FROM this symbol, with to_name and path."""
    if ref_kind:
        rows = conn.execute(
            f"SELECT r.*, s.name AS to_name, f.path "
            f"FROM {_REFS_TABLE} r "
            f"JOIN symbols s ON s.id = r.to_symbol_id "
            f"JOIN files f ON f.id = r.file_id "
            f"WHERE r.from_symbol_id = ? AND r.ref_kind = ? "
            f"LIMIT ?",
            (symbol_id, ref_kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT r.*, s.name AS to_name, f.path "
            f"FROM {_REFS_TABLE} r "
            f"JOIN symbols s ON s.id = r.to_symbol_id "
            f"JOIN files f ON f.id = r.file_id "
            f"WHERE r.from_symbol_id = ? "
            f"LIMIT ?",
            (symbol_id, limit),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_symbols_in_module(
    conn: sqlite3.Connection, module_name: str,
    kind: str | None = None, limit: int = 200,
) -> list[dict]:
    if kind:
        rows = conn.execute(
            "SELECT s.* FROM symbols s "
            "JOIN files f ON f.id = s.file_id "
            "JOIN modules m ON m.id = f.module_id "
            "WHERE m.name = ? AND s.kind = ? "
            "LIMIT ?",
            (module_name, kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT s.* FROM symbols s "
            "JOIN files f ON f.id = s.file_id "
            "JOIN modules m ON m.id = f.module_id "
            "WHERE m.name = ? "
            "LIMIT ?",
            (module_name, limit),
        ).fetchall()
    return _rows_to_dicts(rows)


# ── v2 Insert helpers ────────────────────────────────────────────────────

def insert_config_entry(
    conn: sqlite3.Connection, *, file_path: str, section: str,
    key: str, value: str | None, line: int | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO config_entries (file_path, section, key, value, line) "
        "VALUES (?, ?, ?, ?, ?)",
        (file_path, section, key, value, line),
    )
    return cur.lastrowid


def insert_asset_reference(
    conn: sqlite3.Connection, *, symbol_id: int | None,
    asset_path: str, ref_type: str, file_id: int | None, line: int | None,
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
    conn: sqlite3.Connection, *, name: str, friendly_name: str | None = None,
    description: str | None = None, category: str | None = None,
    version: str | None = None, can_contain_content: bool = False,
    is_beta: bool = False, file_path: str,
) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO plugins "
        "(name, friendly_name, description, category, version, "
        "can_contain_content, is_beta, file_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, friendly_name, description, category, version,
         int(can_contain_content), int(is_beta), file_path),
    )
    if cur.lastrowid and cur.rowcount > 0:
        return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM plugins WHERE name = ?", (name,)
    ).fetchone()
    return row[0]


def insert_plugin_module(
    conn: sqlite3.Connection, *, plugin_id: int, module_name: str,
    module_type: str | None = None, loading_phase: str | None = None,
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
    conn: sqlite3.Connection, *, name: str, file_id: int | None = None,
    line: int | None = None, verbosity: str | None = None,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO log_categories (name, file_id, line, verbosity) "
        "VALUES (?, ?, ?, ?)",
        (name, file_id, line, verbosity),
    )


def insert_replication_entry(
    conn: sqlite3.Connection, *, symbol_id: int, rep_type: str,
    condition: str | None = None, callback: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO replication_entries (symbol_id, rep_type, condition, callback) "
        "VALUES (?, ?, ?, ?)",
        (symbol_id, rep_type, condition, callback),
    )


def insert_pattern_tag(
    conn: sqlite3.Connection, *, symbol_id: int, tag_kind: str,
    metadata: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO pattern_tags (symbol_id, tag_kind, metadata) VALUES (?, ?, ?)",
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


# ── v2 Query helpers ────────────────────────────────────────────────────

def search_config_fts(
    conn: sqlite3.Connection, query: str, limit: int = 20,
) -> list[dict]:
    fts_query = _escape_fts(query)
    rows = conn.execute(
        "SELECT c.* FROM config_fts f "
        "JOIN config_entries c ON c.id = f.rowid "
        "WHERE config_fts MATCH ? "
        "ORDER BY bm25(config_fts) "
        "LIMIT ?",
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
            "SELECT * FROM config_entries WHERE key = ?", (key,)
        ).fetchall()
    return _rows_to_dicts(rows)


def get_asset_references_by_path(
    conn: sqlite3.Connection, asset_path: str, limit: int = 50,
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM asset_references WHERE asset_path LIKE ? LIMIT ?",
        (f"%{asset_path}%", limit),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_asset_references_by_symbol(
    conn: sqlite3.Connection, symbol_id: int, limit: int = 50,
) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM asset_references WHERE symbol_id = ? LIMIT ?",
        (symbol_id, limit),
    ).fetchall()
    return _rows_to_dicts(rows)


def search_gameplay_tags_fts(
    conn: sqlite3.Connection, query: str,
    usage_kind: str | None = None, limit: int = 50,
) -> list[dict]:
    fts_query = _escape_fts(query)
    if usage_kind:
        rows = conn.execute(
            "SELECT g.* FROM tags_fts f "
            "JOIN gameplay_tags g ON g.id = f.rowid "
            "WHERE tags_fts MATCH ? AND g.usage_kind = ? "
            "ORDER BY bm25(tags_fts) "
            "LIMIT ?",
            (fts_query, usage_kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT g.* FROM tags_fts f "
            "JOIN gameplay_tags g ON g.id = f.rowid "
            "WHERE tags_fts MATCH ? "
            "ORDER BY bm25(tags_fts) "
            "LIMIT ?",
            (fts_query, limit),
        ).fetchall()
    return _rows_to_dicts(rows)


def get_module_dependencies(
    conn: sqlite3.Connection, module_id: int, dep_type: str | None = None,
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
        "SELECT m.*, md.dep_type FROM module_dependencies md "
        "JOIN modules m ON m.id = md.module_id "
        "WHERE md.dependency_name = ?",
        (dependency_name,),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_plugin_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM plugins WHERE name = ?", (name,)
    ).fetchone()
    return _row_to_dict(row)


def get_plugin_modules(conn: sqlite3.Connection, plugin_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM plugin_modules WHERE plugin_id = ?", (plugin_id,)
    ).fetchall()
    return _rows_to_dicts(rows)


def get_plugin_dependencies(conn: sqlite3.Connection, plugin_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM plugin_dependencies WHERE plugin_id = ?", (plugin_id,)
    ).fetchall()
    return _rows_to_dicts(rows)


def get_log_category(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute(
        "SELECT lc.*, f.path FROM log_categories lc "
        "LEFT JOIN files f ON f.id = lc.file_id "
        "WHERE lc.name = ?",
        (name,),
    ).fetchone()
    return _row_to_dict(row)


def get_replication_entries(
    conn: sqlite3.Connection, class_name: str | None = None, limit: int = 100,
) -> list[dict]:
    if class_name:
        rows = conn.execute(
            "SELECT re.*, s.name AS symbol_name, s.qualified_name, f.path "
            "FROM replication_entries re "
            "JOIN symbols s ON s.id = re.symbol_id "
            "JOIN files f ON f.id = s.file_id "
            "WHERE s.parent_symbol_id IN ("
            "  SELECT id FROM symbols WHERE name = ? AND kind = 'class'"
            ") "
            "LIMIT ?",
            (class_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT re.*, s.name AS symbol_name, s.qualified_name, f.path "
            "FROM replication_entries re "
            "JOIN symbols s ON s.id = re.symbol_id "
            "JOIN files f ON f.id = s.file_id "
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
        "JOIN files f ON f.id = s.file_id "
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


# ── Existing query helpers (continued) ──────────────────────────────────

def get_module_stats(conn: sqlite3.Connection, module_name: str) -> dict | None:
    """Return file_count and symbol_counts by kind for a module."""
    mod = get_module_by_name(conn, module_name)
    if mod is None:
        return None

    file_count = conn.execute(
        "SELECT COUNT(*) FROM files WHERE module_id = ?", (mod["id"],)
    ).fetchone()[0]

    kind_rows = conn.execute(
        "SELECT s.kind, COUNT(*) as cnt FROM symbols s "
        "JOIN files f ON f.id = s.file_id "
        "WHERE f.module_id = ? "
        "GROUP BY s.kind",
        (mod["id"],),
    ).fetchall()

    symbol_counts = {row["kind"]: row["cnt"] for row in kind_rows}

    return {
        "module": mod,
        "file_count": file_count,
        "symbol_counts": symbol_counts,
    }
