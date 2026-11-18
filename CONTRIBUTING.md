# Contributing to WhatsApp LocalMind

Thank you for your interest in contributing to `whatsapp-localmind`!

## Core Design Principles

Before submitting a pull request, please keep these architectural invariants in mind:

1. **Zero Third-Party Runtime Dependencies**: Everything in `src/wa_localmind/` must run on Python 3.10+ standard library only (`sqlite3`, `json`, `fcntl`, `argparse`, etc.).
2. **100% Offline Read-Only**: Never add network requests, WhatsApp protocol automation, or write operations to WhatsApp's live container directory. All snapshot reads must open via `?mode=ro`.
3. **Policy & Sandbox Integrity**: Every query and media export path (`src/wa_localmind/db.py`, `src/wa_localmind/media.py`, `src/wa_localmind/config.py`) must enforce `chat_scope`, `blacklist`/`whitelist` rules (including bridged `@lid` ↔ `@s.whatsapp.net` pairs), exclude `status@broadcast`, and prevent media sandbox path traversal.

## Development & Testing

The test suite uses in-memory/temporary CoreData fixtures and synthetic Protobuf payloads—no real WhatsApp installation is required.

```bash
git clone https://github.com/qilaidev/whatsapp-localmind.git
cd whatsapp-localmind
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Verify the CLI entrypoints:

```bash
./bin/whatsapp-localmind --help
./skills/whatsapp-localmind/scripts/whatsapp-localmind --help
```

## Pull Request Checklist

- Ensure all existing unit tests pass (`PYTHONPATH=src python3 -m unittest discover -s tests -v`).
- Add unit tests in `tests/test_wa_localmind.py` for new features or bug fixes.
- Do not include real phone numbers, JIDs, personal names, or local machine paths in tests or documentation.
- Keep documentation (`README.md`, `README.en.md`, `llms.txt`, `codemeta.json`, `skills/whatsapp-localmind/SKILL.md`) in sync if CLI flags or MCP tool schemas change.
