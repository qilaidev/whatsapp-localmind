"""Constants, exit codes, default paths, and WhatsApp CoreData message type mappings."""

import os
from pathlib import Path

# POSIX Exit Codes
EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 1
EXIT_ENV_OR_PERM_ERROR = 2
EXIT_POLICY_DENIED = 3
EXIT_RESOURCE_NOT_FOUND = 4
EXIT_INTERNAL_DB_ERROR = 5

# Apple Cocoa CoreData Epoch Offset (2001-01-01 00:00:00 UTC in Unix Epoch seconds)
APPLE_EPOCH_OFFSET = 978307200

# Default macOS Paths
DEFAULT_WA_CONTAINER_DIR = Path(
    os.path.expanduser("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared")
)
DEFAULT_WA_DB_PATH = DEFAULT_WA_CONTAINER_DIR / "ChatStorage.sqlite"
DEFAULT_WA_CONTACTS_DB_PATH = DEFAULT_WA_CONTAINER_DIR / "ContactsV2.sqlite"
DEFAULT_WA_MESSAGE_DIR = DEFAULT_WA_CONTAINER_DIR / "Message"

DEFAULT_APP_SUPPORT_DIR = Path(
    os.path.expanduser("~/Library/Application Support/WhatsApp-LocalMind")
)
DEFAULT_CONFIG_PATH = DEFAULT_APP_SUPPORT_DIR / "config.json"
DEFAULT_SNAPSHOT_DIR = DEFAULT_APP_SUPPORT_DIR / "snapshot"
DEFAULT_SNAPSHOT_DB_PATH = DEFAULT_SNAPSHOT_DIR / "ChatStorage_snapshot.sqlite"
DEFAULT_SNAPSHOT_CONTACTS_DB_PATH = DEFAULT_SNAPSHOT_DIR / "ContactsV2_snapshot.sqlite"
DEFAULT_SNAPSHOT_META_PATH = DEFAULT_SNAPSHOT_DIR / "snapshot_meta.json"
DEFAULT_SNAPSHOT_LOCK_PATH = DEFAULT_SNAPSHOT_DIR / "snapshot.lock"
DEFAULT_EXPORT_MEDIA_DIR = DEFAULT_SNAPSHOT_DIR / "media"

# WhatsApp ZWAMESSAGE.ZMESSAGETYPE Enum Mapping
MSG_TYPE_MAP = {
    0: "text",
    1: "image",
    2: "video",
    3: "audio",
    4: "contact",
    5: "location",
    6: "system_event",
    7: "link",
    8: "document",
    10: "system_security",
    11: "gif",
    12: "system_protocol",
    14: "revoked",
    15: "sticker",
    46: "protocol_stub",
    66: "protocol_stub",
}

# Excluded message types in SQL query layer (system notifications, security events, revoked messages, protocol stubs)
EXCLUDED_MSG_TYPES = (6, 10, 12, 14, 46, 66)

# Media-bearing message types
MEDIA_MSG_TYPES = {
    1: "image",
    2: "video",
    3: "audio",
    8: "document",
    11: "gif",
    15: "sticker",
}

# Default cleaning parameters
DEFAULT_SNAPSHOT_TTL_SEC = 15
DEFAULT_CONTEXT_BUFFER_COUNT = 10
DEFAULT_LONG_AUDIO_THRESHOLD_SEC = 10
DEFAULT_REPLY_SNIPPET_MAX_LEN = 150
DEFAULT_FETCH_LIMIT = 500
MAX_FETCH_LIMIT = 3000
SYNC_LAG_WARNING_SEC = 4 * 3600  # 4 hours

# Preset short acknowledgment phrases for reversible noise folding
ACK_NOISE_PHRASES = frozenset({
    "收到",
    "收到！",
    "收到。",
    "好的",
    "好的！",
    "好的。",
    "好",
    "好滴",
    "好嘞",
    "明白",
    "明白了",
    "已阅",
    "了解",
    "ok",
    "ok!",
    "okay",
    "kk",
    "k",
    "+1",
    "1",
    "谢谢",
    "谢谢！",
    "多谢",
    "感谢",
    "thanks",
    "thx",
    "ty",
    "roger",
    "copy",
    "noted",
})
