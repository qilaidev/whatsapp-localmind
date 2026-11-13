"""Read-only SQLite query engine, universal @lid/phone name resolver, and message pipeline."""

from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .cleaner import (
    clean_unicode_display_name,
    disambiguate_punctuation_name,
    format_fallback_sender_name,
    is_short_ack_noise,
    replace_mentions_with_whitelist,
    strip_jid_Namespace,
    truncate_reply_snippet,
)
from .config import AppConfig
from .constants import (
    APPLE_EPOCH_OFFSET,
    DEFAULT_FETCH_LIMIT,
    EXCLUDED_MSG_TYPES,
    MAX_FETCH_LIMIT,
    MEDIA_MSG_TYPES,
    MSG_TYPE_MAP,
    SYNC_LAG_WARNING_SEC,
)
from .errors import ResourceNotFoundError, UsageError
from .protobuf_parser import (
    decode_groupmember_firstname_proto,
    is_base64_protocol_token,
    parse_message_metadata_blob,
)
from .snapshot import SnapshotState, epoch_to_local_iso, make_ro_sqlite_uri

DURATION_RE = re.compile(r"^(\d+)\s*([smhdw])$", re.IGNORECASE)
SELF_PARTNER_LABELS = frozenset({"你", "You", "Yourself", "Tú", "Vous", "Du"})


def parse_since_to_epoch(since_str: str | None, now_epoch: float | None = None) -> float | None:
    """Parse relative duration ('30m', '12h', '7d') or ISO-8601 timestamp into Unix epoch seconds."""
    if not since_str:
        return None
    raw = since_str.strip()
    now = now_epoch if now_epoch is not None else time.time()

    m = DURATION_RE.match(raw)
    if m:
        val = int(m.group(1))
        unit = m.group(2).lower()
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        return now - (val * multipliers[unit])

    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt.timestamp()
    except ValueError as exc:
        raise UsageError(
            f"Invalid time format '{since_str}'. Expected relative duration (e.g. '12h', '7d') "
            "or ISO-8601 timestamp (e.g. '2026-11-07T09:00:00')."
        ) from exc


class QueryEngine:
    """Executes read-only queries against the atomic SQLite snapshot with dynamic schema adaptation."""

    def __init__(self, config: AppConfig, snapshot: SnapshotState) -> None:
        self.config = config
        self.snapshot = snapshot
        self.wa_message_dir = Path(os.path.expanduser(config.wa_container_dir)) / "Message"
        self._conn: sqlite3.Connection | None = None
        self._table_cols_cache: dict[str, set[str]] = {}
        self._jid_name_map: dict[str, str] | None = None
        self._jid_prefix_map: dict[str, str] | None = None
        self._lid_to_phone_jid: dict[str, str] = {}
        self._auto_self_prefixes: set[str] = set()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            uri = make_ro_sqlite_uri(self.snapshot.snapshot_db_path)
            self._conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _get_table_columns(self, table_name: str) -> set[str]:
        if table_name not in self._table_cols_cache:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(f"PRAGMA table_info({table_name})")
            self._table_cols_cache[table_name] = {row[1] for row in cur.fetchall()}
        return self._table_cols_cache[table_name]

    def _media_duration_expr(self, alias: str = "mi") -> str:
        cols = self._get_table_columns("ZWAMEDIAITEM")
        if "ZMOVIEDURATION" in cols:
            return f"{alias}.ZMOVIEDURATION AS ZMOVIEDURATION"
        if "ZDURATION" in cols:
            return f"{alias}.ZDURATION AS ZMOVIEDURATION"
        return "0 AS ZMOVIEDURATION"

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> QueryEngine:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def build_common_warnings(self) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        if self.snapshot.db_latest_msg_epoch is not None:
            lag_sec = int(round(time.time() - self.snapshot.db_latest_msg_epoch))
            if lag_sec > SYNC_LAG_WARNING_SEC:
                hours = round(lag_sec / 3600.0, 1)
                warnings.append(
                    {
                        "code": "CLIENT_SYNC_LAG",
                        "lag_seconds": lag_sec,
                        "message": f"WhatsApp 客户端数据库已超过 {hours} 小时未收到新消息，请确认客户端是否在线同步。",
                    }
                )
        return warnings

    def _ensure_name_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        """Build universal JID/LID <-> real-name dictionary across ChatStorage, LID.sqlite, and ContactsV2.sqlite."""
        if self._jid_name_map is not None and self._jid_prefix_map is not None:
            return self._jid_name_map, self._jid_prefix_map

        conn = self._get_conn()
        cur = conn.cursor()

        lid_to_phone: dict[str, str] = {}
        phone_to_lid: dict[str, str] = {}
        tier1_remark: dict[str, str] = {}
        tier2_pushname: dict[str, str] = {}
        tier3_member: dict[str, str] = {}
        auto_self: set[str] = set()

        # 0. Load @lid <-> @s.whatsapp.net bridging from LID_snapshot.sqlite (ZWAZACCOUNT)
        if self.snapshot.lid_db_path and self.snapshot.lid_db_path.exists():
            try:
                l_conn = sqlite3.connect(make_ro_sqlite_uri(self.snapshot.lid_db_path), uri=True)
                l_conn.row_factory = sqlite3.Row
                l_cur = l_conn.cursor()
                l_cur.execute(
                    "SELECT ZIDENTIFIER, ZPHONENUMBER, ZUSERNAME, ZDISPLAYNAME FROM ZWAZACCOUNT"
                )
                for row in l_cur.fetchall():
                    ident = (row["ZIDENTIFIER"] or "").strip()
                    phone = (row["ZPHONENUMBER"] or "").strip()
                    if ident and not ident.endswith("@lid") and "@" not in ident:
                        ident = f"{ident}@lid"
                    if phone:
                        phone_jid = phone if "@" in phone else f"{phone}@s.whatsapp.net"
                        if ident:
                            lid_to_phone[ident] = phone_jid
                            phone_to_lid[phone_jid] = ident
                    dname = clean_unicode_display_name(row["ZDISPLAYNAME"] or row["ZUSERNAME"])
                    if dname and ident:
                        tier3_member[ident] = dname
                l_conn.close()
            except Exception:
                pass

        # 0b. Also bridge @lid <-> @s.whatsapp.net from ZWACHATSESSION (ZCONTACTJID <-> ZCONTACTIDENTIFIER)
        cs_cols = self._get_table_columns("ZWACHATSESSION")
        has_contact_ident = "ZCONTACTIDENTIFIER" in cs_cols
        cs_select = (
            "SELECT ZCONTACTJID AS jid, ZCONTACTIDENTIFIER AS ident, ZPARTNERNAME AS pname FROM ZWACHATSESSION"
            if has_contact_ident
            else "SELECT ZCONTACTJID AS jid, NULL AS ident, ZPARTNERNAME AS pname FROM ZWACHATSESSION"
        )
        cur.execute(f"{cs_select} WHERE ZCONTACTJID IS NOT NULL AND ZCONTACTJID NOT LIKE '%@g.us'")
        for row in cur.fetchall():
            jid = row["jid"].strip()
            ident = (row["ident"] or "").strip()
            pname = clean_unicode_display_name(row["pname"])
            if jid.endswith("@lid") and ident.endswith("@s.whatsapp.net"):
                lid_to_phone[jid] = ident
                phone_to_lid[ident] = jid

            # Auto-detect self session ("你" / "You")
            if pname in SELF_PARTNER_LABELS:
                for self_jid in (jid, ident):
                    p = strip_jid_Namespace(self_jid)
                    if p:
                        auto_self.add(p)
                continue

            if pname and not pname.startswith("+") and pname.lower() != "whatsapp":
                tier1_remark[jid] = pname
                if ident:
                    tier1_remark[ident] = pname

        # 1. Load Address Book remarks from ContactsV2_snapshot.sqlite if available
        if self.snapshot.contacts_db_path and self.snapshot.contacts_db_path.exists():
            try:
                c_conn = sqlite3.connect(make_ro_sqlite_uri(self.snapshot.contacts_db_path), uri=True)
                c_conn.row_factory = sqlite3.Row
                c_cur = c_conn.cursor()
                c_cur.execute(
                    "SELECT ZLID, ZWHATSAPPID, ZFULLNAME, ZBUSINESSNAME FROM ZWAADDRESSBOOKCONTACT"
                )
                for row in c_cur.fetchall():
                    cname = clean_unicode_display_name(row["ZFULLNAME"] or row["ZBUSINESSNAME"])
                    lid = (row["ZLID"] or "").strip()
                    waid = (row["ZWHATSAPPID"] or "").strip()
                    if lid and not lid.endswith("@lid"):
                        lid = f"{lid}@lid"
                    if waid and not waid.endswith("@s.whatsapp.net"):
                        waid = f"{waid}@s.whatsapp.net"
                    if lid and waid:
                        lid_to_phone[lid] = waid
                        phone_to_lid[waid] = lid
                    if cname and not cname.startswith("+"):
                        if lid:
                            tier1_remark[lid] = cname
                        if waid:
                            tier1_remark[waid] = cname
                c_conn.close()
            except Exception:
                pass

        # 2. Load WhatsApp PushNames from ZWAPROFILEPUSHNAME
        cur.execute(
            """
            SELECT ZJID AS jid, ZPUSHNAME AS pushname
            FROM ZWAPROFILEPUSHNAME
            WHERE ZJID IS NOT NULL AND ZPUSHNAME IS NOT NULL AND TRIM(ZPUSHNAME) != ''
            """
        )
        for row in cur.fetchall():
            jid = row["jid"].strip()
            pname = clean_unicode_display_name(row["pushname"])
            if pname and not is_base64_protocol_token(pname):
                tier2_pushname[jid] = pname

        # 3a. Load ZWAGROUPMEMBER ZCONTACTNAME and decoded ZFIRSTNAME protobuf
        cur.execute(
            """
            SELECT ZMEMBERJID AS jid, ZCONTACTNAME AS cname, ZFIRSTNAME AS fname
            FROM ZWAGROUPMEMBER
            WHERE ZMEMBERJID IS NOT NULL
            """
        )
        for row in cur.fetchall():
            jid = row["jid"].strip()
            cname = clean_unicode_display_name(row["cname"])
            if cname and not cname.startswith("+") and not is_base64_protocol_token(cname):
                tier3_member[jid] = cname
            else:
                decoded_fn = clean_unicode_display_name(decode_groupmember_firstname_proto(row["fname"]))
                if decoded_fn and not decoded_fn.startswith("+"):
                    tier3_member[jid] = decoded_fn

        # 3b. Load ZWAMESSAGE.ZPUSHNAME ONLY when it is a genuine human string (not a base64 protocol token)
        cur.execute(
            """
            SELECT gm.ZMEMBERJID AS jid, m.ZPUSHNAME AS pushname
            FROM ZWAMESSAGE m
            JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
            WHERE gm.ZMEMBERJID IS NOT NULL
              AND m.ZPUSHNAME IS NOT NULL
              AND TRIM(m.ZPUSHNAME) != ''
            ORDER BY m.Z_PK ASC
            """
        )
        for row in cur.fetchall():
            jid = row["jid"].strip()
            raw_pn = row["pushname"].strip()
            if not is_base64_protocol_token(raw_pn):
                clean_pn = clean_unicode_display_name(raw_pn)
                if clean_pn:
                    tier3_member[jid] = clean_pn

        # Propagate resolved names across bridged @lid <-> @s.whatsapp.net pairs
        for d in (tier1_remark, tier2_pushname, tier3_member):
            for k, v in list(d.items()):
                if k in lid_to_phone and lid_to_phone[k] not in d:
                    d[lid_to_phone[k]] = v
                if k in phone_to_lid and phone_to_lid[k] not in d:
                    d[phone_to_lid[k]] = v

        all_jids = (
            set(tier1_remark.keys())
            | set(tier2_pushname.keys())
            | set(tier3_member.keys())
            | set(lid_to_phone.keys())
            | set(phone_to_lid.keys())
        )
        merged: dict[str, str] = {}
        for jid in all_jids:
            bridged_phone = lid_to_phone.get(jid)
            raw_name = (
                tier1_remark.get(jid)
                or tier2_pushname.get(jid)
                or tier3_member.get(jid)
            )
            if raw_name:
                name = disambiguate_punctuation_name(raw_name, jid, bridged_phone)
            else:
                name = format_fallback_sender_name(jid, bridged_phone)
            merged[jid] = name

        prefix_map: dict[str, str] = {}
        for jid, name in merged.items():
            prefix = strip_jid_Namespace(jid)
            if prefix:
                prefix_map[prefix] = name

        self._lid_to_phone_jid = lid_to_phone
        self._auto_self_prefixes = auto_self
        self._jid_name_map = merged
        self._jid_prefix_map = prefix_map
        return merged, prefix_map

    def resolve_sender_name(
        self,
        is_from_me: bool,
        member_jid: str | None,
        msg_pushname: str | None,
    ) -> str:
        if is_from_me:
            return self.config.my_display_label
        jid_map, _ = self._ensure_name_maps()
        if member_jid and member_jid in jid_map:
            return jid_map[member_jid]
        if msg_pushname and not is_base64_protocol_token(msg_pushname):
            clean_pn = clean_unicode_display_name(msg_pushname)
            if clean_pn:
                return clean_pn
        bridged_phone = self._lid_to_phone_jid.get(member_jid or "")
        return format_fallback_sender_name(member_jid, bridged_phone)

    def get_group_member_prefix_dict(self, chat_session_pk: int) -> dict[str, str]:
        """Return {jid_numeric_prefix: resolved_name} for a specific group session (plus global known JIDs)."""
        jid_map, global_prefix_map = self._ensure_name_maps()
        member_dict = dict(global_prefix_map)
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ZMEMBERJID
            FROM ZWAGROUPMEMBER
            WHERE ZCHATSESSION = ? AND ZMEMBERJID IS NOT NULL
            """,
            (chat_session_pk,),
        )
        for row in cur.fetchall():
            jid = row["ZMEMBERJID"]
            prefix = strip_jid_Namespace(jid)
            if prefix and prefix not in member_dict:
                bridged_phone = self._lid_to_phone_jid.get(jid)
                member_dict[prefix] = jid_map.get(jid) or format_fallback_sender_name(jid, bridged_phone)
        return member_dict

    def list_groups(
        self,
        keyword: str | None = None,
        include_blocked: bool = False,
    ) -> dict[str, Any]:
        """List group sessions with latest cursor, 24h message counts, and policy status."""
        conn = self._get_conn()
        cur = conn.cursor()
        now_apple = time.time() - APPLE_EPOCH_OFFSET
        since_24h_apple = now_apple - 86400

        cs_cols = self._get_table_columns("ZWACHATSESSION")
        removed_filter = "AND COALESCE(s.ZREMOVED, 0) = 0" if "ZREMOVED" in cs_cols else ""
        placeholders = ",".join("?" for _ in EXCLUDED_MSG_TYPES)
        sql = f"""
            SELECT
                s.Z_PK AS session_pk,
                s.ZCONTACTJID AS chat_id,
                COALESCE(s.ZPARTNERNAME, '未命名群聊') AS group_name,
                s.ZLASTMESSAGEDATE AS session_last_date,
                COALESCE(MAX(m.Z_PK), 0) AS latest_msg_id,
                MAX(m.ZMESSAGEDATE) AS latest_msg_date,
                SUM(CASE WHEN m.ZMESSAGEDATE >= ? THEN 1 ELSE 0 END) AS msg_count_24h,
                (SELECT COUNT(*) FROM ZWAGROUPMEMBER gm WHERE gm.ZCHATSESSION = s.Z_PK AND COALESCE(gm.ZISACTIVE, 1) = 1) AS member_count
            FROM ZWACHATSESSION s
            LEFT JOIN ZWAMESSAGE m
                ON m.ZCHATSESSION = s.Z_PK
                AND m.ZMESSAGETYPE NOT IN ({placeholders})
            WHERE s.ZCONTACTJID LIKE '%@g.us'
              {removed_filter}
            GROUP BY s.Z_PK
            ORDER BY COALESCE(MAX(m.ZMESSAGEDATE), s.ZLASTMESSAGEDATE, 0) DESC
        """
        params: list[Any] = [since_24h_apple, *EXCLUDED_MSG_TYPES]
        cur.execute(sql, params)

        groups: list[dict[str, Any]] = []
        kw_lower = keyword.strip().lower() if keyword else None

        for row in cur.fetchall():
            chat_id = row["chat_id"]
            group_name = clean_unicode_display_name(row["group_name"]) or "未命名群聊"
            if kw_lower and kw_lower not in group_name.lower() and kw_lower not in chat_id.lower():
                continue

            allowed = self.config.is_chat_allowed(chat_id)
            if not allowed and not include_blocked:
                continue

            last_apple = row["latest_msg_date"] if row["latest_msg_date"] is not None else row["session_last_date"]
            last_epoch = int(round(float(last_apple) + APPLE_EPOCH_OFFSET)) if last_apple is not None else None

            groups.append(
                {
                    "chat_id": chat_id,
                    "group_name": group_name,
                    "allowed": allowed,
                    "latest_msg_id": int(row["latest_msg_id"] or 0),
                    "last_active_time": epoch_to_local_iso(last_epoch),
                    "msg_count_24h": int(row["msg_count_24h"] or 0),
                    "member_count": int(row["member_count"] or 0),
                }
            )

        return {
            "meta": {
                "snapshot_time": self.snapshot.snapshot_time_iso,
                "snapshot_age_sec": self.snapshot.snapshot_age_sec,
                "db_latest_msg_time": self.snapshot.db_latest_msg_time_iso,
                "global_latest_msg_id": self.snapshot.global_latest_msg_id,
                "filter_mode": self.config.filter_mode,
                "warnings": self.build_common_warnings(),
            },
            "groups": groups,
        }

    def _resolve_target_sessions(self, chat_ids: list[str]) -> list[sqlite3.Row]:
        """Validate requested chat_ids against session isolation policy and return ZWACHATSESSION rows."""
        if not chat_ids:
            raise UsageError("At least one chat_id or 'ALL_ALLOWED' must be specified via --chats.")

        conn = self._get_conn()
        cur = conn.cursor()
        cs_cols = self._get_table_columns("ZWACHATSESSION")
        removed_filter = "AND COALESCE(ZREMOVED, 0) = 0" if "ZREMOVED" in cs_cols else ""

        if len(chat_ids) == 1 and chat_ids[0].upper() == "ALL_ALLOWED":
            cur.execute(
                f"""
                SELECT Z_PK AS session_pk, ZCONTACTJID AS chat_id, COALESCE(ZPARTNERNAME, '未命名群聊') AS group_name
                FROM ZWACHATSESSION
                WHERE ZCONTACTJID LIKE '%@g.us' {removed_filter}
                ORDER BY COALESCE(ZLASTMESSAGEDATE, 0) DESC
                """
            )
            return [r for r in cur.fetchall() if self.config.is_chat_allowed(r["chat_id"])]

        for cid in chat_ids:
            self.config.assert_chat_allowed(cid)

        placeholders = ",".join("?" for _ in chat_ids)
        cur.execute(
            f"""
            SELECT Z_PK AS session_pk, ZCONTACTJID AS chat_id, COALESCE(ZPARTNERNAME, '未命名群聊') AS group_name
            FROM ZWACHATSESSION
            WHERE ZCONTACTJID IN ({placeholders}) AND ZCONTACTJID LIKE '%@g.us'
            """,
            chat_ids,
        )
        rows_by_id = {r["chat_id"]: r for r in cur.fetchall()}
        result: list[sqlite3.Row] = []
        for cid in chat_ids:
            if cid not in rows_by_id:
                raise ResourceNotFoundError(
                    f"Group chat '{cid}' not found in local WhatsApp database.",
                    error_code="GROUP_NOT_FOUND",
                )
            result.append(rows_by_id[cid])
        return result

    def _lookup_parent_reply(
        self,
        parent_pk: int | None,
        quoted_stanza_id: str | None,
        quoted_text_fallback: str | None,
        member_dict: dict[str, str],
    ) -> dict[str, Any] | None:
        if parent_pk is None and not quoted_stanza_id:
            return None

        conn = self._get_conn()
        cur = conn.cursor()
        row = None
        if parent_pk is not None:
            cur.execute(
                """
                SELECT m.Z_PK, m.ZMESSAGETYPE, m.ZISFROMME, m.ZTEXT, m.ZPUSHNAME,
                       gm.ZMEMBERJID, mi.ZTITLE, mi.ZAUTHORNAME
                FROM ZWAMESSAGE m
                LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
                LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                WHERE m.Z_PK = ?
                """,
                (parent_pk,),
            )
            row = cur.fetchone()

        if row is None and quoted_stanza_id:
            cur.execute(
                """
                SELECT m.Z_PK, m.ZMESSAGETYPE, m.ZISFROMME, m.ZTEXT, m.ZPUSHNAME,
                       gm.ZMEMBERJID, mi.ZTITLE, mi.ZAUTHORNAME
                FROM ZWAMESSAGE m
                LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
                LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                WHERE m.ZSTANZAID = ?
                LIMIT 1
                """,
                (quoted_stanza_id,),
            )
            row = cur.fetchone()

        if row is None:
            if quoted_text_fallback:
                cleaned_fb, _ = replace_mentions_with_whitelist(
                    quoted_text_fallback,
                    member_dict,
                    [],
                    self.config,
                    self._auto_self_prefixes,
                )
                return {
                    "msg_id": None,
                    "sender_name": "历史消息",
                    "text_snippet": truncate_reply_snippet(cleaned_fb),
                    "status": "ok_from_metadata",
                }
            return {
                "msg_id": None,
                "sender_name": None,
                "text_snippet": "[原消息不在本地库]",
                "status": "not_found",
            }

        p_pk = int(row["Z_PK"])
        p_type = int(row["ZMESSAGETYPE"] or 0)
        p_sender = self.resolve_sender_name(
            bool(row["ZISFROMME"]),
            row["ZMEMBERJID"],
            row["ZPUSHNAME"],
        )

        if p_type == 14:
            return {
                "msg_id": p_pk,
                "sender_name": p_sender,
                "text_snippet": "[原消息已撤回]",
                "status": "revoked",
            }

        raw_p_text = row["ZTEXT"] or row["ZTITLE"] or row["ZAUTHORNAME"] or ""
        if not raw_p_text and p_type in MEDIA_MSG_TYPES:
            raw_p_text = f"[{MEDIA_MSG_TYPES[p_type]}附件]"
        cleaned_p_text, _ = replace_mentions_with_whitelist(
            raw_p_text,
            member_dict,
            [],
            self.config,
            self._auto_self_prefixes,
        )
        return {
            "msg_id": p_pk,
            "sender_name": p_sender,
            "text_snippet": truncate_reply_snippet(cleaned_p_text),
            "status": "ok",
        }

    def _transform_message_row(
        self,
        row: sqlite3.Row,
        member_dict: dict[str, str],
        is_context_buffer: bool,
    ) -> dict[str, Any] | None:
        msg_pk = int(row["Z_PK"])
        raw_type = int(row["ZMESSAGETYPE"] or 0)
        if raw_type in EXCLUDED_MSG_TYPES:
            return None

        msg_type = MSG_TYPE_MAP.get(raw_type, f"unknown_{raw_type}")
        is_from_me = bool(row["ZISFROMME"])
        member_jid = row["ZMEMBERJID"] if not is_from_me else "me"
        sender_name = self.resolve_sender_name(is_from_me, row["ZMEMBERJID"], row["ZPUSHNAME"])

        proto_meta = parse_message_metadata_blob(row["ZMETADATA"])

        # Add any mentioned JIDs from ZMETADATA into member_dict if not already present
        jid_map, _ = self._ensure_name_maps()
        for m_jid in proto_meta.mentioned_jids:
            m_prefix = strip_jid_Namespace(m_jid)
            if m_prefix and m_prefix not in member_dict:
                bridged_phone = self._lid_to_phone_jid.get(m_jid)
                member_dict[m_prefix] = jid_map.get(m_jid) or format_fallback_sender_name(m_jid, bridged_phone)

        raw_text = (row["ZTEXT"] or "").strip()
        media_title = (row["ZTITLE"] or "").strip()
        media_author = (row["ZAUTHORNAME"] or "").strip()
        media_local_rel = (row["ZMEDIALOCALPATH"] or "").strip()
        media_filesize = int(row["ZFILESIZE"] or 0) if row["ZFILESIZE"] is not None else None
        media_duration = int(row["ZMOVIEDURATION"] or 0) if row["ZMOVIEDURATION"] is not None else None

        media_obj: dict[str, Any] | None = None
        if raw_type in MEDIA_MSG_TYPES or media_local_rel:
            local_available = False
            if media_local_rel:
                full_media_path = self.wa_message_dir / media_local_rel
                local_available = full_media_path.is_file() and full_media_path.stat().st_size > 0

            if raw_type == 8:  # Document
                doc_title = (
                    media_author
                    or media_title
                    or (os.path.basename(media_local_rel) if media_local_rel else "")
                    or raw_text
                    or "未命名文档"
                )
                if not raw_text and media_title and media_title != doc_title:
                    raw_text = media_title
            else:
                doc_title = (
                    (os.path.basename(media_local_rel) if media_local_rel else "")
                    or media_author
                    or None
                )
                if not raw_text and media_title:
                    raw_text = media_title

            media_obj = {
                "media_type": MEDIA_MSG_TYPES.get(raw_type, msg_type),
                "title": doc_title,
                "mime_type": row["ZVCARDSTRING"] or None,
                "file_size_bytes": media_filesize,
                "duration_sec": media_duration if raw_type in (2, 3, 11) else None,
                "local_available": local_available,
            }
        elif raw_type == 4:  # Contact card
            cname = row["ZVCARDNAME"] or raw_text or "联系人"
            raw_text = f"[名片分享: {cname}]"
        elif raw_type == 5:  # Location
            lat = row["ZLATITUDE"]
            lon = row["ZLONGITUDE"]
            loc_title = media_title or raw_text or ""
            raw_text = f"[位置分享: ({lat}, {lon}) {loc_title}]".strip()

        if not raw_text and media_obj is None:
            return None

        cleaned_text, mentions_me = replace_mentions_with_whitelist(
            raw_text,
            member_dict,
            proto_meta.mentioned_jids,
            self.config,
            self._auto_self_prefixes,
        )

        reply_to = self._lookup_parent_reply(
            int(row["ZPARENTMESSAGE"]) if row["ZPARENTMESSAGE"] is not None else None,
            proto_meta.quoted_stanza_id,
            proto_meta.quoted_text_fallback,
            member_dict,
        )

        msg_epoch = int(round(float(row["ZMESSAGEDATE"] or 0) + APPLE_EPOCH_OFFSET))
        ack_noise = is_short_ack_noise(
            cleaned_text,
            msg_type,
            has_reply=(reply_to is not None),
            has_media=(media_obj is not None),
            mentions_me=mentions_me,
        )

        return {
            "msg_id": msg_pk,
            "stanza_id": row["ZSTANZAID"],
            "timestamp": epoch_to_local_iso(msg_epoch),
            "timestamp_epoch": msg_epoch,
            "sender_jid": member_jid,
            "sender_name": sender_name,
            "is_from_me": is_from_me,
            "is_context_buffer": is_context_buffer,
            "is_ack_noise": ack_noise,
            "msg_type": msg_type,
            "text": cleaned_text,
            "mentions_me": mentions_me,
            "reply_to": reply_to,
            "media": media_obj,
        }

    def fetch_messages(
        self,
        chat_ids: list[str],
        after_msg_id: int | None = None,
        since_str: str | None = None,
        until_str: str | None = None,
        context_buffer_count: int | None = None,
        limit_per_chat: int = DEFAULT_FETCH_LIMIT,
    ) -> dict[str, Any]:
        """Fetch cleaned group messages by global cursor (--after-id) or time window (--since)."""
        limit = max(1, min(int(limit_per_chat), MAX_FETCH_LIMIT))
        ctx_count = (
            self.config.cleaning.context_buffer_count
            if context_buffer_count is None
            else max(0, int(context_buffer_count))
        )

        warnings = self.build_common_warnings()
        now_epoch = time.time()
        query_mode = "time_window"
        effective_after_id: int | None = None
        since_epoch: float | None = None
        until_epoch: float | None = parse_since_to_epoch(until_str, now_epoch) if until_str else None

        if after_msg_id is not None:
            if after_msg_id < 0:
                raise UsageError("--after-id must be a non-negative integer.")
            if (
                self.snapshot.global_latest_msg_id > 0
                and after_msg_id > self.snapshot.global_latest_msg_id
            ):
                query_mode = "cursor_reset_fallback_24h"
                since_epoch = now_epoch - 86400
                warnings.append(
                    {
                        "code": "CURSOR_RESET_FALLBACK",
                        "request_after_msg_id": after_msg_id,
                        "global_latest_msg_id": self.snapshot.global_latest_msg_id,
                        "message": (
                            f"传入的游标 after_msg_id ({after_msg_id}) 大于当前数据库最大主键 "
                            f"({self.snapshot.global_latest_msg_id})，已自动降级拉取过去 24 小时消息。"
                        ),
                    }
                )
            else:
                query_mode = "incremental_cursor"
                effective_after_id = after_msg_id
        else:
            since_epoch = parse_since_to_epoch(since_str or "24h", now_epoch)

        sessions = self._resolve_target_sessions(chat_ids)
        is_explicit_single_or_multi = not (len(chat_ids) == 1 and chat_ids[0].upper() == "ALL_ALLOWED")

        conn = self._get_conn()
        cur = conn.cursor()
        excl_placeholders = ",".join("?" for _ in EXCLUDED_MSG_TYPES)
        dur_expr = self._media_duration_expr("mi")

        chats_result: list[dict[str, Any]] = []

        for sess in sessions:
            sess_pk = int(sess["session_pk"])
            chat_id = sess["chat_id"]
            group_name = clean_unicode_display_name(sess["group_name"]) or "未命名群聊"

            where_clauses = [
                "m.ZCHATSESSION = ?",
                f"m.ZMESSAGETYPE NOT IN ({excl_placeholders})",
            ]
            params: list[Any] = [sess_pk, *EXCLUDED_MSG_TYPES]

            if effective_after_id is not None:
                where_clauses.append("m.Z_PK > ?")
                params.append(effective_after_id)
            if since_epoch is not None:
                where_clauses.append("m.ZMESSAGEDATE >= ?")
                params.append(since_epoch - APPLE_EPOCH_OFFSET)
            if until_epoch is not None:
                where_clauses.append("m.ZMESSAGEDATE <= ?")
                params.append(until_epoch - APPLE_EPOCH_OFFSET)

            where_sql = " AND ".join(where_clauses)
            # In incremental_cursor mode (--after-id), advance forward (ASC) from cursor.
            # In time_window mode (--since), take the most recent `limit` messages (DESC) then sort ASC.
            order_dir = "ASC" if effective_after_id is not None else "DESC"
            sql = f"""
                SELECT
                    m.Z_PK, m.ZSTANZAID, m.ZMESSAGEDATE, m.ZMESSAGETYPE,
                    m.ZISFROMME, m.ZTEXT, m.ZPUSHNAME, m.ZPARENTMESSAGE,
                    gm.ZMEMBERJID,
                    mi.ZMEDIALOCALPATH, mi.ZTITLE, mi.ZAUTHORNAME,
                    mi.ZVCARDNAME, mi.ZVCARDSTRING, mi.ZFILESIZE,
                    {dur_expr}, mi.ZLATITUDE, mi.ZLONGITUDE, mi.ZMETADATA
                FROM ZWAMESSAGE m
                LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
                LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                WHERE {where_sql}
                ORDER BY m.Z_PK {order_dir}
                LIMIT ?
            """
            params.append(limit + 1)
            cur.execute(sql, params)
            raw_rows = cur.fetchall()

            has_more = len(raw_rows) > limit
            if has_more:
                raw_rows = raw_rows[:limit]
            if order_dir == "DESC":
                raw_rows.reverse()

            member_dict = self.get_group_member_prefix_dict(sess_pk)
            new_messages: list[dict[str, Any]] = []
            for r in raw_rows:
                item = self._transform_message_row(r, member_dict, is_context_buffer=False)
                if item is not None:
                    new_messages.append(item)

            if not new_messages and not is_explicit_single_or_multi:
                continue

            buffer_messages: list[dict[str, Any]] = []
            if new_messages and ctx_count > 0:
                first_new_pk = new_messages[0]["msg_id"]
                buf_sql = f"""
                    SELECT
                        m.Z_PK, m.ZSTANZAID, m.ZMESSAGEDATE, m.ZMESSAGETYPE,
                        m.ZISFROMME, m.ZTEXT, m.ZPUSHNAME, m.ZPARENTMESSAGE,
                        gm.ZMEMBERJID,
                        mi.ZMEDIALOCALPATH, mi.ZTITLE, mi.ZAUTHORNAME,
                        mi.ZVCARDNAME, mi.ZVCARDSTRING, mi.ZFILESIZE,
                        {dur_expr}, mi.ZLATITUDE, mi.ZLONGITUDE, mi.ZMETADATA
                    FROM ZWAMESSAGE m
                    LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
                    LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                    WHERE m.ZCHATSESSION = ?
                      AND m.ZMESSAGETYPE NOT IN ({excl_placeholders})
                      AND m.Z_PK < ?
                    ORDER BY m.Z_PK DESC
                    LIMIT ?
                """
                cur.execute(buf_sql, [sess_pk, *EXCLUDED_MSG_TYPES, first_new_pk, ctx_count * 2])
                buf_rows = cur.fetchall()
                for r in buf_rows:
                    item = self._transform_message_row(r, member_dict, is_context_buffer=True)
                    if item is not None:
                        buffer_messages.append(item)
                    if len(buffer_messages) >= ctx_count:
                        break
                buffer_messages.reverse()

            cur.execute(
                f"""
                SELECT COALESCE(MAX(Z_PK), 0)
                FROM ZWAMESSAGE
                WHERE ZCHATSESSION = ? AND ZMESSAGETYPE NOT IN ({excl_placeholders})
                """,
                [sess_pk, *EXCLUDED_MSG_TYPES],
            )
            chat_overall_latest = int(cur.fetchone()[0] or 0)

            # Sort buffer and new messages chronologically (by timestamp_epoch, then msg_id)
            # so multi-device history sync messages appear in true conversation order.
            buffer_messages.sort(key=lambda m: (m["timestamp_epoch"], m["msg_id"]))
            new_messages.sort(key=lambda m: (m["timestamp_epoch"], m["msg_id"]))

            all_chat_msgs = buffer_messages + new_messages
            chat_min_id = min(m["msg_id"] for m in new_messages) if new_messages else None
            chat_max_id = max(m["msg_id"] for m in new_messages) if new_messages else chat_overall_latest

            chats_result.append(
                {
                    "chat_id": chat_id,
                    "group_name": group_name,
                    "chat_min_msg_id": chat_min_id,
                    "chat_latest_msg_id": chat_max_id,
                    "new_message_count": len(new_messages),
                    "context_buffer_count": len(buffer_messages),
                    "has_more": has_more,
                    "messages": all_chat_msgs,
                }
            )

        return {
            "meta": {
                "extracted_at": epoch_to_local_iso(now_epoch),
                "snapshot_time": self.snapshot.snapshot_time_iso,
                "snapshot_age_sec": self.snapshot.snapshot_age_sec,
                "query_mode": query_mode,
                "request_after_msg_id": after_msg_id,
                "global_latest_msg_id": self.snapshot.global_latest_msg_id,
                "my_identity": self.config.my_display_label,
                "warnings": warnings,
            },
            "chats": chats_result,
        }

    def search_messages(
        self,
        query: str,
        chat_ids: list[str] | None = None,
        since_str: str | None = None,
        context_window: int = 3,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search messages across allowed groups with +/- N context messages around each hit."""
        q_clean = (query or "").strip()
        if not q_clean:
            raise UsageError("Search --query cannot be empty.")

        target_chats = chat_ids if chat_ids else ["ALL_ALLOWED"]
        sessions = self._resolve_target_sessions(target_chats)
        if not sessions:
            return {
                "meta": {
                    "query": q_clean,
                    "snapshot_time": self.snapshot.snapshot_time_iso,
                    "global_latest_msg_id": self.snapshot.global_latest_msg_id,
                    "match_count": 0,
                    "warnings": self.build_common_warnings(),
                },
                "matches": [],
            }

        since_epoch = parse_since_to_epoch(since_str, time.time()) if since_str else None
        sess_map = {int(s["session_pk"]): s for s in sessions}
        sess_placeholders = ",".join("?" for _ in sess_map)
        excl_placeholders = ",".join("?" for _ in EXCLUDED_MSG_TYPES)
        dur_expr = self._media_duration_expr("mi")

        where_clauses = [
            f"m.ZCHATSESSION IN ({sess_placeholders})",
            f"m.ZMESSAGETYPE NOT IN ({excl_placeholders})",
            "(LOWER(COALESCE(m.ZTEXT, '')) LIKE ? OR LOWER(COALESCE(mi.ZTITLE, '')) LIKE ? OR LOWER(COALESCE(mi.ZAUTHORNAME, '')) LIKE ?)",
        ]
        like_pat = f"%{q_clean.lower()}%"
        params: list[Any] = [*sess_map.keys(), *EXCLUDED_MSG_TYPES, like_pat, like_pat, like_pat]

        if since_epoch is not None:
            where_clauses.append("m.ZMESSAGEDATE >= ?")
            params.append(since_epoch - APPLE_EPOCH_OFFSET)

        conn = self._get_conn()
        cur = conn.cursor()
        sql = f"""
            SELECT
                m.Z_PK, m.ZCHATSESSION, m.ZSTANZAID, m.ZMESSAGEDATE, m.ZMESSAGETYPE,
                m.ZISFROMME, m.ZTEXT, m.ZPUSHNAME, m.ZPARENTMESSAGE,
                gm.ZMEMBERJID,
                mi.ZMEDIALOCALPATH, mi.ZTITLE, mi.ZAUTHORNAME,
                mi.ZVCARDNAME, mi.ZVCARDSTRING, mi.ZFILESIZE,
                {dur_expr}, mi.ZLATITUDE, mi.ZLONGITUDE, mi.ZMETADATA
            FROM ZWAMESSAGE m
            LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
            LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
            WHERE {" AND ".join(where_clauses)}
            ORDER BY m.Z_PK DESC
            LIMIT ?
        """
        params.append(max(1, min(int(limit), 500)))
        cur.execute(sql, params)
        hit_rows = cur.fetchall()

        matches: list[dict[str, Any]] = []
        ctx_n = max(0, int(context_window))

        for hit in hit_rows:
            sess_pk = int(hit["ZCHATSESSION"])
            sess_info = sess_map[sess_pk]
            member_dict = self.get_group_member_prefix_dict(sess_pk)
            hit_pk = int(hit["Z_PK"])

            hit_msg = self._transform_message_row(hit, member_dict, is_context_buffer=False)
            if hit_msg is None:
                continue

            before_msgs: list[dict[str, Any]] = []
            after_msgs: list[dict[str, Any]] = []

            if ctx_n > 0:
                cur.execute(
                    f"""
                    SELECT
                        m.Z_PK, m.ZSTANZAID, m.ZMESSAGEDATE, m.ZMESSAGETYPE,
                        m.ZISFROMME, m.ZTEXT, m.ZPUSHNAME, m.ZPARENTMESSAGE,
                        gm.ZMEMBERJID,
                        mi.ZMEDIALOCALPATH, mi.ZTITLE, mi.ZAUTHORNAME,
                        mi.ZVCARDNAME, mi.ZVCARDSTRING, mi.ZFILESIZE,
                        {dur_expr}, mi.ZLATITUDE, mi.ZLONGITUDE, mi.ZMETADATA
                    FROM ZWAMESSAGE m
                    LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
                    LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                    WHERE m.ZCHATSESSION = ? AND m.ZMESSAGETYPE NOT IN ({excl_placeholders}) AND m.Z_PK < ?
                    ORDER BY m.Z_PK DESC LIMIT ?
                    """,
                    [sess_pk, *EXCLUDED_MSG_TYPES, hit_pk, ctx_n],
                )
                for r in reversed(cur.fetchall()):
                    m_obj = self._transform_message_row(r, member_dict, is_context_buffer=True)
                    if m_obj:
                        before_msgs.append(m_obj)

                cur.execute(
                    f"""
                    SELECT
                        m.Z_PK, m.ZSTANZAID, m.ZMESSAGEDATE, m.ZMESSAGETYPE,
                        m.ZISFROMME, m.ZTEXT, m.ZPUSHNAME, m.ZPARENTMESSAGE,
                        gm.ZMEMBERJID,
                        mi.ZMEDIALOCALPATH, mi.ZTITLE, mi.ZAUTHORNAME,
                        mi.ZVCARDNAME, mi.ZVCARDSTRING, mi.ZFILESIZE,
                        {dur_expr}, mi.ZLATITUDE, mi.ZLONGITUDE, mi.ZMETADATA
                    FROM ZWAMESSAGE m
                    LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
                    LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                    WHERE m.ZCHATSESSION = ? AND m.ZMESSAGETYPE NOT IN ({excl_placeholders}) AND m.Z_PK > ?
                    ORDER BY m.Z_PK ASC LIMIT ?
                    """,
                    [sess_pk, *EXCLUDED_MSG_TYPES, hit_pk, ctx_n],
                )
                for r in cur.fetchall():
                    m_obj = self._transform_message_row(r, member_dict, is_context_buffer=True)
                    if m_obj:
                        after_msgs.append(m_obj)

            matches.append(
                {
                    "chat_id": sess_info["chat_id"],
                    "group_name": clean_unicode_display_name(sess_info["group_name"]) or "未命名群聊",
                    "matched_message": hit_msg,
                    "context_before": before_msgs,
                    "context_after": after_msgs,
                }
            )

        return {
            "meta": {
                "query": q_clean,
                "snapshot_time": self.snapshot.snapshot_time_iso,
                "global_latest_msg_id": self.snapshot.global_latest_msg_id,
                "match_count": len(matches),
                "warnings": self.build_common_warnings(),
            },
            "matches": matches,
        }
