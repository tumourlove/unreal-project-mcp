# Project Intelligence Expansion — Design Document

**Date:** 2026-03-05
**Status:** Approved
**Scope:** Expand unreal-project-mcp from C++ source intelligence to full project intelligence

## Goal

Transform unreal-project-mcp from a C++ source viewer into a comprehensive UE project intelligence engine. Index config files, build dependencies, plugins, gameplay tags, asset references, replication topology, log categories, and more — all queryable through dedicated MCP tools.

## Design Decisions

- **Project root auto-detection**: If `UE_PROJECT_PATH` points to or contains `Source/`, walk up to find the project root. Discover `Source/`, `Config/`, `Content/`, `Plugins/` from there.
- **Dedicated tools per feature** (not composite): 10 new tools, 17 total. Specific tool names improve AI discoverability.
- **Build.cs parsing**: Dependencies only (public/private/dynamic), not full module config.
- **Gameplay tags**: Scan all sources (C++, INI, data tables) since indexing is infrequent.
- **Pattern tags system**: Subsystems, anim notifies, and console commands share a single `pattern_tags` table + tool rather than getting dedicated infrastructure.

---

## Architecture Overview

### New Indexer Modules

| Module | Parses | Output Tables |
|--------|--------|---------------|
| `indexer/config_parser.py` | `Config/*.ini` | `config_entries`, `config_fts` |
| `indexer/build_cs_parser.py` | `Source/**/*.Build.cs` | `module_dependencies` |
| `indexer/plugin_parser.py` | `Plugins/**/*.uplugin` | `plugins`, `plugin_modules`, `plugin_dependencies` |
| `indexer/tag_scanner.py` | C++ index + INI + Content CSVs | `gameplay_tags`, `tags_fts` |
| `indexer/pattern_tagger.py` | Post-index pass on symbols + inheritance | `pattern_tags` |

### Extended Existing Modules

| Module | New Extraction |
|--------|---------------|
| `indexer/cpp_parser.py` | UFUNCTION specifiers (Server/Client/NetMulticast), UPROPERTY replication markers |
| `indexer/reference_builder.py` | Asset path strings, log category declarations + UE_LOG sites |
| `indexer/pipeline.py` | Scan Config/, Plugins/, Content/; run new indexers; extended finalize |
| `config.py` | Auto-detect project root, expose PROJECT_ROOT/CONFIG_DIR/CONTENT_DIR/PLUGINS_DIR |

### New MCP Tools (10)

| # | Tool | Purpose |
|---|------|---------|
| 1 | `get_config_values(key, section="")` | Look up UPROPERTY(Config) field values in .ini files |
| 2 | `search_config(query, limit=20)` | FTS across all config/ini files |
| 3 | `find_asset_references(asset_path="", symbol="")` | C++ code referencing assets by path, or assets referenced by a symbol |
| 4 | `find_data_table_schema(name)` | FTableRowBase struct fields + linked data table |
| 5 | `search_gameplay_tags(query, usage_kind="")` | Find tag definitions, requests, checks, grants |
| 6 | `get_module_dependencies(module_name, direction="both")` | Build.cs dependency graph (dependents/dependencies/both) |
| 7 | `get_plugin_info(plugin_name)` | Plugin metadata, modules, and dependencies |
| 8 | `find_log_sites(category, limit=50)` | Log category declaration + all UE_LOG call sites |
| 9 | `get_replication_map(class_name="")` | Server/Client/NetMulticast RPCs + replicated properties |
| 10 | `search_project_tags(kind="", query="")` | Pattern tags: subsystems, anim_notify, console_command |

---

## Schema (v2)

9 new tables added to `schema.py`. Schema version bumps from 1 to 2.

### Config/INI Data

```sql
CREATE TABLE config_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,
    section     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT,
    line        INTEGER
);
CREATE INDEX idx_config_section_key ON config_entries(section, key);

CREATE VIRTUAL TABLE config_fts USING fts5(
    section, key, value,
    content=config_entries, content_rowid=id
);
```

Triggers to keep `config_fts` in sync:

```sql
CREATE TRIGGER config_ai AFTER INSERT ON config_entries BEGIN
    INSERT INTO config_fts(rowid, section, key, value)
    VALUES (new.id, new.section, new.key, new.value);
END;

CREATE TRIGGER config_ad AFTER DELETE ON config_entries BEGIN
    INSERT INTO config_fts(config_fts, rowid, section, key, value)
    VALUES ('delete', old.id, old.section, old.key, old.value);
END;
```

### Asset References

```sql
CREATE TABLE asset_references (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id   INTEGER REFERENCES symbols(id),
    asset_path  TEXT NOT NULL,
    ref_type    TEXT NOT NULL,   -- "FSoftObjectPath", "LoadObject", "ConstructorHelpers"
    file_id     INTEGER REFERENCES files(id),
    line        INTEGER
);
CREATE INDEX idx_asset_refs_path ON asset_references(asset_path);
CREATE INDEX idx_asset_refs_symbol ON asset_references(symbol_id);
```

### Data Tables

```sql
CREATE TABLE data_tables (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    struct_symbol_id  INTEGER REFERENCES symbols(id),
    table_path        TEXT,
    table_name        TEXT
);
```

### Gameplay Tags

```sql
CREATE TABLE gameplay_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tag         TEXT NOT NULL,
    source_type TEXT NOT NULL,   -- "cpp", "ini", "datatable"
    usage_kind  TEXT NOT NULL,   -- "definition", "request", "check", "grant"
    symbol_id   INTEGER REFERENCES symbols(id),
    file_path   TEXT,
    line        INTEGER
);
CREATE INDEX idx_tags_tag ON gameplay_tags(tag);
CREATE INDEX idx_tags_kind ON gameplay_tags(usage_kind);

CREATE VIRTUAL TABLE tags_fts USING fts5(
    tag, content=gameplay_tags, content_rowid=id
);
```

Triggers:

```sql
CREATE TRIGGER tags_ai AFTER INSERT ON gameplay_tags BEGIN
    INSERT INTO tags_fts(rowid, tag) VALUES (new.id, new.tag);
END;

CREATE TRIGGER tags_ad AFTER DELETE ON gameplay_tags BEGIN
    INSERT INTO tags_fts(tags_fts, rowid, tag)
    VALUES ('delete', old.id, old.tag);
END;
```

### Module Dependencies

```sql
CREATE TABLE module_dependencies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id       INTEGER NOT NULL REFERENCES modules(id),
    dependency_name TEXT NOT NULL,
    dep_type        TEXT NOT NULL,   -- "public", "private", "dynamic"
    UNIQUE(module_id, dependency_name, dep_type)
);
```

### Plugins

```sql
CREATE TABLE plugins (
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

CREATE TABLE plugin_modules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id     INTEGER NOT NULL REFERENCES plugins(id),
    module_name   TEXT NOT NULL,
    module_type   TEXT,
    loading_phase TEXT
);

CREATE TABLE plugin_dependencies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id   INTEGER NOT NULL REFERENCES plugins(id),
    depends_on  TEXT NOT NULL
);
```

### Log Categories

```sql
CREATE TABLE log_categories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    file_id   INTEGER REFERENCES files(id),
    line      INTEGER,
    verbosity TEXT
);
```

### Replication

```sql
CREATE TABLE replication_entries (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id),
    rep_type  TEXT NOT NULL,   -- "Server", "Client", "NetMulticast", "Replicated", "ReplicatedUsing"
    condition TEXT,
    callback  TEXT
);
CREATE INDEX idx_rep_type ON replication_entries(rep_type);
```

### Pattern Tags

```sql
CREATE TABLE pattern_tags (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id),
    tag_kind  TEXT NOT NULL,   -- "subsystem", "anim_notify", "console_command"
    metadata  TEXT             -- JSON blob for extra info
);
CREATE INDEX idx_pattern_tags_kind ON pattern_tags(tag_kind);
```

---

## Indexer Details

### config_parser.py

Parses UE `.ini` files from `Config/`. Cannot use Python's `configparser` because UE INI format has:
- Duplicate keys (array-style `+Key=Value`)
- Special prefixes: `+` (add), `-` (remove), `.` (add unique), `!` (clear)
- Multi-line values

Implementation: line-by-line regex parser.
- Track current section via `[SectionName]` headers
- Extract `key=value` pairs, preserving the `+`/`-`/`.`/`!` prefix in the key
- Insert into `config_entries` with file_path, section, key, value, line number

### build_cs_parser.py

Regex-based extraction from `.Build.cs` C# files. Patterns:

```
PublicDependencyModuleNames.AddRange(new string[] { "Core", "Engine" })  → dep_type="public"
PrivateDependencyModuleNames.AddRange(new string[] { "Slate" })         → dep_type="private"
DynamicallyLoadedModuleNames.Add("OnlineSubsystem")                     → dep_type="dynamic"
PublicDependencyModuleNames.Add("InputCore")                            → dep_type="public"
```

Regex: capture the dependency type from the variable name, then extract quoted strings from the argument list.

### plugin_parser.py

JSON parse of `.uplugin` files. Extract:
- Top-level: `FriendlyName`, `Description`, `Category`, `VersionName`, `bCanContainContent`, `bIsBetaVersion`
- `Modules[]`: each entry has `Name`, `Type`, `LoadingPhase`
- `Plugins[]`: each entry has `Name` (dependency), `Enabled`

### tag_scanner.py

Runs after C++ indexing and config parsing. Three source scans:

**C++ sources** (via `source_fts`):
- `AddNativeGameplayTag(TEXT("Tag.Name"))` → usage_kind="definition"
- `RequestGameplayTag(FName(TEXT("Tag.Name")))` → usage_kind="request"
- `HasMatchingGameplayTag`, `MatchesTag` → usage_kind="check"
- `AddDynamic`, `Broadcast` with tag context → usage_kind="grant"

**INI files** (via `config_entries`):
- Key = `GameplayTagList` or contains `GameplayTag` → extract tag strings from values

**Data tables** (scan `Content/` for `.csv`):
- Look for CSV files whose headers contain "Tag" or "GameplayTag"
- Extract tag-like values (dot-separated identifiers)

### pattern_tagger.py

Post-indexing pass. Queries existing symbol + inheritance data:

**Subsystems:**
- Query inheritance for children of known subsystem base classes: `UGameInstanceSubsystem`, `UWorldSubsystem`, `ULocalPlayerSubsystem`, `UEngineSubsystem`
- tag_kind = "subsystem", metadata includes subsystem type

**Anim notifies:**
- Query inheritance for children of `UAnimNotify`, `UAnimNotifyState`
- tag_kind = "anim_notify"

**Console commands:**
- Search `source_fts` for `RegisterConsoleCommand`, `IConsoleManager::Get()`, and functions named `Exec*`
- tag_kind = "console_command", metadata includes the command string if extractable

### C++ Parser Extensions

**Replication markers** — during UFUNCTION/UPROPERTY extraction in `cpp_parser.py`:
- When parsing UE macro arguments, detect `Server`, `Client`, `NetMulticast` in UFUNCTION specifiers
- Detect `Replicated`, `ReplicatedUsing=OnRep_X` in UPROPERTY specifiers
- Store in `ParsedSymbol` as new fields, pipeline inserts into `replication_entries`

**Asset path extraction** — in `reference_builder.py`:
- Regex scan function bodies for:
  - `TEXT("/Game/...")` or `TEXT("/Script/...")`
  - `FSoftObjectPath(TEXT("..."))`
  - `LoadObject<T>(nullptr, TEXT("..."))`
  - `ConstructorHelpers::FObjectFinder<T>(TEXT("..."))`
- Insert into `asset_references`

**Log category extraction** — in `reference_builder.py`:
- `DECLARE_LOG_CATEGORY_EXTERN(LogName, Warning, All)` → insert into `log_categories`
- `DEFINE_LOG_CATEGORY(LogName)` → update existing or insert
- `UE_LOG(LogName, ...)` sites tracked via source_fts queries at tool query time (not pre-indexed, to avoid massive reference counts)

**Data table struct detection** — in pipeline `_finalize()`:
- After inheritance resolution, find structs inheriting `FTableRowBase`
- Insert into `data_tables` with struct_symbol_id

### Pipeline Changes

`index_project()` execution order:

1. Discover project root from `UE_PROJECT_PATH`
2. **Phase 1 — C++ indexing** (existing): walk Source/, Plugins/*/Source/
3. **Phase 2 — Non-C++ indexing** (new):
   a. `config_parser` scans `Config/`
   b. `build_cs_parser` scans `Source/` for `*.Build.cs`
   c. `plugin_parser` scans `Plugins/` for `*.uplugin`
4. **Phase 3 — Finalize** (extended existing):
   a. Resolve inheritance (existing)
   b. Extract cross-references (existing)
   c. Extract asset references (new)
   d. Extract log categories (new)
   e. Insert replication entries (new)
   f. Detect data table structs (new)
5. **Phase 4 — Post-index passes** (new):
   a. `tag_scanner` (needs C++ index + config data)
   b. `pattern_tagger` (needs inheritance data)

---

## Tool Specifications

### 1. get_config_values(key, section="")

Look up config entries by key name. Optionally filter by INI section.

Cross-references with C++ symbols: if a `UPROPERTY(Config)` symbol matches the key name, include the C++ declaration info alongside the .ini value.

Returns: section, key, value, file path, line number. If cross-referenced, also shows the C++ symbol signature and location.

### 2. search_config(query, limit=20)

FTS across `config_fts` — searches section names, keys, and values.

Returns: matching entries with section.key = value, file path, line.

### 3. find_asset_references(asset_path="", symbol="")

Bidirectional lookup:
- `asset_path` given: find all C++ symbols that reference this asset path (substring match)
- `symbol` given: find all asset paths referenced by this symbol
- Both given: check if this symbol references this asset

Returns: asset_path, ref_type, C++ symbol name, file path, line.

### 4. find_data_table_schema(name)

Look up a `FTableRowBase` struct by name. Uses existing `read_project_source` logic to show struct fields. If a data table asset path is linked, includes that.

Returns: struct name, inheritance, fields with types, linked data table path.

### 5. search_gameplay_tags(query, usage_kind="")

FTS on tag names via `tags_fts`. Optional filter by usage_kind: "definition", "request", "check", "grant".

Returns: tag string, source_type, usage_kind, location (file + line or symbol name).

### 6. get_module_dependencies(module_name, direction="both")

Query `module_dependencies` table.
- `direction="dependencies"`: what this module depends on
- `direction="dependents"`: what modules depend on this one (reverse lookup by dependency_name)
- `direction="both"`: both

Returns: dependency name, dep_type (public/private/dynamic), direction.

### 7. get_plugin_info(plugin_name)

Query `plugins`, `plugin_modules`, `plugin_dependencies`.

Returns: plugin metadata, list of modules with type and loading phase, list of plugin dependencies.

### 8. find_log_sites(category, limit=50)

1. Look up `log_categories` for the declaration site
2. Search `source_fts` for `UE_LOG(CategoryName,` to find usage sites

Returns: category declaration (file, line, verbosity) + list of UE_LOG call sites (file, line, snippet).

### 9. get_replication_map(class_name="")

Query `replication_entries` joined with `symbols`.
- If `class_name` given: filter to that class's members
- If empty: return all, grouped by class

Returns: per entry — symbol name, rep_type, condition, callback (for ReplicatedUsing), file location.

### 10. search_project_tags(kind="", query="")

Query `pattern_tags` joined with `symbols`.
- `kind` filter: "subsystem", "anim_notify", "console_command"
- `query`: substring match on symbol name

Returns: symbol name, tag_kind, file location, metadata.

---

## Config Changes

### config.py additions

```python
def _detect_project_root() -> Path | None:
    """Auto-detect UE project root from UE_PROJECT_PATH.

    If path contains/ends with Source/, walk up.
    Otherwise use the path directly if it contains a .uproject file.
    """
    ...

PROJECT_ROOT: Path | None   # auto-detected
SOURCE_DIR: Path | None      # PROJECT_ROOT / "Source"
CONFIG_DIR: Path | None      # PROJECT_ROOT / "Config"
CONTENT_DIR: Path | None     # PROJECT_ROOT / "Content"
PLUGINS_DIR: Path | None     # PROJECT_ROOT / "Plugins"
```

### Environment variables (unchanged)

No new env vars required. `UE_PROJECT_PATH` remains the only required input. The auto-detection handles the rest.

---

## Migration

When the server opens a v1 database, it should detect the schema version and offer to re-index. Since this is a project-level tool (not engine-level), full re-indexing is fast and the simplest migration path.

---

## Testing Strategy

Each new indexer module gets its own test file with fixture data:
- `tests/fixtures/sample_config/` — sample .ini files
- `tests/fixtures/sample_build_cs/` — sample .Build.cs files
- `tests/fixtures/sample_plugins/` — sample .uplugin files
- `tests/fixtures/sample_content/` — sample .csv data tables

Integration test: full pipeline run on expanded fixtures, then query each new tool.

---

## File Changes Summary

### New files (10)
- `src/unreal_project_mcp/indexer/config_parser.py`
- `src/unreal_project_mcp/indexer/build_cs_parser.py`
- `src/unreal_project_mcp/indexer/plugin_parser.py`
- `src/unreal_project_mcp/indexer/tag_scanner.py`
- `src/unreal_project_mcp/indexer/pattern_tagger.py`
- `tests/test_config_parser.py`
- `tests/test_build_cs_parser.py`
- `tests/test_plugin_parser.py`
- `tests/test_tag_scanner.py`
- `tests/test_pattern_tagger.py`

### Modified files (6)
- `src/unreal_project_mcp/config.py` — project root auto-detection
- `src/unreal_project_mcp/db/schema.py` — 9 new tables, v2
- `src/unreal_project_mcp/db/queries.py` — insert/query helpers for all new tables
- `src/unreal_project_mcp/indexer/cpp_parser.py` — replication marker extraction
- `src/unreal_project_mcp/indexer/reference_builder.py` — asset paths, log categories
- `src/unreal_project_mcp/indexer/pipeline.py` — extended pipeline with new phases
- `src/unreal_project_mcp/server.py` — 10 new tool handlers

### New fixture files
- `tests/fixtures/sample_config/*.ini`
- `tests/fixtures/sample_build_cs/*.Build.cs`
- `tests/fixtures/sample_plugins/*.uplugin`
- `tests/fixtures/sample_content/*.csv`
