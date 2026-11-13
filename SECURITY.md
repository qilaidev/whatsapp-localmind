# Security Policy / 安全策略

## Architecture Security Guarantees

`whatsapp-localmind` is designed from the ground up as a **100% offline, read-only, group-only local extraction capability layer**:

1. **Zero Network & Zero Account Ban Risk**:
   - The tool makes **zero outbound network connections** and never touches WhatsApp Web, unofficial protocol APIs, or live sockets.
   - It never sends messages, modifies read receipts, or writes to WhatsApp's original CoreData databases (`ChatStorage.sqlite`, `LID.sqlite`, `ContactsV2.sqlite`).

2. **Physical `@g.us` Group-Only SQL & Media Guard**:
   - All SQL queries enforce `ZCONTACTJID LIKE '%@g.us'` at the database engine layer (`src/wa_localmind/db.py`).
   - Configuration policy (`src/wa_localmind/config.py`) and CLI/MCP argument validators physically reject 1-on-1 private chats (`@s.whatsapp.net`, `@lid` DMs) and status broadcasts with POSIX Exit Code `3` (`POLICY_DENIED`).
   - Media export (`src/wa_localmind/media.py`) verifies the parent session is an allowed `@g.us` group before copying any sandboxed attachment.

3. **Isolated Local Snapshot & Concurrency Locking**:
   - Live WhatsApp SQLite WAL databases are backed up atomically via Python's `sqlite3.Connection.backup()` (`sqlite3_backup` Online Backup API) protected by POSIX `flock` into `~/Library/Application Support/WhatsApp-LocalMind/snapshot/`.
   - All queries open the isolated snapshot using `?mode=ro` read-only URI mode.

## Reporting a Vulnerability

If you discover a security or privacy isolation issue (for example, a query path that could leak non-`@g.us` sessions or write to the source container), please **do not** open a public issue with exploit details against real user data. Instead, report it via [GitHub Security Advisories](https://github.com/qilaidev/whatsapp-localmind/security/advisories) or contact the maintainers directly.
