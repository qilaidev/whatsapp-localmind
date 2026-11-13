"""Typed exceptions mapped to POSIX exit codes for WhatsApp-LocalMind CLI."""

from .constants import (
    EXIT_ENV_OR_PERM_ERROR,
    EXIT_INTERNAL_DB_ERROR,
    EXIT_POLICY_DENIED,
    EXIT_RESOURCE_NOT_FOUND,
    EXIT_USAGE_ERROR,
)


class WALocalMindError(Exception):
    """Base error with a specific POSIX exit code and structured error code."""

    exit_code: int = EXIT_INTERNAL_DB_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code


class UsageError(WALocalMindError):
    """Invalid CLI arguments or parameters (Exit Code 1)."""

    exit_code = EXIT_USAGE_ERROR
    error_code = "INVALID_ARGUMENTS"


class EnvOrPermissionError(WALocalMindError):
    """WhatsApp DB missing or macOS Full Disk Access permission denied (Exit Code 2)."""

    exit_code = EXIT_ENV_OR_PERM_ERROR
    error_code = "ENV_OR_PERMISSION_ERROR"


class PolicyDeniedError(WALocalMindError):
    """Access blocked by session isolation policy: private chat or blocked group (Exit Code 3)."""

    exit_code = EXIT_POLICY_DENIED
    error_code = "POLICY_DENIED"


class ResourceNotFoundError(WALocalMindError):
    """Target message ID or local media file does not exist (Exit Code 4)."""

    exit_code = EXIT_RESOURCE_NOT_FOUND
    error_code = "RESOURCE_NOT_FOUND"


class InternalDatabaseError(WALocalMindError):
    """SQLite snapshot backup or read query error (Exit Code 5)."""

    exit_code = EXIT_INTERNAL_DB_ERROR
    error_code = "INTERNAL_DB_ERROR"
