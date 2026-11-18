"""Zero-dependency Model Context Protocol (MCP) Stdio Server for WhatsApp-LocalMind."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import AppConfig
from .constants import DEFAULT_FETCH_LIMIT, VALID_CHAT_TYPES
from .db import QueryEngine
from .errors import UsageError, WALocalMindError
from .formatter import (
    format_chats_markdown,
    format_fetch_markdown,
    format_groups_markdown,
    format_json_output,
    format_search_markdown,
)
from .media import MediaExporter
from .snapshot import SnapshotManager

READONLY_TOOL_ANNOTATIONS: dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

MCP_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "whatsapp_list_chats",
        "description": (
            "List accessible macOS WhatsApp chat sessions across 1-on-1 direct DMs (@s.whatsapp.net / @lid), "
            "group chats (@g.us), and channels (@newsletter), including chat_id, chat_name, chat_type, "
            "latest_msg_id cursor, 24h message count, and member count."
        ),
        "annotations": dict(READONLY_TOOL_ANNOTATIONS),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_type": {
                    "type": "string",
                    "enum": list(VALID_CHAT_TYPES),
                    "description": "Filter by session type: 'all' (default), 'direct', 'group', 'newsletter', or 'broadcast'.",
                    "default": "all",
                },
                "keyword": {
                    "type": "string",
                    "description": "Optional case-insensitive keyword filter for chat name or JID.",
                },
                "include_blocked": {
                    "type": "boolean",
                    "description": "Whether to include chats blocked by current scope or blacklist/whitelist policy.",
                    "default": False,
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "markdown"],
                    "default": "json",
                },
                "fresh": {
                    "type": "boolean",
                    "description": "Force immediate SQLite online backup snapshot refresh.",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "whatsapp_list_groups",
        "description": (
            "List accessible macOS WhatsApp group chats (@g.us), including chat_id, group_name, "
            "latest_msg_id cursor, 24h message count, and member count."
        ),
        "annotations": dict(READONLY_TOOL_ANNOTATIONS),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Optional case-insensitive keyword filter for group name.",
                },
                "include_blocked": {
                    "type": "boolean",
                    "description": "Whether to include groups blocked by blacklist/whitelist policy.",
                    "default": False,
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "markdown"],
                    "default": "json",
                },
                "fresh": {
                    "type": "boolean",
                    "description": "Force immediate SQLite online backup snapshot refresh.",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "whatsapp_fetch_messages",
        "description": (
            "Fetch cleaned WhatsApp messages across 1-on-1 direct chats, group chats, or channels by "
            "incremental cursor (after_msg_id) or time window (since). Automatically resolves real names, "
            "@lid identities, @mentions, 150-char reply chains, filters out revoked messages, and prepends context buffer."
        ),
        "annotations": dict(READONLY_TOOL_ANNOTATIONS),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Array of WhatsApp chat_ids (@s.whatsapp.net, @lid, @g.us, @newsletter) "
                        "or ['ALL_ALLOWED'] / ['ALL_DIRECT'] / ['ALL_GROUPS']."
                    ),
                },
                "chat_type": {
                    "type": "string",
                    "enum": list(VALID_CHAT_TYPES),
                    "description": "Optional session type filter ('all', 'direct', 'group', 'newsletter').",
                    "default": "all",
                },
                "after_msg_id": {
                    "type": "integer",
                    "description": "Global monotonic message cursor (Z_PK). Fetches only messages with msg_id > after_msg_id.",
                },
                "since": {
                    "type": "string",
                    "description": "Relative duration (e.g. '12h', '24h', '7d') or ISO-8601 timestamp when after_msg_id is not set.",
                    "default": "24h",
                },
                "until": {
                    "type": "string",
                    "description": "Optional upper bound ISO-8601 timestamp.",
                },
                "context_buffer": {
                    "type": "integer",
                    "description": "Number of preceding history messages to include as context buffer (default 10).",
                    "default": 10,
                },
                "limit_per_chat": {
                    "type": "integer",
                    "description": "Max messages per chat session (default 500, max 3000).",
                    "default": 500,
                },
                "fold_noise": {
                    "type": "boolean",
                    "description": "Fold consecutive short acknowledgment messages ('收到', 'OK', '+1') in markdown mode.",
                    "default": True,
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "default": "markdown",
                },
                "fresh": {
                    "type": "boolean",
                    "description": "Force immediate SQLite online backup snapshot refresh.",
                    "default": False,
                },
            },
            "required": ["chat_ids"],
        },
    },
    {
        "name": "whatsapp_search_messages",
        "description": (
            "Search keyword across allowed WhatsApp 1-on-1 direct chats, group chats, and channels, "
            "returning matching messages with surrounding context messages."
        ),
        "annotations": dict(READONLY_TOOL_ANNOTATIONS),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in message text, media captions, and attachment titles.",
                },
                "chat_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of chat_ids or ['ALL_ALLOWED'] / ['ALL_DIRECT'] / ['ALL_GROUPS'].",
                },
                "chat_type": {
                    "type": "string",
                    "enum": list(VALID_CHAT_TYPES),
                    "description": "Optional session type filter ('all', 'direct', 'group', 'newsletter').",
                    "default": "all",
                },
                "since": {
                    "type": "string",
                    "description": "Optional time window filter (e.g. '30d', '7d').",
                },
                "context": {
                    "type": "integer",
                    "description": "Number of before/after context messages per match (default 3).",
                    "default": 3,
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                },
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "default": "markdown",
                },
                "fresh": {
                    "type": "boolean",
                    "description": "Force immediate SQLite online backup snapshot refresh.",
                    "default": False,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "whatsapp_export_media",
        "description": (
            "Safely export local WhatsApp media attachments (voice .opus, documents .pdf/.xlsx, images, videos) "
            "from allowed chats by msg_id to the shared snapshot/media directory and return absolute file paths."
        ),
        "annotations": dict(READONLY_TOOL_ANNOTATIONS),
        "inputSchema": {
            "type": "object",
            "properties": {
                "msg_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of target message msg_ids to export.",
                },
                "fresh": {
                    "type": "boolean",
                    "description": "Force immediate SQLite online backup snapshot refresh.",
                    "default": False,
                },
            },
            "required": ["msg_ids"],
        },
    },
]

VALID_MCP_TOOL_NAMES = frozenset(t["name"] for t in MCP_TOOLS_SCHEMA)


def _execute_mcp_tool(
    name: str,
    arguments: dict[str, Any],
    config_path: Path | None = None,
) -> tuple[str, bool]:
    if name not in VALID_MCP_TOOL_NAMES:
        return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False), True
    if not isinstance(arguments, dict):
        raise UsageError("MCP tool `arguments` must be a JSON object.")

    cfg = AppConfig.load(config_path)
    snap_mgr = SnapshotManager(cfg)
    fresh = bool(arguments.get("fresh", False))
    snap = snap_mgr.ensure_snapshot(force_fresh=fresh)

    if name == "whatsapp_list_chats":
        with QueryEngine(cfg, snap) as engine:
            res = engine.list_chats(
                keyword=arguments.get("keyword"),
                include_blocked=bool(arguments.get("include_blocked", False)),
                chat_type=str(arguments.get("chat_type", "all")),
            )
        fmt = arguments.get("format", "json")
        if fmt in ("md", "markdown"):
            return format_chats_markdown(res), False
        return format_json_output(res), False

    if name == "whatsapp_list_groups":
        with QueryEngine(cfg, snap) as engine:
            res = engine.list_groups(
                keyword=arguments.get("keyword"),
                include_blocked=bool(arguments.get("include_blocked", False)),
            )
        fmt = arguments.get("format", "json")
        if fmt in ("md", "markdown"):
            return format_groups_markdown(res), False
        return format_json_output(res), False

    if name == "whatsapp_fetch_messages":
        chat_ids = arguments.get("chat_ids") or ["ALL_ALLOWED"]
        if isinstance(chat_ids, str):
            chat_ids = [c.strip() for c in chat_ids.split(",") if c.strip()]
        with QueryEngine(cfg, snap) as engine:
            res = engine.fetch_messages(
                chat_ids=chat_ids,
                after_msg_id=arguments.get("after_msg_id"),
                since_str=arguments.get("since"),
                until_str=arguments.get("until"),
                context_buffer_count=arguments.get("context_buffer"),
                limit_per_chat=int(arguments.get("limit_per_chat", DEFAULT_FETCH_LIMIT)),
                chat_type=str(arguments.get("chat_type", "all")),
            )
        fmt = arguments.get("format", "markdown")
        if fmt == "json":
            return format_json_output(res), False
        fold = bool(arguments.get("fold_noise", cfg.cleaning.fold_noise_markdown))
        return format_fetch_markdown(
            res,
            fold_noise=fold,
            long_audio_threshold_sec=cfg.cleaning.long_audio_threshold_sec,
        ), False

    if name == "whatsapp_search_messages":
        chat_ids = arguments.get("chat_ids")
        if isinstance(chat_ids, str):
            chat_ids = [c.strip() for c in chat_ids.split(",") if c.strip()]
        with QueryEngine(cfg, snap) as engine:
            res = engine.search_messages(
                query=str(arguments.get("query", "")),
                chat_ids=chat_ids,
                since_str=arguments.get("since"),
                context_window=int(arguments.get("context", 3)),
                limit=int(arguments.get("limit", 50)),
                chat_type=str(arguments.get("chat_type", "all")),
            )
        fmt = arguments.get("format", "markdown")
        if fmt == "json":
            return format_json_output(res), False
        return format_search_markdown(
            res,
            long_audio_threshold_sec=cfg.cleaning.long_audio_threshold_sec,
        ), False

    if name == "whatsapp_export_media":
        raw_ids = arguments.get("msg_ids") or []
        msg_ids = [int(x) for x in raw_ids]
        exporter = MediaExporter(cfg, snap)
        res = exporter.export_media_by_msg_ids(msg_ids)
        return format_json_output(res), False

    return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False), True


def _dispatch_single_rpc(req: Any, config_path: Path | None) -> dict[str, Any] | None:
    if not isinstance(req, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request: expected JSON object"},
        }

    req_id = req.get("id")
    method = req.get("method", "")
    raw_params = req.get("params")

    if req_id is None:
        return None

    if not isinstance(method, str) or not method:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "Invalid Request: missing method string"},
        }

    if raw_params is not None and not isinstance(raw_params, dict):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": "Invalid params: expected JSON object"},
        }
    params = raw_params or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "whatsapp-localmind",
                    "version": __version__,
                },
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS_SCHEMA},
        }
    if method == "tools/call":
        tool_name = str(params.get("name", ""))
        tool_args = params.get("arguments")
        if tool_args is None:
            tool_args = {}
        try:
            text_out, is_err = _execute_mcp_tool(tool_name, tool_args, config_path)
        except WALocalMindError as exc:
            err_payload = {
                "error_code": exc.error_code,
                "exit_code": exc.exit_code,
                "message": exc.message,
            }
            text_out = json.dumps(err_payload, ensure_ascii=False, indent=2)
            is_err = True
        except Exception as exc:
            text_out = json.dumps({"error": str(exc)}, ensure_ascii=False)
            is_err = True

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": text_out}],
                "isError": is_err,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_mcp_stdio_server(config_path: Path | None = None) -> int:
    """Run JSON-RPC 2.0 MCP Server over stdin/stdout."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, list):
            if not parsed:
                out_payload: Any = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request: empty batch"},
                }
            else:
                batch_resps = [
                    r for r in (_dispatch_single_rpc(item, config_path) for item in parsed) if r is not None
                ]
                if not batch_resps:
                    continue
                out_payload = batch_resps
        else:
            resp = _dispatch_single_rpc(parsed, config_path)
            if resp is None:
                continue
            out_payload = resp

        sys.stdout.write(json.dumps(out_payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    return 0
