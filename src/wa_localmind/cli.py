"""CLI entrypoint and subcommand dispatcher for `whatsapp-localmind`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import AppConfig
from .constants import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_FETCH_LIMIT,
    EXIT_INTERNAL_DB_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    VALID_CHAT_SCOPES,
    VALID_CHAT_TYPES,
)
from .db import QueryEngine
from .errors import EnvOrPermissionError, UsageError, WALocalMindError
from .formatter import (
    format_chats_markdown,
    format_fetch_markdown,
    format_groups_markdown,
    format_json_output,
    format_search_markdown,
)
from .mcp_server import run_mcp_stdio_server
from .media import MediaExporter
from .snapshot import SnapshotManager


class _RigorousArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that raises UsageError (Exit Code 1) instead of default exit(2)."""

    def error(self, message: str) -> None:
        raise UsageError(message)


def _split_csv_list(items: list[str] | str | None) -> list[str]:
    if not items:
        return []
    if isinstance(items, str):
        items = [items]
    out: list[str] = []
    for item in items:
        for part in item.split(","):
            clean = part.strip()
            if clean:
                out.append(clean)
    return out


def _add_common_options(parser: argparse.ArgumentParser, default_format: str = "json") -> None:
    parser.add_argument(
        "--format",
        choices=["json", "md", "markdown"],
        default=default_format,
        help=f"Output format: json or md (default: {default_format}).",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore TTL cache and force immediate SQLite online backup refresh.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Path to config.json (default: {DEFAULT_CONFIG_PATH}).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-fatal diagnostic messages on stderr.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _RigorousArgumentParser(
        prog="whatsapp-localmind",
        description="WhatsApp-LocalMind: macOS WhatsApp Local Chat Data Extraction Capability Layer (CLI & MCP).",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"whatsapp-localmind {__version__}",
    )

    subparsers = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")

    # 1. doctor
    p_doc = subparsers.add_parser(
        "doctor",
        help="Run environment, TCC permission, and database health checks.",
    )
    _add_common_options(p_doc, default_format="json")

    # 2. config
    p_cfg = subparsers.add_parser(
        "config",
        help="Inspect or update identity anchor, chat scope, and blacklist/whitelist rules.",
    )
    cfg_sub = p_cfg.add_subparsers(dest="config_action", metavar="<action>")

    p_cfg_show = cfg_sub.add_parser("show", help="Print current configuration as JSON.")
    _add_common_options(p_cfg_show, default_format="json")

    p_cfg_id = cfg_sub.add_parser("set-identity", help="Set user's display name and phone suffix anchor.")
    p_cfg_id.add_argument("--name", required=True, help="Your display name (e.g. '张工').")
    p_cfg_id.add_argument("--phone-suffix", default="", help="Last 4+ digits of your phone number (e.g. '8888').")
    p_cfg_id.add_argument(
        "--jid",
        action="append",
        default=[],
        help="Optional full JID or numeric prefix (repeatable or comma-separated).",
    )
    _add_common_options(p_cfg_id, default_format="json")

    p_cfg_scope = cfg_sub.add_parser(
        "set-scope",
        help="Set accessible session scope (all | groups | direct | newsletter).",
    )
    p_cfg_scope.add_argument(
        "scope",
        choices=list(VALID_CHAT_SCOPES),
        help="Target chat scope ('all' enables all chats; 'groups' restricts to @g.us; 'direct' restricts to 1-on-1 DMs).",
    )
    _add_common_options(p_cfg_scope, default_format="json")

    p_cfg_mode = cfg_sub.add_parser("set-mode", help="Switch chat filtering mode (blacklist | whitelist).")
    p_cfg_mode.add_argument("mode", choices=["blacklist", "whitelist"], help="Target filter mode.")
    _add_common_options(p_cfg_mode, default_format="json")

    for act, help_txt in (
        ("block", "Add chat_id(s) (group, direct DM, or channel) to blacklist."),
        ("unblock", "Remove chat_id(s) from blacklist."),
        ("allow", "Add chat_id(s) (group, direct DM, or channel) to whitelist."),
        ("disallow", "Remove chat_id(s) from whitelist."),
    ):
        p_act = cfg_sub.add_parser(act, help=help_txt)
        p_act.add_argument(
            "chats",
            nargs="+",
            help="One or more WhatsApp chat_ids (@s.whatsapp.net, @lid, @g.us, @newsletter), comma-separated.",
        )
        _add_common_options(p_act, default_format="json")

    # 3. chats / list-chats (primary all-chats listing)
    for cmd_name in ("chats", "list-chats"):
        p_chats = subparsers.add_parser(
            cmd_name,
            help="List accessible WhatsApp chat sessions (1-on-1 DMs, groups, channels) and latest cursors.",
        )
        p_chats.add_argument(
            "--type",
            dest="chat_type",
            choices=list(VALID_CHAT_TYPES),
            default="all",
            help="Filter by chat type: all (default), direct, group, newsletter, or broadcast.",
        )
        p_chats.add_argument("--keyword", default=None, help="Filter chats by name or chat_id keyword.")
        p_chats.add_argument(
            "--include-blocked",
            action="store_true",
            help="Include chats blocked by current scope or blacklist/whitelist policy.",
        )
        _add_common_options(p_chats, default_format="json")

    # 4. groups / list-groups (backward-compatible group-filtered alias)
    for cmd_name in ("groups", "list-groups"):
        p_grp = subparsers.add_parser(
            cmd_name,
            help="List accessible WhatsApp group chats (@g.us) and their latest message cursors.",
        )
        p_grp.add_argument("--keyword", default=None, help="Filter groups by name or chat_id keyword.")
        p_grp.add_argument(
            "--include-blocked",
            action="store_true",
            help="Include groups blocked by current blacklist/whitelist policy.",
        )
        _add_common_options(p_grp, default_format="json")

    # 5. fetch
    p_fetch = subparsers.add_parser(
        "fetch",
        help="Fetch cleaned WhatsApp messages across 1-on-1 DMs, groups, or channels by cursor (--after-id) or time window (--since).",
    )
    p_fetch.add_argument(
        "--chats",
        required=True,
        action="append",
        help="Comma-separated chat_ids (@s.whatsapp.net, @lid, @g.us, @newsletter) or 'ALL_ALLOWED' / 'ALL_DIRECT' / 'ALL_GROUPS'.",
    )
    p_fetch.add_argument(
        "--type",
        dest="chat_type",
        choices=list(VALID_CHAT_TYPES),
        default="all",
        help="Optional session type filter (all, direct, group, newsletter, broadcast).",
    )
    p_fetch.add_argument(
        "--after-id",
        type=int,
        default=None,
        help="Global monotonic message cursor (msg_id / Z_PK). Fetches only messages with msg_id > after-id.",
    )
    p_fetch.add_argument(
        "--since",
        default=None,
        help="Relative time window (e.g. '12h', '24h', '7d') or ISO-8601 timestamp when --after-id is not set.",
    )
    p_fetch.add_argument(
        "--until",
        default=None,
        help="Optional upper bound ISO-8601 timestamp or relative time.",
    )
    p_fetch.add_argument(
        "--context-buffer",
        type=int,
        default=None,
        help="Number of preceding messages per chat to include as context buffer (default: 10).",
    )
    p_fetch.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_FETCH_LIMIT,
        help=f"Maximum messages per chat session (default: {DEFAULT_FETCH_LIMIT}, max: 3000).",
    )
    fold_grp = p_fetch.add_mutually_exclusive_group()
    fold_grp.add_argument(
        "--fold",
        dest="fold_override",
        action="store_true",
        default=None,
        help="Force enable folding of consecutive short acknowledgment messages.",
    )
    fold_grp.add_argument(
        "--no-fold",
        dest="fold_override",
        action="store_false",
        default=None,
        help="Disable folding of short acknowledgment messages.",
    )
    p_fetch.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Optional file path to save the output (in addition to stdout).",
    )
    _add_common_options(p_fetch, default_format="md")

    # 6. search
    p_search = subparsers.add_parser(
        "search",
        help="Search messages across allowed WhatsApp chats (1-on-1 DMs, groups, channels) with surrounding context.",
    )
    p_search.add_argument("--query", "-k", required=True, help="Keyword to search in messages and attachment titles.")
    p_search.add_argument(
        "--chats",
        action="append",
        default=None,
        help="Optional chat_ids or 'ALL_ALLOWED' / 'ALL_DIRECT' / 'ALL_GROUPS'.",
    )
    p_search.add_argument(
        "--type",
        dest="chat_type",
        choices=list(VALID_CHAT_TYPES),
        default="all",
        help="Optional session type filter (all, direct, group, newsletter, broadcast).",
    )
    p_search.add_argument("--since", default=None, help="Optional time window filter (e.g. '30d', '7d').")
    p_search.add_argument(
        "--context",
        type=int,
        default=3,
        help="Number of before/after context messages around each match (default: 3).",
    )
    p_search.add_argument("--limit", type=int, default=50, help="Maximum matched messages to return (default: 50).")
    _add_common_options(p_search, default_format="md")

    # 7. export-media
    p_media = subparsers.add_parser(
        "export-media",
        help="Safely export chat media attachments (voice, PDF, Excel, images, videos) by msg_id.",
    )
    p_media.add_argument(
        "--msg-ids",
        "--msg-id",
        dest="msg_ids",
        required=True,
        action="append",
        help="Comma-separated target message msg_id(s) to export.",
    )
    p_media.add_argument(
        "--dest-dir",
        type=Path,
        default=None,
        help="Optional destination directory (default: snapshot/media/).",
    )
    _add_common_options(p_media, default_format="json")

    # 8. clean
    p_clean = subparsers.add_parser(
        "clean",
        help="Clean exported media cache or destroy local SQLite snapshot files.",
    )
    p_clean.add_argument(
        "--media-only",
        action="store_true",
        help="Only remove exported media files under snapshot/media/, keeping SQLite snapshot.",
    )
    p_clean.add_argument(
        "--all",
        action="store_true",
        help="Remove both exported media cache and SQLite snapshot files (default).",
    )
    _add_common_options(p_clean, default_format="json")

    # 9. mcp-serve
    p_mcp = subparsers.add_parser(
        "mcp-serve",
        help="Start read-only Model Context Protocol (MCP) Server over Stdio.",
    )
    p_mcp.add_argument("--config", type=Path, default=None, help="Optional path to config.json.")

    # 10. install
    p_inst = subparsers.add_parser(
        "install",
        help="Install `whatsapp-localmind` CLI symlink to ~/.local/bin and optionally install SKILL.md bundle.",
    )
    p_inst.add_argument(
        "--bin-dir",
        type=Path,
        default=Path.home() / ".local" / "bin",
        help="Target directory for CLI symlink (default: ~/.local/bin).",
    )
    p_inst.add_argument(
        "--skill-dir",
        type=Path,
        default=None,
        help="Optional target skills parent directory (e.g. ~/.gemini/config/skills or ~/.claude/skills).",
    )

    return parser


def _handle_doctor(args: argparse.Namespace) -> str:
    cfg = AppConfig.load(args.config)
    snap_mgr = SnapshotManager(cfg)
    src_check = snap_mgr.check_source_access()

    snapshot_status: dict[str, Any] = {"ok": False}
    warnings: list[dict[str, Any]] = []
    if src_check.get("source_db_readable"):
        snap = snap_mgr.ensure_snapshot(force_fresh=args.fresh)
        with QueryEngine(cfg, snap) as engine:
            warnings = engine.build_common_warnings()
        snapshot_status = {
            "ok": True,
            "snapshot_db_path": str(snap.snapshot_db_path),
            "snapshot_time": snap.snapshot_time_iso,
            "snapshot_age_sec": snap.snapshot_age_sec,
            "db_latest_msg_time": snap.db_latest_msg_time_iso,
            "global_latest_msg_id": snap.global_latest_msg_id,
            "backup_duration_ms": snap.backup_duration_ms,
        }

    overall_healthy = bool(src_check.get("source_db_readable") and snapshot_status.get("ok"))
    report = {
        "healthy": overall_healthy,
        "version": __version__,
        "source_database": src_check,
        "snapshot_engine": snapshot_status,
        "config": {
            "config_path": str(args.config or DEFAULT_CONFIG_PATH),
            "chat_scope": cfg.chat_scope,
            "filter_mode": cfg.filter_mode,
            "identity_label": cfg.my_display_label,
            "blacklist_count": len(cfg.blacklist_chats),
            "whitelist_count": len(cfg.whitelist_chats),
        },
        "warnings": warnings,
    }
    if not overall_healthy:
        raise EnvOrPermissionError(
            src_check.get("error") or "WhatsApp local database check failed.",
            error_code="DOCTOR_CHECK_FAILED",
        )
    if args.format in ("md", "markdown"):
        lines = [
            "# WhatsApp-LocalMind 环境与权限自检报告 (Doctor)",
            f"- 整体状态: {'🟢 正常就绪 (Healthy)' if overall_healthy else '🔴 异常'}",
            f"- 原库路径: `{src_check['source_db_path']}` (可读: `{src_check['source_db_readable']}`)",
            (
                f"- 会话统计: 共 `{src_check.get('total_session_count', 0)}` 个会话 "
                f"(私聊: `{src_check.get('direct_session_count', 0)}`, 群聊: `{src_check.get('group_session_count', 0)}`)"
            ),
            f"- 快照路径: `{snapshot_status.get('snapshot_db_path')}` (备份耗时: `{snapshot_status.get('backup_duration_ms')} ms`)",
            f"- 全局最新消息游标 (`global_latest_msg_id`): `{snapshot_status.get('global_latest_msg_id')}`",
            f"- 原库最后活跃时间: `{snapshot_status.get('db_latest_msg_time')}`",
            f"- 当前身份锚点: `{cfg.my_display_label}` | 会话范围: `{cfg.chat_scope}` | 过滤模式: `{cfg.filter_mode}`",
        ]
        for w in warnings:
            lines.append(f"- [⚠️ 预警 {w.get('code')}]: {w.get('message')}")
        return "\n".join(lines) + "\n"
    return format_json_output(report)


def _handle_config(args: argparse.Namespace) -> str:
    action = args.config_action or "show"
    cfg_path = getattr(args, "config", None)
    cfg = AppConfig.load(cfg_path)

    if action == "show":
        return format_json_output(cfg.to_dict())

    if action == "set-identity":
        cfg.identity.name = args.name.strip() or "我"
        cfg.identity.phone_suffix = (args.phone_suffix or "").strip()
        jids = _split_csv_list(args.jid)
        if jids:
            cfg.identity.jid_prefixes = jids
        saved = cfg.save(cfg_path)
        return format_json_output({"status": "updated", "config_path": str(saved), "identity": cfg.to_dict()["identity"]})

    if action == "set-scope":
        cfg.chat_scope = args.scope
        saved = cfg.save(cfg_path)
        return format_json_output({"status": "updated", "config_path": str(saved), "chat_scope": cfg.chat_scope})

    if action == "set-mode":
        cfg.filter_mode = args.mode
        saved = cfg.save(cfg_path)
        return format_json_output({"status": "updated", "config_path": str(saved), "filter_mode": cfg.filter_mode})

    raw_chats = _split_csv_list(getattr(args, "chats", []))
    chats: list[str] = []
    for c in raw_chats:
        norm_c = f"{c.lstrip('+')}@s.whatsapp.net" if ("@" not in c and c.lstrip("+").isdigit() and len(c.lstrip("+")) >= 6) else c
        if not AppConfig.is_valid_chat_jid(norm_c):
            raise UsageError(
                f"Invalid WhatsApp chat_id '{c}': expected JID ending with '@s.whatsapp.net', '@lid', '@g.us', or '@newsletter'."
            )
        chats.append(norm_c)

    if action == "block":
        for c in chats:
            if c not in cfg.blacklist_chats:
                cfg.blacklist_chats.append(c)
    elif action == "unblock":
        cfg.blacklist_chats = [x for x in cfg.blacklist_chats if x not in chats]
    elif action == "allow":
        for c in chats:
            if c not in cfg.whitelist_chats:
                cfg.whitelist_chats.append(c)
    elif action == "disallow":
        cfg.whitelist_chats = [x for x in cfg.whitelist_chats if x not in chats]
    else:
        raise UsageError(f"Unknown config action: {action}")

    saved = cfg.save(cfg_path)
    return format_json_output(
        {
            "status": "updated",
            "action": action,
            "config_path": str(saved),
            "chat_scope": cfg.chat_scope,
            "filter_mode": cfg.filter_mode,
            "blacklist_chats": cfg.blacklist_chats,
            "whitelist_chats": cfg.whitelist_chats,
        }
    )


def _handle_install(args: argparse.Namespace) -> str:
    import os
    import shutil

    pkg_dir = Path(__file__).resolve().parent
    repo_root = pkg_dir.parent.parent
    bin_script = repo_root / "bin" / "whatsapp-localmind"
    if not bin_script.exists():
        bin_script = pkg_dir.parent / "whatsapp-localmind"

    bin_dir = args.bin_dir.expanduser().resolve()
    bin_dir.mkdir(parents=True, exist_ok=True)
    target_bin = bin_dir / "whatsapp-localmind"
    if target_bin.is_symlink() or target_bin.exists():
        target_bin.unlink()
    os.symlink(str(bin_script), str(target_bin))

    skill_installed_to: str | None = None
    if args.skill_dir:
        src_skill_dir = repo_root / "skills" / "whatsapp-localmind"
        dst_skill_dir = args.skill_dir.expanduser().resolve() / "whatsapp-localmind"
        if dst_skill_dir.is_symlink():
            if dst_skill_dir.resolve() == src_skill_dir.resolve():
                skill_installed_to = str(dst_skill_dir)
                return format_json_output(
                    {
                        "status": "installed",
                        "cli_symlink": str(target_bin),
                        "cli_target": str(bin_script),
                        "skill_bundle_dir": skill_installed_to,
                    }
                )
            dst_skill_dir.unlink()
        elif dst_skill_dir.exists():
            shutil.rmtree(dst_skill_dir)
        dst_skill_dir.mkdir(parents=True, exist_ok=True)
        if (src_skill_dir / "SKILL.md").exists():
            shutil.copy2(src_skill_dir / "SKILL.md", dst_skill_dir / "SKILL.md")
        dst_scripts = dst_skill_dir / "scripts"
        dst_scripts.mkdir(parents=True, exist_ok=True)
        if (src_skill_dir / "scripts" / "whatsapp-localmind").exists():
            shutil.copy2(src_skill_dir / "scripts" / "whatsapp-localmind", dst_scripts / "whatsapp-localmind")
            (dst_scripts / "whatsapp-localmind").chmod(0o755)
        shutil.copytree(
            pkg_dir,
            dst_scripts / "wa_localmind",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        skill_installed_to = str(dst_skill_dir)

    return format_json_output(
        {
            "status": "installed",
            "cli_symlink": str(target_bin),
            "cli_target": str(bin_script),
            "skill_bundle_dir": skill_installed_to,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if not args.subcommand:
            parser.print_help(sys.stderr)
            return EXIT_USAGE_ERROR

        if args.subcommand == "mcp-serve":
            return run_mcp_stdio_server(args.config)

        if args.subcommand == "install":
            out = _handle_install(args)
            sys.stdout.write(out)
            return EXIT_SUCCESS

        if args.subcommand == "doctor":
            out = _handle_doctor(args)
            sys.stdout.write(out)
            return EXIT_SUCCESS

        if args.subcommand == "config":
            out = _handle_config(args)
            sys.stdout.write(out)
            return EXIT_SUCCESS

        cfg = AppConfig.load(args.config)
        snap_mgr = SnapshotManager(cfg)

        if args.subcommand == "clean":
            res = snap_mgr.clean(media_only=bool(args.media_only and not args.all))
            sys.stdout.write(format_json_output(res))
            return EXIT_SUCCESS

        snap = snap_mgr.ensure_snapshot(force_fresh=args.fresh)

        if args.subcommand in ("chats", "list-chats"):
            with QueryEngine(cfg, snap) as engine:
                res = engine.list_chats(
                    keyword=args.keyword,
                    include_blocked=args.include_blocked,
                    chat_type=args.chat_type,
                )
            if args.format in ("md", "markdown"):
                out = format_chats_markdown(res)
            else:
                out = format_json_output(res)
            sys.stdout.write(out)
            return EXIT_SUCCESS

        if args.subcommand in ("groups", "list-groups"):
            with QueryEngine(cfg, snap) as engine:
                res = engine.list_groups(
                    keyword=args.keyword,
                    include_blocked=args.include_blocked,
                )
            if args.format in ("md", "markdown"):
                out = format_groups_markdown(res)
            else:
                out = format_json_output(res)
            sys.stdout.write(out)
            return EXIT_SUCCESS

        if args.subcommand == "fetch":
            chat_ids = _split_csv_list(args.chats)
            with QueryEngine(cfg, snap) as engine:
                res = engine.fetch_messages(
                    chat_ids=chat_ids,
                    after_msg_id=args.after_id,
                    since_str=args.since,
                    until_str=args.until,
                    context_buffer_count=args.context_buffer,
                    limit_per_chat=args.limit,
                    chat_type=args.chat_type,
                )
            if args.format == "json":
                out = format_json_output(res)
            else:
                fold = (
                    cfg.cleaning.fold_noise_markdown
                    if args.fold_override is None
                    else bool(args.fold_override)
                )
                out = format_fetch_markdown(
                    res,
                    fold_noise=fold,
                    long_audio_threshold_sec=cfg.cleaning.long_audio_threshold_sec,
                )

            if args.output:
                out_path = args.output.expanduser().resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(out, encoding="utf-8")
            sys.stdout.write(out)
            return EXIT_SUCCESS

        if args.subcommand == "search":
            chat_ids = _split_csv_list(args.chats) if args.chats else None
            with QueryEngine(cfg, snap) as engine:
                res = engine.search_messages(
                    query=args.query,
                    chat_ids=chat_ids,
                    since_str=args.since,
                    context_window=args.context,
                    limit=args.limit,
                    chat_type=args.chat_type,
                )
            if args.format == "json":
                out = format_json_output(res)
            else:
                out = format_search_markdown(
                    res,
                    long_audio_threshold_sec=cfg.cleaning.long_audio_threshold_sec,
                )
            sys.stdout.write(out)
            return EXIT_SUCCESS

        if args.subcommand == "export-media":
            raw_ids = _split_csv_list(args.msg_ids)
            try:
                msg_ids = [int(x) for x in raw_ids]
            except ValueError as exc:
                raise UsageError(f"--msg-ids must be integers, got: {raw_ids}") from exc

            exporter = MediaExporter(cfg, snap)
            res = exporter.export_media_by_msg_ids(msg_ids, dest_dir=args.dest_dir)
            sys.stdout.write(format_json_output(res))
            return EXIT_SUCCESS

        raise UsageError(f"Unknown subcommand: {args.subcommand}")

    except WALocalMindError as exc:
        err_obj = {
            "error": True,
            "error_code": exc.error_code,
            "exit_code": exc.exit_code,
            "message": exc.message,
        }
        sys.stderr.write(json.dumps(err_obj, ensure_ascii=False) + "\n")
        return exc.exit_code
    except Exception as exc:
        err_obj = {
            "error": True,
            "error_code": "UNEXPECTED_INTERNAL_ERROR",
            "exit_code": EXIT_INTERNAL_DB_ERROR,
            "message": str(exc),
        }
        sys.stderr.write(json.dumps(err_obj, ensure_ascii=False) + "\n")
        return EXIT_INTERNAL_DB_ERROR


if __name__ == "__main__":
    sys.exit(main())
