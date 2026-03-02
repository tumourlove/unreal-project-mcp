# unreal-project-mcp

Project-level C++ source intelligence for Unreal Engine AI development via [Model Context Protocol](https://modelcontextprotocol.io/).

Indexes your UE project's C++ source code (Source/ + Plugins/) into a SQLite database and exposes structural queries — class hierarchy, call graphs, cross-references, and full-text search — as MCP tools for AI coding assistants like Claude Code.

## Why?

AI assistants are great at writing code but struggle to *understand* large codebases. This server gives them structural awareness of your project — what calls what, how classes relate, where symbols are used — so they can make informed changes instead of guessing.

**Complements** (does not replace):
- [unreal-source-mcp](https://github.com/tumourlove/unreal-source-mcp) — Engine-level source intelligence (full UE C++ and HLSL)
- [unreal-api-mcp](https://github.com/nicobailon/unreal-api-mcp) by [Nico Bailon](https://github.com/nicobailon) — API surface lookup (signatures, #include paths, deprecation warnings)

Together these three servers give AI agents full-stack UE understanding: engine internals, API surface, and your project code.

## Quick Start

### Install from GitHub

```bash
uvx --from git+https://github.com/tumourlove/unreal-project-mcp.git unreal-project-mcp --index
```

### Claude Code Configuration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "unreal-project": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/tumourlove/unreal-project-mcp.git", "unreal-project-mcp"],
      "env": {
        "UE_PROJECT_PATH": "D:/Unreal Projects/MyProject",
        "UE_PROJECT_NAME": "MyProject"
      }
    }
  }
}
```

Or run from local source during development:

```json
{
  "mcpServers": {
    "unreal-project": {
      "command": "uv",
      "args": ["run", "--directory", "C:/Projects/unreal-project-mcp", "python", "-m", "unreal_project_mcp"],
      "env": {
        "UE_PROJECT_PATH": "D:/Unreal Projects/MyProject",
        "UE_PROJECT_NAME": "MyProject"
      }
    }
  }
}
```

The server auto-indexes on first run if no database exists.

## Tools

| Tool | Description |
|------|-------------|
| `search_project` | Full-text search across project C++ source. Supports FTS, regex, and substring modes. Filter by module, path, or symbol kind. |
| `read_project_source` | Read the actual implementation of a class, function, or struct with line numbers. Shows both .h and .cpp. |
| `find_project_callers` | Find all functions that call a given function. Includes heuristic delegate/binding detection. |
| `find_project_callees` | Find all functions called by a given function. |
| `find_project_references` | Find all usage sites of a symbol (calls, type references, includes). |
| `get_project_class_hierarchy` | Show the inheritance tree for a class — ancestors, descendants, or both. |
| `get_project_module_info` | Module statistics: file count, symbol counts by kind, key classes. |

## CLI

```bash
# Index project source (first time)
unreal-project-mcp --index

# Rebuild from scratch
unreal-project-mcp --reindex

# Incremental update (only changed files)
unreal-project-mcp --reindex-changed

# Run as MCP server (default, used by Claude Code)
unreal-project-mcp
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `UE_PROJECT_PATH` | Yes | Path to the project root (containing Source/ and Plugins/) |
| `UE_PROJECT_NAME` | No | Project name for the DB filename. Auto-detected from .uproject if not set. |
| `UNREAL_PROJECT_MCP_DB_DIR` | No | Override DB storage location (default: `~/.unreal-project-mcp/`) |

## How It Works

1. **Discovery** — Walks `Source/` for game modules and `Plugins/*/Source/` for plugin modules. Uses the actual module subdirectory names, not plugin folder names (handles marketplace hashed folders correctly).

2. **Parsing** — Uses [tree-sitter](https://tree-sitter.github.io/) with the C++ grammar to build ASTs. Handles UE macros (UCLASS, UFUNCTION, UPROPERTY, etc.) that often cause parse errors, with regex fallback for misparsed nodes.

3. **Storage** — SQLite with FTS5 full-text search. Symbols, inheritance, cross-references, and source text are all indexed. Database is typically <30MB for large projects.

4. **Serving** — FastMCP server exposes 7 tools over stdio. Claude Code manages the server lifecycle automatically.

## What Gets Indexed

- Classes, structs, enums (with base classes and UE macro metadata)
- Functions (declarations and definitions, with qualified names like `UMyClass::MyMethod`)
- Variables (member variables with UPROPERTY detection)
- Includes
- Call references (function A calls function B)
- Type references (function A uses type B)
- Inheritance relationships
- Docstrings (/** */ and /// comments)

## Development

```bash
# Clone and install
git clone https://github.com/tumourlove/unreal-project-mcp.git
cd unreal-project-mcp
uv sync

# Run tests
uv run pytest -v

# Run locally
UE_PROJECT_PATH="/path/to/project" uv run python -m unreal_project_mcp
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## License

MIT
