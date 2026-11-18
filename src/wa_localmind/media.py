"""Controlled media attachment export with policy enforcement and sandbox path traversal protection."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .cleaner import clean_unicode_display_name
from .config import AppConfig, classify_wa_jid
from .constants import MEDIA_MSG_TYPES, MSG_TYPE_MAP
from .errors import PolicyDeniedError, ResourceNotFoundError, UsageError
from .snapshot import SnapshotState, make_ro_sqlite_uri

UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


def sanitize_filename(name: str) -> str:
    cleaned = UNSAFE_FILENAME_RE.sub("_", name.strip())
    return cleaned.strip("._") or "attachment"


def resolve_safe_wa_sandbox_path(rel_path: str, wa_message_root: Path) -> tuple[Path | None, bool]:
    """Safely resolve a relative media path strictly inside `wa_message_root`."""
    if not rel_path or "\x00" in rel_path:
        return None, False
    norm_rel = rel_path.replace("\\", "/").strip().lstrip("/")
    if not norm_rel or ":" in norm_rel.split("/")[0]:
        return None, False

    root_resolved = wa_message_root.resolve()
    cand = (root_resolved / norm_rel).resolve()
    if cand == root_resolved or not cand.is_relative_to(root_resolved):
        return None, False
    try:
        if cand.is_file() and cand.stat().st_size > 0:
            return cand, True
    except OSError:
        return None, True
    return None, True


class MediaExporter:
    """Safely exports media files from the WhatsApp sandbox after verifying session policy."""

    def __init__(self, config: AppConfig, snapshot: SnapshotState) -> None:
        self.config = config
        self.snapshot = snapshot
        self.wa_message_root = (
            Path(os.path.expanduser(config.wa_container_dir)) / "Message"
        ).resolve()
        self.default_export_dir = (
            Path(os.path.expanduser(config.snapshot_dir)) / "media"
        )

    def export_media_by_msg_ids(
        self,
        msg_ids: list[int],
        dest_dir: Path | None = None,
    ) -> dict[str, Any]:
        if not msg_ids:
            raise UsageError("At least one message ID must be provided via --msg-ids.")

        target_dir = (dest_dir or self.default_export_dir).expanduser().resolve()
        target_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

        conn = sqlite3.connect(make_ro_sqlite_uri(self.snapshot.snapshot_db_path), uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(ZWAMEDIAITEM)")
        mi_cols = {r[1] for r in cur.fetchall()}
        dur_col = "mi.ZMOVIEDURATION" if "ZMOVIEDURATION" in mi_cols else ("mi.ZDURATION" if "ZDURATION" in mi_cols else "0")

        cur.execute("PRAGMA table_info(ZWACHATSESSION)")
        cs_cols = {r[1] for r in cur.fetchall()}
        ident_col = "s.ZCONTACTIDENTIFIER" if "ZCONTACTIDENTIFIER" in cs_cols else "NULL"

        exported_items: list[dict[str, Any]] = []
        try:
            for mid in msg_ids:
                cur.execute(
                    f"""
                    SELECT
                        m.Z_PK AS msg_id,
                        m.ZMESSAGETYPE AS msg_type,
                        m.ZTEXT AS msg_text,
                        s.ZCONTACTJID AS chat_id,
                        {ident_col} AS contact_ident,
                        s.ZPARTNERNAME AS partner_name,
                        mi.ZMEDIALOCALPATH AS local_rel_path,
                        mi.ZTITLE AS media_title,
                        mi.ZAUTHORNAME AS media_author,
                        mi.ZVCARDSTRING AS mime_type,
                        mi.ZFILESIZE AS file_size,
                        {dur_col} AS duration_sec
                    FROM ZWAMESSAGE m
                    JOIN ZWACHATSESSION s ON m.ZCHATSESSION = s.Z_PK
                    LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                    WHERE m.Z_PK = ?
                    """,
                    (mid,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ResourceNotFoundError(
                        f"Message msg_id={mid} does not exist in local database.",
                        error_code="MESSAGE_NOT_FOUND",
                    )

                chat_id = (row["chat_id"] or "").strip()
                alt_jid = (row["contact_ident"] or "").strip() or None
                self.config.assert_chat_allowed(chat_id, bridged_alt_jid=alt_jid)

                raw_type = int(row["msg_type"] or 0)
                if raw_type == 14:
                    raise PolicyDeniedError(
                        f"Message msg_id={mid} has been revoked and cannot be exported.",
                        error_code="REVOKED_MESSAGE_DENIED",
                    )

                rel_path = (row["local_rel_path"] or "").strip()
                if not rel_path:
                    raise ResourceNotFoundError(
                        f"Message msg_id={mid} has no downloaded local media path (local_available=false).",
                        error_code="MEDIA_NOT_DOWNLOADED",
                    )

                src_file, within_sandbox = resolve_safe_wa_sandbox_path(rel_path, self.wa_message_root)
                if not within_sandbox:
                    raise PolicyDeniedError(
                        f"Invalid media path outside WhatsApp sandbox for msg_id={mid}.",
                        error_code="INVALID_SANDBOX_PATH",
                    )
                if src_file is None:
                    raise ResourceNotFoundError(
                        f"Media file for msg_id={mid} does not exist on disk ('{rel_path}').",
                        error_code="MEDIA_FILE_MISSING",
                    )

                orig_title = (
                    (row["media_author"] or "").strip()
                    or (row["media_title"] or "").strip()
                    or src_file.name
                )
                src_ext = src_file.suffix
                safe_base = sanitize_filename(orig_title)
                if src_ext and not safe_base.lower().endswith(src_ext.lower()):
                    safe_base = f"{safe_base}{src_ext}"

                dst_file = target_dir / f"{mid}_{safe_base}"
                shutil.copy2(src_file, dst_file)
                try:
                    os.chmod(dst_file, 0o600)
                except OSError:
                    pass

                chat_type = classify_wa_jid(chat_id)
                default_label = "未命名群聊" if chat_type == "group" else "未命名会话"
                chat_name = clean_unicode_display_name(row["partner_name"]) or chat_id or default_label
                media_type_str = MEDIA_MSG_TYPES.get(raw_type, MSG_TYPE_MAP.get(raw_type, "media"))
                exported_items.append(
                    {
                        "msg_id": mid,
                        "chat_id": chat_id,
                        "chat_name": chat_name,
                        "group_name": chat_name,
                        "chat_type": chat_type,
                        "media_type": media_type_str,
                        "mime_type": row["mime_type"] or None,
                        "original_title": orig_title,
                        "exported_path": str(dst_file),
                        "file_size_bytes": dst_file.stat().st_size,
                        "duration_sec": int(row["duration_sec"]) if row["duration_sec"] else None,
                    }
                )
        finally:
            conn.close()

        return {
            "meta": {
                "snapshot_time": self.snapshot.snapshot_time_iso,
                "export_dir": str(target_dir),
                "exported_count": len(exported_items),
            },
            "exported": exported_items,
        }
