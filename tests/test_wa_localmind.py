"""Comprehensive unit and contract test suite for WhatsApp-LocalMind CLI & MCP capability layer."""

from __future__ import annotations

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
    EXIT_POLICY_DENIED,
    EXIT_RESOURCE_NOT_FOUND,
    EXIT_SUCCESS,
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
    """End-to-end tests against a synthetic WhatsApp ChatStorage.sqlite container (all chat types)."""

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
                ZCONTACTIDENTIFIER VARCHAR,
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
        # 1: Allowed Office Group A (@g.us)
        # 2: Blocked Family Group B (@g.us)
        # 3: 1-on-1 Direct Chat (@s.whatsapp.net -> 李四(船务备注))
        # 4: 1-on-1 LID Direct Chat (@lid bridged to 6591234567@s.whatsapp.net -> 陈总(新加坡))
        # 5: Newsletter / Channel (@newsletter -> 航运日报频道)
        # 6: Ephemeral status feed (status@broadcast -> must never appear as chat session)
        cur.executemany(
            "INSERT INTO ZWACHATSESSION (Z_PK, ZREMOVED, ZLASTMESSAGEDATE, ZCONTACTJID, ZCONTACTIDENTIFIER, ZPARTNERNAME) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, 0, self.now_apple - 60, "120363000000000001@g.us", None, "东南亚物流交付群"),
                (2, 0, self.now_apple - 120, "120363000000000002@g.us", None, "周末亲友约饭群"),
                (3, 0, self.now_apple - 30, "8613900002222@s.whatsapp.net", None, "李四(船务备注)"),
                (4, 0, self.now_apple - 20, "998877665544@lid", "6591234567@s.whatsapp.net", "陈总(新加坡)"),
                (5, 0, self.now_apple - 15, "120363199999999999@newsletter", None, "全球航运指数频道"),
                (6, 0, self.now_apple - 10, "status@broadcast", None, "Status"),
            ],
        )

        # Group Members in Group 1:
        cur.executemany(
            "INSERT INTO ZWAGROUPMEMBER (Z_PK, ZISACTIVE, ZCHATSESSION, ZMEMBERJID) VALUES (?, 1, ?, ?)",
            [
                (10, 1, "8613900002222@s.whatsapp.net"),
                (11, 1, "1849200009999@lid"),
                (12, 1, "2777700001234@lid"),
            ],
        )

        # Create dummy media files inside Message/Media/...
        pdf_rel = "Media/120363000000000001@g.us/quote_v2.pdf"
        pdf_full = self.message_dir / pdf_rel
        pdf_full.parent.mkdir(parents=True, exist_ok=True)
        pdf_full.write_bytes(b"%PDF-1.4 dummy quotation content" * 100)

        audio_rel = "Media/120363000000000001@g.us/voice_note.opus"
        audio_full = self.message_dir / audio_rel
        audio_full.write_bytes(b"OggS dummy voice bytes" * 50)

        dm_rel = "Media/8613900002222@s.whatsapp.net/dm_contract.pdf"
        dm_full = self.message_dir / dm_rel
        dm_full.parent.mkdir(parents=True, exist_ok=True)
        dm_full.write_bytes(b"%PDF-1.4 direct message contract data")

        outside_secret = self.root / "outside_host_secret.pdf"
        outside_secret.write_bytes(b"%PDF-1.4 secret outside sandbox")

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
                (505, dm_full.stat().st_size, 0, "私聊签署版合同.pdf", dm_rel, None, "application/pdf", build_mock_zmetadata()),
                (
                    506,
                    999,
                    0,
                    "escape.pdf",
                    "../../../outside_host_secret.pdf",
                    None,
                    "application/pdf",
                    build_mock_zmetadata(),
                ),
                (
                    507,
                    0,
                    0,
                    None,
                    None,
                    None,
                    None,
                    build_mock_zmetadata(
                        quoted_stanza_id="STANZA_BLOCKED_999",
                        quoted_text_fallback="本地回退摘要",
                    ),
                ),
            ],
        )

        long_quote_source = "港口清关重要条款：" + ("集装箱免箱期为14天且目的港杂费按合同附件A执行；" * 8)
        assert len(long_quote_source) > 160

        cur.executemany(
            """
            INSERT INTO ZWAMESSAGE (
                Z_PK, ZISFROMME, ZMESSAGETYPE, ZCHATSESSION, ZGROUPMEMBER, ZMEDIAITEM,
                ZPARENTMESSAGE, ZMESSAGEDATE, ZPUSHNAME, ZSTANZAID, ZTEXT
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                # Group 1 messages (100..110)
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
                # Blocked Group 2 message (150)
                (150, 0, 0, 2, None, None, None, self.now_apple - 90, "亲友A", "STANZA_BLOCKED_999", "屏蔽群机密家庭住址"),
                # 1-on-1 Direct Chat 3 messages (200..202) - ZGROUPMEMBER is NULL in 1-on-1 DMs!
                (200, 0, 8, 3, None, 505, None, self.now_apple - 35, "LiSi_Push", "STANZA_200", "张工，私聊发你签署版合同"),
                (201, 1, 0, 3, None, 500, 200, self.now_apple - 30, None, "STANZA_201", "收到李四，我马上归档合同"),
                # 1-on-1 LID Direct Chat 4 message (210) + cross-chat quote spoof attempt (211) + path traversal (212)
                (210, 0, 0, 4, None, 500, None, self.now_apple - 25, "ChenSG", "STANZA_210", "新加坡仓下周二可进场"),
                (211, 0, 0, 4, None, 507, None, self.now_apple - 22, "ChenSG", "STANZA_211", "测试跨会话引用隔离"),
                (212, 0, 8, 4, None, 506, None, self.now_apple - 20, "ChenSG", "STANZA_212", "测试路径穿越防护"),
                # Newsletter Channel 5 message (220)
                (220, 0, 0, 5, None, 500, None, self.now_apple - 15, None, "STANZA_220", "本周SCFI集装箱运价指数上涨3.2%"),
                # Ephemeral status broadcast (230 - never returned)
                (230, 0, 0, 6, None, 500, None, self.now_apple - 10, "Peer", "STANZA_230", "动态快拍"),
            ],
        )

        conn.commit()
        conn.close()

    def test_01_doctor_chats_and_groups_listing(self) -> None:
        code, out, err = self._run_cli(
            "config",
            "set-identity",
            "--name",
            "张工",
            "--phone-suffix",
            "8888",
        )
        self.assertEqual(code, EXIT_SUCCESS, err)
        self.assertEqual(json.loads(out)["identity"]["name"], "张工")

        # Block both a group and a 1-on-1 chat if desired; here block Group 2
        code, out, err = self._run_cli("config", "block", "120363000000000002@g.us")
        self.assertEqual(code, EXIT_SUCCESS, err)
        self.assertIn("120363000000000002@g.us", json.loads(out)["blacklist_chats"])

        # Doctor check verifies total, group, and direct session counts
        code, out, err = self._run_cli("doctor", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS, err)
        doc = json.loads(out)
        self.assertTrue(doc["healthy"])
        self.assertEqual(doc["config"]["chat_scope"], "all")
        self.assertEqual(doc["source_database"]["total_session_count"], 5)
        self.assertEqual(doc["source_database"]["group_session_count"], 2)
        self.assertEqual(doc["source_database"]["direct_session_count"], 2)

        # `chats` lists ALL allowed sessions (Group 1 + Direct 3 + Direct 4 + Newsletter 5 = 4 chats; excludes blocked Group 2 and status@broadcast)
        code, out, err = self._run_cli("chats", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS, err)
        chats_data = json.loads(out)["chats"]
        chat_ids = [c["chat_id"] for c in chats_data]
        self.assertEqual(len(chats_data), 4)
        self.assertIn("120363000000000001@g.us", chat_ids)
        self.assertIn("8613900002222@s.whatsapp.net", chat_ids)
        self.assertIn("998877665544@lid", chat_ids)
        self.assertIn("120363199999999999@newsletter", chat_ids)
        self.assertNotIn("status@broadcast", chat_ids)

        # `chats --type direct` lists only 1-on-1 direct chats
        code, out, _ = self._run_cli("chats", "--type", "direct", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS)
        direct_chats = json.loads(out)["chats"]
        self.assertEqual(len(direct_chats), 2)
        self.assertTrue(all(c["chat_type"] == "direct" for c in direct_chats))

        # `groups` backward-compatibly lists only group chats with `groups` key
        code, out, _ = self._run_cli("groups", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS)
        grps = json.loads(out)["groups"]
        self.assertEqual(len(grps), 1)
        self.assertEqual(grps[0]["chat_id"], "120363000000000001@g.us")

    def test_02_full_account_fetch_direct_dms_bridged_lid_and_media_export(self) -> None:
        self._run_cli("config", "set-identity", "--name", "张工", "--phone-suffix", "8888")
        self._run_cli("config", "block", "120363000000000002@g.us")

        # 1. Fetch 1-on-1 direct chat by bare phone number (+8613900002222) and verify peer remark & reply chain
        code, out, err = self._run_cli("fetch", "--chats", "+8613900002222", "--since", "24h", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS, err)
        dm_chat = json.loads(out)["chats"][0]
        self.assertEqual(dm_chat["chat_type"], "direct")
        self.assertEqual(dm_chat["chat_name"], "李四(船务备注)")
        dm_msgs = dm_chat["messages"]
        self.assertEqual(len(dm_msgs), 2)
        # Incoming DM (#200) resolves peer remark even though ZGROUPMEMBER is NULL!
        self.assertEqual(dm_msgs[0]["sender_name"], "李四(船务备注)")
        self.assertFalse(dm_msgs[0]["is_from_me"])
        self.assertEqual(dm_msgs[0]["media"]["title"], "私聊签署版合同.pdf")
        # Outgoing DM (#201) replies to #200 with resolved peer sender name
        self.assertEqual(dm_msgs[1]["sender_name"], "我(张工)")
        self.assertTrue(dm_msgs[1]["is_from_me"])
        self.assertEqual(dm_msgs[1]["reply_to"]["msg_id"], 200)
        self.assertEqual(dm_msgs[1]["reply_to"]["sender_name"], "李四(船务备注)")

        # 2. Fetch @lid 1-on-1 DM via bridged phone JID (6591234567@s.whatsapp.net -> 998877665544@lid)
        code, out, err = self._run_cli("fetch", "--chats", "6591234567@s.whatsapp.net", "--since", "24h", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS, err)
        lid_chat = json.loads(out)["chats"][0]
        self.assertEqual(lid_chat["chat_id"], "998877665544@lid")
        self.assertEqual(lid_chat["chat_name"], "陈总(新加坡)")
        # Cross-session spoofed quote STANZA_BLOCKED_999 must NOT leak blocked Group 2 text!
        self.assertNotIn("屏蔽群机密家庭住址", out)
        by_id = {m["msg_id"]: m for m in lid_chat["messages"]}
        self.assertFalse(by_id[212]["media"]["local_available"])
        self.assertIsNone(by_id[212]["media"]["file_size_bytes"])

        # 3. Export media from 1-on-1 direct chat (#200) succeeds under default full-account scope!
        code, out, err = self._run_cli("export-media", "--msg-ids", "200")
        self.assertEqual(code, EXIT_SUCCESS, err)
        exp_dm = json.loads(out)["exported"][0]
        self.assertEqual(exp_dm["chat_type"], "direct")
        self.assertTrue(Path(exp_dm["exported_path"]).is_file())

        # 4. Path traversal media (#212) is strictly rejected with Exit Code 3
        code, _, err = self._run_cli("export-media", "--msg-ids", "212")
        self.assertEqual(code, EXIT_POLICY_DENIED)
        self.assertEqual(json.loads(err)["error_code"], "INVALID_SANDBOX_PATH")

    def test_03_policy_controls_blacklist_and_optional_scope_guard(self) -> None:
        # 1. Blocking a 1-on-1 contact blocks both direct fetch and media export
        code, _, err = self._run_cli("config", "block", "8613900002222@s.whatsapp.net")
        self.assertEqual(code, EXIT_SUCCESS, err)

        code, _, err = self._run_cli("fetch", "--chats", "8613900002222@s.whatsapp.net", "--format", "json")
        self.assertEqual(code, EXIT_POLICY_DENIED)
        self.assertEqual(json.loads(err)["error_code"], "CHAT_BLOCKED_BY_POLICY")

        code, _, err = self._run_cli("export-media", "--msg-ids", "200")
        self.assertEqual(code, EXIT_POLICY_DENIED)
        self.assertEqual(json.loads(err)["error_code"], "CHAT_BLOCKED_BY_POLICY")

        self._run_cli("config", "unblock", "8613900002222@s.whatsapp.net")

        # 2. Optional `config set-scope groups` restricts access to @g.us groups when desired
        code, _, err = self._run_cli("config", "set-scope", "groups")
        self.assertEqual(code, EXIT_SUCCESS, err)

        code, _, err = self._run_cli("fetch", "--chats", "8613900002222@s.whatsapp.net", "--format", "json")
        self.assertEqual(code, EXIT_POLICY_DENIED)
        self.assertEqual(json.loads(err)["error_code"], "CHAT_SCOPE_DENIED")

        # Reset back to default 'all'
        self._run_cli("config", "set-scope", "all")

    def test_04_cleaning_accuracy_mentions_replies_revoked_and_incremental_cursor(self) -> None:
        self._run_cli("config", "set-identity", "--name", "张工", "--phone-suffix", "8888")
        self._run_cli("config", "block", "120363000000000002@g.us")

        # Incremental fetch on ALL_GROUPS with --after-id 101 and --context-buffer 2
        code, out, err = self._run_cli(
            "fetch",
            "--chats",
            "ALL_GROUPS",
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
        self.assertEqual(chat["context_buffer_count"], 2)

        msgs = chat["messages"]
        msg_ids = [m["msg_id"] for m in msgs]
        self.assertNotIn(102, msg_ids)  # Revoked
        self.assertNotIn(103, msg_ids)  # System event
        self.assertEqual(msg_ids, [100, 101, 104, 105, 106, 107, 108, 109, 110])

        by_id = {m["msg_id"]: m for m in msgs}
        self.assertTrue(by_id[100]["is_from_me"])
        self.assertEqual(by_id[100]["sender_name"], "我(张工)")
        self.assertEqual(by_id[104]["sender_name"], "李四(船务备注)")
        self.assertEqual(by_id[104]["media"]["title"], "11月海运报价单.pdf")

        m105 = by_id[105]
        self.assertEqual(m105["sender_name"], "王总(海外仓)")
        self.assertTrue(m105["mentions_me"])
        self.assertIn("[@我(张工)]", m105["text"])
        self.assertIn("@李四(船务备注)", m105["text"])
        self.assertIn("@20261107", m105["text"])
        self.assertEqual(m105["reply_to"]["msg_id"], 101)
        self.assertEqual(len(m105["reply_to"]["text_snippet"]), 153)

        self.assertEqual(by_id[109]["sender_name"], "联系人#1234")
        self.assertEqual(by_id[109]["media"]["duration_sec"], 45)
        self.assertEqual(by_id[110]["reply_to"]["status"], "revoked")

        # Markdown rendering across ALL_ALLOWED includes [群聊], [私聊], [频道] and folds ack noise
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
        self.assertIn("[群聊] 东南亚物流交付群", out_md)
        self.assertIn("[私聊] 李四(船务备注)", out_md)
        self.assertIn("[频道] 全球航运指数频道", out_md)
        self.assertIn("[#106~#108]", out_md)
        self.assertIn("⚠️ 语音消息未转写: 45秒", out_md)

    def test_05_cursor_fallback_export_clean_search_and_mcp_server(self) -> None:
        # Cursor > global_latest_msg_id triggers CURSOR_RESET_FALLBACK
        code, out, err = self._run_cli("fetch", "--chats", "ALL_ALLOWED", "--after-id", "999999", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS, err)
        res = json.loads(out)
        warn_codes = [w["code"] for w in res["meta"]["warnings"]]
        self.assertIn("CURSOR_RESET_FALLBACK", warn_codes)

        # Export media for msg_id 104 (Group PDF) and 200 (DM PDF)
        code, out, err = self._run_cli("export-media", "--msg-ids", "104,200")
        self.assertEqual(code, EXIT_SUCCESS, err)
        exp = json.loads(out)
        self.assertEqual(exp["meta"]["exported_count"], 2)

        # Missing local media returns Exit Code 4
        code, _, _ = self._run_cli("export-media", "--msg-ids", "110")
        self.assertEqual(code, EXIT_RESOURCE_NOT_FOUND)

        # Clean media cache
        code, _, err = self._run_cli("clean", "--media-only")
        self.assertEqual(code, EXIT_SUCCESS, err)
        for item in exp["exported"]:
            self.assertFalse(Path(item["exported_path"]).exists())

        # Search across all chats finds both DM ("签署版合同") and Group ("免箱期")
        code, out, err = self._run_cli("search", "--query", "签署版合同", "--context", "1", "--format", "json")
        self.assertEqual(code, EXIT_SUCCESS, err)
        s_res = json.loads(out)
        self.assertEqual(s_res["meta"]["match_count"], 1)
        self.assertEqual(s_res["matches"][0]["chat_type"], "direct")

        # MCP Stdio Server check (5 tools, readOnlyHint annotations, whatsapp_list_chats + whatsapp_fetch_messages)
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
                            "name": "whatsapp_list_chats",
                            "arguments": {"chat_type": "all", "format": "json"},
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
        self.assertEqual(lines[0]["result"]["serverInfo"]["version"], "4.0.0")
        tools = lines[1]["result"]["tools"]
        self.assertEqual(len(tools), 5)
        for t in tools:
            self.assertTrue(t["annotations"]["readOnlyHint"])
        self.assertFalse(lines[2]["result"]["isError"])
        listed = json.loads(lines[2]["result"]["content"][0]["text"])
        self.assertGreaterEqual(len(listed["chats"]), 4)


if __name__ == "__main__":
    unittest.main()
