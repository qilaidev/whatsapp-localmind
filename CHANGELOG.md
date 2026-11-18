# Changelog

All notable changes to `whatsapp-localmind` will be documented in this file.

## [4.0.0] - 2026-11-18

### Changed
- **Full-Account WhatsApp Chat Extraction (`chat_scope = "all"` default)**: Expanded from group-only extraction to all WhatsApp chat sessions out of the box—1-on-1 direct DMs (`@s.whatsapp.net`, `@lid`, and bare phone numbers like `+86139...`), group chats (`@g.us`), channels (`@newsletter`), and broadcast lists (`@broadcast`), while always excluding ephemeral `status@broadcast`.
- **Bidirectional `@lid` ↔ `@s.whatsapp.net` Cross-Table Bridging**: Unified resolution across `LID.sqlite` (`ZWAZACCOUNT`), `ZWACHATSESSION` (`ZCONTACTJID` ↔ `ZCONTACTIDENTIFIER`), and `ContactsV2.sqlite` (`ZWAADDRESSBOOKCONTACT`), including self-chat detection and standardized fallback labels (`联系人(+XX-XXXX)` / `联系人#XXXX`).
- **Optional Privacy Scope & Policy Filtering**: Added `whatsapp-localmind config set-scope <all|groups|direct|newsletter>` and `WHATSAPP_LOCALMIND_CHAT_SCOPE` environment variable, plus generalized `config block|unblock|allow|disallow` for any valid JID or phone number (enforcing policy across bridged JIDs with `EXIT_POLICY_DENIED` = `3` / `CHAT_SCOPE_DENIED` / `CHAT_BLOCKED_BY_POLICY`).
- **10 CLI Subcommands**: Added `chats` (alias `list-chats`, with `--type all|direct|group|newsletter|broadcast`), extended `fetch` (`--chats ALL_ALLOWED | ALL_DIRECT | ALL_GROUPS | <jids>` and `--type`), and extended `search` (`--type` and `--chats`), while retaining `groups` (`list-groups`) as a backward-compatible `@g.us` filter.
- **5 Read-Only MCP Stdio Tools (`readOnlyHint: true`)**: Added `whatsapp_list_chats` alongside `whatsapp_list_groups`, and updated `whatsapp_fetch_messages`, `whatsapp_search_messages`, and `whatsapp_export_media` schemas with `chat_type` and `ALL_DIRECT` / `ALL_GROUPS` / `ALL_ALLOWED` support.
- **JSON Output Schema**: Added `chat_name` and `chat_type` (`direct | group | newsletter | broadcast`) across `chats`, `fetch`, `search`, and `export-media` outputs while preserving `group_name` as a backward-compatible alias.

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
