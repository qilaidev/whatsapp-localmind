"""Atomic SQLite online backup (sqlite3_backup), multi-path auto-discovery, and file lock manager."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import AppConfig
from .constants import APPLE_EPOCH_OFFSET, DEFAULT_WA_CONTAINER_DIR
from .errors import EnvOrPermissionError, InternalDatabaseError

CANDIDATE_WA_CONTAINERS = (
    "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared",
    "~/Library/Group Containers/group.net.whatsapp.WhatsApp.private",
    "~/Library/Containers/net.whatsapp.WhatsApp/Data/Library/Application Support/WhatsApp",
    "~/Library/Containers/desktop.WhatsApp/Data/Library/Application Support/WhatsApp",
)


@dataclass
class SnapshotState:
    snapshot_db_path: Path
    contacts_db_path: Path | None
    lid_db_path: Path | None
    snapshot_time_iso: str
    snapshot_epoch: float
    snapshot_age_sec: int
    db_latest_msg_epoch: int | None
    db_latest_msg_time_iso: str | None
    global_latest_msg_id: int
    refreshed: bool
    backup_duration_ms: float


def epoch_to_local_iso(epoch_sec: float | int | None) -> str | None:
    if epoch_sec is None:
        return None
    dt = datetime.fromtimestamp(float(epoch_sec)).astimezone()
    return dt.isoformat(timespec="seconds")


def make_ro_sqlite_uri(db_path: Path) -> str:
    return f"{db_path.resolve().as_uri()}?mode=ro"


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


@contextmanager
def _acquire_snapshot_lock(lock_path: Path) -> Iterator[None]:
    """Cross-platform exclusive file lock (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows)."""
    lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if sys.platform == "win32":
        import msvcrt

        with open(lock_path, "a+b") as lock_file:
            if lock_file.tell() == 0:
                lock_file.write(b" ")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
    else:
        import fcntl

        with open(lock_path, "w", encoding="utf-8") as lock_file:
            _chmod_best_effort(lock_path, 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def resolve_wa_container_and_db(configured_dir: str) -> tuple[Path, Path]:
    """Resolve WhatsApp container directory and ChatStorage.sqlite across macOS installation variants."""
    primary = Path(os.path.expanduser(configured_dir))
    for sub in ("ChatStorage.sqlite", "App/ChatStorage.sqlite"):
        cand_db = primary / sub
        try:
            if cand_db.exists():
                return primary, cand_db
        except PermissionError:
            return primary, cand_db

    if primary == DEFAULT_WA_CONTAINER_DIR:
        for cand_str in CANDIDATE_WA_CONTAINERS:
            cdir = Path(os.path.expanduser(cand_str))
            for sub in ("ChatStorage.sqlite", "App/ChatStorage.sqlite"):
                cdb = cdir / sub
                try:
                    if cdb.exists():
                        return cdir, cdb
                except PermissionError:
                    return cdir, cdb

    return primary, primary / "ChatStorage.sqlite"


class SnapshotManager:
    """Manages atomic SQLite snapshots with file locking and TTL caching."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.container_dir, self.source_db_path = resolve_wa_container_and_db(config.wa_container_dir)
        self.source_contacts_db_path = self.container_dir / "ContactsV2.sqlite"
        self.source_lid_db_path = self.container_dir / "LID.sqlite"
        self.source_message_dir = self.container_dir / "Message"

        self.snapshot_dir = Path(os.path.expanduser(config.snapshot_dir))
        self.snapshot_db_path = self.snapshot_dir / "ChatStorage_snapshot.sqlite"
        self.snapshot_contacts_db_path = self.snapshot_dir / "ContactsV2_snapshot.sqlite"
        self.snapshot_lid_db_path = self.snapshot_dir / "LID_snapshot.sqlite"
        self.meta_path = self.snapshot_dir / "snapshot_meta.json"
        self.lock_path = self.snapshot_dir / "snapshot.lock"
        self.media_dir = self.snapshot_dir / "media"

    def check_source_access(self) -> dict[str, Any]:
        """Inspect source WhatsApp database existence, read permissions, and session counts for `doctor`."""
        info: dict[str, Any] = {
            "container_dir": str(self.container_dir),
            "container_exists": False,
            "source_db_path": str(self.source_db_path),
            "source_db_exists": False,
            "source_db_readable": False,
            "source_db_size_bytes": None,
            "lid_db_exists": False,
            "contacts_db_exists": False,
            "error": None,
        }
        try:
            info["container_exists"] = self.container_dir.exists()
            if not info["container_exists"]:
                info["error"] = f"WhatsApp container directory not found: {self.container_dir}"
                return info
            info["source_db_exists"] = self.source_db_path.exists()
            if not info["source_db_exists"]:
                info["error"] = f"ChatStorage.sqlite not found at: {self.source_db_path}"
                return info
            info["source_db_size_bytes"] = self.source_db_path.stat().st_size
            info["lid_db_exists"] = self.source_lid_db_path.exists()
            info["contacts_db_exists"] = self.source_contacts_db_path.exists()

            uri = make_ro_sqlite_uri(self.source_db_path)
            conn = sqlite3.connect(uri, uri=True, timeout=3.0)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    COUNT(*),
                    SUM(CASE WHEN ZCONTACTJID LIKE '%@g.us' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN ZCONTACTJID LIKE '%@s.whatsapp.net' OR ZCONTACTJID LIKE '%@lid' THEN 1 ELSE 0 END)
                FROM ZWACHATSESSION
                WHERE ZCONTACTJID IS NOT NULL AND ZCONTACTJID != 'status@broadcast'
                """
            )
            counts_row = cur.fetchone() or (0, 0, 0)
            conn.close()
            info["source_db_readable"] = True
            info["total_session_count"] = int(counts_row[0] or 0)
            info["group_session_count"] = int(counts_row[1] or 0)
            info["direct_session_count"] = int(counts_row[2] or 0)
        except PermissionError as exc:
            info["error"] = (
                f"Permission denied reading {self.source_db_path}. "
                "Please grant Full Disk Access to your terminal or host process in macOS System Settings."
            )
            info["exception"] = str(exc)
        except sqlite3.OperationalError as exc:
            info["error"] = (
                f"SQLite cannot open {self.source_db_path} in read-only mode ({exc}). "
                "Check macOS Full Disk Access permissions."
            )
        except Exception as exc:
            info["error"] = f"Unexpected error checking source DB: {exc}"
        return info

    def ensure_snapshot(self, force_fresh: bool = False) -> SnapshotState:
        """Ensure a fresh or valid cached snapshot exists using exclusive file lock."""
        self.snapshot_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        _chmod_best_effort(self.snapshot_dir, 0o700)
        ttl_sec = max(0, self.config.cleaning.snapshot_ttl_sec)
        now = time.time()

        if not force_fresh and self._is_cache_valid(now, ttl_sec):
            return self._load_cached_state(now)

        with _acquire_snapshot_lock(self.lock_path):
            now = time.time()
            if not force_fresh and self._is_cache_valid(now, max(1, ttl_sec)):
                return self._load_cached_state(now)
            return self._perform_atomic_backup()

    def _is_cache_valid(self, now: float, ttl_sec: int) -> bool:
        if not self.snapshot_db_path.exists() or not self.meta_path.exists():
            return False
        if self.source_lid_db_path.exists() and not self.snapshot_lid_db_path.exists():
            return False
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            created_epoch = float(meta.get("snapshot_epoch", 0))
            return (now - created_epoch) <= ttl_sec
        except Exception:
            return False

    def _load_cached_state(self, now: float) -> SnapshotState:
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        created_epoch = float(meta["snapshot_epoch"])
        contacts_path = (
            self.snapshot_contacts_db_path
            if self.snapshot_contacts_db_path.exists()
            else None
        )
        lid_path = (
            self.snapshot_lid_db_path
            if self.snapshot_lid_db_path.exists()
            else None
        )
        return SnapshotState(
            snapshot_db_path=self.snapshot_db_path,
            contacts_db_path=contacts_path,
            lid_db_path=lid_path,
            snapshot_time_iso=meta["snapshot_time_iso"],
            snapshot_epoch=created_epoch,
            snapshot_age_sec=max(0, int(round(now - created_epoch))),
            db_latest_msg_epoch=meta.get("db_latest_msg_epoch"),
            db_latest_msg_time_iso=meta.get("db_latest_msg_time_iso"),
            global_latest_msg_id=int(meta.get("global_latest_msg_id", 0)),
            refreshed=False,
            backup_duration_ms=float(meta.get("backup_duration_ms", 0.0)),
        )

    @staticmethod
    def _backup_auxiliary_db(src_path: Path, dst_path: Path, snapshot_dir: Path, prefix: str) -> Path | None:
        if not src_path.exists():
            return None
        tmp_path = snapshot_dir / f"{prefix}.{os.getpid()}.tmp.sqlite"
        try:
            src_conn = sqlite3.connect(make_ro_sqlite_uri(src_path), uri=True, timeout=2.0)
            dst_conn = sqlite3.connect(str(tmp_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
            _chmod_best_effort(tmp_path, 0o600)
            tmp_path.replace(dst_path)
            _chmod_best_effort(dst_path, 0o600)
            return dst_path
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return None

    def _perform_atomic_backup(self) -> SnapshotState:
        try:
            if not self.source_db_path.exists():
                raise EnvOrPermissionError(
                    f"WhatsApp database not found at '{self.source_db_path}'. "
                    "Ensure macOS WhatsApp client is installed and logged in.",
                    error_code="SOURCE_DB_NOT_FOUND",
                )
        except PermissionError as exc:
            raise EnvOrPermissionError(
                f"macOS Full Disk Access permission denied while accessing '{self.source_db_path}'. "
                "Please grant Full Disk Access in System Settings -> Privacy & Security.",
                error_code="PERMISSION_DENIED_TCC",
            ) from exc

        t0 = time.perf_counter()
        tmp_db_path = self.snapshot_dir / f"ChatStorage_snapshot.{os.getpid()}.tmp.sqlite"
        if tmp_db_path.exists():
            tmp_db_path.unlink()

        try:
            src_uri = make_ro_sqlite_uri(self.source_db_path)
            src_conn = sqlite3.connect(src_uri, uri=True, timeout=5.0)
            dst_conn = sqlite3.connect(str(tmp_db_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
        except PermissionError as exc:
            if tmp_db_path.exists():
                tmp_db_path.unlink(missing_ok=True)
            raise EnvOrPermissionError(
                f"Permission denied reading '{self.source_db_path}'. "
                "Grant Full Disk Access to the caller process.",
                error_code="PERMISSION_DENIED_TCC",
            ) from exc
        except sqlite3.OperationalError as exc:
            if tmp_db_path.exists():
                tmp_db_path.unlink(missing_ok=True)
            msg = str(exc).lower()
            if "unable to open" in msg or "authorization denied" in msg or "permission" in msg:
                raise EnvOrPermissionError(
                    f"Cannot open WhatsApp database '{self.source_db_path}' ({exc}). "
                    "Grant Full Disk Access in macOS System Settings.",
                    error_code="PERMISSION_DENIED_TCC",
                ) from exc
            raise InternalDatabaseError(
                f"SQLite online backup failed: {exc}",
                error_code="SQLITE_BACKUP_FAILED",
            ) from exc
        except Exception as exc:
            if tmp_db_path.exists():
                tmp_db_path.unlink(missing_ok=True)
            raise InternalDatabaseError(
                f"Unexpected error during SQLite online backup: {exc}",
                error_code="SQLITE_BACKUP_FAILED",
            ) from exc

        _chmod_best_effort(tmp_db_path, 0o600)
        tmp_db_path.replace(self.snapshot_db_path)
        _chmod_best_effort(self.snapshot_db_path, 0o600)

        lid_path = self._backup_auxiliary_db(
            self.source_lid_db_path,
            self.snapshot_lid_db_path,
            self.snapshot_dir,
            "LID_snapshot",
        )
        contacts_path = self._backup_auxiliary_db(
            self.source_contacts_db_path,
            self.snapshot_contacts_db_path,
            self.snapshot_dir,
            "ContactsV2_snapshot",
        )

        global_latest_msg_id = 0
        db_latest_msg_epoch: int | None = None
        try:
            snap_conn = sqlite3.connect(make_ro_sqlite_uri(self.snapshot_db_path), uri=True)
            cur = snap_conn.cursor()
            cur.execute("SELECT COALESCE(MAX(Z_PK), 0), MAX(ZMESSAGEDATE) FROM ZWAMESSAGE")
            row = cur.fetchone()
            if row:
                global_latest_msg_id = int(row[0] or 0)
                if row[1] is not None:
                    db_latest_msg_epoch = int(round(float(row[1]) + APPLE_EPOCH_OFFSET))
            snap_conn.close()
        except Exception as exc:
            raise InternalDatabaseError(
                f"Snapshot verification query failed: {exc}",
                error_code="SNAPSHOT_VERIFY_FAILED",
            ) from exc

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        now_epoch = time.time()
        now_iso = epoch_to_local_iso(now_epoch) or ""
        latest_msg_iso = epoch_to_local_iso(db_latest_msg_epoch)

        meta = {
            "snapshot_epoch": now_epoch,
            "snapshot_time_iso": now_iso,
            "db_latest_msg_epoch": db_latest_msg_epoch,
            "db_latest_msg_time_iso": latest_msg_iso,
            "global_latest_msg_id": global_latest_msg_id,
            "backup_duration_ms": duration_ms,
            "snapshot_size_bytes": self.snapshot_db_path.stat().st_size,
        }
        tmp_meta = self.snapshot_dir / f"snapshot_meta.{os.getpid()}.tmp.json"
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _chmod_best_effort(tmp_meta, 0o600)
        tmp_meta.replace(self.meta_path)
        _chmod_best_effort(self.meta_path, 0o600)

        return SnapshotState(
            snapshot_db_path=self.snapshot_db_path,
            contacts_db_path=contacts_path,
            lid_db_path=lid_path,
            snapshot_time_iso=now_iso,
            snapshot_epoch=now_epoch,
            snapshot_age_sec=0,
            db_latest_msg_epoch=db_latest_msg_epoch,
            db_latest_msg_time_iso=latest_msg_iso,
            global_latest_msg_id=global_latest_msg_id,
            refreshed=True,
            backup_duration_ms=duration_ms,
        )

    def clean(self, media_only: bool = False) -> dict[str, Any]:
        """Remove exported media cache and optionally destroy the SQLite snapshot files."""
        removed_items: list[str] = []
        if self.media_dir.exists():
            shutil.rmtree(self.media_dir)
            removed_items.append(str(self.media_dir))

        if not media_only:
            for p in (
                self.snapshot_db_path,
                self.snapshot_contacts_db_path,
                self.snapshot_lid_db_path,
                self.meta_path,
            ):
                if p.exists():
                    p.unlink()
                    removed_items.append(str(p))

        return {
            "status": "cleaned",
            "media_only": media_only,
            "removed_paths": removed_items,
        }
