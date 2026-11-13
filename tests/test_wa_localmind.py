"""Comprehensive unit and contract test suite for WhatsApp-LocalMind CLI & MCP capability layer."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
BIN_PATH = PROJECT_ROOT / "bin" / "whatsapp-localmind"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from wa_localmind.constants import (
    APPLE_EPOCH_OFFSET,
    EXIT_ENV_OR_PERM_ERROR,
    EXIT_POLICY_DENIED,
    EXIT_RESOURCE_NOT_FOUND,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
)


def _encode_varint(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _encode_proto_bytes_field(field_num: int, data: bytes) -> bytes:
    tag = (field_num << 3) | 2
    return _encode_varint(tag) + _encode_varint(len(data)) + data


def build_mock_zmetadata(
    quoted_stanza_id: str | None = None,
    quoted_text_fallback: str | None = None,
    mentioned_jids: list[str] | None = None,
) -> bytes:
    buf = bytearray()
    if quoted_stanza_id:
        buf.extend(_encode_proto_bytes_field(5, quoted_stanza_id.encode("utf-8")))
    if quoted_text_fallback:
        buf.extend(_encode_proto_bytes_field(6, quoted_text_fallback.encode("utf-8")))
    for jid in mentioned_jids or []:
        buf.extend(_encode_proto_bytes_field(8, jid.encode("utf-8")))
    return bytes(buf)


class TestWALocalMindCapabilityLayer(unittest.TestCase):
    """End-to-end tests against a synthetic WhatsApp ChatStorage.sqlite container."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.container_dir = self.root / "group.net.whatsapp.WhatsApp.shared"
        self.message_dir = self.container_dir / "Message"
        self.snapshot_dir = self.root / "app_support" / "snapshot"
        self.config_path = self.root / "app_support" / "config.json"

        self.container_dir.mkdir(parents=True)
        self.message_dir.mkdir(parents=True)

        self.now_epoch = int(time.time())
        self.now_apple = float(self.now_epoch - APPLE_EPOCH_OFFSET)

        self._create_mock_whatsapp_db()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _run_cli(self, *args: str) -> tuple[int, str, str]:
        env = os.environ.copy()
        env["WA_LOCALMIND_CONTAINER_DIR"] = str(self.container_dir)
        env["WA_LOCALMIND_SNAPSHOT_DIR"] = str(self.snapshot_dir)
        cmd = [sys.executable, str(BIN_PATH), *args, "--config", str(self.config_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
        return proc.returncode, proc.stdout, proc.stderr

    def _create_mock_whatsapp_db(self) -> None:
        db_path = self.container_dir / "ChatStorage.sqlite"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        cur.executescript(
            """
            CREATE TABLE ZWACHATSESSION (
                Z_PK INTEGER PRIMARY KEY,
                ZREMOVED INTEGER DEFAULT 0,
                ZLASTMESSAGEDATE TIMESTAMP,
                ZCONTACTJID VARCHAR,
                ZPARTNERNAME VARCHAR
            );
            CREATE TABLE ZWAGROUPMEMBER (
                Z_PK INTEGER PRIMARY KEY,
                ZISACTIVE INTEGER DEFAULT 1,
                ZCHATSESSION INTEGER,
                ZCONTACTNAME VARCHAR,
                ZFIRSTNAME VARCHAR,
                ZMEMBERJID VARCHAR
            );
            CREATE TABLE ZWAPROFILEPUSHNAME (
                Z_PK INTEGER PRIMARY KEY,
                ZJID VARCHAR,
                ZPUSHNAME VARCHAR
            );
            CREATE TABLE ZWAMEDIAITEM (
                Z_PK INTEGER PRIMARY KEY,
                ZFILESIZE INTEGER,
                ZMOVIEDURATION INTEGER,
                ZLATITUDE FLOAT,
                ZLONGITUDE FLOAT,
                ZAUTHORNAME VARCHAR,
                ZMEDIALOCALPATH VARCHAR,
                ZTITLE VARCHAR,
                ZVCARDNAME VARCHAR,
                ZVCARDSTRING VARCHAR,
                ZMETADATA BLOB
            );
            CREATE TABLE ZWAMESSAGE (
                Z_PK INTEGER PRIMARY KEY,
                ZISFROMME INTEGER DEFAULT 0,
                ZMESSAGETYPE INTEGER DEFAULT 0,
                ZGROUPEVENTTYPE INTEGER DEFAULT 0,
                ZCHATSESSION INTEGER,
                ZGROUPMEMBER INTEGER,
                ZMEDIAITEM INTEGER,
                ZPARENTMESSAGE INTEGER,
                ZMESSAGEDATE TIMESTAMP,
                ZFROMJID VARCHAR,
                ZPUSHNAME VARCHAR,
                ZSTANZAID VARCHAR,
                ZTEXT VARCHAR
            );
            """
        )

        # Sessions:
        # 1: Allowed Office Group A
        # 2: Blocked Family Group B
        # 3: 1-on-1 Private Chat (also serves as Contact Remark Name source for 8613900002222@s.whatsapp.net)
        cur.executemany(
            "INSERT INTO ZWACHATSESSION (Z_PK, ZREMOVED, ZLASTMESSAGEDATE, ZCONTACTJID, ZPARTNERNAME) VALUES (?, ?, ?, ?, ?)",
            [
                (1, 0, self.now_apple - 60, "120363000000000001@g.us", "东南亚物流交付群"),
                (2, 0, self.now_apple - 120, "120363000000000002@g.us", "周末亲友约饭群"),
                (3, 0, self.now_apple - 30, "8613900002222@s.whatsapp.net", "李四(船务备注)"),
            ],
        )

        # Group Members in Group 1:
        # 10: 8613900002222@s.whatsapp.net (resolved via ZWACHATSESSION remark -> 李四(船务备注))
        # 11: 1849200009999@lid (resolved via ZWAMESSAGE.ZPUSHNAME -> 王总(海外仓))
        # 12: 2777700001234@lid (no remark, no pushname -> fallback 外部群友#1234)
        cur.executemany(
            "INSERT INTO ZWAGROUPMEMBER (Z_PK, ZISACTIVE, ZCHATSESSION, ZMEMBERJID) VALUES (?, 1, ?, ?)",
            [
                (10, 1, "8613900002222@s.whatsapp.net"),
                (11, 1, "1849200009999@lid"),
                (12, 1, "2777700001234@lid"),
            ],
        )

        # Create real dummy media files inside Message/Media/...
        pdf_rel = "Media/120363000000000001@g.us/quote_v2.pdf"
        pdf_full = self.message_dir / pdf_rel
        pdf_full.parent.mkdir(parents=True, exist_ok=True)
        pdf_full.write_bytes(b"%PDF-1.4 dummy quotation content" * 100)

        audio_rel = "Media/120363000000000001@g.us/voice_note.opus"
        audio_full = self.message_dir / audio_rel
        audio_full.write_bytes(b"OggS dummy voice bytes" * 50)

        priv_rel = "Media/8613900002222@s.whatsapp.net/private_secret.pdf"
        priv_full = self.message_dir / priv_rel
        priv_full.parent.mkdir(parents=True, exist_ok=True)
        priv_full.write_bytes(b"private secret data")

        # Media items:
        # 500: Long text metadata only
        # 501: PDF Document attachment (local_available=True)
        # 502: Reply via Protobuf Field 5 (stanza_id="STANZA_101") + mention self ("8613800008888@s.whatsapp.net")
        # 503: 45s Voice message (local_available=True)
        # 504: Image with caption in ZTITLE (ZTEXT is NULL) and missing local file (local_available=False)
        # 505: Private chat attachment
        cur.executemany(
            """
            INSERT INTO ZWAMEDIAITEM (
                Z_PK, ZFILESIZE, ZMOVIEDURATION, ZAUTHORNAME, ZMEDIALOCALPATH, ZTITLE, ZVCARDSTRING, ZMETADATA
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (500, 0, 0, None, None, None, None, build_mock_zmetadata()),
                (501, pdf_full.stat().st_size, 0, "11月海运报价单.pdf", pdf_rel, None, "application/pdf", build_mock_zmetadata()),
                (
                    502,
                    0,
                    0,
                    None,
                    None,
                    None,
                    None,
                    build_mock_zmetadata(
                        quoted_stanza_id="STANZA_101",
                        quoted_text_fallback="历史报价上下文",
                        mentioned_jids=["8613800008888@s.whatsapp.net"],
                    ),
                ),
                (503, audio_full.stat().st_size, 45, None, audio_rel, None, "audio/ogg; codecs=opus", build_mock_zmetadata()),
                (504, 102400, 0, None, None, "这是图片配文Caption：集装箱铅封号照片", "image/jpeg", build_mock_zmetadata()),
                (505, priv_full.stat().st_size, 0, "private.pdf", priv_rel, None, "application/pdf", build_mock_zmetadata()),
            ],
        )

        long_quote_source = "港口清关重要条款：" + ("集装箱免箱期为14天且目的港杂费按合同附件A执行；" * 8)
        assert len(long_quote_source) > 160

        # Messages in Group 1:
        # 100: Context buffer message (older) from Me (ZISFROMME=1, ZGROUPMEMBER=NULL)
        # 101: Long text message (>150 chars) from Member 10 (STANZA_101)
        # 102: Revoked message (ZMESSAGETYPE=14) - MUST BE EXCLUDED
        # 103: System event message (ZMESSAGETYPE=6) - MUST BE EXCLUDED
        # 104: Document message (ZMESSAGETYPE=8) with media 501
        # 105: Reply message to STANZA_101 via Protobuf Field 5, mentioning @8613800008888 (self), @8613900002222 (member), and order number @20261107
        # 106: Short ack noise 1 ("收到")
        # 107: Short ack noise 2 ("OK")
        # 108: Short ack noise 3 ("+1")
        # 109: 45s Audio message (ZMESSAGETYPE=3) from unmapped @lid member 12
        # 110: Image with ZTEXT=NULL and caption in ZTITLE (media 504)
        # 200: Private 1-on-1 message in session 3 - MUST BE 100% BLOCKED
        cur.executemany(
            """
            INSERT INTO ZWAMESSAGE (
                Z_PK, ZISFROMME, ZMESSAGETYPE, ZCHATSESSION, ZGROUPMEMBER, ZMEDIAITEM,
                ZPARENTMESSAGE, ZMESSAGEDATE, ZPUSHNAME, ZSTANZAID, ZTEXT
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (100, 1, 0, 1, None, 500, None, self.now_apple - 600, None, "STANZA_100", "各位早，今天核对东南亚海运排期"),
                (101, 0, 0, 1, 10, 500, None, self.now_apple - 500, "LiSi_Push", "STANZA_101", long_quote_source),
                (102, 0, 14, 1, 10, None, None, self.now_apple - 450, "LiSi_Push", "STANZA_102", "这条报价写错了已撤回 99999美元"),
                (103, 0, 6, 1, 10, None, None, self.now_apple - 400, None, "STANZA_103", "系统通知：群名称已修改"),
                (104, 0, 8, 1, 10, 501, None, self.now_apple - 300, "LiSi_Push", "STANZA_104", "请查收最新PDF报价单"),
                (
                    105,
                    0,
                    0,
                    1,
                    11,
                    502,
                    None,
                    self.now_apple - 240,
                    "王总(海外仓)",
                    "STANZA_105",
                    "@8613800008888 和 @8613900002222 请确认单号 @20261107 的免箱期",
                ),
                (106, 0, 0, 1, 10, 500, None, self.now_apple - 200, "LiSi_Push", "STANZA_106", "收到"),
                (107, 0, 0, 1, 11, 500, None, self.now_apple - 190, "王总(海外仓)", "STANZA_107", "OK"),
                (108, 0, 0, 1, 12, 500, None, self.now_apple - 180, None, "STANZA_108", "+1"),
                (109, 0, 3, 1, 12, 503, None, self.now_apple - 120, None, "STANZA_109", None),
                (110, 0, 1, 1, 11, 504, 102, self.now_apple - 60, "王总(海外仓)", "STANZA_110", None),
                (200, 0, 8, 3, None, 505, None, self.now_apple - 30, "PrivatePeer", "STANZA_200", "私聊机密合同文件"),
            ],
        )

        conn.commit()
        conn.close()

    def test_01_doctor_and_config_management(self) -> None:
        # Configure identity and blacklist
        code, out, err = self._run_cli(
            "config",
            "set-identity",
            "--name",
            "张工",
            "--phone-suffix",
            "8888",
        )
        self.assertEqual(code, EXIT_SUCCESS, err)
        res = json.loads(out)
        self.assertEqual(res["identity"]["name"], "张工")

        code, out, err = self._run_cli("config", "block", "120363000000000002@g.us")
        self.assertEqual(code, EXIT_SUCCESS, err)
        res = json.loads(out)
        self.assertIn("120363000000000002@g.us", res["blacklist_chats"])

        # Doctor check
        code, out, err = self._run_cli("doctor", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS, err)
        doc = json.loads(out)
        self.assertTrue(doc["healthy"])
        self.assertEqual(doc["config"]["identity_label"], "我(张工)")

    def test_02_privacy_isolation_blocks_private_and_blacklisted_chats(self) -> None:
        self._run_cli("config", "block", "120363000000000002@g.us")

        # 1. Fetching 1-on-1 private chat JID must fail with Exit Code 3
        code, out, err = self._run_cli("fetch", "--chats", "8613900002222@s.whatsapp.net", "--format", "json")
        self.assertEqual(code, EXIT_POLICY_DENIED)
        self.assertEqual(out, "")
        err_json = json.loads(err)
        self.assertEqual(err_json["error_code"], "PRIVATE_SESSION_BLOCKED")

        # 2. Fetching blacklisted group JID must fail with Exit Code 3
        code, out, err = self._run_cli("fetch", "--chats", "120363000000000002@g.us", "--format", "json")
        self.assertEqual(code, EXIT_POLICY_DENIED)
        err_json = json.loads(err)
        self.assertEqual(err_json["error_code"], "GROUP_BLOCKED_BY_POLICY")

        # 3. Exporting media from a 1-on-1 private chat msg_id (200) must fail with Exit Code 3
        code, out, err = self._run_cli("export-media", "--msg-ids", "200")
        self.assertEqual(code, EXIT_POLICY_DENIED)
        err_json = json.loads(err)
        self.assertEqual(err_json["error_code"], "PRIVATE_SESSION_BLOCKED")

    def test_03_cleaning_accuracy_mentions_replies_revoked_and_Incremental_cursor(self) -> None:
        self._run_cli("config", "set-identity", "--name", "张工", "--phone-suffix", "8888")
        self._run_cli("config", "block", "120363000000000002@g.us")

        # Incremental fetch with --after-id 101 and --context-buffer 2
        code, out, err = self._run_cli(
            "fetch",
            "--chats",
            "ALL_ALLOWED",
            "--after-id",
            "101",
            "--context-buffer",
            "2",
            "--format",
            "json",
        )
        self.assertEqual(code, EXIT_SUCCESS, err)
        payload = json.loads(out)
        self.assertEqual(len(payload["chats"]), 1)
        chat = payload["chats"][0]
        self.assertEqual(chat["chat_id"], "120363000000000001@g.us")

        # Verify context buffer messages (100 and 101)
        self.assertEqual(chat["context_buffer_count"], 2)
        msgs = chat["messages"]
        msg_ids = [m["msg_id"] for m in msgs]

        # Revoked (102), System Event (103), and Private (200) MUST NOT be present
        self.assertNotIn(102, msg_ids)
        self.assertNotIn(103, msg_ids)
        self.assertNotIn(200, msg_ids)
        self.assertEqual(msg_ids, [100, 101, 104, 105, 106, 107, 108, 109, 110])

        by_id = {m["msg_id"]: m for m in msgs}

        # Check 100: Self message (ZISFROMME=1, ZGROUPMEMBER=NULL) preserved
        self.assertTrue(by_id[100]["is_from_me"])
        self.assertEqual(by_id[100]["sender_name"], "我(张工)")
        self.assertTrue(by_id[100]["is_context_buffer"])

        # Check 104: Document attachment with ZAUTHORNAME
        self.assertEqual(by_id[104]["sender_name"], "李四(船务备注)")
        self.assertEqual(by_id[104]["media"]["media_type"], "document")
        self.assertEqual(by_id[104]["media"]["title"], "11月海运报价单.pdf")
        self.assertTrue(by_id[104]["media"]["local_available"])

        # Check 105: @mention whitelist replacement, [@我(张工)], order number @20261107 untouched, and 150-char reply chain via Protobuf Field 5
        m105 = by_id[105]
        self.assertEqual(m105["sender_name"], "王总(海外仓)")
        self.assertTrue(m105["mentions_me"])
        self.assertIn("[@我(张工)]", m105["text"])
        self.assertIn("@李四(船务备注)", m105["text"])
        self.assertIn("@20261107", m105["text"])  # Order number not corrupted!
        self.assertIsNotNone(m105["reply_to"])
        self.assertEqual(m105["reply_to"]["msg_id"], 101)
        self.assertEqual(m105["reply_to"]["sender_name"], "李四(船务备注)")
        self.assertTrue(m105["reply_to"]["text_snippet"].endswith("..."))
        self.assertEqual(len(m105["reply_to"]["text_snippet"]), 153)  # 150 chars + "..."

        # Check 106, 107, 108: Short ack noise marked in JSON without losing items
        self.assertTrue(by_id[106]["is_ack_noise"])
        self.assertTrue(by_id[107]["is_ack_noise"])
        self.assertTrue(by_id[108]["is_ack_noise"])

        # Check 109: Unmapped @lid fallback + 45s voice note
        self.assertEqual(by_id[109]["sender_name"], "外部群友#1234")
        self.assertEqual(by_id[109]["media"]["duration_sec"], 45)

        # Check 110: Image with caption in ZTITLE + reply to revoked message 102
        self.assertIn("这是图片配文Caption：集装箱铅封号照片", by_id[110]["text"])
        self.assertEqual(by_id[110]["reply_to"]["status"], "revoked")
        self.assertEqual(by_id[110]["reply_to"]["text_snippet"], "[原消息已撤回]")

        # Check Markdown rendering folds consecutive ack noise (106~108) and tags 45s audio
        code_md, out_md, err_md = self._run_cli(
            "fetch",
            "--chats",
            "ALL_ALLOWED",
            "--after-id",
            "101",
            "--format",
            "md",
        )
        self.assertEqual(code_md, EXIT_SUCCESS, err_md)
        self.assertIn("[#106~#108]", out_md)
        self.assertIn("系统折叠", out_md)
        self.assertIn("⚠️ 语音消息未转写: 45秒", out_md)

    def test_04_cursor_out_of_bounds_fallback_and_export_media(self) -> None:
        # Cursor > global_latest_msg_id triggers CURSOR_RESET_FALLBACK warning
        code, out, err = self._run_cli(
            "fetch",
            "--chats",
            "ALL_ALLOWED",
            "--after-id",
            "999999",
            "--format",
            "json",
        )
        self.assertEqual(code, EXIT_SUCCESS, err)
        res = json.loads(out)
        warn_codes = [w["code"] for w in res["meta"]["warnings"]]
        self.assertIn("CURSOR_RESET_FALLBACK", warn_codes)
        self.assertGreater(len(res["chats"][0]["messages"]), 0)

        # Export media for msg_id 104 (PDF) and 109 (Voice)
        code, out, err = self._run_cli("export-media", "--msg-ids", "104,109")
        self.assertEqual(code, EXIT_SUCCESS, err)
        exp = json.loads(out)
        self.assertEqual(exp["meta"]["exported_count"], 2)
        for item in exp["exported"]:
            self.assertTrue(Path(item["exported_path"]).is_file())

        # Export media for msg_id 110 (not downloaded locally) returns Exit Code 4
        code, out, err = self._run_cli("export-media", "--msg-ids", "110")
        self.assertEqual(code, EXIT_RESOURCE_NOT_FOUND)

        # Clean media cache
        code, out, err = self._run_cli("clean", "--media-only")
        self.assertEqual(code, EXIT_SUCCESS, err)
        for item in exp["exported"]:
            self.assertFalse(Path(item["exported_path"]).exists())

    def test_05_search_and_mcp_stdio_server(self) -> None:
        # Test search across allowed groups
        code, out, err = self._run_cli(
            "search",
            "--query",
            "免箱期",
            "--context",
            "1",
            "--format",
            "json",
        )
        self.assertEqual(code, EXIT_SUCCESS, err)
        search_res = json.loads(out)
        self.assertGreaterEqual(search_res["meta"]["match_count"], 1)
        first_hit = search_res["matches"][0]["matched_message"]
        self.assertIn("免箱期", first_hit["text"])

        # Test MCP Stdio Server (initialize -> tools/list -> tools/call)
        env = os.environ.copy()
        env["WA_LOCALMIND_CONTAINER_DIR"] = str(self.container_dir)
        env["WA_LOCALMIND_SNAPSHOT_DIR"] = str(self.snapshot_dir)
        mcp_reqs = "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "whatsapp_list_groups",
                            "arguments": {"format": "json"},
                        },
                    }
                ),
            ]
        ) + "\n"
        cmd = [sys.executable, str(BIN_PATH), "mcp-serve", "--config", str(self.config_path)]
        proc = subprocess.run(cmd, input=mcp_reqs, capture_output=True, text=True, env=env, check=False)
        self.assertEqual(proc.returncode, EXIT_SUCCESS, proc.stderr)
        lines = [json.loads(line) for line in proc.stdout.strip().splitlines()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "whatsapp-localmind")
        self.assertEqual(len(lines[1]["result"]["tools"]), 4)
        self.assertFalse(lines[2]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()

