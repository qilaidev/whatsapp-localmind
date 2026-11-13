"""Semantic text cleaning: @mention dictionary replacement, [@我] tagging, and ack noise detection."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .config import AppConfig
from .constants import ACK_NOISE_PHRASES, DEFAULT_REPLY_SNIPPET_MAX_LEN

MENTION_TOKEN_RE = re.compile(r"@(\d{5,22})\b")
BIDI_CONTROL_CHARS_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def clean_unicode_display_name(val: str | None) -> str:
    """Strip invisible Unicode directional marks and normalize non-breaking spaces/hyphens."""
    if not val:
        return ""
    s = BIDI_CONTROL_CHARS_RE.sub("", val)
    s = s.replace("\xa0", " ").replace("\u2011", "-")
    return " ".join(s.split()).strip()


def strip_jid_Namespace(jid: str | None) -> str:
    if not jid:
        return ""
    return jid.split("@", 1)[0].strip()


def format_fallback_sender_name(jid: str | None, bridged_phone_jid: str | None = None) -> str:
    """Format anonymized fallback name when contact name and pushname are both empty."""
    # Prefer phone JID if bridged from LID.sqlite so user sees (+country-last4) instead of opaque LID
    target = bridged_phone_jid if (bridged_phone_jid and bridged_phone_jid.endswith("@s.whatsapp.net")) else jid
    if not target:
        return "未知群友"
    user_part = strip_jid_Namespace(target)
    if target.endswith("@lid"):
        tail = user_part[-4:] if len(user_part) >= 4 else user_part
        return f"外部群友#{tail}"
    if target.endswith("@s.whatsapp.net"):
        if len(user_part) >= 6:
            prefix = user_part[:2]
            tail = user_part[-4:]
            return f"群友(+{prefix}-{tail})"
        return f"群友({user_part})"
    return f"群友({user_part[-4:] if len(user_part) >= 4 else user_part})"


def disambiguate_punctuation_name(
    name: str,
    jid: str | None,
    bridged_phone_jid: str | None = None,
) -> str:
    """If a user's nickname consists purely of punctuation (e.g. '.'), append a short phone/ID tag."""
    if not name:
        return format_fallback_sender_name(jid, bridged_phone_jid)
    # Check if name contains any letter, digit, CJK character, or emoji symbol
    has_word_or_emoji = any(
        ch.isalnum() or unicodedata.category(ch) in ("Lo", "So") or ord(ch) >= 0x1F000
        for ch in name
    )
    if has_word_or_emoji:
        return name
    target = bridged_phone_jid if (bridged_phone_jid and bridged_phone_jid.endswith("@s.whatsapp.net")) else jid
    user_part = strip_jid_Namespace(target)
    if target and target.endswith("@s.whatsapp.net") and len(user_part) >= 6:
        return f"{name}(+{user_part[:2]}-{user_part[-4:]})"
    if user_part:
        return f"{name}(#{user_part[-4:]})"
    return name


def is_my_jid_prefix(
    jid_prefix: str,
    config: AppConfig,
    auto_self_prefixes: set[str] | None = None,
) -> bool:
    """Determine whether a numeric JID/LID prefix belongs to the user identity."""
    if not jid_prefix:
        return False
    if auto_self_prefixes and jid_prefix in auto_self_prefixes:
        return True
    for explicit in config.identity.jid_prefixes:
        clean_exp = strip_jid_Namespace(explicit)
        if clean_exp and jid_prefix == clean_exp:
            return True
    suffix = (config.identity.phone_suffix or "").strip()
    if len(suffix) >= 4 and jid_prefix.endswith(suffix):
        return True
    return False


def replace_mentions_with_whitelist(
    text: str,
    member_dict: dict[str, str],
    mentioned_jids: list[str],
    config: AppConfig,
    auto_self_prefixes: set[str] | None = None,
) -> tuple[str, bool]:
    """Replace @<jid_digits> in text strictly using the group member dictionary and user identity.

    Returns (cleaned_text, mentions_me).
    Unrecognized @digits (e.g., order numbers @20261107) are preserved untouched.
    """
    mentions_me = False

    for m_jid in mentioned_jids:
        prefix = strip_jid_Namespace(m_jid)
        if is_my_jid_prefix(prefix, config, auto_self_prefixes):
            mentions_me = True

    if not text:
        return "", mentions_me

    my_label = f"[@{config.my_display_label}]"

    def _replacer(match: re.Match[str]) -> str:
        nonlocal mentions_me
        digits = match.group(1)
        if is_my_jid_prefix(digits, config, auto_self_prefixes):
            mentions_me = True
            return my_label
        if digits in member_dict:
            resolved = member_dict[digits]
            return f"@{resolved}"
        return match.group(0)

    cleaned = MENTION_TOKEN_RE.sub(_replacer, text)

    my_name = (config.identity.name or "").strip()
    if my_name and my_name != "我" and f"@{my_name}" in cleaned:
        mentions_me = True
        cleaned = cleaned.replace(f"@{my_name}", my_label)

    return cleaned, mentions_me


def is_pure_emoji_text(s: str) -> bool:
    """Return True if string consists purely of emojis, symbols, or variation selectors."""
    stripped = "".join(ch for ch in s if not ch.isspace())
    if not stripped or len(stripped) > 8:
        return False
    for ch in stripped:
        if ch in ("\ufe0f", "\ufe0e", "\u200d", "\u20e3"):
            continue
        cat = unicodedata.category(ch)
        if cat not in ("So", "Sk") and ord(ch) < 0x1F000:
            return False
    return True


def is_short_ack_noise(
    text: str,
    msg_type: str,
    has_reply: bool,
    has_media: bool,
    mentions_me: bool,
) -> bool:
    """Determine if a message is a short acknowledgment noise ('收到', 'OK', '+1', pure emoji)."""
    if has_reply or has_media or mentions_me or msg_type != "text":
        return False
    clean = (text or "").strip()
    if not clean or "@" in clean or len(clean) > 10:
        return False
    normalized = clean.lower().rstrip("!！.。~～,，")
    if normalized in ACK_NOISE_PHRASES or clean.lower() in ACK_NOISE_PHRASES:
        return True
    return is_pure_emoji_text(clean)


def truncate_reply_snippet(text: str | None, max_len: int = DEFAULT_REPLY_SNIPPET_MAX_LEN) -> str:
    """Truncate quoted parent message text to 150 characters with single-line normalization."""
    if not text:
        return ""
    single_line = " ".join(text.splitlines()).strip()
    if len(single_line) <= max_len:
        return single_line
    return single_line[:max_len] + "..."


def fold_consecutive_ack_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group consecutive non-buffer ack noise messages into folded summary entries for Markdown rendering."""
    result: list[dict[str, Any]] = []
    ack_run: list[dict[str, Any]] = []

    def _flush_ack_run() -> None:
        nonlocal ack_run
        if not ack_run:
            return
        if len(ack_run) == 1:
            result.append(ack_run[0])
        else:
            senders: list[str] = []
            for m in ack_run:
                s = m["sender_name"]
                if s not in senders:
                    senders.append(s)
            sender_preview = "、".join(senders[:3])
            if len(senders) > 3:
                sender_preview += f"等 {len(senders)} 人"
            else:
                sender_preview += f" ({len(ack_run)}条)"
            first_msg = ack_run[0]
            last_msg = ack_run[-1]
            sample_texts = []
            for m in ack_run:
                t = m["text"].strip()
                if t and t not in sample_texts:
                    sample_texts.append(t)
                if len(sample_texts) >= 2:
                    break
            sample_str = "/".join(sample_texts) if sample_texts else "收到/OK"
            result.append(
                {
                    "_folded_ack_summary": True,
                    "start_msg_id": first_msg["msg_id"],
                    "end_msg_id": last_msg["msg_id"],
                    "timestamp": last_msg["timestamp"],
                    "is_context_buffer": first_msg["is_context_buffer"],
                    "count": len(ack_run),
                    "sender_preview": sender_preview,
                    "sample_text": sample_str,
                }
            )
        ack_run = []

    for msg in messages:
        if msg.get("is_ack_noise") and not msg.get("is_context_buffer"):
            ack_run.append(msg)
        else:
            _flush_ack_run()
            result.append(msg)
    _flush_ack_run()
    return result
