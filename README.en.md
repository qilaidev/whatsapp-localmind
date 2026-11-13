# WhatsApp LocalMind (`whatsapp-localmind`)

**WhatsApp LocalMind (`whatsapp-localmind`)** is a zero-dependency, strictly read-only CLI and JSON-RPC 2.0 MCP Stdio Server that extracts and cleans **macOS WhatsApp group chats (`@g.us`)** for AI Agents such as Claude Desktop, Cursor, and Google Antigravity. Built purely on Python 3.10+ standard library using `sqlite3_backup` + POSIX `flock` offline snapshots opened with `?mode=ro` (across `ChatStorage.sqlite`, `LID.sqlite`, and `ContactsV2.sqlite`), it physically blocks 1-on-1 private DMs (`@s.whatsapp.net` / `@lid`), resolves `@lid` identities, decodes Protobuf reply chains, and sends zero outbound requests.

[![CI](https://github.com/qilaidev/whatsapp-localmind/actions/workflows/ci.yml/badge.svg)](https://github.com/qilaidev/whatsapp-localmind/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero%20Runtime%20Deps-brightgreen.svg)](./pyproject.toml)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-black.svg)](#quickstart)
[![MCP Server](https://img.shields.io/badge/MCP-Stdio%20Read--Only-6E56CF.svg)](#mcp-stdio-server-setup--tool-contracts)
[![Agent CLI](https://img.shields.io/badge/Agent-CLI%20%26%20SKILL.md-orange.svg)](./skills/whatsapp-localmind/SKILL.md)

**[简体中文](./README.md)** | **English** | **[llms.txt](./llms.txt)** | **[codemeta.json](./codemeta.json)** | **[SKILL.md](./skills/whatsapp-localmind/SKILL.md)** | **[SECURITY](./SECURITY.md)** | **[CONTRIBUTING](./CONTRIBUTING.md)** | **[CHANGELOG](./CHANGELOG.md)** | **[LICENSE](./LICENSE)**

> **`*-localmind` Local Instant Messaging Read-Only Extraction Family**
>
> Alongside its sister repository [`wechat-localmind`](https://github.com/qilaidev/wechat-localmind) (macOS & Windows WeChat local group extraction layer), this project belongs to the **`*-localmind` family** and strictly adheres to five shared architectural pillars:
> **100% Offline Read-Only Snapshots + Physical 1-on-1 DM Blocking + 4-Tier Real-Name Resolution + Monotonic Incremental Cursors + Dual CLI & MCP Delivery**.

---

## Entity Snapshot

| Attribute | Specification & Fact |
| :--- | :--- |
| **Identifier** | `whatsapp-localmind` (Python package `wa_localmind`, version `3.2.0`) |
| **License** | [MIT License](./LICENSE) |
| **Runtime & Dependencies** | **macOS** + Python `>= 3.10` (**100% Python standard library only; zero pip dependencies**; reading the live container requires granting terminal **Full Disk Access**) |
| **Local Data Sources** | macOS WhatsApp CoreData Group Containers (`ChatStorage.sqlite`, `LID.sqlite`, `ContactsV2.sqlite`, and `Message/` sandbox media) |
| **Privacy Boundary** | **Group chats (`@g.us`) only**; physically blocks 1-on-1 DMs (`@s.whatsapp.net` / `@lid`) and status broadcasts across SQL & media layers (`EXIT_POLICY_DENIED` = `3`) |
| **Delivery Interfaces** | 9 POSIX CLI subcommands (+ `list-groups` alias) + 4 read-only JSON-RPC 2.0 MCP Stdio tools + `SKILL.md` agent bundle |
| **Default Snapshot Path** | `~/Library/Application Support/WhatsApp-LocalMind/snapshot` (overridable via `WHATSAPP_LOCALMIND_SNAPSHOT_DIR`) |
| **Maintainer** | [`qilaidev`](https://github.com/qilaidev) · [qilai Engineering Studio (`qilaidav.com`)](https://qilaidav.com/en/) |

---

## Positioning: What It Is / What It Is Not

| Dimension | What It Is | What It Is Not |
| :--- | :--- | :--- |
| **Execution** | **100% Offline Read-Only Local Extractor**: Reads macOS WhatsApp CoreData SQLite containers via `sqlite3_backup` + `flock` | **NOT a Protocol Bot or Web Scraper**: Never connects to WhatsApp Web, unofficial APIs, or remote servers |
| **Scope** | **Physical `@g.us` Group-Only Guard**: Enforces group isolation at both the SQL engine and media export layers | **NOT a Full-Account Dumper**: Blocks 1-on-1 DMs (`@s.whatsapp.net` / `@lid`) and broadcasts with blacklist/whitelist modes |
| **Mutation** | **Strictly Read-Only**: Opens isolated snapshots with `?mode=ro`; never writes to or locks live DBs | **NOT a Messaging Client**: Contains zero code to send messages, alter read receipts, or mutate source databases |
| **Delivery** | **AI Agent Native Delivery Layer**: Ships 9 CLI subcommands, 4 read-only MCP tools, and `SKILL.md` | **Zero Third-Party Pip Dependencies**: Requires no external `protobuf`, `mcp`, or C-extension packages |

---

## Use Cases & Alternatives Comparison

### Common Workflows

| Use Case | Recommended Entry / Command | Outcome |
| :--- | :--- | :--- |
| **AI Agent Daily Group Digest & Action Items** | MCP `whatsapp_fetch_messages` or `fetch --chats ALL_ALLOWED --since 24h` | Resolves `@lid` identities, 150-char reply chains, and folds consecutive ack noise |
| **Idempotent Incremental Message Sync** | `fetch --chats ALL_ALLOWED --after-id <msg_id> --format json` | Advances monotonically via `ZWAMESSAGE.Z_PK` with 10-message context buffer and 24h fallback |
| **Cross-Group Quote, Invoice & Doc Search** | `search --query "invoice" --context 3` or MCP `whatsapp_search_messages` | Searches message text, media captions (`ZTITLE`), and filenames (`ZAUTHORNAME`) with context |
| **Controlled Sandboxed Media Export** | `export-media --msg-ids 128498 --format json` or MCP `whatsapp_export_media` | Safely copies `.opus`, `.pdf`, `.xlsx`, and images to `snapshot/media/` and returns local paths |

### Architectural Comparison

> Honest architectural comparison across approaches — no fabricated benchmarks or telemetry claims.

| Capability / Boundary | **WhatsApp LocalMind** | Raw `sqlite3` CLI Queries | Unofficial Web Bots (Baileys / `whatsapp-web.js`) | Official WhatsApp Business Cloud API |
| :--- | :---: | :---: | :---: | :---: |
| **Account Ban & ToS Risk** | Zero (100% offline snapshot, zero network traffic) | Zero (offline read) | High/moderate risk (unofficial WebSocket / headless session) | Compliant, requires Meta Business verification & cloud routing |
| **Data Residency & Offline Mode** | 100% local on your Mac | Local read | Requires live remote socket/browser connection | Routes messages through Meta cloud servers |
| **Live DB WAL Concurrency Safety** | `sqlite3_backup` + `flock` merges `-wal`, reads via `?mode=ro` | Risk of lock contention or missing uncommitted WAL pages | N/A | N/A |
| **Physical 1-on-1 DM Blocking** | Enforced in SQL & media layers (`EXIT_POLICY_DENIED = 3`) | Manual SQL filter every query (error-prone) | Unbounded event stream includes all DMs | Business ticket model |
| **`@lid` Bridging & Protobuf Reply Chains** | Joins `LID.sqlite` + `ContactsV2.sqlite` + pure-Python Protobuf parser | Must join multiple DBs and decode binary `ZMETADATA` manually | Protocol event payloads | JSON webhook payloads |
| **AI Agent Delivery (MCP + Cursor)** | 4 read-only MCP tools + 9 CLI commands + `SKILL.md` | Raw table rows only | Requires custom wrapper & storage | Requires custom webhook server |
| **Sending Messages / Automation** | None (strictly read-only by design) | None | Yes | Yes |

---

## Legal & Privacy Compliance Notice

- **Intended Use**: Strictly designed for **personal local group chat backup and authorized offline research on your own macOS machine**. Users are responsible for complying with applicable laws and participant privacy expectations.
- **100% Offline Read-Only Snapshot**: Uses SQLite Online Backup (`sqlite3.Connection.backup`) with POSIX `flock` to copy `ChatStorage.sqlite`, `LID.sqlite`, and `ContactsV2.sqlite` into `~/Library/Application Support/WhatsApp-LocalMind/snapshot` (overridable via `WHATSAPP_LOCALMIND_SNAPSHOT_DIR`) and opens snapshots with `?mode=ro`. Zero network calls, zero client injection, zero write-backs.
- **Physical `@g.us` Guard**: Both SQL queries (`src/wa_localmind/db.py`) and media exports (`src/wa_localmind/media.py`) enforce `ZCONTACTJID LIKE '%@g.us'`, rejecting 1-on-1 DMs (`@s.whatsapp.net` / `@lid`) and status broadcasts with `EXIT_POLICY_DENIED` (`3`).

---

## Six Architectural Pillars

1. **SQLite Online Backup Snapshots & POSIX `flock` (100% Offline Read-Only)**
   - Uses `sqlite3_backup` (`sqlite3.Connection.backup`) with POSIX `flock` concurrency locking to materialize WAL-merged single-file snapshots inside `~/Library/Application Support/WhatsApp-LocalMind/snapshot` and opens them with `?mode=ro`. Never locks or mutates WhatsApp's live database—**zero ban risk and zero outbound network traffic**.
2. **Physical `@g.us` Group-Only SQL Guard & Blacklist/Whitelist Modes**
   - Every SQL query (`src/wa_localmind/db.py`) and media export check (`src/wa_localmind/media.py`) enforces `ZCONTACTJID LIKE '%@g.us'`, **100% physically blocking 1-on-1 private chats (`@s.whatsapp.net` / `@lid` DMs) and status broadcasts**, with configurable blacklist (default) and whitelist filtering.
3. **4-Tier Real-Name Resolution & `@lid` Cross-Table Bridging**
   - Joins `LID.sqlite` (`ZWAZACCOUNT`), `ZWACHATSESSION` (1-on-1 contact remarks), `ContactsV2.sqlite`, `ZWAGROUPMEMBER`, `ZWAPROFILEPUSHNAME`, and `ZWAMESSAGE.ZPUSHNAME` to resolve senders in priority order: **Contact Remark > Group Nickname > PushName > Last 4 Phone Digits (`用户(xxxx)`)**, while tagging self-sent messages (`ZISFROMME = 1`).
4. **Zero-Dependency Protobuf Wire Parser for 150-Char Reply Chains & `@mentions`**
   - Includes a pure-Python Protobuf wire decoder (`src/wa_localmind/protobuf_parser.py`) to parse `ZWAMEDIAITEM.ZMETADATA`, reconstructing **150-character parent reply chains** (`ZSTANZAID`), whitelisted group-member `@mentions` (avoiding false positives on emails/order IDs), and filtering out revoked messages (`ZMESSAGETYPE = 14`) and system/protocol stubs (`6, 10, 12, 14, 46, 66`).
5. **Global Monotonic Incremental Cursor (`--after-id`) & Context Buffer**
   - Uses `ZWAMESSAGE.Z_PK` as a monotonic `--after-id` cursor, automatically prepending 10 preceding history messages (`is_context_buffer: true`) for conversational continuity and falling back to a 24-hour window with `CURSOR_RESET_FALLBACK` warnings if the cursor goes out of bounds.
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
2. **`config`** — Set self identity anchor and group blacklist/whitelist rules (`show` / `set-identity` / `set-mode` / `block` / `unblock` / `allow` / `disallow`):
   ```bash
   whatsapp-localmind config set-identity --name "Alex" --phone-suffix "8888"
   whatsapp-localmind config block "120363000000000002@g.us"
   whatsapp-localmind config set-mode whitelist
   whatsapp-localmind config allow "120363000000000001@g.us"
   ```
3. **`groups`** (alias: `list-groups`) — List accessible group chats and cursors:
   ```bash
   whatsapp-localmind groups --format md
   whatsapp-localmind groups --keyword "Logistics" --include-blocked --format json
   ```
4. **`fetch`** — Fetch cleaned messages by time window or monotonic cursor (`--limit`, `--fold`/`--no-fold`, `-o`, `--fresh`):
   ```bash
   whatsapp-localmind fetch --chats ALL_ALLOWED --since 24h --format md
   whatsapp-localmind fetch --chats ALL_ALLOWED --after-id 1500 --limit 200 --format json | jq .
   ```
5. **`search`** — Search across allowed groups with surrounding context:
   ```bash
   whatsapp-localmind search --query "invoice" --since 30d --context 3 --format md
   ```
6. **`export-media`** — Export group attachments by `msg_id`:
   ```bash
   whatsapp-localmind export-media --msg-ids 128498,128499 --format json
   ```
7. **`clean`** — Clean exported media cache (`--media-only`) or destroy local SQLite snapshots (`--all`):
   ```bash
   whatsapp-localmind clean --media-only
   ```
8. **`mcp-serve`** — Start the JSON-RPC 2.0 MCP Stdio Server:
   ```bash
   whatsapp-localmind mcp-serve
   ```
9. **`install`** — Symlink the CLI into `~/.local/bin` and optionally install `SKILL.md`:
   ```bash
   ./bin/whatsapp-localmind install --bin-dir ~/.local/bin --skill-dir ~/.gemini/config/skills
   ```

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

<details>
<summary><strong>1. Is there any risk of my WhatsApp account getting banned?</strong></summary>

**No — zero ban risk.** `whatsapp-localmind` makes zero network requests, never touches WhatsApp Web or unofficial protocol endpoints, and never writes to WhatsApp's live database; it only reads an offline `sqlite3_backup` snapshot.

</details>

<details>
<summary><strong>2. How are 1-on-1 private chats physically blocked?</strong></summary>

Both the SQL engine (`src/wa_localmind/db.py`) and policy/media layers (`src/wa_localmind/config.py`, `src/wa_localmind/media.py`) enforce `ZCONTACTJID LIKE '%@g.us'`. Any attempt to query or export a 1-on-1 `@s.whatsapp.net` or `@lid` DM is rejected immediately with POSIX Exit Code `3` (`EXIT_POLICY_DENIED`).

</details>

<details>
<summary><strong>3. What should I do if <code>doctor</code> reports a macOS TCC / Full Disk Access error?</strong></summary>

Open **System Settings -> Privacy & Security -> Full Disk Access**, add your terminal or MCP host application (Terminal, iTerm2, Ghostty, VS Code, or Cursor), and restart it.

</details>

<details>
<summary><strong>4. How does <code>--after-id</code> recover if the cursor goes out of bounds?</strong></summary>

If `after_msg_id` exceeds `global_latest_msg_id` (e.g., after reinstalling WhatsApp), `fetch` automatically falls back to fetching the last 24 hours of group messages (`query_mode: "cursor_reset_fallback_24h"`) and emits a `CURSOR_RESET_FALLBACK` warning in `meta.warnings` so downstream agents can reset their stored cursor.

</details>

<details>
<summary><strong>5. When should I use MCP Server vs. CLI?</strong></summary>

Use `whatsapp-localmind mcp-serve` when integrating with MCP-native AI hosts (Claude Desktop, Cursor, Google Antigravity). Use the `whatsapp-localmind` CLI for shell pipelines (`jq`), cron automations, or `SKILL.md`-driven agent workflows.

</details>

<details>
<summary><strong>6. Why zero third-party pip dependencies?</strong></summary>

Local privacy tools should be minimal, auditable, and immune to supply-chain bloat. Implementing everything—including the Protobuf wire parser and JSON-RPC 2.0 MCP server—using only Python 3.10+ standard library guarantees zero dependency conflicts.

</details>

<details>
<summary><strong>7. How are anonymous <code>@lid</code> members resolved to readable names?</strong></summary>

`QueryEngine` cross-references `LID.sqlite` (`ZWAZACCOUNT`), `ZWACHATSESSION`, `ContactsV2.sqlite` (`ZWAADDRESSBOOKCONTACT`), `ZWAGROUPMEMBER`, and `ZWAPROFILEPUSHNAME` to bridge `@lid` IDs to phone JIDs and resolve names in 4-tier priority (`Contact Remark > Group Nickname > PushName > Last 4 Digits`).

</details>

<details>
<summary><strong>8. Is it safe to run while WhatsApp Desktop is open and writing WAL logs?</strong></summary>

**Yes — zero lock contention and zero missed WAL pages.** Snapshots are taken atomically via `sqlite3.Connection.backup()` (`sqlite3_backup` Online Backup API) under POSIX `flock`, merging uncommitted `-wal` data into an isolated file opened strictly with `?mode=ro`.

</details>

<details>
<summary><strong>9. How do I purge local snapshots and exported media files?</strong></summary>

Run `whatsapp-localmind clean --all` to remove both the exported media cache and local SQLite snapshots (`ChatStorage_snapshot.sqlite`, `ContactsV2_snapshot.sqlite`, `LID_snapshot.sqlite`), or run `whatsapp-localmind clean --media-only` to clear only exported files.

</details>

---

## Testing & Repository Layout

The test suite includes an in-memory/temporary CoreData fixture generator and synthetic Protobuf payloads, requiring no real WhatsApp installation:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

```text
whatsapp-localmind/
├── README.md                        # Chinese Documentation
├── README.en.md                     # English Documentation
├── llms.txt                         # llmstxt.org AI index & schema contract
├── codemeta.json                    # CodeMeta 2.0 structured software metadata
├── LICENSE                          # MIT License
├── SECURITY.md                      # Offline read-only & @g.us isolation policy
├── CONTRIBUTING.md                  # Contributing & test guidelines
├── CHANGELOG.md                     # Release changelog
├── pyproject.toml                   # Python package metadata (>=3.10, zero runtime deps)
├── bin/
│   └── whatsapp-localmind           # CLI entrypoint
├── skills/
│   └── whatsapp-localmind/          # AI Agent SKILL.md bundle
├── src/
│   └── wa_localmind/                # Core snapshot, CoreData query & MCP server modules
└── tests/
    └── test_wa_localmind.py         # CoreData snapshot, DM guard, @lid & MCP test suite
```

---

<details>
<summary><strong>Search Intent & Query Mapping</strong></summary>

| User Intent / Problem | Common Queries (EN & ZH) | Relevant Capability & Section |
| :--- | :--- | :--- |
| Connect Claude / Cursor to macOS WhatsApp groups | `whatsapp mcp server macos` · `AI Agent 读取 WhatsApp 群聊` | `mcp-serve` & 4 read-only tools ([MCP Setup](#mcp-stdio-server-setup--tool-contracts)) |
| Safely snapshot live WhatsApp `ChatStorage.sqlite` WAL | `sqlite3_backup whatsapp wal read-only` · `ChatStorage.sqlite 只读快照` | `sqlite3_backup` + `flock` + `?mode=ro` ([Six Architectural Pillars](#six-architectural-pillars)) |
| Block 1-on-1 DMs while allowing `@g.us` groups | `read-only whatsapp group exporter` · `禁止读取私聊 WhatsApp 工具` | `@g.us` physical guard, exit code `3` ([Compliance Notice](#legal--privacy-compliance-notice)) |
| Resolve WhatsApp `@lid` senders & Protobuf quotes | `whatsapp lid.sqlite contacts resolution` · `WhatsApp @lid 实名映射` | `LID.sqlite` bridging + Protobuf parser ([Six Architectural Pillars](#six-architectural-pillars)) |
| Fix macOS TCC / Full Disk Access errors | `Full Disk Access WhatsApp CLI` · `whatsapp-localmind doctor` | `doctor` diagnostics & TCC instructions ([FAQ](#faq)) |

</details>

<sub>**Keywords**: whatsapp-localmind · macOS WhatsApp CoreData · ChatStorage.sqlite · LID.sqlite · ContactsV2.sqlite · sqlite3_backup WAL snapshot · `@g.us` group-only isolation · Protobuf `ZMETADATA` · MCP Stdio Server · zero-dependency Python CLI · local-first privacy · WhatsApp 群聊提取 · WhatsApp MCP 服务器</sub>

---

## Architecture & Ecosystem · qilai (`qilaidav.com`)

This open-source project is engineered and maintained by **[qilai · qilaidav](https://qilaidav.com/en/)** — an independent systems engineering studio focused on **Deterministic Systems Engineering & High-Signal Technical Diagnostics**.

- **Related System / Pillar**: [Telegram Channel Ops & Persona Engine (OASH)](https://qilaidav.com/en/oash/) · [中文主站](https://qilaidav.com/oash/)
- **Sister Repository (`*-localmind`)**: [`wechat-localmind`](https://github.com/qilaidev/wechat-localmind)
- **Studio Website**: [https://qilaidav.com/en/](https://qilaidav.com/en/) ([ZH](https://qilaidav.com))
- **Technical Notes & Field Reports**: [https://qilaidav.com/notes/](https://qilaidav.com/notes/)
- **Direct Engineering Contact**: [Telegram @BD8888](https://t.me/BD8888) · [Public Channel @AIKB8](https://t.me/AIKB8) · `hello@qilaidav.com`
