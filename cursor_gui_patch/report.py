"""Report data classes for patch/unpatch/status operations."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _has_permission_error(errors: List[Tuple[Path, str]]) -> bool:
    """Check if any error looks like a permission issue."""
    for _, msg in errors:
        low = msg.lower()
        if "permission denied" in low or "errno 13" in low or "access is denied" in low:
            return True
    return False


def _permission_hint() -> str:
    if sys.platform == "win32":
        return "Fix: Run as Administrator"
    return "Fix: Run with elevated permissions:\n  sudo cgp patch        (Linux/macOS)"


@dataclass
class CodesignInfo:
    """Info about a codesign operation on a macOS .app bundle."""
    app_path: str = ""
    success: bool = False
    error: str = ""


@dataclass
class PatchReport:
    """Report for a patch or unpatch operation."""
    scanned: int = 0
    patched: List[Path] = field(default_factory=list)
    already_patched: int = 0
    skipped_not_applicable: int = 0
    skipped_cached: int = 0
    errors: List[Tuple[Path, str]] = field(default_factory=list)
    codesign: List[CodesignInfo] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"Scanned: {self.scanned}",
            f"Patched: {len(self.patched)}",
            f"Already patched: {self.already_patched}",
            f"Not applicable: {self.skipped_not_applicable}",
            f"Cached (skipped): {self.skipped_cached}",
        ]
        if self.codesign:
            for cs in self.codesign:
                if cs.success:
                    lines.append(f"Codesign: {cs.app_path} (re-signed)")
                elif cs.error:
                    lines.append(f"Codesign FAILED: {cs.error}")
                    lines.append(
                        f"Fix: sudo codesign --force --deep --sign - {cs.app_path}"
                    )
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for path, msg in self.errors:
                lines.append(f"  {path}: {msg}")
            if _has_permission_error(self.errors):
                lines.append("")
                lines.append(_permission_hint())
        if not self.errors:
            lines.append("")
            lines.append("Tip: If Cursor behaves unexpectedly after patching, run:")
            lines.append("  cgp unpatch")
        return "\n".join(lines)


@dataclass
class UnpatchReport:
    """Report for an unpatch operation."""
    restored: List[Path] = field(default_factory=list)
    no_backup: List[Path] = field(default_factory=list)
    errors: List[Tuple[Path, str]] = field(default_factory=list)
    codesign: List[CodesignInfo] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"Restored: {len(self.restored)}",
            f"No backup: {len(self.no_backup)}",
        ]
        if self.codesign:
            for cs in self.codesign:
                if cs.success:
                    lines.append(f"Codesign: {cs.app_path} (re-signed)")
                elif cs.error:
                    lines.append(f"Codesign FAILED: {cs.error}")
                    lines.append(
                        f"Fix: sudo codesign --force --deep --sign - {cs.app_path}"
                    )
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for path, msg in self.errors:
                lines.append(f"  {path}: {msg}")
            if _has_permission_error(self.errors):
                lines.append("")
                if sys.platform == "win32":
                    lines.append("Fix: Run as Administrator")
                else:
                    lines.append("Fix: Run with elevated permissions:")
                    lines.append("  sudo cgp unpatch")
        return "\n".join(lines)


@dataclass
class FileStatus:
    """Status of a single target file."""
    path: Path
    extension: str
    patch_names: List[str]
    patched: Dict[str, bool] = field(default_factory=dict)  # patch_name → is_patched
    has_backup: bool = False
    error: str = ""


@dataclass
class StatusReport:
    """Report for status command."""
    installations: List[Dict[str, Any]] = field(default_factory=list)
    files: List[FileStatus] = field(default_factory=list)

    def summary(self) -> str:
        lines: List[str] = []
        if not self.installations:
            lines.append("No Cursor installations found.")
            return "\n".join(lines)

        for inst in self.installations:
            lines.append(f"[{inst['kind']}] {inst['root']} (version: {inst['version_id']})")

        lines.append("")
        if not self.files:
            lines.append("No target files found.")
        else:
            for f in self.files:
                status_parts = []
                for pname in f.patch_names:
                    is_patched = f.patched.get(pname, False)
                    status_parts.append(f"{pname}:{'patched' if is_patched else 'unpatched'}")
                backup_str = " [backup]" if f.has_backup else ""
                error_str = f" ERROR: {f.error}" if f.error else ""
                lines.append(
                    f"  {f.extension}/{f.path.name}: "
                    f"{', '.join(status_parts)}{backup_str}{error_str}"
                )
        return "\n".join(lines)
