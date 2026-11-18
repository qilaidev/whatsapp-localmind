"""Configuration management for WhatsApp-LocalMind (Identity anchor, Chat Scope, Blacklist/Whitelist, Cleaning rules)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_APP_SUPPORT_DIR,
    DEFAULT_CONFIG_PATH,
    DEFAULT_CONTEXT_BUFFER_COUNT,
    DEFAULT_LONG_AUDIO_THRESHOLD_SEC,
    DEFAULT_SNAPSHOT_DIR,
    DEFAULT_SNAPSHOT_TTL_SEC,
    DEFAULT_WA_CONTAINER_DIR,
    VALID_CHAT_SCOPES,
)
from .errors import PolicyDeniedError, UsageError


def classify_wa_jid(chat_jid: str | None) -> str:
    """Classify a WhatsApp JID into 'group', 'direct', 'newsletter', 'broadcast', 'status', or 'unknown'."""
    if not chat_jid:
        return "unknown"
    s = chat_jid.strip()
    if not s or "@" not in s:
        return "unknown"
    if s == "status@broadcast":
        return "status"
    if s.endswith("@g.us"):
        return "group"
    if s.endswith("@s.whatsapp.net") or s.endswith("@lid"):
        return "direct"
    if s.endswith("@newsletter"):
        return "newsletter"
    if s.endswith("@broadcast"):
        return "broadcast"
    return "direct"


@dataclass
class IdentityConfig:
    name: str = "我"
    phone_suffix: str = ""
    jid_prefixes: list[str] = field(default_factory=list)


@dataclass
class CleaningConfig:
    snapshot_ttl_sec: int = DEFAULT_SNAPSHOT_TTL_SEC
    context_buffer_count: int = DEFAULT_CONTEXT_BUFFER_COUNT
    long_audio_threshold_sec: int = DEFAULT_LONG_AUDIO_THRESHOLD_SEC
    fold_noise_markdown: bool = True
    fold_noise_json: bool = False


@dataclass
class AppConfig:
    chat_scope: str = "all"          # "all" | "groups" | "direct" | "newsletter"
    filter_mode: str = "blacklist"   # "blacklist" | "whitelist"
    blacklist_chats: list[str] = field(default_factory=list)
    whitelist_chats: list[str] = field(default_factory=list)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    cleaning: CleaningConfig = field(default_factory=CleaningConfig)
    wa_container_dir: str = str(DEFAULT_WA_CONTAINER_DIR)
    snapshot_dir: str = str(DEFAULT_SNAPSHOT_DIR)

    @classmethod
    def load(cls, config_path: Path | None = None) -> AppConfig:
        path = config_path or DEFAULT_CONFIG_PATH
        env_container = (
            os.environ.get("WHATSAPP_LOCALMIND_CONTAINER_DIR")
            or os.environ.get("WA_LOCALMIND_CONTAINER_DIR")
        )
        env_snapshot = (
            os.environ.get("WHATSAPP_LOCALMIND_SNAPSHOT_DIR")
            or os.environ.get("WA_LOCALMIND_SNAPSHOT_DIR")
        )
        env_scope = (
            os.environ.get("WHATSAPP_LOCALMIND_CHAT_SCOPE")
            or os.environ.get("WA_LOCALMIND_CHAT_SCOPE")
        )

        if not path.exists():
            cfg = cls()
        else:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise UsageError(f"Failed to parse config file at {path}: {exc}") from exc

            identity_raw = raw.get("identity", {})
            cleaning_raw = raw.get("cleaning", {})
            raw_scope = str(raw.get("chat_scope", "all")).strip().lower() or "all"
            if raw_scope == "group":
                raw_scope = "groups"
            if raw_scope not in VALID_CHAT_SCOPES:
                raise UsageError(
                    f"Invalid chat_scope '{raw_scope}' in {path}. Expected one of {VALID_CHAT_SCOPES}."
                )
            cfg = cls(
                chat_scope=raw_scope,
                filter_mode=raw.get("filter_mode", "blacklist"),
                blacklist_chats=list(raw.get("blacklist_chats", [])),
                whitelist_chats=list(raw.get("whitelist_chats", [])),
                identity=IdentityConfig(
                    name=identity_raw.get("name", "我") or "我",
                    phone_suffix=str(identity_raw.get("phone_suffix", "")),
                    jid_prefixes=list(identity_raw.get("jid_prefixes", [])),
                ),
                cleaning=CleaningConfig(
                    snapshot_ttl_sec=int(cleaning_raw.get("snapshot_ttl_sec", DEFAULT_SNAPSHOT_TTL_SEC)),
                    context_buffer_count=int(
                        cleaning_raw.get("context_buffer_count", DEFAULT_CONTEXT_BUFFER_COUNT)
                    ),
                    long_audio_threshold_sec=int(
                        cleaning_raw.get("long_audio_threshold_sec", DEFAULT_LONG_AUDIO_THRESHOLD_SEC)
                    ),
                    fold_noise_markdown=bool(cleaning_raw.get("fold_noise_markdown", True)),
                    fold_noise_json=bool(cleaning_raw.get("fold_noise_json", False)),
                ),
                wa_container_dir=raw.get("wa_container_dir", str(DEFAULT_WA_CONTAINER_DIR)),
                snapshot_dir=raw.get("snapshot_dir", str(DEFAULT_SNAPSHOT_DIR)),
            )

        if env_container:
            cfg.wa_container_dir = env_container
        if env_snapshot:
            cfg.snapshot_dir = env_snapshot
        if env_scope:
            norm_scope = env_scope.strip().lower()
            if norm_scope == "group":
                norm_scope = "groups"
            if norm_scope not in VALID_CHAT_SCOPES:
                raise UsageError(
                    f"Invalid WHATSAPP_LOCALMIND_CHAT_SCOPE '{env_scope}'. Expected one of {VALID_CHAT_SCOPES}."
                )
            cfg.chat_scope = norm_scope
        return cfg

    def save(self, config_path: Path | None = None) -> Path:
        path = config_path or DEFAULT_CONFIG_PATH
        parent_existed = path.parent.exists()
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not parent_existed or path.parent == DEFAULT_APP_SUPPORT_DIR:
            try:
                os.chmod(path.parent, 0o700)
            except OSError:
                pass
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        tmp_path.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def my_display_label(self) -> str:
        name = (self.identity.name or "").strip()
        if not name or name == "我":
            return "我"
        return f"我({name})"

    @staticmethod
    def is_group_jid(chat_jid: str) -> bool:
        return bool(chat_jid and chat_jid.endswith("@g.us"))

    @staticmethod
    def is_valid_chat_jid(chat_jid: str) -> bool:
        ctype = classify_wa_jid(chat_jid)
        return ctype not in ("unknown", "status")

    def is_chat_in_scope(self, chat_jid: str) -> bool:
        ctype = classify_wa_jid(chat_jid)
        if ctype in ("unknown", "status"):
            return False
        scope = (self.chat_scope or "all").lower()
        if scope == "all":
            return True
        if scope in ("groups", "group"):
            return ctype == "group"
        if scope == "direct":
            return ctype == "direct"
        if scope == "newsletter":
            return ctype == "newsletter"
        return True

    def is_chat_allowed(self, chat_jid: str, bridged_alt_jid: str | None = None) -> bool:
        """Check whether a WhatsApp chat session is allowed under `chat_scope` and blacklist/whitelist rules."""
        if not self.is_chat_in_scope(chat_jid):
            return False
        candidates = {chat_jid}
        if bridged_alt_jid:
            candidates.add(bridged_alt_jid)
        if self.filter_mode == "whitelist":
            return bool(candidates & set(self.whitelist_chats))
        return not bool(candidates & set(self.blacklist_chats))

    def assert_chat_allowed(self, chat_jid: str, bridged_alt_jid: str | None = None) -> None:
        """Raise PolicyDeniedError (Exit Code 3) if session is out of scope or blocked."""
        ctype = classify_wa_jid(chat_jid)
        if ctype == "status":
            raise PolicyDeniedError(
                "Access denied: 'status@broadcast' ephemeral status feed is not a chat session.",
                error_code="STATUS_BROADCAST_DENIED",
            )
        if not self.is_chat_in_scope(chat_jid):
            raise PolicyDeniedError(
                f"Access denied: chat '{chat_jid}' (type={ctype}) is outside configured chat_scope='{self.chat_scope}'.",
                error_code="CHAT_SCOPE_DENIED",
            )
        if not self.is_chat_allowed(chat_jid, bridged_alt_jid=bridged_alt_jid):
            raise PolicyDeniedError(
                f"Access denied: chat '{chat_jid}' is blocked by current {self.filter_mode} policy.",
                error_code="CHAT_BLOCKED_BY_POLICY",
            )
