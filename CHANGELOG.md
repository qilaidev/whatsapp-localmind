# Changelog

All notable changes to `whatsapp-localmind` will be documented in this file.

## [3.2.0] - 2026-11-13

### Added
- Open-source release under the MIT License (`qilaidev/whatsapp-localmind`).
- Added English documentation (`README.en.md`), `llms.txt` (GEO / llmstxt.org standard), `SECURITY.md`, `CONTRIBUTING.md`, and `LICENSE`.
- Zero-dependency CLI (`whatsapp-localmind`) with 9 subcommands (`doctor`, `config`, `groups`, `fetch`, `search`, `export-media`, `clean`, `mcp-serve`, `install`).
- Zero-dependency JSON-RPC 2.0 MCP Stdio Server exposing 4 read-only tools (`whatsapp_list_groups`, `whatsapp_fetch_messages`, `whatsapp_search_messages`, `whatsapp_export_media`).
- SQLite Online Backup (`sqlite3_backup`) + POSIX `flock` snapshot isolation with `?mode=ro` read-only queries.
- Physical `@g.us` group-only SQL and media guard blocking 1-on-1 DMs (`@s.whatsapp.net` / `@lid`).
- 4-tier real-name resolution & `@lid` cross-table mapping (`ZWACHATSESSION`, `ContactsV2.sqlite`, `ZWAGROUPMEMBER`, `ZWAPROFILEPUSHNAME`, `ZWAMESSAGE.ZPUSHNAME`).
- Pure Python zero-dependency Protobuf wire parser for 150-char reply quote chains and whitelisted `@mentions`.
- Monotonic incremental cursor (`--after-id` via `ZWAMESSAGE.Z_PK`) with 10-message context buffer and out-of-bounds 24h fallback.
