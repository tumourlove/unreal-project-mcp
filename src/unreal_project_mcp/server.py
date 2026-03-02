"""MCP server with 7 tools for Unreal project source intelligence."""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from unreal_project_mcp.config import get_db_path, UE_PROJECT_PATH, _project_root
from unreal_project_mcp.db.schema import init_db
from unreal_project_mcp.db.queries import (
    find_file_by_suffix,
    get_file_by_id,
    get_file_by_path,
    get_inheritance_children,
    get_inheritance_parents,
    get_module_stats,
    get_references_from,
    get_references_to,
    get_source_chunks,
    get_symbols_by_name,
    get_symbols_in_module,
    search_source_fts,
    search_source_fts_filtered,
    search_symbols_fts,
    search_symbols_fts_filtered,
)

mcp = FastMCP(
    "unreal-project",
    instructions=(
        "Project-level C++ source intelligence. "
        "Read source code, search symbols, trace call graphs, "
        "and explore class hierarchies across your UE project code."
    ),
)

_conn: sqlite3.Connection | None = None
_path_prefix: str = ""


def _short_path(path: str) -> str:
    """Shorten absolute project paths to relative."""
    global _path_prefix
    if not _path_prefix:
        _path_prefix = _project_root()
    if _path_prefix and path.startswith(_path_prefix):
        return path[len(_path_prefix):].replace("\\", "/")
    return path


def _get_conn() -> sqlite3.Connection:
    """Lazy-init the SQLite connection. Auto-index if DB doesn't exist."""
    global _conn
    if _conn is not None:
        return _conn

    db_path = get_db_path()

    if not db_path.exists() and UE_PROJECT_PATH:
        print(f"[unreal-project-mcp] Indexing project from {UE_PROJECT_PATH}...", file=sys.stderr)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        init_db(conn)

        from unreal_project_mcp.indexer.pipeline import IndexingPipeline
        pipeline = IndexingPipeline(conn)
        stats = pipeline.index_project(Path(UE_PROJECT_PATH))
        print(
            f"[unreal-project-mcp] Indexed {stats['files_processed']} files, "
            f"{stats['symbols_extracted']} symbols, {stats['errors']} errors.",
            file=sys.stderr,
        )
        _conn = conn
        return _conn

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _conn = conn
    return _conn


def _read_file_lines(path: str, start: int, end: int) -> str:
    """Read specific lines from a source file on disk, return with line numbers."""
    try:
        p = Path(path)
        if not p.is_file():
            return f"[File not found: {path}]"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        # Clamp to valid range (1-based input)
        start = max(1, start)
        end = min(len(lines), end)
        result_lines = []
        for i in range(start, end + 1):
            result_lines.append(f"{i:5d} | {lines[i - 1]}")
        return "\n".join(result_lines)
    except Exception as e:
        return f"[Error reading {path}: {e}]"


def _get_file_path(conn: sqlite3.Connection, file_id: int) -> str:
    """Get the file path for a file ID."""
    f = get_file_by_id(conn, file_id)
    return f["path"] if f else "<unknown>"


_FORWARD_DECL_RE = re.compile(r"^\s*(class|struct|enum)\s+\w[\w:]*\s*;")


def _is_forward_declaration(path: str, line_start: int, line_end: int) -> bool:
    """Check if a symbol entry is a single-line forward declaration."""
    if line_end - line_start > 1:
        return False
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if line_start <= len(lines):
            return bool(_FORWARD_DECL_RE.match(lines[line_start - 1]))
    except OSError:
        pass
    return False


def _extract_members(path: str, start: int, end: int) -> str:
    """Extract member declarations from a class/struct, skipping inline implementations."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return f"[Error reading {path}]"

    start = max(1, start)
    end = min(len(lines), end)
    result_lines: list[str] = []
    brace_depth = 0
    in_body = False

    for i in range(start - 1, end):
        line = lines[i]
        stripped = line.strip()

        # Track braces to skip inline function bodies
        if in_body:
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0:
                in_body = False
                brace_depth = 0
            continue

        # Keep access specifiers, UE macros, declarations, comments, and braces
        if (stripped.startswith(("public:", "protected:", "private:", "GENERATED"))
            or stripped.startswith(("UFUNCTION", "UPROPERTY", "UENUM", "USTRUCT"))
            or stripped.startswith(("//", "/**", "*", "*/"))
            or stripped == ""
            or stripped == "{" or stripped == "}"
            or ";" in stripped):
            result_lines.append(f"{i+1:5d} | {line}")
        elif "{" in stripped:
            # Function with inline body — show signature, skip body
            sig_part = stripped.split("{")[0].rstrip()
            if sig_part:
                result_lines.append(f"{i+1:5d} | {sig_part};  // [inline body omitted]")
            brace_depth = stripped.count("{") - stripped.count("}")
            if brace_depth > 0:
                in_body = True

    return "\n".join(result_lines)


# ── Tool 1: read_project_source ─────────────────────────────────────────

@mcp.tool()
def read_project_source(
    symbol: str,
    include_header: bool = True,
    max_lines: int = 0,
    members_only: bool = False,
) -> str:
    """Get the implementation source code for a class, function, or struct in the project.

    Shows the actual source lines from disk with line numbers.
    For classes, shows both .h declaration and .cpp implementation if available.
    """
    conn = _get_conn()

    # Look up by exact name first, then FTS fallback
    symbols = get_symbols_by_name(conn, symbol)
    if not symbols:
        symbols = search_symbols_fts(conn, symbol, limit=5)
    if not symbols:
        return f"No symbol found matching '{symbol}'."

    # Filter out forward declarations when a real definition exists
    has_definition = any(
        (sym["line_end"] - sym["line_start"]) > 1
        for sym in symbols
    )
    if has_definition:
        filtered = []
        for sym in symbols:
            filepath = _get_file_path(conn, sym["file_id"])
            if _is_forward_declaration(filepath, sym["line_start"], sym["line_end"]):
                continue
            filtered.append(sym)
        symbols = filtered if filtered else symbols  # fallback to all if filtering removes everything

    parts: list[str] = []
    seen_files: set[tuple[int, int, int]] = set()

    for sym in symbols:
        file_id = sym["file_id"]
        line_start = sym["line_start"]
        line_end = sym["line_end"]
        key = (file_id, line_start, line_end)
        if key in seen_files:
            continue
        seen_files.add(key)

        filepath = _get_file_path(conn, file_id)

        # Skip headers if not requested
        if not include_header and filepath.endswith(".h"):
            continue

        header = f"--- {_short_path(filepath)} (lines {line_start}-{line_end}) ---"
        doc = ""
        if sym.get("docstring"):
            doc = f"// {sym['docstring']}\n"

        if members_only and sym["kind"] in ("class", "struct"):
            source = _extract_members(filepath, line_start, line_end)
        else:
            source = _read_file_lines(filepath, line_start, line_end)
        parts.append(f"{header}\n{doc}{source}")

    result = "\n\n".join(parts) if parts else f"Found symbol '{symbol}' but could not read source files."

    # Apply max_lines truncation
    if max_lines > 0:
        lines = result.split("\n")
        if len(lines) > max_lines:
            result = "\n".join(lines[:max_lines])
            remaining = len(lines) - max_lines
            result += f"\n[...truncated, {remaining} more lines]"

    return result


# ── Tool 2: find_project_references ─────────────────────────────────────

@mcp.tool()
def find_project_references(symbol: str, ref_kind: str = "", limit: int = 50) -> str:
    """Find all usage sites of a symbol in the project (calls, includes, type references, etc.).

    ref_kind: filter by reference kind (e.g. 'call', 'include', 'type'). Empty for all.
    """
    conn = _get_conn()

    symbols = get_symbols_by_name(conn, symbol)
    if not symbols:
        symbols = search_symbols_fts(conn, symbol, limit=5)
    if not symbols:
        return f"No symbol found matching '{symbol}'."

    lines: list[str] = []
    for sym in symbols:
        refs = get_references_to(
            conn, sym["id"],
            ref_kind=ref_kind if ref_kind else None,
            limit=limit,
        )
        for ref in refs:
            kind_tag = f"[{ref['ref_kind']}]"
            path = ref.get("path", "<unknown>")
            line = ref.get("line", "?")
            from_name = ref.get("from_name", "<unknown>")
            lines.append(f"{kind_tag} {_short_path(path)}:{line} (from {from_name})")

    if not lines:
        return f"No references found for '{symbol}'."
    return "\n".join(lines)


# ── Tool 3: find_project_callers ────────────────────────────────────────

@mcp.tool()
def find_project_callers(function: str, limit: int = 50) -> str:
    """Find all functions in the project that call the given function."""
    conn = _get_conn()

    symbols = get_symbols_by_name(conn, function, kind="function")
    if not symbols:
        symbols = search_symbols_fts(conn, function, limit=5)
        symbols = [s for s in symbols if s["kind"] == "function"]
    if not symbols:
        return f"No function found matching '{function}'."

    lines: list[str] = []
    for sym in symbols:
        refs = get_references_to(conn, sym["id"], ref_kind="call", limit=limit)
        for ref in refs:
            from_name = ref.get("from_name", "<unknown>")
            path = ref.get("path", "<unknown>")
            line = ref.get("line", "?")
            lines.append(f"{from_name} \u2014 {_short_path(path)}:{line}")

    if not lines:
        # Search for function pointer / delegate references
        func_name = symbols[0]["name"]
        qualified = symbols[0]["qualified_name"]

        delegate_hits: list[str] = []
        # Search source FTS for the function name — look for & references in raw text
        delegate_results = search_source_fts(conn, func_name, limit=10)
        for match in delegate_results:
            text = match.get("text", "")
            if "&" in text and func_name in text:
                fid = match["file_id"]
                filepath = _get_file_path(conn, fid)
                line_num = match.get("line_number", "?")
                delegate_hits.append(f"  {_short_path(filepath)}:{line_num}")

        msg = (
            f"No direct C++ callers found for '{function}'. "
            "This function may be called via delegates, Blueprints, "
            "input bindings, or reflection (e.g. ProcessEvent)."
        )
        if delegate_hits:
            msg += "\n\nPossible indirect references (delegates/bindings):\n"
            msg += "\n".join(delegate_hits)
        return msg
    return "\n".join(lines)


# ── Tool 4: find_project_callees ────────────────────────────────────────

@mcp.tool()
def find_project_callees(function: str, limit: int = 50) -> str:
    """Find all functions called by the given function in the project."""
    conn = _get_conn()

    symbols = get_symbols_by_name(conn, function, kind="function")
    if not symbols:
        symbols = search_symbols_fts(conn, function, limit=5)
        symbols = [s for s in symbols if s["kind"] == "function"]
    if not symbols:
        return f"No function found matching '{function}'."

    lines: list[str] = []
    for sym in symbols:
        refs = get_references_from(conn, sym["id"], ref_kind="call", limit=limit)
        for ref in refs:
            to_name = ref.get("to_name", "<unknown>")
            path = ref.get("path", "<unknown>")
            line = ref.get("line", "?")
            lines.append(f"{to_name} \u2014 {_short_path(path)}:{line}")

    if not lines:
        return f"No callees found for '{function}'."
    return "\n".join(lines)


# ── Tool 5: search_project ──────────────────────────────────────────────

def _search_source_pattern(
    conn: sqlite3.Connection, pattern: str, scope: str, limit: int, mode: str,
) -> list[str]:
    """Search source using regex or substring matching."""
    import re as re_mod

    # Extract a keyword for FTS narrowing
    words = re_mod.findall(r'[a-zA-Z_]\w{2,}', pattern)
    if not words:
        return ["Pattern must contain at least one keyword (3+ chars) for pre-filtering."]
    keyword = max(words, key=len)

    # Map scope to file_type values for querying
    scopes: list[str] = []
    if scope == "cpp":
        scopes = ["header", "source", "inline"]
    else:
        scopes = ["all"]

    all_chunks: list[dict] = []
    for s in scopes:
        all_chunks.extend(get_source_chunks(conn, keyword, scope=s, limit=500))

    if mode == "regex":
        try:
            compiled = re_mod.compile(pattern)
        except re_mod.error as e:
            return [f"Invalid regex: {e}"]
        match_fn = lambda text: compiled.search(text) is not None
    else:
        compiled = None
        match_fn = lambda text: pattern in text

    parts: list[str] = [f"=== Pattern Matches ({mode}) ==="]
    seen: set[tuple[int, object]] = set()
    shown = 0
    for chunk in all_chunks:
        if shown >= limit:
            break
        text = chunk.get("text", "")
        if not match_fn(text):
            continue
        fid = chunk["file_id"]
        line_num = chunk.get("line_number", "?")
        key = (fid, line_num)
        if key in seen:
            continue
        seen.add(key)
        filepath = _get_file_path(conn, fid)

        # Find the specific matching line within the chunk
        for i, line in enumerate(text.split("\n")):
            if (mode == "regex" and compiled is not None and compiled.search(line)) or (mode == "substring" and pattern in line):
                display = line.strip()[:120]
                actual_line = line_num + i if isinstance(line_num, int) else line_num
                parts.append(f"  {_short_path(filepath)}:{actual_line}")
                parts.append(f"    {display}")
                shown += 1
                break

    if len(parts) == 1:
        return []  # Only header, no matches
    return parts


@mcp.tool()
def search_project(
    query: str, scope: str = "all", limit: int = 20, mode: str = "fts",
    module: str = "", path_filter: str = "", symbol_kind: str = "",
) -> str:
    """Full-text search across project source code.

    scope: 'cpp' (headers+source), 'all'
    mode: 'fts' (default, token-based), 'regex', 'substring'
    module: filter to files in this module (e.g. 'MyGameModule')
    path_filter: filter to files whose path contains this string
    symbol_kind: filter symbol results by kind (class, function, struct, etc.)
    Returns both symbol matches and source line matches.
    """
    conn = _get_conn()

    parts: list[str] = []

    if mode in ("regex", "substring"):
        parts.extend(_search_source_pattern(conn, query, scope, limit, mode))
    else:
        # Symbol FTS search
        sym_results = search_symbols_fts_filtered(
            conn, query, limit=limit,
            kind=symbol_kind or None,
            module=module or None,
            path_filter=path_filter or None,
        )
        if sym_results:
            parts.append("=== Symbol Matches ===")
            for sym in sym_results:
                filepath = _get_file_path(conn, sym["file_id"])
                sig = sym.get("signature") or ""
                parts.append(f"  [{sym['kind']}] {sym['qualified_name']} ({_short_path(filepath)}:{sym['line_start']})")
                if sig:
                    parts.append(f"         {sig}")

        # Source FTS search — map scope to file_type
        _mod = module or None
        _pf = path_filter or None
        if scope == "cpp":
            source_results = search_source_fts_filtered(conn, query, limit=limit, scope="header", module=_mod, path_filter=_pf)
            source_results += search_source_fts_filtered(conn, query, limit=limit, scope="source", module=_mod, path_filter=_pf)
            source_results += search_source_fts_filtered(conn, query, limit=limit, scope="inline", module=_mod, path_filter=_pf)
        else:
            source_results = search_source_fts_filtered(conn, query, limit=limit, scope="all", module=_mod, path_filter=_pf)

        if source_results:
            parts.append("\n=== Source Line Matches ===")
            seen: set[tuple[int, object]] = set()
            shown = 0
            for match in source_results:
                if shown >= limit:
                    break
                fid = match["file_id"]
                line_num = match.get("line_number", "?")
                key = (fid, line_num)
                if key in seen:
                    continue
                seen.add(key)
                filepath = _get_file_path(conn, fid)
                text = match.get("text", "").strip()
                # Truncate long text
                if len(text) > 120:
                    text = text[:120] + "..."
                parts.append(f"  {_short_path(filepath)}:{line_num}")
                parts.append(f"    {text}")
                shown += 1

    if not parts:
        return f"No results found for '{query}'."
    return "\n".join(parts)


# ── Tool 6: get_project_class_hierarchy ──────────────────────────────────

@mcp.tool()
def get_project_class_hierarchy(class_name: str, direction: str = "both", depth: int = 1) -> str:
    """Show the inheritance tree for a class in the project.

    direction: 'ancestors' (parents), 'descendants' (children), 'both'
    """
    conn = _get_conn()

    symbols = get_symbols_by_name(conn, class_name, kind="class")
    if not symbols:
        symbols = get_symbols_by_name(conn, class_name, kind="struct")
    if not symbols:
        symbols = search_symbols_fts(conn, class_name, limit=5)
        symbols = [s for s in symbols if s["kind"] in ("class", "struct")]
    if not symbols:
        return f"No class or struct found matching '{class_name}'."

    sym = symbols[0]
    filepath = _get_file_path(conn, sym["file_id"])
    lines: list[str] = [f"{sym['name']} ({_short_path(filepath)})"]

    counter = _Counter()

    if direction in ("ancestors", "both"):
        lines.append("\nAncestors:")
        _walk_ancestors(conn, sym["id"], lines, indent=1, max_depth=depth, counter=counter)
        if not any("<-" in l for l in lines):
            lines.append("  (none)")

    if direction in ("descendants", "both"):
        lines.append("\nDescendants:")
        _walk_descendants(conn, sym["id"], lines, indent=1, max_depth=depth, counter=counter)
        if counter.truncated > 0:
            lines.append(f"\n  ... and {counter.truncated} more (increase depth to see all)")

    return "\n".join(lines)


class _Counter:
    """Track how many entries were truncated."""
    __slots__ = ("shown", "truncated", "limit")
    def __init__(self, limit: int = 80):
        self.shown = 0
        self.limit = limit
        self.truncated = 0


def _walk_ancestors(
    conn: sqlite3.Connection, sym_id: int, lines: list[str],
    indent: int, max_depth: int, counter: _Counter,
    visited: set[int] | None = None,
) -> None:
    if visited is None:
        visited = set()
    if indent > max_depth or sym_id in visited:
        return
    visited.add(sym_id)
    parents = get_inheritance_parents(conn, sym_id)
    for p in parents:
        if counter.shown >= counter.limit:
            counter.truncated += 1
            continue
        prefix = "  " * indent
        lines.append(f"{prefix}<- {p['name']}")
        counter.shown += 1
        _walk_ancestors(conn, p["id"], lines, indent + 1, max_depth, counter, visited)


def _walk_descendants(
    conn: sqlite3.Connection, sym_id: int, lines: list[str],
    indent: int, max_depth: int, counter: _Counter,
    visited: set[int] | None = None,
) -> None:
    if visited is None:
        visited = set()
    if indent > max_depth or sym_id in visited:
        return
    visited.add(sym_id)
    children = get_inheritance_children(conn, sym_id)
    if indent >= max_depth and children:
        counter.truncated += len(children)
        return
    for c in children:
        if counter.shown >= counter.limit:
            counter.truncated += 1
            continue
        prefix = "  " * indent
        lines.append(f"{prefix}-> {c['name']}")
        counter.shown += 1
        _walk_descendants(conn, c["id"], lines, indent + 1, max_depth, counter, visited)


# ── Tool 7: get_project_module_info ──────────────────────────────────────

@mcp.tool()
def get_project_module_info(module_name: str) -> str:
    """Get project module statistics: file count, symbol counts by kind, and key classes."""
    conn = _get_conn()

    stats = get_module_stats(conn, module_name)
    if stats is None:
        return f"No module found matching '{module_name}'."

    mod = stats["module"]
    lines: list[str] = [
        f"Module: {mod['name']}",
        f"Path: {_short_path(mod['path'])}",
        f"Type: {mod['module_type']}",
        f"Files: {stats['file_count']}",
        "",
        "Symbol counts by kind:",
    ]

    for kind, count in sorted(stats["symbol_counts"].items()):
        lines.append(f"  {kind}: {count}")

    # Show key classes
    key_symbols = get_symbols_in_module(conn, module_name, kind="class", limit=20)
    if key_symbols:
        lines.append("")
        lines.append("Key classes:")
        for sym in key_symbols:
            lines.append(f"  {sym['name']} (line {sym['line_start']})")

    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────────────

def main() -> None:
    """Run the MCP server."""
    mcp.run()
