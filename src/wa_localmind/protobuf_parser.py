"""Zero-dependency Protobuf wire parser for WhatsApp ZWAMEDIAITEM.ZMETADATA and ZWAGROUPMEMBER.ZFIRSTNAME."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

B64_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/]{6,}={1,2}$")


@dataclass
class MessageMetadataProto:
    quoted_stanza_id: str | None = None
    quoted_text_fallback: str | None = None
    mentioned_jids: list[str] = field(default_factory=list)


def is_base64_protocol_token(val: str | None) -> bool:
    """Return True if a string in ZPUSHNAME or ZFIRSTNAME is a base64-encoded binary protocol token."""
    if not val:
        return False
    s = val.strip()
    if s.startswith("+") and B64_TOKEN_RE.match(s[1:]):
        return True
    if B64_TOKEN_RE.match(s):
        try:
            raw = base64.b64decode(s)
            # Protocol tokens contain binary control bytes (< 0x20)
            if any(b < 0x20 for b in raw):
                return True
        except Exception:
            pass
    return False


def decode_groupmember_firstname_proto(val: str | None) -> str | None:
    """Decode ZWAGROUPMEMBER.ZFIRSTNAME when stored as '+<base64_protobuf>' (Field 1 = pushname)."""
    if not val:
        return None
    s = val.strip()
    if not s.startswith("+"):
        return s if not is_base64_protocol_token(s) else None
    b64_part = s[1:]
    if not B64_TOKEN_RE.match(b64_part):
        # Might be a phone number like +86138...
        return None
    try:
        blob = base64.b64decode(b64_part)
    except Exception:
        return None

    # Parse Field 1 (tag 0x0A: field_num=1, wire_type=2)
    if len(blob) >= 2 and blob[0] == 0x0A:
        length = blob[1]
        if 0 < length <= len(blob) - 2:
            try:
                name = blob[2 : 2 + length].decode("utf-8").strip()
                if name and not any(ord(c) < 0x20 for c in name):
                    return name
            except UnicodeDecodeError:
                return None
    return None


def parse_message_metadata_blob(blob: bytes | None) -> MessageMetadataProto:
    """Parse WhatsApp ZWAMEDIAITEM.ZMETADATA protobuf wire buffer.

    Verified field mapping in macOS WhatsApp ChatStorage.sqlite:
    - Field 5 (wire type 2): Quoted parent message ZSTANZAID (string)
    - Field 6 (wire type 2): Quoted parent message text snippet fallback (string)
    - Field 8 (wire type 2, repeated): Mentioned JIDs (e.g. '12345@lid', '86138...@s.whatsapp.net')
    """
    result = MessageMetadataProto()
    if not blob:
        return result

    i = 0
    n = len(blob)
    while i < n:
        tag = 0
        shift = 0
        while i < n:
            b = blob[i]
            i += 1
            tag |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
            if shift > 63:
                return result

        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num == 0:
            break

        if wire_type == 0:  # Varint
            shift = 0
            while i < n:
                b = blob[i]
                i += 1
                if not (b & 0x80):
                    break
                shift += 7
                if shift > 63:
                    return result
        elif wire_type == 1:  # 64-bit
            i += 8
        elif wire_type == 2:  # Length-delimited bytes
            length = 0
            shift = 0
            while i < n:
                b = blob[i]
                i += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
                if shift > 63:
                    return result
            if length < 0 or i + length > n:
                break
            chunk = blob[i : i + length]
            i += length

            if field_num == 5 and result.quoted_stanza_id is None:
                try:
                    s = chunk.decode("utf-8").strip()
                    if s:
                        result.quoted_stanza_id = s
                except UnicodeDecodeError:
                    pass
            elif field_num == 6 and result.quoted_text_fallback is None:
                try:
                    s = chunk.decode("utf-8").strip()
                    if s:
                        result.quoted_text_fallback = s
                except UnicodeDecodeError:
                    pass
            elif field_num == 8:
                try:
                    s = chunk.decode("utf-8").strip()
                    if s and "@" in s and s not in result.mentioned_jids:
                        result.mentioned_jids.append(s)
                except UnicodeDecodeError:
                    pass
        elif wire_type == 5:  # 32-bit
            i += 4
        else:
            break

    return result
