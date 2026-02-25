"""macOS code signing: re-sign .app bundles after patching."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CodesignResult:
    """Result of a codesign operation."""
    needed: bool = False  # True if codesigning was needed
    success: bool = False  # True if codesigning succeeded
    skipped_reason: str = ""  # Why codesigning was skipped
    app_path: Optional[Path] = None  # The .app bundle path
    error: str = ""  # Error message if failed


def _find_app_bundle(app_root: Path) -> Optional[Path]:
    """
    Given a Cursor app root (e.g. .../Cursor.app/Contents/Resources/app/),
    find the .app bundle path.

    Walks up the directory tree looking for a directory ending in .app
    that contains Contents/Info.plist.
    """
    current = app_root.resolve()
    # Walk up at most 6 levels
    for _ in range(6):
        if current.name.endswith(".app") and (current / "Contents" / "Info.plist").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def needs_codesign(app_root: Path, kind: str) -> bool:
    """Check if an installation needs code re-signing after patching."""
    if sys.platform != "darwin":
        return False
    if kind != "gui":
        return False
    return _find_app_bundle(app_root) is not None


def codesign_app(app_root: Path) -> CodesignResult:
    """
    Re-sign a macOS .app bundle with an ad-hoc signature.

    This is needed after modifying files inside the bundle to prevent
    Gatekeeper from blocking the app ("app is damaged" warnings).

    Uses: codesign --force --deep --sign - <app_path>
    """
    result = CodesignResult()

    if sys.platform != "darwin":
        result.skipped_reason = "not macOS"
        return result

    codesign_bin = shutil.which("codesign")
    if not codesign_bin:
        result.needed = True
        result.error = "codesign binary not found"
        return result

    app_path = _find_app_bundle(app_root)
    if app_path is None:
        result.skipped_reason = "no .app bundle found"
        return result

    result.needed = True
    result.app_path = app_path

    try:
        proc = subprocess.run(
            [codesign_bin, "--force", "--deep", "--sign", "-", str(app_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode == 0:
            result.success = True
        else:
            result.error = proc.stderr.strip() or f"codesign exited with code {proc.returncode}"
    except subprocess.TimeoutExpired:
        result.error = "codesign timed out"
    except Exception as e:
        result.error = str(e)

    return result


def remove_quarantine(app_root: Path) -> bool:
    """
    Remove the quarantine extended attribute from the .app bundle.

    This prevents the "app downloaded from the internet" warning after
    re-signing. Uses: xattr -cr <app_path>
    """
    if sys.platform != "darwin":
        return False

    app_path = _find_app_bundle(app_root)
    if app_path is None:
        return False

    xattr_bin = shutil.which("xattr")
    if not xattr_bin:
        return False

    try:
        subprocess.run(
            [xattr_bin, "-cr", str(app_path)],
            capture_output=True,
            timeout=60,
        )
        return True
    except Exception:
        return False
