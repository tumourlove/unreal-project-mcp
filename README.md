# unreal-project-mcp

Project-level source and configuration intelligence for Unreal Engine AI development via [Model Context Protocol](https://modelcontextprotocol.io/).

Indexes your UE project's C++ source code, config/INI files, Build.cs dependencies, plugin descriptors, gameplay tags, replication topology, asset references, and log categories into a SQLite database. Exposes 17 MCP tools for AI coding assistants like Claude Code — structural queries, config lookups, dependency graphs, and full-text search across your entire project.

## Why?

AI assistants are great at writing code but struggle to *understand* large codebases. This server gives them structural awareness of your project — what calls what, how classes relate, where symbols are used, what config drives behavior, how modules depend on each other — so they can make informed changes instead of guessing.

**Complements** (does not replace):
- [unreal-source-mcp](https://github.com/tumourlove/unreal-source-mcp) — Engine-level source intelligence (full UE C++ and HLSL)
- [unreal-editor-mcp](https://github.com/tumourlove/unreal-editor-mcp) — Build diagnostics and editor log tools (Live Coding, error parsing, log search)
- [unreal-blueprint-mcp](https://github.com/tumourlove/unreal-blueprint-mcp) — Blueprint graph reading (nodes, pins, connections, execution flow)
- [unreal-blueprint-reader](https://github.com/tumourlove/unreal-blueprint-reader) — C++ editor plugin that serializes Blueprint graphs to JSON for AI tooling
- [unreal-material-mcp](https://github.com/tumourlove/unreal-material-mcp) — Material graph intelligence, editing, and procedural creation (46 tools: expressions, parameters, instances, graph building, templates, C++ plugin)
- [unreal-config-mcp](https://github.com/tumourlove/unreal-config-mcp) — Config/INI intelligence (resolve inheritance chains, search settings, diff from defaults, explain CVars)
- [unreal-animation-mcp](https://github.com/tumourlove/unreal-animation-mcp) — Animation data inspector and editor (sequences, montages, blend spaces, ABPs, skeletons, 62 tools)
- [unreal-niagara-mcp](https://github.com/tumourlove/unreal-niagara-mcp) — Niagara VFX intelligence and editing (emitters, modules, HLSL generation, procedural creation, 70 tools)
- [unreal-api-mcp](https://github.com/nicobailon/unreal-api-mcp) by [Nico Bailon](https://github.com/nicobailon) — API surface lookup (signatures, #include paths, deprecation warnings)

Together these servers give AI agents full-stack UE understanding: engine internals, API surface, your project code, build/runtime feedback, Blueprint graph data, config/INI intelligence, material graph inspection + editing, animation data inspection + editing, and Niagara VFX inspection + creation.

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

## Tools (17)

### C++ Source Intelligence

| Tool | Description |
|------|-------------|
| `search_project` | Full-text search across project C++ source. Supports FTS, regex, and substring modes. Filter by module, path, or symbol kind. |
| `read_project_source` | Read the actual implementation of a class, function, or struct with line numbers. Shows both .h and .cpp. |
| `find_project_callers` | Find all functions that call a given function. Includes heuristic delegate/binding detection. |
| `find_project_callees` | Find all functions called by a given function. |
| `find_project_references` | Find all usage sites of a symbol (calls, type references, includes). |
| `get_project_class_hierarchy` | Show the inheritance tree for a class — ancestors, descendants, or both. |
| `get_project_module_info` | Module statistics: file count, symbol counts by kind, key classes. |

### Config & Build Intelligence

| Tool | Description |
|------|-------------|
| `get_config_values` | Look up config/INI values by key with optional section filter. Cross-references with UPROPERTY(Config) C++ symbols. |
| `search_config` | Full-text search across all project config/INI files (sections, keys, values). |
| `get_module_dependencies` | Build.cs module dependency graph — dependencies, dependents, or both directions. |
| `get_plugin_info` | Plugin metadata, modules, and plugin-to-plugin dependencies from .uplugin files. |
| `find_data_table_schema` | Data table struct definitions — finds FTableRowBase children and linked data tables. |

### Runtime & Asset Intelligence

| Tool | Description |
|------|-------------|
| `find_asset_references` | Find C++ code that references assets by path (`TEXT("/Game/...")`, `LoadObject`, `ConstructorHelpers`, `FSoftObjectPath`). |
| `search_gameplay_tags` | Search gameplay tag definitions and usage across C++, INI config, and CSV data tables. |
| `find_log_sites` | Find log category declarations (`DECLARE_LOG_CATEGORY_EXTERN`) and `UE_LOG` usage sites. |
| `get_replication_map` | Replicated properties and Server/Client/NetMulticast RPCs for a class or the entire project. |
| `search_project_tags` | Pattern-based classifications: subsystems, anim notifies, console commands. |

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

2. **C++ Parsing** — Uses [tree-sitter](https://tree-sitter.github.io/) with the C++ grammar to build ASTs. Handles UE macros (UCLASS, UFUNCTION, UPROPERTY, etc.) with regex fallback for misparsed nodes. Extracts replication specifiers, asset path references, and log category declarations.

3. **Config & Build Parsing** — Parses UE's non-standard INI format (duplicate keys, `+`/`-`/`.`/`!` prefixes), Build.cs module dependencies, and .uplugin plugin descriptors.

4. **Post-Processing** — Scans for gameplay tags across C++, INI, and CSV sources. Applies pattern-based classification to identify subsystems, anim notifies, and console commands.

5. **Storage** — SQLite with FTS5 full-text search. 19 tables covering symbols, inheritance, cross-references, config entries, asset references, gameplay tags, replication entries, module dependencies, plugins, log categories, and pattern tags.

6. **Serving** — FastMCP server exposes 17 tools over stdio. Claude Code manages the server lifecycle automatically.

## What Gets Indexed

**C++ Source:**
- Classes, structs, enums (with base classes and UE macro metadata)
- Functions (declarations and definitions, with qualified names like `UMyClass::MyMethod`)
- Variables (member variables with UPROPERTY detection)
- Includes, call references, type references, inheritance relationships
- Replication markers (Server/Client/NetMulticast RPCs, Replicated/ReplicatedUsing properties)
- Asset path references (`TEXT("/Game/...")`, `LoadObject<T>`, `ConstructorHelpers`, `FSoftObjectPath`)
- Log categories (`DECLARE_LOG_CATEGORY_EXTERN`, `DEFINE_LOG_CATEGORY`)
- Docstrings (`/** */` and `///` comments)

**Config & Build:**
- INI config key-value pairs across all `Config/*.ini` files
- Build.cs module dependencies (public, private, dynamically loaded)
- Plugin descriptors (metadata, modules, plugin dependencies)

**Derived Intelligence:**
- Gameplay tags from C++ source, INI config, and CSV data tables
- Data table struct detection (FTableRowBase children)
- Pattern classifications (subsystems, anim notifies, console commands)

## Adding to Your Project's CLAUDE.md

```markdown
## Project Intelligence (unreal-project MCP)

Use `unreal-project` MCP tools to search, read, and understand your project's C++ source,
config files, module dependencies, gameplay tags, and replication topology.

| Tool | When |
|------|------|
| `search_project` | Full-text search across project C++ source |
| `read_project_source` | Read implementation of a class/function |
| `find_project_callers` | What calls this function? |
| `find_project_references` | Find all usage sites of a symbol |
| `get_project_class_hierarchy` | Inheritance tree (ancestors/descendants) |
| `get_config_values` | Look up config/INI values by key |
| `get_module_dependencies` | Module dependency graph from Build.cs |
| `search_gameplay_tags` | Search gameplay tag definitions and usage |
| `get_replication_map` | Replicated properties and RPCs |
```

## Development

```bash
# Clone and install
git clone https://github.com/tumourlove/unreal-project-mcp.git
cd unreal-project-mcp
uv sync

# Run tests (157 tests)
uv run pytest -v

# Run locally
UE_PROJECT_PATH="/path/to/project" uv run python -m unreal_project_mcp
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## License

MIT
