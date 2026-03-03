# CLAUDE.md — unreal-project-mcp

## Project Overview

**unreal-project-mcp** — Project-level C++ source intelligence for Unreal Engine AI development.

An MCP (Model Context Protocol) server that indexes a UE project's C++ source code into a SQLite database, providing structural queries (class hierarchy, call graphs, cross-references) and full-text search across the project codebase.

Forked from **unreal-source-mcp v0.1.1** (engine-level indexing). This variant focuses on project-level code rather than engine source.

**Complements** (does not replace):
- `unreal-source-mcp` — Engine-level source intelligence (full engine C++ and HLSL)
- `unreal-config-mcp` — Config/INI intelligence (inheritance chains, settings search, diff from defaults, CVars)
- `unreal-api-mcp` — API surface (signatures, includes, deprecation)
- `Agent Integration Kit` — Editor control (Blueprints, assets, Python execution)

**We provide:** Project-level implementation understanding — actual source code, cross-references, call graphs, and patterns within your UE project.

## Tech Stack

- **Language:** Python 3.11+
- **Parser:** tree-sitter + tree-sitter-cpp (C++ AST)
- **Storage:** SQLite + FTS5 full-text search
- **MCP SDK:** `mcp` Python package
- **Distribution:** PyPI via `uvx unreal-project-mcp`
- **Package manager:** `uv` (for dev and build)

## Project Structure

```
unreal-project-mcp/
├── pyproject.toml              # Package config, dependencies, entry point
├── CLAUDE.md                   # This file
├── README.md                   # User-facing docs
├── .gitignore
├── src/
│   └── unreal_project_mcp/
│       ├── __init__.py         # Version
│       ├── __main__.py         # Entry point (uvx runs this)
│       ├── config.py           # Env vars, DB path, project name detection
│       ├── server.py           # MCP server + all 7 tool handlers
│       ├── indexer/
│       │   ├── __init__.py
│       │   ├── pipeline.py     # Orchestrates full indexing run
│       │   ├── cpp_parser.py   # tree-sitter C++ symbol/reference extraction + UE macro handling
│       │   └── reference_builder.py  # Cross-reference extraction (calls, types)
│       └── db/
│           ├── __init__.py
│           ├── schema.py       # SQLite table definitions + FTS5 + triggers
│           └── queries.py      # All SQL queries (no inline SQL elsewhere)
└── tests/
    ├── test_config.py
    ├── test_cpp_parser.py
    ├── test_db.py
    ├── test_pipeline.py
    ├── test_server.py
    ├── test_e2e.py
    └── fixtures/
        └── sample_project_source/   # Small UE-like .h/.cpp files for testing
```

## Build & Run

```bash
# Install dev dependencies
uv sync

# Run the MCP server locally
uv run python -m unreal_project_mcp

# Run tests
uv run pytest

# Build and index (first time)
UE_PROJECT_PATH="D:/Unreal Projects/MyProject/Source" \
UE_PROJECT_NAME="MyProject" \
uv run python -m unreal_project_mcp --index

# Install globally via uvx (after publishing)
uvx unreal-project-mcp
```

## MCP Configuration (for Claude Code)

```json
{
  "mcpServers": {
    "unreal-project": {
      "command": "uvx",
      "args": ["unreal-project-mcp"],
      "env": {
        "UE_PROJECT_PATH": "D:/Unreal Projects/MyProject/Source",
        "UE_PROJECT_NAME": "MyProject"
      }
    }
  }
}
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `UE_PROJECT_PATH` | Path to the project's Source directory (required for indexing) |
| `UE_PROJECT_NAME` | Project name, used for DB filename (defaults to directory name) |
| `UNREAL_PROJECT_MCP_DB_DIR` | Override DB storage location (default: `~/.unreal-project-mcp/`) |

## MCP Tools (7)

| Tool | Purpose |
|------|---------|
| `search_project` | Full-text search across project C++ source |
| `read_project_source` | Get implementation code for a symbol (class, function, struct) |
| `find_project_callers` | What functions call this function? |
| `find_project_callees` | What does this function call internally? |
| `find_project_references` | Find all usage sites of a symbol across the project |
| `get_project_class_hierarchy` | Inheritance tree with virtual function overrides |
| `get_project_module_info` | Module contents, dependencies, statistics |

## Database

- **Location:** `~/.unreal-project-mcp/{project_name}.db`
- **Schema:** See `src/unreal_project_mcp/db/schema.py`
- **Index time:** Depends on project size, typically <5 minutes

### Key Tables
- `files` — path, module, file_type (cpp/h)
- `symbols` — name, qualified_name, kind, signature, docstring, line range
- `inheritance` — class hierarchy relationships
- `references` — cross-references (call/use/include/override)
- `modules` — project module metadata
- `source_fts` / `symbols_fts` — FTS5 full-text search

## Coding Conventions

- **All SQL lives in `db/queries.py`** — no inline SQL in tool handlers
- **Tool handlers are thin** — validate params, call query, format response
- **UE macro handling lives in `indexer/cpp_parser.py`** — `UE_MACROS` set, `_try_get_ue_macro()`, `_try_get_ue_macro_field()`, etc.
- Follow standard Python conventions: snake_case, type hints, docstrings on public functions
- Use `logging` module, not print statements
- Tests use pytest with fixtures in `tests/fixtures/`
- Keep dependencies minimal — stdlib SQLite, tree-sitter, mcp SDK, and that's it

## UE-Specific Parsing Notes

- `UCLASS()`, `UFUNCTION()`, `UPROPERTY()`, `UENUM()`, `USTRUCT()` are macros that precede declarations — parse them as annotations on the following symbol
- `GENERATED_BODY()` / `GENERATED_UCLASS_BODY()` expand to compiler-generated code — skip
- `DECLARE_DELEGATE*`, `DECLARE_DYNAMIC_MULTICAST_DELEGATE*` — extract as delegate symbols
- `TEXT("...")` and `LOCTEXT(...)` are string macros — don't confuse with function calls

## Known Limitations / Future Work

- **Incremental indexing:** A future enhancement should compare mtimes and skip unchanged files, with careful handling of cross-file reference invalidation when a single file changes.
- **Method call type inference:** `->Method()` calls resolve to the unqualified method name when the object type can't be determined from local variable declarations. Full type inference is not implemented.
