"""Controlled media attachment export with strict session isolation and path traversal protection."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .config import AppConfig
from .constants import MEDIA_MSG_TYPES, MSG_TYPE_MAP
from .errors import PolicyDeniedError, ResourceNotFoundError, UsageError
from .snapshot import SnapshotState, make_ro_sqlite_uri

UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


def sanitize_filename(name: str) -> str:
    cleaned = UNSAFE_FILENAME_RE.sub("_", name.strip())
    return cleaned.strip("._") or "attachment"


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
        target_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(make_ro_sqlite_uri(self.snapshot.snapshot_db_path), uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        exported_items: list[dict[str, Any]] = []
        try:
            for mid in msg_ids:
                cur.execute(
                    """
                    SELECT
                        m.Z_PK AS msg_id,
                        m.ZMESSAGETYPE AS msg_type,
                        m.ZTEXT AS msg_text,
                        s.ZCONTACTJID AS chat_id,
                        COALESCE(s.ZPARTNERNAME, '未命名群聊') AS group_name,
                        mi.ZMEDIALOCALPATH AS local_rel_path,
                        mi.ZTITLE AS media_title,
                        mi.ZAUTHORNAME AS media_author,
                        mi.ZVCARDSTRING AS mime_type,
                        mi.ZFILESIZE AS file_size,
                        mi.ZMOVIEDURATION AS duration_sec
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

                chat_id = row["chat_id"] or ""
                # Policy enforcement: 100% reject private chats and blocked groups (Exit Code 3)
                self.config.assert_chat_allowed(chat_id)

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

                src_file = (self.wa_message_root / rel_path).resolve()
                # Path traversal protection: ensure src_file is strictly inside wa_message_root
                if not str(src_file).startswith(str(self.wa_message_root) + os.sep):
                    raise PolicyDeniedError(
                        f"Invalid media path outside WhatsApp sandbox for msg_id={mid}.",
                        error_code="INVALID_SANDBOX_PATH",
                    )

                if not src_file.is_file() or src_file.stat().st_size == 0:
                    raise ResourceNotFoundError(
                        f"Media file for msg_id={mid} does not exist on disk at '{src_file}'.",
                        error_code="MEDIA_FILE_MISSING",
                    )

                orig_title = (
                    (row["media_author"] or "").strip()
                    or (row["media_title"] or "").strip()
                    or src_file.name
                )
                # Ensure file extension is preserved
                src_ext = src_file.suffix
                safe_base = sanitize_filename(orig_title)
                if src_ext and not safe_base.lower().endswith(src_ext.lower()):
                    safe_base = f"{safe_base}{src_ext}"

                dst_file = target_dir / f"{mid}_{safe_base}"
                shutil.copy2(src_file, dst_file)

                media_type_str = MEDIA_MSG_TYPES.get(raw_type, MSG_TYPE_MAP.get(raw_type, "media"))
                exported_items.append(
                    {
                        "msg_id": mid,
                        "chat_id": chat_id,
                        "group_name": row["group_name"],
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
