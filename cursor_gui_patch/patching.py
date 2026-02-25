"""Core patching engine: orchestrates discovery, patches, cache, and backup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from . import backup as bak
from . import cache as ca
from .codesign import codesign_app, needs_codesign
from .discovery import CursorInstallation, TargetFile, discover_all
from .patches import get_patch
from .patches.base import BasePatch
from .report import CodesignInfo, FileStatus, PatchReport, StatusReport, UnpatchReport


def patch(
    *,
    installations: Optional[List[CursorInstallation]] = None,
    server_dir: Optional[str] = None,
    gui_dir: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    only_patches: Optional[Set[str]] = None,
) -> PatchReport:
    """
    Apply patches to all discovered Cursor installations.

    Args:
        installations: Pre-discovered installations (if None, auto-discover).
        server_dir: Explicit server directory override.
        gui_dir: Explicit GUI directory override.
        dry_run: If True, don't write anything.
        force: If True, ignore cache.
        only_patches: If set, only apply these patch names.
    """
    if installations is None:
        installations = discover_all(server_dir=server_dir, gui_dir=gui_dir)

    report = PatchReport()

    for inst in installations:
        patched_before = len(report.patched)
        _patch_installation(
            inst, report,
            dry_run=dry_run, force=force, only_patches=only_patches,
        )
        patched_after = len(report.patched)

        # Re-sign macOS .app bundles if any files were actually modified
        if not dry_run and patched_after > patched_before:
            if needs_codesign(inst.root, inst.kind):
                cs = codesign_app(inst.root)
                report.codesign.append(CodesignInfo(
                    app_path=str(cs.app_path) if cs.app_path else str(inst.root),
                    success=cs.success,
                    error=cs.error,
                ))

    return report


def _patch_installation(
    inst: CursorInstallation,
    report: PatchReport,
    *,
    dry_run: bool,
    force: bool,
    only_patches: Optional[Set[str]],
) -> None:
    """Apply patches to a single installation."""
    # Load cache
    cache_data: Optional[Dict[str, Dict[str, Any]]] = None
    new_cache: Optional[Dict[str, Dict[str, Any]]] = None
    if not dry_run and not force:
        cache_data = ca.load_cache(inst.root)
    if not dry_run:
        new_cache = {}

    targets = inst.target_files()

    for target in targets:
        _patch_target(
            target, report,
            cache_data=cache_data,
            new_cache=new_cache,
            dry_run=dry_run,
            only_patches=only_patches,
        )

    # Save cache
    if new_cache is not None:
        try:
            ca.save_cache(inst.root, new_cache)
        except Exception:
            pass


def _patch_target(
    target: TargetFile,
    report: PatchReport,
    *,
    cache_data: Optional[Dict[str, Dict[str, Any]]],
    new_cache: Optional[Dict[str, Dict[str, Any]]],
    dry_run: bool,
    only_patches: Optional[Set[str]],
) -> None:
    """Apply relevant patches to a single target file."""
    path = target.path
    root = target.installation.root
    cache_key = ca.make_cache_key(path, root)

    # Check cache
    st: Optional[os.stat_result] = None
    if cache_data is not None:
        try:
            st = path.stat()
        except Exception as e:
            report.errors.append((path, f"stat failed: {e}"))
            return
        cached = cache_data.get(cache_key)
        if isinstance(cached, dict) and ca.cache_entry_matches(cached, st):
            report.skipped_cached += 1
            status = cached.get("status")
            if status == ca.STATUS_PATCHED:
                report.already_patched += 1
            elif status == ca.STATUS_NOT_APPLICABLE:
                report.skipped_not_applicable += 1
            if new_cache is not None:
                new_cache[cache_key] = cached
            return

    report.scanned += 1

    # Read file
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        report.errors.append((path, f"read failed: {e}"))
        return

    # Determine which patches to apply
    patch_names = target.patch_names
    if only_patches:
        patch_names = [n for n in patch_names if n in only_patches]

    # Apply patches
    new_content = content
    any_applied = False
    any_already = False
    any_not_applicable = True  # assume not applicable until proven otherwise

    for patch_name in patch_names:
        try:
            p = get_patch(patch_name)
        except ValueError as e:
            report.errors.append((path, str(e)))
            continue

        new_content, result = p.apply(new_content)
        if result.applied:
            any_applied = True
            any_not_applicable = False
        if result.already_patched:
            any_already = True
            any_not_applicable = False

    if not any_applied:
        # Nothing changed
        if any_already:
            report.already_patched += 1
            cache_status = ca.STATUS_PATCHED
        else:
            report.skipped_not_applicable += 1
            cache_status = ca.STATUS_NOT_APPLICABLE

        if new_cache is not None:
            if st is None:
                try:
                    st = path.stat()
                except Exception:
                    st = None
            if st is not None:
                new_cache[cache_key] = ca.make_cache_entry(cache_status, st)
        return

    if dry_run:
        report.patched.append(path)
        return

    # Create backup (idempotent)
    bak.create_backup(path)

    # Write patched content
    if st is None:
        try:
            st = path.stat()
        except Exception:
            st = None

    try:
        path.write_text(new_content, encoding="utf-8")
        # Preserve permissions
        if st is not None:
            try:
                os.chmod(path, st.st_mode)
            except Exception:
                pass
        report.patched.append(path)

        # Update cache
        if new_cache is not None:
            try:
                st_after = path.stat()
                new_cache[cache_key] = ca.make_cache_entry(ca.STATUS_PATCHED, st_after)
            except Exception:
                pass
    except Exception as e:
        report.errors.append((path, f"write failed: {e}"))


def unpatch(
    *,
    installations: Optional[List[CursorInstallation]] = None,
    server_dir: Optional[str] = None,
    gui_dir: Optional[str] = None,
    dry_run: bool = False,
) -> UnpatchReport:
    """Restore all patched files from backups."""
    if installations is None:
        installations = discover_all(server_dir=server_dir, gui_dir=gui_dir)

    report = UnpatchReport()

    for inst in installations:
        restored_before = len(report.restored)
        targets = inst.target_files()
        for target in targets:
            path = target.path
            if not bak.has_backup(path):
                report.no_backup.append(path)
                continue

            if dry_run:
                report.restored.append(path)
                continue

            try:
                if bak.restore_backup(path):
                    report.restored.append(path)
                    # Remove the backup after successful restore
                    bak.remove_backup(path)
                    # Invalidate cache
                    try:
                        cache_file = ca.cache_path(inst.root)
                        if cache_file.exists():
                            cache_file.unlink()
                    except Exception:
                        pass
                else:
                    report.errors.append((path, "restore failed"))
            except Exception as e:
                report.errors.append((path, f"restore failed: {e}"))

        restored_after = len(report.restored)

        # Re-sign macOS .app bundles if any files were actually restored
        if not dry_run and restored_after > restored_before:
            if needs_codesign(inst.root, inst.kind):
                cs = codesign_app(inst.root)
                report.codesign.append(CodesignInfo(
                    app_path=str(cs.app_path) if cs.app_path else str(inst.root),
                    success=cs.success,
                    error=cs.error,
                ))

    return report


def status(
    *,
    installations: Optional[List[CursorInstallation]] = None,
    server_dir: Optional[str] = None,
    gui_dir: Optional[str] = None,
) -> StatusReport:
    """Check the status of all target files."""
    if installations is None:
        installations = discover_all(server_dir=server_dir, gui_dir=gui_dir)

    report = StatusReport()

    for inst in installations:
        report.installations.append({
            "kind": inst.kind,
            "root": str(inst.root),
            "version_id": inst.version_id,
        })

        targets = inst.target_files()
        for target in targets:
            fs = FileStatus(
                path=target.path,
                extension=target.extension,
                patch_names=target.patch_names,
                has_backup=bak.has_backup(target.path),
            )

            try:
                content = target.path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                fs.error = f"read failed: {e}"
                report.files.append(fs)
                continue

            for patch_name in target.patch_names:
                try:
                    p = get_patch(patch_name)
                    fs.patched[patch_name] = p.is_already_patched(content)
                except Exception:
                    fs.patched[patch_name] = False

            report.files.append(fs)

    return report
