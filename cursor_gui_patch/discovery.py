"""Discover Cursor installations (server + GUI, cross-platform)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

try:
    import winreg
except ImportError:  # pragma: no cover - unavailable outside native Windows
    winreg = None

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

_WSL_SKIP_USERS = {"public", "default", "default user", "all users"}
_WINDOWS_APP_PATHS_CURSOR = r"Software\Microsoft\Windows\CurrentVersion\App Paths\Cursor.exe"
_WINDOWS_UNINSTALL_KEYS = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
    r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)


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


def _preferred_windows_usernames() -> List[str]:
    """Return lowercase preferred Windows usernames from env vars."""
    names: List[str] = []
    seen = set()
    for key in ("CGP_WINDOWS_USER", "WSL_WINDOWS_USER", "USERNAME", "USER", "LOGNAME"):
        raw = os.environ.get(key)
        if not isinstance(raw, str):
            continue
        value = raw.strip().strip("\\/")
        if not value:
            continue
        # Allow DOMAIN\\user or /path/like/value forms.
        value = value.split("\\")[-1].split("/")[-1]
        low = value.lower()
        if low not in seen:
            seen.add(low)
            names.append(low)
    return names


def _ordered_wsl_user_dirs(user_dirs: Sequence[Path]) -> List[Path]:
    """Order WSL Windows user dirs: preferred usernames first, then others."""
    if not user_dirs:
        return []

    preferred = _preferred_windows_usernames()
    ordered: List[Path] = []
    seen = set()

    if preferred:
        by_name: Dict[str, List[Path]] = {}
        for p in user_dirs:
            by_name.setdefault(p.name.lower(), []).append(p)
        for name in preferred:
            for p in by_name.get(name, []):
                key = str(p)
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(p)

    for p in user_dirs:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(p)

    return ordered


def _wsl_user_dirs(users_dir: Path) -> List[Path]:
    """List non-system user directories under /mnt/c/Users."""
    out: List[Path] = []
    try:
        for user_dir in sorted(users_dir.iterdir()):
            if not user_dir.is_dir():
                continue
            name = user_dir.name.strip().lower()
            if not name or name.startswith(".") or name in _WSL_SKIP_USERS:
                continue
            out.append(user_dir)
    except PermissionError:
        pass
    return out


def _choose_wsl_user_dir(user_dirs: Sequence[Path]) -> Optional[Path]:
    """Choose a Windows user directory in WSL (preferred names first)."""
    ordered = _ordered_wsl_user_dirs(user_dirs)
    if not ordered:
        return None
    return ordered[0]


_RE_WIN_DRIVE_ABS = re.compile(r"^[a-zA-Z]:[\\/]")


def _safe_relative_folder_name(raw: str) -> Optional[str]:
    """Validate and normalize a relative folder name used under home/."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if _RE_WIN_DRIVE_ABS.match(s):
        return None
    s = s.replace("\\", "/")
    if s.startswith("/"):
        return None
    parts = [p for p in s.split("/") if p and p != "."]
    if not parts:
        return None
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _nonempty_env_path(name: str) -> Optional[Path]:
    """Return an environment-backed path when the variable is set."""
    raw = os.environ.get(name)
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    return Path(value)


def _dedupe_paths(paths: Sequence[Path], *, case_insensitive: bool = False) -> List[Path]:
    """Preserve order while dropping duplicate paths."""
    seen = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path).replace("\\", "/")
        if case_insensitive:
            key = key.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _path_from_scan_string(raw: str) -> Path:
    """Normalize path separators so Windows-like paths work in cross-platform tests."""
    return Path(raw.replace("\\", "/"))


def _normalize_windows_cursor_exe_path(raw: object) -> Optional[Path]:
    """Parse a registry/PATH value into a Cursor.exe path."""
    if not isinstance(raw, str):
        return None
    value = os.path.expandvars(raw.strip())
    if not value:
        return None

    if value.startswith('"'):
        end = value.find('"', 1)
        if end > 1:
            value = value[1:end]
        else:
            value = value[1:]
    else:
        exe_idx = value.lower().find(".exe")
        if exe_idx != -1:
            value = value[: exe_idx + 4]
        comma_idx = value.find(",")
        if comma_idx != -1:
            value = value[:comma_idx]
        value = value.strip()

    if not value:
        return None
    path = _path_from_scan_string(value)
    if path.name.lower() != "cursor.exe":
        return None
    return path


def _windows_gui_root_from_exe(exe_path: Path) -> Path:
    """Derive resources/app from a Cursor.exe path."""
    return exe_path.parent / "resources" / "app"


def _windows_cursor_exe_from_path_command(raw: Optional[str]) -> Optional[Path]:
    """Resolve PATH results like Cursor.exe or resources/app/bin/cursor.cmd."""
    if not isinstance(raw, str):
        return None
    path = _path_from_scan_string(raw)
    name = path.name.lower()
    if name == "cursor.exe":
        return path
    if name == "cursor.cmd":
        lower_parts = [part.lower() for part in path.parts]
        if len(lower_parts) >= 4 and lower_parts[-4:] == ["resources", "app", "bin", "cursor.cmd"]:
            return path.parents[3] / "Cursor.exe"
        if len(lower_parts) >= 2 and lower_parts[-2:] == ["bin", "cursor.cmd"]:
            return path.parents[1] / "Cursor.exe"
    return None


def _windows_registry_hives() -> Sequence[object]:
    """Return the registry hives consulted for Cursor discovery."""
    if winreg is None:
        return ()
    return (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)


def _read_windows_registry_value(hive: object, subkey: str, value_name: str = "") -> Optional[str]:
    """Best-effort registry value read."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def _iter_windows_registry_subkeys(hive: object, subkey: str) -> List[str]:
    """Enumerate registry subkey names under a given key."""
    if winreg is None:
        return []
    try:
        with winreg.OpenKey(hive, subkey) as key:
            count, _, _ = winreg.QueryInfoKey(key)
            return [winreg.EnumKey(key, i) for i in range(count)]
    except OSError:
        return []


def _windows_registry_app_paths_cursor_exes() -> List[Path]:
    """Read Cursor.exe from the standard App Paths registration."""
    candidates: List[Path] = []
    for hive in _windows_registry_hives():
        exe_path = _normalize_windows_cursor_exe_path(
            _read_windows_registry_value(hive, _WINDOWS_APP_PATHS_CURSOR)
        )
        if exe_path is not None:
            candidates.append(exe_path)
    return _dedupe_paths(candidates, case_insensitive=True)


def _windows_registry_uninstall_cursor_exes() -> List[Path]:
    """Read Cursor.exe from uninstall metadata when App Paths is absent."""
    candidates: List[Path] = []
    for hive in _windows_registry_hives():
        for base_key in _WINDOWS_UNINSTALL_KEYS:
            for entry_name in _iter_windows_registry_subkeys(hive, base_key):
                subkey = f"{base_key}\\{entry_name}"
                display_name = _read_windows_registry_value(hive, subkey, "DisplayName")
                if not isinstance(display_name, str) or "cursor" not in display_name.lower():
                    continue
                display_icon = _normalize_windows_cursor_exe_path(
                    _read_windows_registry_value(hive, subkey, "DisplayIcon")
                )
                if display_icon is not None:
                    candidates.append(display_icon)
                install_location = _read_windows_registry_value(hive, subkey, "InstallLocation")
                if isinstance(install_location, str) and install_location.strip():
                    candidates.append(_path_from_scan_string(install_location.strip()) / "Cursor.exe")
    return _dedupe_paths(candidates, case_insensitive=True)


def _native_windows_registry_cursor_exes() -> List[Path]:
    """Registry-backed Cursor.exe discovery for native Windows."""
    return _dedupe_paths(
        _windows_registry_app_paths_cursor_exes() + _windows_registry_uninstall_cursor_exes(),
        case_insensitive=True,
    )


def _windows_exe_candidates_for_roots(
    *,
    local_appdata_roots: Sequence[Path] = (),
    program_files_roots: Sequence[Path] = (),
) -> List[Path]:
    """Build Cursor.exe fallback candidates from Windows LocalAppData/Program Files roots."""
    candidates: List[Path] = []
    for local_root in local_appdata_roots:
        candidates.extend([
            local_root / "Programs" / "cursor" / "Cursor.exe",
            local_root / "cursor" / "Cursor.exe",
        ])
    for program_root in program_files_roots:
        candidates.append(program_root / "Cursor" / "Cursor.exe")
    return _dedupe_paths(candidates, case_insensitive=True)


def _windows_gui_candidates_from_exes(exe_paths: Sequence[Path]) -> List[Path]:
    """Convert Cursor.exe candidates into resources/app roots."""
    return _dedupe_paths(
        [_windows_gui_root_from_exe(path) for path in exe_paths],
        case_insensitive=True,
    )


def _native_windows_cursor_exe_candidates() -> List[Path]:
    """Return native Windows Cursor.exe candidates in priority order."""
    local_appdata_roots: List[Path] = []
    local_appdata = _nonempty_env_path("LOCALAPPDATA")
    if local_appdata is not None:
        local_appdata_roots.append(local_appdata)

    program_files_roots: List[Path] = []
    for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        root = _nonempty_env_path(name)
        if root is not None:
            program_files_roots.append(root)

    candidates: List[Path] = []
    candidates.extend(_native_windows_registry_cursor_exes())
    for command in ("cursor", "cursor.exe"):
        exe_path = _windows_cursor_exe_from_path_command(shutil.which(command))
        if exe_path is not None:
            candidates.append(exe_path)
    candidates.extend(
        _windows_exe_candidates_for_roots(
            local_appdata_roots=local_appdata_roots,
            program_files_roots=program_files_roots,
        )
    )
    return _dedupe_paths(candidates, case_insensitive=True)


def _native_windows_gui_candidates() -> List[Path]:
    """Return Windows GUI install candidates from the current environment."""
    return _windows_gui_candidates_from_exes(_native_windows_cursor_exe_candidates())


def _wsl_gui_candidates_from_mount_root(mnt_c: Path) -> List[Path]:
    """Find Windows GUI install candidates from a mounted Windows drive in WSL."""
    if not mnt_c.is_dir():
        return []

    users_dir = mnt_c / "Users"
    local_appdata_roots: List[Path] = []
    if users_dir.is_dir():
        for user_dir in _ordered_wsl_user_dirs(_wsl_user_dirs(users_dir)):
            local_appdata_roots.append(user_dir / "AppData" / "Local")

    return _windows_gui_candidates_from_exes(
        _windows_exe_candidates_for_roots(
            local_appdata_roots=local_appdata_roots,
            program_files_roots=[
                mnt_c / "Program Files",
                mnt_c / "Program Files (x86)",
            ],
        )
    )


def discover_server_installations(
    *,
    explicit_dir: Optional[str] = None,
) -> List[CursorInstallation]:
    """Discover Cursor Remote SSH Server installations."""
    results: List[CursorInstallation] = []

    # Priority: explicit arg > env var > auto-discover

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

    # Auto-discover: enumerate ~/<serverDataFolderName>/bin/<hash>/.
    # Start with default then augment from discovered GUI product.json files.
    folder_names = {".cursor-server"}
    for gui_root in _gui_candidates():
        if gui_root.is_dir() and _is_cursor_app_root(gui_root):
            folder = _safe_relative_folder_name(_get_server_data_folder_name(gui_root))
            if folder:
                folder_names.add(folder)

    home = Path.home()
    for folder_name in sorted(folder_names):
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
    platform = sys.platform

    if platform == "darwin":
        home = Path.home()
        candidates.extend([
            Path("/Applications/Cursor.app/Contents/Resources/app"),
            home / "Applications/Cursor.app/Contents/Resources/app",
        ])
    elif platform == "win32":
        candidates.extend(_native_windows_gui_candidates())
    else:
        # Linux
        home = Path.home()
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
    return _wsl_gui_candidates_from_mount_root(Path("/mnt/c"))


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
