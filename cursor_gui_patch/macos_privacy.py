"""macOS privacy-denial detection and best-effort settings opener."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


def _is_cursor_app_path(path: Path) -> bool:
    s = str(path)
    return s.startswith("/Applications/") and ".app/" in s


@dataclass(frozen=True)
class MacOSPrivacyDiagnosis:
    """Structured diagnosis for macOS privacy-related write failures."""
    platform: str
    total_errors: int
    app_bundle_errors: int
    backup_failed_errors: int
    operation_not_permitted_errors: int
    errno1_errors: int
    permission_denied_errors: int
    readonly_errors: int
    likely: bool
    certain: bool


@dataclass(frozen=True)
class ProcessContext:
    """Best-effort runtime process context for user-facing diagnostics."""
    current_process: str
    terminal_process: str
    terminal_source: str


_TERM_PROGRAM_MAP = {
    "Apple_Terminal": "Terminal",
    "iTerm.app": "iTerm",
    "vscode": "VS Code Integrated Terminal",
    "WarpTerminal": "Warp",
    "WezTerm": "WezTerm",
}

_TCC_SERVICE_LIST = Path(
    "/System/Library/ExtensionKit/Extensions/"
    "SecurityPrivacyExtension.appex/Contents/Resources/TCCServiceList.plist"
)


def _normalize_process_name(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    if not s:
        return ""
    return Path(s).name or s


def _ps_value(pid: int, field: str) -> str:
    ps_bin = shutil.which("ps")
    if not ps_bin:
        return ""
    try:
        proc = subprocess.run(
            [ps_bin, "-o", f"{field}=", "-p", str(pid)],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return proc.stdout.strip()
    except Exception:
        return ""


def _detected_app_management_privacy_key() -> str:
    """
    Detect best privacy section key for "App Management" on this macOS.

    Returns a revealElementKeyName such as "Privacy_AppBundles" when available.
    Falls back to "Privacy_AppManagement".
    """
    try:
        if not _TCC_SERVICE_LIST.is_file():
            return "Privacy_AppManagement"
        raw = _TCC_SERVICE_LIST.read_bytes()
        data = plistlib.loads(raw)
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                tcc = str(item.get("tcc", ""))
                if tcc in ("kTCCServiceSystemPolicyAppBundles", "kTCCServiceAppManagement"):
                    key = str(item.get("revealElementKeyName", "")).strip()
                    if key:
                        return key
        return "Privacy_AppManagement"
    except Exception:
        return "Privacy_AppManagement"


def _looks_like_terminal_process(name: str) -> bool:
    low = name.lower()
    hints = (
        "terminal",
        "iterm",
        "warp",
        "wezterm",
        "alacritty",
        "kitty",
        "hyper",
        "ghostty",
        "tabby",
        "rio",
    )
    return any(h in low for h in hints)


def detect_current_process_context() -> ProcessContext:
    """Detect current process and terminal app name (best effort)."""
    try:
        pid = os.getpid()
        current = _normalize_process_name(_ps_value(pid, "comm"))
        if not current:
            current = _normalize_process_name(sys.executable) or "unknown"

        term_program = os.environ.get("TERM_PROGRAM", "").strip()
        if term_program:
            terminal = _TERM_PROGRAM_MAP.get(term_program, term_program)
            return ProcessContext(
                current_process=current,
                terminal_process=terminal,
                terminal_source="TERM_PROGRAM",
            )

        walk_pid = pid
        for _ in range(10):
            ppid_raw = _ps_value(walk_pid, "ppid")
            if not ppid_raw:
                break
            try:
                ppid = int(ppid_raw)
            except ValueError:
                break
            if ppid <= 1 or ppid == walk_pid:
                break
            pname = _normalize_process_name(_ps_value(ppid, "comm"))
            if pname and _looks_like_terminal_process(pname):
                return ProcessContext(
                    current_process=current,
                    terminal_process=pname,
                    terminal_source="parent process chain",
                )
            walk_pid = ppid

        parent_name = _normalize_process_name(_ps_value(os.getppid(), "comm"))
        if parent_name:
            return ProcessContext(
                current_process=current,
                terminal_process=parent_name,
                terminal_source="parent process fallback",
            )

        return ProcessContext(
            current_process=current,
            terminal_process="unknown",
            terminal_source="unavailable",
        )
    except Exception:
        return ProcessContext(
            current_process="unknown",
            terminal_process="unknown",
            terminal_source="error fallback",
        )


def diagnose_macos_privacy_denial(errors: List[Tuple[Path, str]]) -> MacOSPrivacyDiagnosis:
    """Return structured diagnosis for macOS privacy-denial signals."""
    total = len(errors)
    app_bundle_errors = 0
    backup_failed_errors = 0
    op_not_permitted_errors = 0
    errno1_errors = 0
    permission_denied_errors = 0
    readonly_errors = 0

    for path, msg in errors:
        low = msg.lower()
        if _is_cursor_app_path(path):
            app_bundle_errors += 1
        if "backup failed" in low:
            backup_failed_errors += 1
        if "operation not permitted" in low:
            op_not_permitted_errors += 1
        if "errno 1" in low:
            errno1_errors += 1
        if "permission denied" in low or "errno 13" in low:
            permission_denied_errors += 1
        if "read-only file system" in low or "errno 30" in low:
            readonly_errors += 1

    is_macos = sys.platform == "darwin"
    likely = (
        is_macos
        and total > 0
        and app_bundle_errors > 0
        and (
            op_not_permitted_errors > 0
            or permission_denied_errors > 0
            or backup_failed_errors > 0
        )
    )
    certain = (
        is_macos
        and total > 0
        and app_bundle_errors == total
        and op_not_permitted_errors == total
        and errno1_errors == total
        and permission_denied_errors == 0
        and readonly_errors == 0
    )

    return MacOSPrivacyDiagnosis(
        platform=sys.platform,
        total_errors=total,
        app_bundle_errors=app_bundle_errors,
        backup_failed_errors=backup_failed_errors,
        operation_not_permitted_errors=op_not_permitted_errors,
        errno1_errors=errno1_errors,
        permission_denied_errors=permission_denied_errors,
        readonly_errors=readonly_errors,
        likely=likely,
        certain=certain,
    )


def is_certain_macos_privacy_denial(errors: List[Tuple[Path, str]]) -> bool:
    """
    Return True only for high-confidence macOS privacy-denial failures.

    Strict gating (intentionally conservative):
    - platform is darwin
    - every error is under /Applications/*.app
    - every message contains both EPERM and "operation not permitted"
    - excludes other common non-privacy causes
    """
    return diagnose_macos_privacy_denial(errors).certain


def _run_open(args: List[str]) -> bool:
    open_bin = shutil.which("open")
    if not open_bin:
        return False
    try:
        subprocess.run(
            [open_bin, *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        return True
    except Exception:
        return False


def maybe_open_privacy_settings(errors: List[Tuple[Path, str]]) -> bool:
    """
    Best-effort open of macOS settings when privacy denial is certain.

    Set CGP_NO_OPEN_SETTINGS=1 to disable.
    """
    return open_privacy_settings_with_status(errors) == "opened"


def open_privacy_settings_with_status(errors: List[Tuple[Path, str]]) -> str:
    """
    Attempt to open macOS Privacy settings and return a status string.

    Status:
      - "opened": settings opened successfully
      - "disabled": disabled by CGP_NO_OPEN_SETTINGS=1
      - "not_certain": signal is not 100% certain
      - "open_failed": signal is certain but opening settings failed
    """
    if os.environ.get("CGP_NO_OPEN_SETTINGS", "").strip() == "1":
        return "disabled"
    if not is_certain_macos_privacy_denial(errors):
        return "not_certain"

    # Try direct App-Management subpages first, then broader fallbacks.
    app_key = _detected_app_management_privacy_key()
    keys = [app_key]
    for candidate in ("Privacy_AppBundles", "Privacy_AppManagement", "Privacy_AllFiles"):
        if candidate not in keys:
            keys.append(candidate)

    targets = []
    for key in keys:
        targets.append(f"x-apple.systempreferences:com.apple.preference.security?{key}")
        targets.append(f"x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?{key}")
    targets.extend([
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
        "x-apple.systempreferences:com.apple.preference.security",
    ])
    for target in targets:
        if _run_open([target]):
            return "opened"

    if _run_open(["-b", "com.apple.SystemSettings"]):
        return "opened"
    if _run_open(["-b", "com.apple.systempreferences"]):
        return "opened"
    return "open_failed"
