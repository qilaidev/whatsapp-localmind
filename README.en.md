# WhatsApp LocalMind (`whatsapp-localmind`)

**Zero-dependency macOS WhatsApp local group chat read-only extractor, structured cleaner, CLI & MCP Server for AI Agents**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero%20Runtime%20Deps-brightgreen.svg)](./pyproject.toml)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-black.svg)](https://www.apple.com/macos/)
[![MCP Server](https://img.shields.io/badge/MCP-Stdio%20Read--Only-6E56CF.svg)](#mcp-stdio-server-setup--tool-contracts)
[![Agent CLI](https://img.shields.io/badge/Agent-CLI%20%26%20SKILL.md-orange.svg)](./skills/whatsapp-localmind/SKILL.md)

[简体中文](./README.md) | **English** | [llms.txt](./llms.txt) | [Agent Skill](./skills/whatsapp-localmind/SKILL.md) | [Security Policy](./SECURITY.md) | [Contributing](./CONTRIBUTING.md) | [Changelog](./CHANGELOG.md) | [MIT License](./LICENSE)

**WhatsApp LocalMind (`whatsapp-localmind`)** is a pure Python standard-library **read-only local group chat extraction and structured cleaning capability layer for macOS WhatsApp**, delivering both a POSIX-compliant CLI and a zero-dependency JSON-RPC 2.0 MCP Stdio Server. It reads local CoreData SQLite databases (`ChatStorage.sqlite`, `LID.sqlite`, `ContactsV2.sqlite`) offline via `sqlite3_backup` atomic snapshots and `?mode=ro`, physically blocking 1-on-1 DMs while transforming group conversations into high-signal JSON or Markdown streams for AI Agents such as Claude Desktop, Cursor, and Antigravity.

> **`*-localmind` Local Instant Messaging Read-Only Extraction Family**
>
> Alongside its sister repository [`wechat-localmind`](https://github.com/qilaidev/wechat-localmind) (macOS & Windows WeChat local group extraction layer), this project belongs to the **`*-localmind` family** and strictly adheres to five shared architectural pillars:
> **100% Offline Read-Only Snapshots + Physical 1-on-1 DM Blocking + 4-Tier Real-Name Resolution + Monotonic Incremental Cursors + Dual CLI & MCP Delivery**.

---

## Positioning: What It Is / What It Is Not

| What it is | What it is not |
| :--- | :--- |
| ✅ **100% Offline Read-Only Local Extractor**: Reads macOS WhatsApp CoreData SQLite containers locally | ❌ **Not a Protocol Bot or Web Scraper**: Never connects to WhatsApp Web, unofficial APIs, or remote servers |
| ✅ **Physical `@g.us` Group-Only Guard**: Enforces group isolation at both the SQL engine and media export layers | ❌ **Not a Messaging Client**: Contains zero code to send messages, alter read receipts, or write to live DBs |
| ✅ **AI Agent Native Delivery Layer**: Ships 9 CLI subcommands, 4 read-only MCP tools, and `SKILL.md` | ❌ **Zero Third-Party Pip Dependencies**: Requires no external `protobuf`, `mcp`, or C-extension packages |

---

## Six Architectural Pillars

1. **SQLite Online Backup Snapshots & POSIX `flock` (100% Offline Read-Only)**
   - Uses `sqlite3_backup` (`sqlite3.Connection.backup`) with POSIX `flock` concurrency locking to materialize WAL-merged single-file snapshots inside `~/Library/Application Support/WhatsApp-LocalMind/snapshot` and opens them with `?mode=ro`. Never locks or mutates WhatsApp's live database—**zero ban risk and zero outbound network traffic**.
2. **Physical `@g.us` Group-Only SQL Guard & Blacklist/Whitelist Modes**
   - Every SQL query (`src/wa_localmind/db.py`) and media export check (`src/wa_localmind/media.py`) enforces `ZCONTACTJID LIKE '%@g.us'`, **100% physically blocking 1-on-1 private chats (`@s.whatsapp.net` / `@lid` DMs) and status broadcasts**, with configurable blacklist (default) and whitelist filtering.
3. **4-Tier Real-Name Resolution & `@lid` Cross-Table Bridging**
   - Joins `LID.sqlite` (`ZWAZACCOUNT`), `ZWACHATSESSION` (1-on-1 contact remarks), `ContactsV2.sqlite`, `ZWAGROUPMEMBER`, `ZWAPROFILEPUSHNAME`, and `ZWAMESSAGE.ZPUSHNAME` to resolve senders in priority order: **Contact Remark > Group Nickname > PushName > Last 4 Phone Digits (`用户(xxxx)`)**, while tagging self-sent messages (`ZISFROMME = 1`).
4. **Zero-Dependency Protobuf Wire Parser for 150-Char Reply Chains & `@mentions`**
   - Includes a pure-Python Protobuf wire decoder (`src/wa_localmind/protobuf_parser.py`) to parse `ZWAMEDIAITEM.ZMETADATA`, reconstructing **150-character parent reply chains** (`ZSTANZAID`), whitelisted group-member `@mentions` (avoiding false positives on emails/order IDs), and filtering out revoked messages (`ZMESSAGETYPE = 14`).
5. **Global Monotonic Incremental Cursor (`--after-id`) & Context Buffer**
   - Uses `ZWAMESSAGE.Z_PK` as a monotonic `--after-id` cursor, automatically prepending 10 preceding history messages (`is_context_buffer: true`) for conversational continuity and falling back to a 24-hour window with structured warnings if the cursor goes out of bounds.
6. **Noise Folding & On-Demand Sandboxed Media Export**
   - Preserves image/video captions (`ZWAMEDIAITEM.ZTITLE`), document filenames (`ZAUTHORNAME`), and voice durations (`ZMOVIEDURATION`); folds consecutive short acknowledgment noise (`OK`, `+1`, `收到`) in Markdown output and exports sandboxed `.opus`, `.pdf`, `.xlsx`, and image files on demand via `export-media`.

---

## Quickstart

Requirements: **macOS** + **Python `>= 3.10`** (zero third-party pip dependencies; reading the live WhatsApp container requires granting **Full Disk Access** to your terminal in macOS System Settings).

```bash
git clone https://github.com/qilaidev/whatsapp-localmind.git
cd whatsapp-localmind

# Symlink CLI to ~/.local/bin and optionally install the SKILL.md bundle
./bin/whatsapp-localmind install --bin-dir ~/.local/bin --skill-dir ~/.gemini/config/skills

# Verify environment, TCC Full Disk Access, and database health
whatsapp-localmind doctor --format md
```

---

## MCP Stdio Server Setup & Tool Contracts

Add the following read-only server configuration to any MCP-compatible client (Claude Desktop, Cursor, Google Antigravity, Codex):

```json
{
  "mcpServers": {
    "whatsapp-localmind": {
      "command": "whatsapp-localmind",
      "args": ["mcp-serve"]
    }
  }
}
```

### Exposed Read-Only MCP Tools (4)

| Tool Name | Required Args | Optional Args & Defaults | Description |
| :--- | :--- | :--- | :--- |
| `whatsapp_list_groups` | None | `keyword` (`string`), `include_blocked` (`false`), `format` (`"json"` \| `"markdown"`), `fresh` (`false`) | List accessible `@g.us` group chats, member counts, 24h message counts, and `latest_msg_id` cursors |
| `whatsapp_fetch_messages` | `chat_ids` (`string[]`, group JIDs or `["ALL_ALLOWED"]`) | `after_msg_id` (`int`, `Z_PK`), `since` (`"24h"`), `until` (`string`), `context_buffer` (`10`), `limit_per_chat` (`500`, max `3000`), `fold_noise` (`true`), `format` (`"markdown"` \| `"json"`), `fresh` (`false`) | Fetch cleaned group messages with 4-tier real-name resolution, `@lid` bridging, 150-char reply chains, and revoked-message filtering |
| `whatsapp_search_messages` | `query` (`string`) | `chat_ids` (`string[]`), `since` (`string`), `context` (`3`), `limit` (`50`), `format` (`"markdown"` \| `"json"`) | Search keywords across allowed groups (text & attachment titles) with surrounding context messages |
| `whatsapp_export_media` | `msg_ids` (`int[]`) | None | Export sandboxed group voice notes (`.opus`), images, and documents (`.pdf`/`.xlsx`) by `msg_id` to `snapshot/media` and return absolute paths |

---

## CLI Reference (9 Subcommands)

1. **`doctor`** — Check macOS TCC permissions and CoreData DB health:
   ```bash
   whatsapp-localmind doctor --format md
   ```
2. **`config`** — Set self identity anchor and group blacklist/whitelist rules:
   ```bash
   whatsapp-localmind config set-identity --name "Alex" --phone-suffix "8888"
   whatsapp-localmind config block "120363000000000002@g.us"
   whatsapp-localmind config set-mode --mode whitelist
   whatsapp-localmind config allow "120363000000000001@g.us"
   ```
3. **`groups`** (alias: `list-groups`) — List accessible group chats and cursors:
   ```bash
   whatsapp-localmind groups --format md
   whatsapp-localmind groups --keyword "Logistics" --include-blocked --format json
   ```
4. **`fetch`** — Fetch cleaned messages by time window or monotonic cursor:
   ```bash
   whatsapp-localmind fetch --chats ALL_ALLOWED --since 24h --format md
   whatsapp-localmind fetch --chats ALL_ALLOWED --after-id 1500 --format json | jq .
   ```
5. **`search`** — Search across allowed groups with surrounding context:
   ```bash
   whatsapp-localmind search --query "invoice" --since 30d --context 3 --format md
   ```
6. **`export-media`** — Export group attachments by `msg_id`:
   ```bash
   whatsapp-localmind export-media --msg-ids 128498,128499 --format json
   ```
7. **`clean`** — Clean exported media cache or destroy local SQLite snapshots:
   ```bash
   whatsapp-localmind clean --media-only
   ```
8. **`mcp-serve`** — Start the JSON-RPC 2.0 MCP Stdio Server.
9. **`install`** — Symlink the CLI into `~/.local/bin` and optionally install `SKILL.md`.

---

## Environment Variables & POSIX Exit Codes

### Environment Variables
- `WHATSAPP_LOCALMIND_CONTAINER_DIR`: Override the default WhatsApp Group Container directory path.
- `WHATSAPP_LOCALMIND_SNAPSHOT_DIR`: Override the local snapshot and exported media directory path.

### POSIX Exit Codes
| Code | Constant | Meaning |
| :--- | :--- | :--- |
| `0` | `EXIT_SUCCESS` | Command completed successfully |
| `1` | `EXIT_USAGE_ERROR` | Invalid CLI arguments or time expression |
| `2` | `EXIT_ENV_OR_PERM_ERROR` | WhatsApp DB missing or macOS `Full Disk Access` (TCC) denied |
| `3` | `EXIT_POLICY_DENIED` | Blocked by `@g.us` group-only isolation or blacklist/whitelist policy |
| `4` | `EXIT_RESOURCE_NOT_FOUND` | Target `chat_id`, `msg_id`, or local media file does not exist |
| `5` | `EXIT_INTERNAL_DB_ERROR` | SQLite snapshot backup or read query error |

---

## FAQ

### 1. Is there any risk of my WhatsApp account getting banned?
No. `whatsapp-localmind` carries **zero ban risk**. It makes zero network requests, never touches WhatsApp Web or unofficial protocol endpoints, and never writes to WhatsApp's live database—it only reads an offline `sqlite3_backup` snapshot.

### 2. How are 1-on-1 private chats physically blocked?
Both the SQL engine (`src/wa_localmind/db.py`) and policy/media layers (`src/wa_localmind/config.py`, `src/wa_localmind/media.py`) enforce `ZCONTACTJID LIKE '%@g.us'`. Any attempt to query or export a 1-on-1 `@s.whatsapp.net` or `@lid` DM is rejected immediately with POSIX Exit Code `3` (`POLICY_DENIED`).

### 3. What should I do if `doctor` reports a macOS TCC / Full Disk Access error?
Open **System Settings -> Privacy & Security -> Full Disk Access**, add your terminal application (Terminal, iTerm2, Ghostty, VS Code, or Cursor), and restart the terminal.

### 4. How does `--after-id` recover if the cursor goes out of bounds?
If `after_msg_id` exceeds `global_latest_msg_id` (e.g., after reinstalling WhatsApp), `fetch` automatically falls back to fetching the last 24 hours of group messages and emits a warning in `meta.warnings` so downstream agents can reset their stored cursor.

### 5. When should I use MCP Server vs. CLI?
Use `whatsapp-localmind mcp-serve` when integrating with MCP-native AI hosts (Claude Desktop, Cursor, Antigravity). Use the `whatsapp-localmind` CLI for shell pipelines (`jq`), cron automations, or `SKILL.md`-driven agent workflows.

### 6. Why zero third-party pip dependencies?
Local privacy tools should be minimal, auditable, and immune to supply-chain bloat. Implementing everything—including the Protobuf wire parser and JSON-RPC 2.0 MCP server—using only Python 3.10+ standard library guarantees zero dependency conflicts.

---

## Testing

The test suite includes an in-memory/temporary CoreData fixture generator and synthetic Protobuf payloads, requiring no real WhatsApp installation:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
