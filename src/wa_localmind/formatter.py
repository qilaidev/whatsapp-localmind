"""Deterministic JSON Schema serializer and Markdown conversation stream renderer."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .cleaner import fold_consecutive_ack_messages
from .constants import DEFAULT_LONG_AUDIO_THRESHOLD_SEC

WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def format_human_bytes(num_bytes: int | None) -> str:
    if not num_bytes or num_bytes <= 0:
        return "未知大小"
    if num_bytes < 1024:
        return f"{num_bytes}B"
    if num_bytes < 1024 * 1024:
        return f"{round(num_bytes / 1024)}KB"
    return f"{round(num_bytes / (1024 * 1024), 1)}MB"


def iso_to_short_time(iso_str: str | None) -> str:
    if not iso_str:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str


def format_header_datetime(iso_str: str | None) -> str:
    if not iso_str:
        dt = datetime.now().astimezone()
    else:
        try:
            dt = datetime.fromisoformat(iso_str)
        except Exception:
            dt = datetime.now().astimezone()
    weekday = WEEKDAY_CN[dt.weekday()]
    tz_offset = dt.strftime("%z")
    if len(tz_offset) == 5:
        tz_label = f"UTC{tz_offset[:3]}:{tz_offset[3:]}"
    else:
        tz_label = "Local"
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} ({weekday}, {tz_label})"


def render_single_message_md(
    msg: dict[str, Any],
    long_audio_threshold_sec: int = DEFAULT_LONG_AUDIO_THRESHOLD_SEC,
) -> str:
    if msg.get("_folded_ack_summary"):
        t_str = iso_to_short_time(msg.get("timestamp"))
        return (
            f"[#{msg['start_msg_id']}~#{msg['end_msg_id']}] {t_str} "
            f"[系统折叠: {msg['sender_preview']} 回复了 \"{msg['sample_text']}\"]"
        )

    mid = msg["msg_id"]
    t_str = iso_to_short_time(msg.get("timestamp"))
    sender = msg["sender_name"]

    reply_part = ""
    reply_to = msg.get("reply_to")
    if reply_to:
        r_status = reply_to.get("status")
        r_mid = reply_to.get("msg_id")
        r_sender = reply_to.get("sender_name")
        r_snippet = reply_to.get("text_snippet") or ""
        if r_status == "revoked":
            reply_part = f" (回复 #{r_mid}: [原消息已撤回])"
        elif r_status == "not_found":
            reply_part = " (回复历史消息: [原消息不在本地库])"
        elif r_mid is not None:
            reply_part = f' (回复 #{r_mid} @{r_sender}: "{r_snippet}")'
        else:
            reply_part = f' (回复 @{r_sender}: "{r_snippet}")'

    media_part = ""
    media = msg.get("media")
    if media:
        mtype = media.get("media_type", "media")
        avail = bool(media.get("local_available"))
        avail_str = "true" if avail else "false"
        dur = media.get("duration_sec")
        title = media.get("title") or mtype
        fsize_str = format_human_bytes(media.get("file_size_bytes"))

        if mtype == "audio":
            dur_val = int(dur or 0)
            if dur_val >= long_audio_threshold_sec:
                media_part = (
                    f"[⚠️ 语音消息未转写: {dur_val}秒 | msg_id: {mid} | local_available: {avail_str}]"
                )
            else:
                media_part = f"[语音消息: {dur_val}秒 | msg_id: {mid} | local_available: {avail_str}]"
        elif mtype == "document":
            media_part = (
                f"[附带文档: {title} ({fsize_str}) | msg_id: {mid} | local_available: {avail_str}]"
            )
        elif mtype == "image":
            media_part = f"[图片附件: {title} | msg_id: {mid} | local_available: {avail_str}]"
        elif mtype in ("video", "gif"):
            dur_info = f", {dur}秒" if dur else ""
            media_part = f"[视频附件: {title} ({fsize_str}{dur_info}) | msg_id: {mid} | local_available: {avail_str}]"
        elif mtype == "sticker":
            media_part = "[贴纸]"
        else:
            media_part = f"[附件: {title} | msg_id: {mid} | local_available: {avail_str}]"

    text = (msg.get("text") or "").strip()
    # Avoid duplicating filename if document text is identical to media title
    if media and media.get("media_type") == "document" and text == media.get("title"):
        body = media_part
    elif text and media_part:
        body = f"{text} {media_part}"
    elif media_part:
        body = media_part
    else:
        body = text

    # Normalize multi-line body indentation
    body_lines = body.splitlines()
    if len(body_lines) > 1:
        body = "\n  ".join(body_lines)

    return f"[#{mid}] {t_str} [{sender}]{reply_part}: {body}"


def format_groups_markdown(data: dict[str, Any]) -> str:
    meta = data.get("meta", {})
    groups = data.get("groups", [])
    lines = [
        "# WhatsApp 本地群聊列表",
        f"- 快照基准时间: {format_header_datetime(meta.get('snapshot_time'))} (缓存年龄: {meta.get('snapshot_age_sec', 0)}s)",
        f"- 全局最新消息游标 (`global_latest_msg_id`): {meta.get('global_latest_msg_id', 0)}",
        f"- 当前过滤策略: `{meta.get('filter_mode', 'blacklist')}` | 共返回 {len(groups)} 个群聊",
    ]
    for w in meta.get("warnings", []):
        lines.append(f"- [⚠️ 预警 {w.get('code')}]: {w.get('message')}")
    lines.append("")
    lines.append("| 状态 | 群聊名称 | 群聊 JID (`chat_id`) | 最新游标 (`latest_msg_id`) | 过去24h消息数 | 群成员数 | 最后活跃时间 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for g in groups:
        status_icon = "✅ 允许" if g.get("allowed", True) else "🚫 屏蔽"
        lines.append(
            f"| {status_icon} | {g['group_name']} | `{g['chat_id']}` | `{g['latest_msg_id']}` | "
            f"{g['msg_count_24h']} | {g['member_count']} | {iso_to_short_time(g.get('last_active_time'))} |"
        )
    return "\n".join(lines) + "\n"


def format_fetch_markdown(
    data: dict[str, Any],
    fold_noise: bool = True,
    long_audio_threshold_sec: int = DEFAULT_LONG_AUDIO_THRESHOLD_SEC,
) -> str:
    meta = data.get("meta", {})
    chats = data.get("chats", [])
    lines = [
        "# WhatsApp 群聊提取记录",
        f"- 数据提取基准时间: {format_header_datetime(meta.get('extracted_at'))}",
        f"- 全局最新游标 (`global_latest_msg_id`): {meta.get('global_latest_msg_id', 0)} | 提取模式: `{meta.get('query_mode')}`",
        f"- 本人身份锚点: `{meta.get('my_identity', '我')}`",
    ]
    for w in meta.get("warnings", []):
        lines.append(f"- [⚠️ 预警 {w.get('code')}]: {w.get('message')}")

    if not chats:
        lines.append("")
        lines.append("*(当前时间窗口或增量游标下无新增群聊消息)*")
        return "\n".join(lines) + "\n"

    for chat in chats:
        lines.append("")
        lines.append(f"## 群聊: {chat['group_name']} (`{chat['chat_id']}`)")
        more_flag = " | ⚠️ 仍有更多消息 (`has_more: true`)" if chat.get("has_more") else ""
        lines.append(
            f"- 本群最新游标 (`chat_latest_msg_id`): {chat['chat_latest_msg_id']} | "
            f"新增消息: {chat['new_message_count']} 条 | "
            f"上下文缓冲: {chat['context_buffer_count']} 条{more_flag}"
        )
        lines.append("")

        raw_msgs = chat.get("messages", [])
        if not raw_msgs:
            lines.append("*(本群在此窗口内无新增消息)*")
            continue

        msgs_to_render = fold_consecutive_ack_messages(raw_msgs) if fold_noise else raw_msgs
        buf_msgs = [m for m in msgs_to_render if m.get("is_context_buffer")]
        new_msgs = [m for m in msgs_to_render if not m.get("is_context_buffer")]

        if buf_msgs:
            lines.append(f"--- [以下为前 {chat['context_buffer_count']} 条历史上下文缓冲，仅供还原语境] ---")
            for m in buf_msgs:
                lines.append(render_single_message_md(m, long_audio_threshold_sec))
            lines.append("--- [以下为本次提取窗口内的新增消息] ---")

        for m in new_msgs:
            lines.append(render_single_message_md(m, long_audio_threshold_sec))

    return "\n".join(lines) + "\n"


def format_search_markdown(
    data: dict[str, Any],
    long_audio_threshold_sec: int = DEFAULT_LONG_AUDIO_THRESHOLD_SEC,
) -> str:
    meta = data.get("meta", {})
    matches = data.get("matches", [])
    lines = [
        f"# WhatsApp 跨群检索结果: \"{meta.get('query', '')}\"",
        f"- 快照基准时间: {format_header_datetime(meta.get('snapshot_time'))} | 命中条数: {meta.get('match_count', 0)}",
    ]
    for w in meta.get("warnings", []):
        lines.append(f"- [⚠️ 预警 {w.get('code')}]: {w.get('message')}")

    if not matches:
        lines.append("")
        lines.append("*(未找到匹配该关键词的群聊消息)*")
        return "\n".join(lines) + "\n"

    for idx, item in enumerate(matches, 1):
        hit = item["matched_message"]
        lines.append("")
        lines.append(
            f"### {idx}. [{item['group_name']}] 命中消息 `#{hit['msg_id']}` ({iso_to_short_time(hit.get('timestamp'))})"
        )
        for b in item.get("context_before", []):
            lines.append("  " + render_single_message_md(b, long_audio_threshold_sec))
        lines.append("👉 **" + render_single_message_md(hit, long_audio_threshold_sec) + "**")
        for a in item.get("context_after", []):
            lines.append("  " + render_single_message_md(a, long_audio_threshold_sec))

    return "\n".join(lines) + "\n"


def format_json_output(data: dict[str, Any]) -> str:
    """Serialize output dictionary to deterministic pretty-printed JSON."""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
