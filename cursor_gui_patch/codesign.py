"""macOS code signing: re-sign .app bundles after patching."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class CodesignResult:
    """Result of a codesign operation."""
    needed: bool = False  # True if codesigning was needed
    success: bool = False  # True if codesigning succeeded
    skipped_reason: str = ""  # Why codesigning was skipped
    app_path: Optional[Path] = None  # The .app bundle path
    error: str = ""  # Error message if failed
    identity_requested: str = "-"  # Preferred identity requested
    identity_used: str = "-"  # Actual identity used
    warning: str = ""  # Non-fatal warning (e.g. fallback used)


_DEFAULT_STABLE_IDENTITY_NAME = "CGP Cursor Patch"


def _parse_security_identities(output: str) -> List[str]:
    """Extract identity display names from `security find-identity` output."""
    out: List[str] = []
    for line in output.splitlines():
        m = re.search(r'"([^"]+)"', line)
        if m:
            out.append(m.group(1).strip())
    return out


def _available_codesign_identities() -> List[str]:
    """List available codesign identities from keychain (best effort)."""
    security_bin = shutil.which("security")
    if not security_bin:
        return []
    try:
        proc = subprocess.run(
            [security_bin, "find-identity", "-v", "-p", "codesigning"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return []
        return _parse_security_identities(proc.stdout)
    except Exception:
        return []


def _resolve_preferred_identity() -> Tuple[str, str]:
    """
    Resolve preferred codesign identity.

    Order:
      1) explicit CGP_CODESIGN_IDENTITY (including "-" for ad-hoc)
      2) auto-detect a stable identity containing CGP_CODESIGN_STABLE_IDENTITY_NAME
      3) fallback ad-hoc "-"
    """
    explicit = os.environ.get("CGP_CODESIGN_IDENTITY", "").strip()
    if explicit:
        return explicit, "env:CGP_CODESIGN_IDENTITY"

    stable_hint = os.environ.get("CGP_CODESIGN_STABLE_IDENTITY_NAME", "").strip()
    stable_name = stable_hint or _DEFAULT_STABLE_IDENTITY_NAME
    available = _available_codesign_identities()
    for ident in available:
        if ident == stable_name or stable_name.lower() in ident.lower():
            return ident, "auto:stable-identity"

    return "-", "fallback:ad-hoc"


def _run_codesign(codesign_bin: str, app_path: Path, identity: str) -> subprocess.CompletedProcess:
    """Run codesign with a specific identity."""
    return subprocess.run(
        [codesign_bin, "--force", "--deep", "--sign", identity, str(app_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )


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

    Default behavior: ad-hoc signature ("-").
    Stable behavior: if available, prefer a fixed identity:
      - CGP_CODESIGN_IDENTITY (explicit)
      - identity containing CGP_CODESIGN_STABLE_IDENTITY_NAME (default: "CGP Cursor Patch")
    On failure with a non-ad-hoc identity, it falls back to ad-hoc once.
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
    preferred_identity, identity_source = _resolve_preferred_identity()
    result.identity_requested = preferred_identity

    try:
        proc = _run_codesign(codesign_bin, app_path, preferred_identity)
        if proc.returncode == 0:
            result.success = True
            result.identity_used = preferred_identity
        else:
            # Keep robustness: if preferred identity fails, retry ad-hoc once.
            if preferred_identity != "-":
                fallback = _run_codesign(codesign_bin, app_path, "-")
                if fallback.returncode == 0:
                    result.success = True
                    result.identity_used = "-"
                    result.warning = (
                        f"preferred identity '{preferred_identity}' ({identity_source}) failed; "
                        "fell back to ad-hoc signature"
                    )
                else:
                    primary_err = proc.stderr.strip() or f"codesign exited with code {proc.returncode}"
                    fallback_err = (
                        fallback.stderr.strip()
                        or f"ad-hoc codesign exited with code {fallback.returncode}"
                    )
                    result.error = (
                        f"preferred identity '{preferred_identity}' failed: {primary_err}; "
                        f"ad-hoc fallback failed: {fallback_err}"
                    )
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
