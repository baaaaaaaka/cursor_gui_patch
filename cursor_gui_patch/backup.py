"""Backup and restore for patched files (.cgp.bak)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

_BACKUP_SUFFIX = ".cgp.bak"


def backup_path(original: Path) -> Path:
    """Return the backup path for a given file."""
    return original.with_name(original.name + _BACKUP_SUFFIX)


def create_backup(original: Path) -> Optional[Path]:
    """
    Create a backup of the original file (idempotent: only on first call).

    Returns the backup path if created or already exists, None on failure.
    """
    bak, _ = create_backup_with_error(original)
    return bak


def create_backup_with_error(original: Path) -> Tuple[Optional[Path], Optional[Exception]]:
    """
    Create a backup and return both result and underlying error if any.

    Returns:
      (backup_path, None) on success or already exists.
      (None, exception) on failure.
    """
    bak = backup_path(original)
    if bak.exists():
        return bak, None
    try:
        content = original.read_bytes()
        bak.write_bytes(content)
        # Preserve permissions
        try:
            st = original.stat()
            os.chmod(bak, st.st_mode)
        except Exception:
            pass
        return bak, None
    except Exception as e:
        return None, e


def restore_backup(original: Path) -> bool:
    """
    Restore a file from its backup.

    Returns True if restored, False if no backup exists or on failure.
    """
    bak = backup_path(original)
    if not bak.exists():
        return False
    try:
        content = bak.read_bytes()
        original.write_bytes(content)
        # Preserve permissions from backup
        try:
            st = bak.stat()
            os.chmod(original, st.st_mode)
        except Exception:
            pass
        return True
    except Exception:
        return False


def remove_backup(original: Path) -> bool:
    """Remove the backup file if it exists."""
    bak = backup_path(original)
    if not bak.exists():
        return False
    try:
        bak.unlink()
        return True
    except Exception:
        return False


def has_backup(original: Path) -> bool:
    """Check if a backup exists for the given file."""
    return backup_path(original).exists()
