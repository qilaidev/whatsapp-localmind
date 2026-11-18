# Security Policy / 安全策略

## Architecture Security Guarantees

`whatsapp-localmind` (`v4.0.0`) is designed from the ground up as a **100% offline, strictly read-only local extraction capability layer** with configurable session scope and policy enforcement:

1. **Zero Network & Zero Account Ban Risk**:
   - The tool makes **zero outbound network connections** and never touches WhatsApp Web, unofficial protocol APIs, or live sockets.
   - It never sends messages, modifies read receipts, or writes to WhatsApp's original CoreData databases (`ChatStorage.sqlite`, `LID.sqlite`, `ContactsV2.sqlite`).

2. **Configurable Session Scope & Blacklist/Whitelist Guard**:
   - While full-account extraction (`chat_scope = "all"`) is enabled by default for 1-on-1 DMs (`@s.whatsapp.net`, `@lid`), groups (`@g.us`), channels (`@newsletter`), and broadcast lists, ephemeral `status@broadcast` feeds are always excluded and rejected (`STATUS_BROADCAST_DENIED`).
   - Users and administrators can restrict access via `config set-scope <all|groups|direct|newsletter>` (or `WHATSAPP_LOCALMIND_CHAT_SCOPE`) and `blacklist`/`whitelist` policies (`src/wa_localmind/config.py`, `src/wa_localmind/db.py`).
   - Policy checks resolve bridged `@lid` ↔ `@s.whatsapp.net` pairs so blocking either identifier blocks the session consistently across queries and media exports (`src/wa_localmind/media.py`), returning POSIX Exit Code `3` (`EXIT_POLICY_DENIED`).

3. **Isolated Local Snapshot, File Permissions & Sandbox Protection**:
   - Live WhatsApp SQLite WAL databases are backed up atomically via Python's `sqlite3.Connection.backup()` (`sqlite3_backup` Online Backup API) protected by POSIX `flock` into `~/Library/Application Support/WhatsApp-LocalMind/snapshot/` with restrictive directory/file permissions (`0o700` / `0o600`).
   - All queries open the isolated snapshot strictly via `?mode=ro` URI mode, and `export-media` enforces sandbox containment inside WhatsApp's `Message/` directory to prevent path traversal (`INVALID_SANDBOX_PATH`).

## Reporting a Vulnerability

If you discover a security or privacy isolation issue (for example, a query path that could bypass `chat_scope` / blacklist-whitelist policy, traverse out of the media sandbox, or write to the source container), please **do not** open a public issue with exploit details against real user data. Instead, report it via [GitHub Security Advisories](https://github.com/qilaidev/whatsapp-localmind/security/advisories) or contact the maintainers directly.
