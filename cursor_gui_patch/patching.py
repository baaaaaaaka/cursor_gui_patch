"""Core patching engine: orchestrates discovery, patches, cache, and backup."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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
    errors_before_install = len(report.errors)

    # Load cache
    cache_data: Optional[Dict[str, Dict[str, Any]]] = None
    new_cache: Optional[Dict[str, Dict[str, Any]]] = None
    if not dry_run and not force:
        cache_data = ca.load_cache(inst.root)
    if not dry_run:
        new_cache = {}

    targets = inst.target_files()
    hash_pairs: List[Tuple[str, str]] = []
    patched_before = len(report.patched)

    for target in targets:
        result = _patch_target(
            target, report,
            cache_data=cache_data,
            new_cache=new_cache,
            dry_run=dry_run,
            only_patches=only_patches,
        )
        if result is not None:
            hash_pairs.append(result)

    # Update extension host hashes after all extension files are patched
    ext_host_modified = False
    if hash_pairs:
        ext_host_modified = _update_extension_host_hashes(inst, hash_pairs, report)

    # Update product.json checksums for any modified files under out/
    if not dry_run:
        newly_patched = report.patched[patched_before:]
        out_dir = inst.root / "out"
        out_files: List[Path] = []
        for p in newly_patched:
            try:
                p.relative_to(out_dir)
                out_files.append(p)
            except ValueError:
                pass
        if ext_host_modified:
            ext_host = inst.root / _EXT_HOST_RELPATH
            if ext_host not in out_files:
                out_files.append(ext_host)
        if out_files:
            _update_product_json_checksums(inst, out_files, report)

    # Roll back this installation if any errors happened after writes.
    if not dry_run and len(report.errors) > errors_before_install and len(report.patched) > patched_before:
        _rollback_installation_changes(inst, report, patched_from=patched_before)

    # Save cache
    if new_cache is not None and len(report.errors) == errors_before_install:
        try:
            ca.save_cache(inst.root, new_cache)
        except Exception:
            pass


_EXT_HOST_RELPATH = Path("out/vs/workbench/api/node/extensionHostProcess.js")


def _rollback_installation_changes(
    inst: CursorInstallation,
    report: PatchReport,
    *,
    patched_from: int,
) -> None:
    """Best-effort rollback of files modified during this installation patch run."""
    restore_paths: List[Path] = []
    restore_paths.extend(report.patched[patched_from:])
    restore_paths.extend([inst.root / _EXT_HOST_RELPATH, inst.root / "product.json"])

    seen: Set[Path] = set()
    for p in restore_paths:
        if p in seen:
            continue
        seen.add(p)
        if not bak.has_backup(p):
            continue
        try:
            if not bak.restore_backup(p):
                report.errors.append((p, "rollback restore failed"))
        except Exception as e:
            report.errors.append((p, f"rollback restore failed: {e}"))

    # These paths are no longer considered patched after rollback.
    del report.patched[patched_from:]

    # Cache may contain stale "patched" states; drop it.
    try:
        cache_file = ca.cache_path(inst.root)
        if cache_file.exists():
            cache_file.unlink()
    except Exception:
        pass


def _update_extension_host_hashes(
    inst: CursorInstallation,
    hash_pairs: List[Tuple[str, str]],
    report: PatchReport,
) -> bool:
    """Replace old extension file hashes with new ones in extensionHostProcess.js.

    Returns True if the file was modified.
    """
    ext_host = inst.root / _EXT_HOST_RELPATH
    if not ext_host.is_file():
        return False

    try:
        content = ext_host.read_bytes().decode("utf-8", errors="replace")
    except Exception as e:
        report.errors.append((ext_host, f"read failed: {e}"))
        return False

    original_content = content
    for old_hash, new_hash in hash_pairs:
        content = content.replace(old_hash, new_hash)

    if content == original_content:
        # No hashes were found/replaced — nothing to do
        return False

    if bak.create_backup(ext_host) is None:
        report.errors.append((ext_host, "backup failed"))
        return False

    try:
        ext_host.write_bytes(content.encode("utf-8"))
        return True
    except Exception as e:
        report.errors.append((ext_host, f"write failed: {e}"))
        return False


def _update_product_json_checksums(
    inst: CursorInstallation,
    modified_files: List[Path],
    report: PatchReport,
) -> None:
    """Update checksums in product.json for modified files under out/.

    GUI installs have a non-empty ``checksums`` dict in product.json mapping
    relative paths (from ``out/``) to ``base64(sha256, no padding)``.  Server
    installs have ``{}`` and are skipped automatically.
    """
    product_json = inst.root / "product.json"
    if not product_json.is_file():
        return

    try:
        raw = product_json.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        report.errors.append((product_json, f"read failed: {e}"))
        return

    checksums = data.get("checksums")
    if not isinstance(checksums, dict) or not checksums:
        return  # Server installs have empty checksums — nothing to update

    out_dir = inst.root / "out"
    updated = False

    for file_path in modified_files:
        try:
            rel = file_path.relative_to(out_dir).as_posix()
        except ValueError:
            continue  # Not under out/, skip

        if rel not in checksums:
            continue

        try:
            file_bytes = file_path.read_bytes()
        except Exception:
            continue

        digest = hashlib.sha256(file_bytes).digest()
        new_hash = base64.b64encode(digest).decode("ascii").rstrip("=")
        checksums[rel] = new_hash
        updated = True

    if not updated:
        return

    if bak.create_backup(product_json) is None:
        report.errors.append((product_json, "backup failed"))
        return

    try:
        # Write back with compact separators to match original Cursor format
        product_json.write_bytes(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except Exception as e:
        report.errors.append((product_json, f"write failed: {e}"))


def _patch_target(
    target: TargetFile,
    report: PatchReport,
    *,
    cache_data: Optional[Dict[str, Dict[str, Any]]],
    new_cache: Optional[Dict[str, Dict[str, Any]]],
    dry_run: bool,
    only_patches: Optional[Set[str]],
) -> Optional[Tuple[str, str]]:
    """Apply relevant patches to a single target file.

    Returns (old_hash, new_hash) if a file was actually written, else None.
    """
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
            return None
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
            return None

    report.scanned += 1

    # Read file (binary mode to preserve exact bytes — avoids Windows text-mode
    # converting \n to \r\n on write).
    try:
        original_bytes = path.read_bytes()
        content = original_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        report.errors.append((path, f"read failed: {e}"))
        return None

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
        return None

    if dry_run:
        report.patched.append(path)
        return None

    # Compute hash of original content before writing
    old_hash = hashlib.sha256(original_bytes).hexdigest()

    # Create backup (idempotent)
    if bak.create_backup(path) is None:
        report.errors.append((path, "backup failed"))
        return None

    # Write patched content
    if st is None:
        try:
            st = path.stat()
        except Exception:
            st = None

    try:
        new_bytes = new_content.encode("utf-8")
        path.write_bytes(new_bytes)
        # Preserve permissions
        if st is not None:
            try:
                os.chmod(path, st.st_mode)
            except Exception:
                pass
        report.patched.append(path)

        # Compute hash of new content
        new_hash = hashlib.sha256(new_bytes).hexdigest()

        # Update cache
        if new_cache is not None:
            try:
                st_after = path.stat()
                new_cache[cache_key] = ca.make_cache_entry(ca.STATUS_PATCHED, st_after)
            except Exception:
                pass

        return (old_hash, new_hash)
    except Exception as e:
        report.errors.append((path, f"write failed: {e}"))
        return None


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

        # Restore auxiliary files (extensionHostProcess.js, product.json) if backed up
        for aux_path in (inst.root / _EXT_HOST_RELPATH, inst.root / "product.json"):
            if not dry_run and bak.has_backup(aux_path):
                try:
                    if bak.restore_backup(aux_path):
                        report.restored.append(aux_path)
                        bak.remove_backup(aux_path)
                    else:
                        report.errors.append((aux_path, "restore failed"))
                except Exception as e:
                    report.errors.append((aux_path, f"restore failed: {e}"))
            elif dry_run and bak.has_backup(aux_path):
                report.restored.append(aux_path)

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
                content = target.path.read_bytes().decode("utf-8", errors="replace")
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
