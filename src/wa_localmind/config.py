"""Configuration management for WhatsApp-LocalMind (Identity anchor, Blacklist/Whitelist, Cleaning rules)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_CONTEXT_BUFFER_COUNT,
    DEFAULT_LONG_AUDIO_THRESHOLD_SEC,
    DEFAULT_SNAPSHOT_DIR,
    DEFAULT_SNAPSHOT_TTL_SEC,
    DEFAULT_WA_CONTAINER_DIR,
)
from .errors import PolicyDeniedError, UsageError


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
    filter_mode: str = "blacklist"  # "blacklist" | "whitelist"
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

        if not path.exists():
            cfg = cls()
            if env_container:
                cfg.wa_container_dir = env_container
            if env_snapshot:
                cfg.snapshot_dir = env_snapshot
            return cfg

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise UsageError(f"Failed to parse config file at {path}: {exc}") from exc

        identity_raw = raw.get("identity", {})
        cleaning_raw = raw.get("cleaning", {})
        cfg = cls(
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
        return cfg

    def save(self, config_path: Path | None = None) -> Path:
        path = config_path or DEFAULT_CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
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

    def is_chat_allowed(self, chat_jid: str) -> bool:
        """Strictly enforce 100% private chat blocking and group blacklist/whitelist."""
        if not self.is_group_jid(chat_jid):
            return False
        if self.filter_mode == "whitelist":
            return chat_jid in self.whitelist_chats
        return chat_jid not in self.blacklist_chats

    def assert_chat_allowed(self, chat_jid: str) -> None:
        """Raise PolicyDeniedError (Exit Code 3) if session is private or blocked."""
        if not self.is_group_jid(chat_jid):
            raise PolicyDeniedError(
                f"Access denied: '{chat_jid}' is not a group session (@g.us). "
                "1-on-1 private chats and broadcasts are strictly blocked.",
                error_code="PRIVATE_SESSION_BLOCKED",
            )
        if not self.is_chat_allowed(chat_jid):
            raise PolicyDeniedError(
                f"Access denied: group '{chat_jid}' is blocked by current {self.filter_mode} policy.",
                error_code="GROUP_BLOCKED_BY_POLICY",
            )
