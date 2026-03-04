"""Report data classes for patch/unpatch/status operations."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .macos_privacy import detect_current_process_context, diagnose_macos_privacy_denial


def _is_macos_app_bundle_path(path: Path) -> bool:
    s = str(path)
    return s.startswith("/Applications/") and ".app/" in s


def _has_permission_error(errors: List[Tuple[Path, str]]) -> bool:
    """Check if any error looks like a permission issue."""
    for _, msg in errors:
        low = msg.lower()
        if (
            "permission denied" in low
            or "errno 13" in low
            or "access is denied" in low
            or ("operation not permitted" in low and sys.platform == "darwin")
        ):
            return True
    return False


def _permission_hint() -> str:
    if sys.platform == "win32":
        return "Fix: Run as Administrator"
    return "Fix: Run with elevated permissions:\n  sudo cgp patch        (Linux/macOS)"


def _looks_like_macos_privacy_error(errors: List[Tuple[Path, str]]) -> bool:
    """Detect likely macOS TCC/App Management denial when patching Cursor.app."""
    return diagnose_macos_privacy_denial(errors).likely


def _macos_privacy_hint(command: str) -> List[str]:
    """Actionable fix steps for macOS privacy permission denial."""
    proc = detect_current_process_context()
    return [
        "macOS privacy protections likely blocked writes to /Applications/Cursor.app.",
        "What happened:",
        "  cgp could read target files but failed while creating in-place backups (*.cgp.bak).",
        "Detected process info (best effort):",
        f"  current process: {proc.current_process}",
        (
            f"  detected terminal app: {proc.terminal_process} "
            f"(source: {proc.terminal_source})"
        ),
        "  Note: detection may be inaccurate; use the terminal app you are actually using.",
        "Fix:",
        "  1) Quit Cursor completely.",
        "  2) System Settings -> Privacy & Security -> App Management:",
        "     allow your terminal app (Terminal/iTerm).",
        "  3) If still blocked, enable Full Disk Access for your terminal app.",
        f"  4) Re-run with elevated permissions: sudo cgp {command}",
    ]


def _macos_keychain_popup_note(
    *,
    operation: str,
    identities: List[str],
) -> List[str]:
    """Explain expected Keychain prompts and best-practice handling on macOS."""
    uniq = sorted({i for i in identities if i})
    has_adhoc = "-" in uniq
    identity_str = ", ".join(uniq) if uniq else "unknown"
    lines = [
        "================ macOS Keychain / Signature =================",
        "Why prompts may appear:",
        "  Keychain permission is tied to code-sign identity.",
        f"  This run used identity: {identity_str}",
        "Best practice:",
        "  1) Use a fixed identity: export CGP_CODESIGN_IDENTITY=\"CGP Cursor Patch\"",
        "  2) Confirm requester path is /Applications/Cursor.app, then click Always Allow.",
        "  3) If prompts repeat, review \"Cursor Safe Storage\" access in Keychain Access.",
        "Password prompts (typical):",
        "  Usually 0-2 prompts around update/patch cycles.",
        "  Each prompt may ask macOS login password once.",
    ]
    if has_adhoc:
        lines.append(
            "Note: ad-hoc identity (-) was used; this is more likely to trigger repeated prompts."
        )

    if operation == "unpatch":
        lines.extend([
            "Official signature restore:",
            "  This run used file-level restore + re-sign; vendor signature was not restored.",
            "  To return to official signature, restore from cgp official snapshot or reinstall/update Cursor.",
            "TLDR >>> fallback unpatch does not restore vendor signature; use snapshot restore or reinstall/update Cursor."
            " If trusted prompts from /Applications/Cursor.app appear, click Always Allow (or equivalent).",
        ])
    else:
        lines.append(
            "TLDR >>> prompts after update+patch are expected; if trusted prompt path is /Applications/Cursor.app,"
            " click Always Allow (or equivalent) once and keep one fixed identity."
        )
    return lines


@dataclass
class CodesignInfo:
    """Info about a codesign operation on a macOS .app bundle."""
    app_path: str = ""
    success: bool = False
    error: str = ""
    identity: str = "-"
    warning: str = ""


@dataclass
class PatchReport:
    """Report for a patch or unpatch operation."""
    scanned: int = 0
    patched: List[Path] = field(default_factory=list)
    already_patched: int = 0
    skipped_not_applicable: int = 0
    skipped_cached: int = 0
    errors: List[Tuple[Path, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
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
        if self.notes:
            lines.append("")
            lines.append("Notes:")
            for note in self.notes:
                lines.append(f"  {note}")
        if self.codesign:
            for cs in self.codesign:
                if cs.success:
                    lines.append(
                        f"Codesign: {cs.app_path} (re-signed, identity: {cs.identity})"
                    )
                    if sys.platform == "darwin" and cs.identity == "-":
                        lines.append(
                            "Codesign TIP: set CGP_CODESIGN_IDENTITY to a fixed identity"
                            " to reduce repeated Keychain prompts."
                        )
                    if cs.warning:
                        lines.append(f"Codesign NOTE: {cs.warning}")
                elif cs.error:
                    lines.append(f"Codesign FAILED: {cs.error}")
                    lines.append(
                        f"Fix: sudo codesign --force --deep --sign - {cs.app_path}"
                    )
            if sys.platform == "darwin" and any(cs.success for cs in self.codesign):
                lines.append("")
                lines.extend(_macos_keychain_popup_note(
                    operation="patch",
                    identities=[cs.identity for cs in self.codesign if cs.success],
                ))
        elif (
            sys.platform == "darwin"
            and not self.errors
            and self.already_patched > 0
            and len(self.patched) == 0
        ):
            # No write occurred in this run, so codesign did not run.
            lines.append("")
            lines.append("macOS Keychain note:")
            lines.append("  This run made no file changes, so Cursor.app was not re-signed.")
            lines.append("  If Cursor was updated recently, first launch may still show Keychain prompts.")
            lines.append("  Approve trusted prompts for /Applications/Cursor.app.")
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for path, msg in self.errors:
                lines.append(f"  {path}: {msg}")
            if _looks_like_macos_privacy_error(self.errors):
                diag = diagnose_macos_privacy_denial(self.errors)
                lines.append("")
                lines.append("macOS privacy diagnosis:")
                lines.append(
                    f"  app-bundle paths: {diag.app_bundle_errors}/{diag.total_errors}, "
                    f"EPERM (Errno 1 + operation not permitted): {diag.errno1_errors}/{diag.total_errors}"
                )
                lines.append(
                    f"  confidence: {'certain' if diag.certain else 'likely (not certain)'}"
                )
                lines.extend(_macos_privacy_hint("patch"))
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
    notes: List[str] = field(default_factory=list)
    codesign: List[CodesignInfo] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"Restored: {len(self.restored)}",
            f"No backup: {len(self.no_backup)}",
        ]
        snapshot_restored = any("snapshot restored" in n.lower() for n in self.notes)
        has_macos_gui_target = any(_is_macos_app_bundle_path(p) for p in self.no_backup)
        has_snapshot_note = any("snapshot" in n.lower() for n in self.notes)
        no_restore_happened = (
            len(self.restored) == 0
            and len(self.no_backup) > 0
            and not self.errors
            and (has_macos_gui_target or has_snapshot_note)
        )
        if self.notes:
            lines.append("")
            lines.append("Notes:")
            for note in self.notes:
                lines.append(f"  {note}")
        if sys.platform == "darwin" and no_restore_happened:
            lines.append("")
            lines.append("macOS restore hint:")
            lines.append("  No snapshot/backup restore was applied in this run.")
            lines.append("  This is common if app was patched by older cgp versions without app snapshot.")
            lines.append("  To return to official state, reinstall/update Cursor from the official installer.")
        if self.codesign:
            for cs in self.codesign:
                if cs.success:
                    lines.append(
                        f"Codesign: {cs.app_path} (re-signed, identity: {cs.identity})"
                    )
                    if sys.platform == "darwin" and cs.identity == "-":
                        lines.append(
                            "Codesign TIP: set CGP_CODESIGN_IDENTITY to a fixed identity"
                            " to reduce repeated Keychain prompts."
                        )
                    if cs.warning:
                        lines.append(f"Codesign NOTE: {cs.warning}")
                elif cs.error:
                    lines.append(f"Codesign FAILED: {cs.error}")
                    lines.append(
                        f"Fix: sudo codesign --force --deep --sign - {cs.app_path}"
                    )
            if sys.platform == "darwin" and any(cs.success for cs in self.codesign):
                lines.append("")
                if snapshot_restored:
                    lines.append(
                        "Note: installs restored from official snapshots kept vendor signatures;"
                        " notes below apply to file-level restore + re-sign paths."
                    )
                lines.extend(_macos_keychain_popup_note(
                    operation="unpatch",
                    identities=[cs.identity for cs in self.codesign if cs.success],
                ))
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for path, msg in self.errors:
                lines.append(f"  {path}: {msg}")
            if _looks_like_macos_privacy_error(self.errors):
                diag = diagnose_macos_privacy_denial(self.errors)
                lines.append("")
                lines.append("macOS privacy diagnosis:")
                lines.append(
                    f"  app-bundle paths: {diag.app_bundle_errors}/{diag.total_errors}, "
                    f"EPERM (Errno 1 + operation not permitted): {diag.errno1_errors}/{diag.total_errors}"
                )
                lines.append(
                    f"  confidence: {'certain' if diag.certain else 'likely (not certain)'}"
                )
                lines.extend(_macos_privacy_hint("unpatch"))
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
