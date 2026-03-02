"""Indexing pipeline — discovers, parses, and stores UE project source into SQLite."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable

from unreal_project_mcp.db.queries import (
    get_file_by_path,
    insert_file,
    insert_include,
    insert_inheritance,
    insert_module,
    insert_symbol,
)
from unreal_project_mcp.indexer.cpp_parser import CppParser
from unreal_project_mcp.indexer.reference_builder import ReferenceBuilder

logger = logging.getLogger(__name__)

_CPP_EXTENSIONS = {".h", ".cpp", ".inl"}
_EXT_TO_FILETYPE = {
    ".h": "header",
    ".cpp": "source",
    ".inl": "inline",
}


class IndexingPipeline:
    """Walks an Unreal Engine project source tree, parses files, and stores results."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._cpp_parser = CppParser()
        self._symbol_name_to_id: dict[str, Any] = {}
        self._symbol_spans: dict[str, tuple[int, int]] = {}  # name → (line_start, line_end)
        self._class_name_to_id: dict[str, int] = {}  # class/struct only — for inheritance
        self._class_spans: dict[str, tuple[int, int]] = {}  # class name → (line_start, line_end)
        conn.commit()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

    # ── Public API ──────────────────────────────────────────────────────

    def index_directory(
        self,
        path: Path,
        module_name: str | None = None,
        module_type: str = "Runtime",
        *,
        finalize: bool = True,
    ) -> dict[str, Any]:
        """Index all C++ files under *path*.

        If *finalize* is True (default), resolves inheritance and extracts
        cross-references after parsing.  Set to False when calling from
        index_project, which does a single global finalize at the end.

        Returns stats: {files_processed, symbols_extracted, errors}.
        """
        path = Path(path)
        if module_name is None:
            module_name = path.name

        mod_id = insert_module(
            self._conn,
            name=module_name,
            path=str(path),
            module_type=module_type,
        )

        files_processed = 0
        symbols_extracted = 0
        errors = 0

        for dirpath, _dirnames, filenames in os.walk(path):
            for fname in filenames:
                fpath = Path(dirpath) / fname
                ext = fpath.suffix.lower()
                try:
                    if ext in _CPP_EXTENSIONS:
                        n = self._index_cpp_file(fpath, mod_id)
                        symbols_extracted += n
                        files_processed += 1
                except Exception:
                    logger.warning("Error indexing %s", fpath, exc_info=True)
                    errors += 1

        self._conn.commit()

        if finalize:
            self._finalize()

        return {
            "files_processed": files_processed,
            "symbols_extracted": symbols_extracted,
            "errors": errors,
        }

    def index_project(
        self,
        project_path: Path,
        on_progress: Callable[[str, int, int, int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Index a UE project's C++ source tree.

        Walks Source/ and own Plugins/*/Source/ directories.
        """
        project_path = Path(project_path)
        total_files = 0
        total_symbols = 0
        total_errors = 0

        # Discover modules
        modules: list[tuple[Path, str, str]] = []  # (path, name, type)

        # Source/ directory (the game module)
        source_dir = project_path / "Source"
        if source_dir.is_dir():
            for sub in sorted(source_dir.iterdir()):
                if sub.is_dir():
                    modules.append((sub, sub.name, "GameModule"))

        # Plugins/ — each plugin with a Source/ dir is a module
        plugins_dir = project_path / "Plugins"
        if plugins_dir.is_dir():
            for plugin_dir in sorted(plugins_dir.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                plugin_source = plugin_dir / "Source"
                if plugin_source.is_dir():
                    modules.append((plugin_source, plugin_dir.name, "Plugin"))

        # If project_path itself contains .h/.cpp files (test fixture case),
        # index it as a single module
        if not modules:
            has_cpp = any(
                f.suffix.lower() in _CPP_EXTENSIONS
                for f in project_path.rglob("*") if f.is_file()
            )
            if has_cpp:
                modules.append((project_path, project_path.name, "GameModule"))

        total_modules = len(modules)

        for i, (mod_path, mod_name, mod_type) in enumerate(modules):
            stats = self.index_directory(
                mod_path,
                module_name=mod_name,
                module_type=mod_type,
                finalize=False,
            )
            total_files += stats["files_processed"]
            total_symbols += stats["symbols_extracted"]
            total_errors += stats["errors"]

            if on_progress:
                on_progress(mod_name, i + 1, total_modules, total_files, total_symbols)

        # Global finalize
        if on_progress:
            on_progress("Finalizing (inheritance + references)...", total_modules, total_modules, total_files, total_symbols)
        self._finalize()

        return {
            "files_processed": total_files,
            "symbols_extracted": total_symbols,
            "errors": total_errors,
        }

    def reindex_changed(
        self,
        project_path: Path,
        on_progress: Callable[[str, int, int, int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Incremental reindex: only re-parse files whose mtime has changed."""
        project_path = Path(project_path)
        files_processed = 0
        files_skipped = 0
        symbols_extracted = 0
        errors = 0

        # Discover all C++ files
        cpp_files: list[tuple[Path, str, str]] = []

        source_dir = project_path / "Source"
        if source_dir.is_dir():
            for sub in sorted(source_dir.iterdir()):
                if sub.is_dir():
                    for dirpath, _, filenames in os.walk(sub):
                        for fname in filenames:
                            fpath = Path(dirpath) / fname
                            if fpath.suffix.lower() in _CPP_EXTENSIONS:
                                cpp_files.append((fpath, sub.name, "GameModule"))

        plugins_dir = project_path / "Plugins"
        if plugins_dir.is_dir():
            for plugin_dir in sorted(plugins_dir.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                plugin_source = plugin_dir / "Source"
                if plugin_source.is_dir():
                    for dirpath, _, filenames in os.walk(plugin_source):
                        for fname in filenames:
                            fpath = Path(dirpath) / fname
                            if fpath.suffix.lower() in _CPP_EXTENSIONS:
                                cpp_files.append((fpath, plugin_dir.name, "Plugin"))

        for fpath, mod_name, mod_type in cpp_files:
            current_mtime = fpath.stat().st_mtime

            existing = get_file_by_path(self._conn, str(fpath))
            if existing and existing["last_modified"] >= current_mtime:
                files_skipped += 1
                continue

            if existing:
                file_id = existing["id"]
                self._conn.execute("DELETE FROM \"references\" WHERE file_id = ?", (file_id,))
                self._conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
                self._conn.execute("DELETE FROM includes WHERE file_id = ?", (file_id,))
                self._conn.execute("DELETE FROM source_fts WHERE file_id = ?", (file_id,))
                self._conn.execute("DELETE FROM files WHERE id = ?", (file_id,))

            mod_id = insert_module(
                self._conn,
                name=mod_name,
                path=str(fpath.parent),
                module_type=mod_type,
            )

            try:
                n = self._index_cpp_file(fpath, mod_id)
                symbols_extracted += n
                files_processed += 1
            except Exception:
                logger.warning("Error indexing %s", fpath, exc_info=True)
                errors += 1

        self._conn.commit()

        if files_processed > 0:
            self._finalize()

        return {
            "files_processed": files_processed,
            "files_skipped": files_skipped,
            "symbols_extracted": symbols_extracted,
            "errors": errors,
        }

    def _finalize(self) -> None:
        """Resolve inheritance and extract cross-references globally."""
        self._resolve_inheritance()
        self._conn.commit()

        # Extract cross-references from all indexed C++ files
        ref_builder = ReferenceBuilder(self._conn, self._symbol_name_to_id)
        rows = self._conn.execute(
            "SELECT id, path FROM files WHERE file_type IN ('header', 'source', 'inline')"
        ).fetchall()
        for row in rows:
            fpath = Path(row[1])
            try:
                ref_builder.extract_references(fpath, row[0])
            except Exception:
                logger.warning("Error extracting refs from %s", fpath, exc_info=True)
        self._conn.commit()

    # ── Private helpers ─────────────────────────────────────────────────

    def _index_cpp_file(self, path: Path, mod_id: int) -> int:
        """Parse and store a C++ file. Returns symbol count."""
        result = self._cpp_parser.parse_file(path)

        ext = path.suffix.lower()
        file_type = _EXT_TO_FILETYPE.get(ext, "source")

        file_id = insert_file(
            self._conn,
            path=str(path),
            module_id=mod_id,
            file_type=file_type,
            line_count=len(result.source_lines),
            last_modified=path.stat().st_mtime,
        )

        # Includes
        for inc_path in result.includes:
            # Determine line number — scan source_lines for the include
            line_num = 0
            for i, line in enumerate(result.source_lines, 1):
                if inc_path in line and "#include" in line:
                    line_num = i
                    break
            insert_include(
                self._conn,
                file_id=file_id,
                included_path=inc_path,
                line=line_num,
            )

        # Symbols
        count = 0
        for sym in result.symbols:
            # Skip include-kind symbols
            if sym.kind == "include":
                continue

            qualified_name = sym.name
            if sym.parent_class:
                qualified_name = f"{sym.parent_class}::{sym.name}"

            parent_symbol_id = None
            if sym.parent_class and sym.parent_class in self._symbol_name_to_id:
                parent_symbol_id = self._symbol_name_to_id[sym.parent_class]

            sym_id = insert_symbol(
                self._conn,
                name=sym.name,
                qualified_name=qualified_name,
                kind=sym.kind,
                file_id=file_id,
                line_start=sym.line_start,
                line_end=sym.line_end,
                parent_symbol_id=parent_symbol_id,
                access=sym.access or None,
                signature=sym.signature or None,
                docstring=sym.docstring or None,
                is_ue_macro=1 if sym.is_ue_macro else 0,
            )

            # Track all symbols for reference resolution — prefer definitions
            # over forward declarations (multi-line span = real definition)
            self._update_symbol_map(sym.name, sym_id, sym.line_start, sym.line_end)
            if qualified_name != sym.name:
                self._update_symbol_map(qualified_name, sym_id, sym.line_start, sym.line_end)

            # Track classes/structs separately for inheritance — prefer definitions
            if sym.kind in ("class", "struct"):
                self._update_class_map(sym.name, sym_id, sym.line_start, sym.line_end)
                if sym.base_classes:
                    # Only store bases if not already set (first definition is canonical)
                    self._symbol_name_to_id.setdefault(f"_bases_{sym.name}", sym.base_classes)

            count += 1

        # Source FTS
        self._insert_source_lines(file_id, result.source_lines)

        return count

    def _insert_source_lines(self, file_id: int, lines: list[str]) -> None:
        """Group every 10 consecutive lines into one FTS row.

        Includes blank lines to keep line numbers exact — chunk_start is the
        1-based line number of the first line in the chunk.
        """
        batch: list[tuple[int, int, str]] = []

        for i in range(0, len(lines), 10):
            chunk = lines[i : i + 10]
            chunk_start = i + 1  # 1-based
            batch.append((file_id, chunk_start, "\n".join(chunk)))

        if batch:
            self._conn.executemany(
                "INSERT INTO source_fts (file_id, line_number, text) VALUES (?, ?, ?)",
                batch,
            )

    @staticmethod
    def _is_definition(line_start: int, line_end: int) -> bool:
        """A multi-line span indicates a real definition, not a forward declaration."""
        return line_end > line_start

    def _update_symbol_map(
        self, name: str, sym_id: int, line_start: int, line_end: int
    ) -> None:
        """Update _symbol_name_to_id, preferring definitions over forward decls."""
        if name.startswith("_bases_"):
            return  # Don't interfere with base-class tracking
        existing_span = self._symbol_spans.get(name)
        if existing_span is None:
            # No existing entry — just set it
            self._symbol_name_to_id[name] = sym_id
            self._symbol_spans[name] = (line_start, line_end)
        elif self._is_definition(line_start, line_end) and not self._is_definition(*existing_span):
            # New is a definition, existing is a forward decl — overwrite
            self._symbol_name_to_id[name] = sym_id
            self._symbol_spans[name] = (line_start, line_end)
        # Otherwise keep existing (it's already a definition, or both are forward decls)

    def _update_class_map(
        self, name: str, sym_id: int, line_start: int, line_end: int
    ) -> None:
        """Update _class_name_to_id, preferring definitions over forward decls."""
        existing_span = self._class_spans.get(name)
        if existing_span is None:
            self._class_name_to_id[name] = sym_id
            self._class_spans[name] = (line_start, line_end)
        elif self._is_definition(line_start, line_end) and not self._is_definition(*existing_span):
            self._class_name_to_id[name] = sym_id
            self._class_spans[name] = (line_start, line_end)

    def _resolve_inheritance(self) -> None:
        """Second pass: resolve base class names to symbol IDs and insert inheritance.

        Uses _class_name_to_id (class/struct only) so that constructors
        and other symbols with the same name don't shadow class entries.
        """
        keys_to_process = [k for k in self._symbol_name_to_id if k.startswith("_bases_")]
        for key in keys_to_process:
            child_name = key[len("_bases_"):]
            base_classes = self._symbol_name_to_id[key]
            child_id = self._class_name_to_id.get(child_name)
            if child_id is None:
                continue
            for parent_name in base_classes:
                parent_id = self._class_name_to_id.get(parent_name)
                if parent_id is not None:
                    try:
                        insert_inheritance(
                            self._conn,
                            child_id=child_id,
                            parent_id=parent_id,
                        )
                    except sqlite3.IntegrityError:
                        pass  # Already exists
