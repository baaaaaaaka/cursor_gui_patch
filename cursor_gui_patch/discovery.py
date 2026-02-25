"""Discover Cursor installations (server + GUI, cross-platform)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ENV_CURSOR_SERVER_DIR = "CGP_CURSOR_SERVER_DIR"
ENV_CURSOR_GUI_DIR = "CGP_CURSOR_GUI_DIR"

# Extension targets and which patches apply to each.
EXTENSION_TARGETS: Dict[str, Dict[str, object]] = {
    "cursor-agent-exec": {"file": "dist/main.js", "patches": ["autorun"]},
    "cursor-always-local": {"file": "dist/main.js", "patches": ["models"]},
    "cursor-retrieval": {"file": "dist/main.js", "patches": ["models"]},
    "cursor-commits": {"file": "dist/main.js", "patches": ["models"]},
}

# Workbench targets (directly under installation root, only present in GUI installs).
WORKBENCH_TARGETS: Dict[str, Dict[str, object]] = {
    "workbench.desktop.main.js": {
        "file": "out/vs/workbench/workbench.desktop.main.js",
        "patches": ["autorun_workbench"],
    },
}


@dataclass
class CursorInstallation:
    kind: str  # "server" | "gui"
    root: Path  # app root (contains product.json + extensions/)
    version_id: str  # commit hash or version string

    @property
    def extensions_dir(self) -> Path:
        return self.root / "extensions"

    def target_files(self) -> List[TargetFile]:
        """Return all patchable target files in this installation."""
        targets: List[TargetFile] = []
        for ext_name, info in EXTENSION_TARGETS.items():
            ext_dir = self.extensions_dir / ext_name
            if not ext_dir.is_dir():
                continue
            js_file = ext_dir / str(info["file"])
            if js_file.is_file():
                patches = list(info["patches"]) if isinstance(info["patches"], list) else []
                targets.append(TargetFile(
                    path=js_file,
                    extension=ext_name,
                    patch_names=patches,
                    installation=self,
                ))
        # Workbench targets (directly under root, GUI installs only)
        for wb_name, info in WORKBENCH_TARGETS.items():
            js_file = self.root / str(info["file"])
            if js_file.is_file():
                patches = list(info["patches"]) if isinstance(info["patches"], list) else []
                targets.append(TargetFile(
                    path=js_file,
                    extension=wb_name,
                    patch_names=patches,
                    installation=self,
                ))
        return targets


@dataclass
class TargetFile:
    path: Path
    extension: str  # e.g. "cursor-agent-exec"
    patch_names: List[str]  # e.g. ["autorun"]
    installation: CursorInstallation


def _is_cursor_app_root(p: Path) -> bool:
    """Validate that a directory is a Cursor installation root."""
    product_json = p / "product.json"
    if not product_json.is_file():
        return False
    try:
        data = json.loads(product_json.read_text(encoding="utf-8"))
    except Exception:
        return False
    return data.get("applicationName") == "cursor"


def _version_id_from_path(p: Path) -> str:
    """Extract a version identifier from the installation path."""
    # For server installs: ~/.cursor-server/bin/<hash>/ → use the hash
    if p.parent.name == "bin":
        return p.name
    # For GUI installs: use the directory name or "gui"
    return p.name or "unknown"


def _get_server_data_folder_name(app_root: Path) -> str:
    """Read serverDataFolderName from product.json, default to .cursor-server."""
    product_json = app_root / "product.json"
    try:
        data = json.loads(product_json.read_text(encoding="utf-8"))
        return data.get("serverDataFolderName", ".cursor-server")
    except Exception:
        return ".cursor-server"


def discover_server_installations(
    *,
    explicit_dir: Optional[str] = None,
) -> List[CursorInstallation]:
    """Discover Cursor Remote SSH Server installations."""
    results: List[CursorInstallation] = []

    # Priority: explicit arg > env var > auto-discover
    candidates: List[Path] = []

    explicit = explicit_dir or os.environ.get(ENV_CURSOR_SERVER_DIR)
    if explicit:
        p = Path(explicit).expanduser()
        if _is_cursor_app_root(p):
            results.append(CursorInstallation(
                kind="server",
                root=p,
                version_id=_version_id_from_path(p),
            ))
        return results

    # Auto-discover: enumerate ~/.cursor-server/bin/<hash>/
    # We try common data folder names
    home = Path.home()
    for folder_name in (".cursor-server",):
        bin_dir = home / folder_name / "bin"
        if not bin_dir.is_dir():
            continue
        try:
            for child in sorted(bin_dir.iterdir()):
                if child.is_dir() and _is_cursor_app_root(child):
                    results.append(CursorInstallation(
                        kind="server",
                        root=child,
                        version_id=child.name,
                    ))
        except PermissionError:
            continue

    return results


def _gui_candidates() -> List[Path]:
    """Return platform-specific candidate paths for Cursor GUI installations."""
    candidates: List[Path] = []
    home = Path.home()
    platform = sys.platform

    if platform == "darwin":
        candidates.extend([
            Path("/Applications/Cursor.app/Contents/Resources/app"),
            home / "Applications/Cursor.app/Contents/Resources/app",
        ])
    elif platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if local != Path(""):
            candidates.extend([
                local / "Programs" / "cursor" / "resources" / "app",
                local / "cursor" / "resources" / "app",
            ])
    else:
        # Linux
        candidates.extend([
            Path("/opt/cursor/resources/app"),
            Path("/usr/share/cursor/resources/app"),
            Path("/usr/lib/cursor/resources/app"),
            Path("/snap/cursor/current/resources/app"),
            home / ".local/share/cursor/resources/app",
        ])
        # WSL: detect Windows Cursor installs
        if _is_wsl():
            candidates.extend(_wsl_gui_candidates())

    return candidates


def _is_wsl() -> bool:
    """Detect if running under WSL."""
    try:
        release = Path("/proc/version").read_text()
        return "microsoft" in release.lower() or "wsl" in release.lower()
    except Exception:
        return False


def _wsl_gui_candidates() -> List[Path]:
    """Find Cursor GUI installations in Windows filesystem from WSL."""
    candidates: List[Path] = []
    mnt_c = Path("/mnt/c")
    if not mnt_c.is_dir():
        return candidates
    users_dir = mnt_c / "Users"
    if not users_dir.is_dir():
        return candidates
    try:
        for user_dir in users_dir.iterdir():
            if user_dir.name.startswith(".") or user_dir.name in ("Public", "Default", "Default User", "All Users"):
                continue
            if not user_dir.is_dir():
                continue
            candidate = user_dir / "AppData" / "Local" / "Programs" / "cursor" / "resources" / "app"
            candidates.append(candidate)
    except PermissionError:
        pass
    return candidates


def discover_gui_installations(
    *,
    explicit_dir: Optional[str] = None,
) -> List[CursorInstallation]:
    """Discover Cursor GUI (desktop Electron) installations."""
    results: List[CursorInstallation] = []

    explicit = explicit_dir or os.environ.get(ENV_CURSOR_GUI_DIR)
    if explicit:
        p = Path(explicit).expanduser()
        if _is_cursor_app_root(p):
            results.append(CursorInstallation(
                kind="gui",
                root=p,
                version_id=_version_id_from_path(p),
            ))
        return results

    for candidate in _gui_candidates():
        if candidate.is_dir() and _is_cursor_app_root(candidate):
            results.append(CursorInstallation(
                kind="gui",
                root=candidate,
                version_id=_version_id_from_path(candidate),
            ))

    return results


def discover_all(
    *,
    server_dir: Optional[str] = None,
    gui_dir: Optional[str] = None,
) -> List[CursorInstallation]:
    """Discover all Cursor installations (server + GUI)."""
    installations: List[CursorInstallation] = []
    installations.extend(discover_server_installations(explicit_dir=server_dir))
    installations.extend(discover_gui_installations(explicit_dir=gui_dir))
    return installations
