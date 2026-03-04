"""macOS-only full app snapshot support for restoring official signatures."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .codesign import _find_app_bundle


_DEFAULT_AUTHORITY_HINTS = ["Anysphere"]


@dataclass
class SignatureInfo:
    """Best-effort parsed codesign signature details."""

    is_adhoc: bool = False
    authorities: List[str] = field(default_factory=list)
    team_identifier: str = ""
    cdhash: str = ""
    error: str = ""


@dataclass
class MacOSAppSnapshotResult:
    """Result for snapshot update/restore operations."""

    enabled: bool = False
    action: str = "skipped"  # created | updated | kept | restored | skipped | error
    app_path: Optional[Path] = None
    snapshot_path: Optional[Path] = None
    message: str = ""
    error: str = ""


def _truthy_env(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _is_enabled() -> bool:
    return sys.platform == "darwin" and not _truthy_env("CGP_DISABLE_MACOS_APP_SNAPSHOT")


def _snapshot_base_dir() -> Path:
    raw = os.environ.get("CGP_MACOS_APP_SNAPSHOT_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cursor_gui_patch" / "macos_official_app_snapshots"


def _slot_dir_for_app(app_path: Path) -> Path:
    digest = hashlib.sha256(str(app_path).encode("utf-8")).hexdigest()[:16]
    return _snapshot_base_dir() / f"{app_path.name}-{digest}"


def _snapshot_paths(app_path: Path) -> Tuple[Path, Path]:
    slot = _slot_dir_for_app(app_path)
    return slot / app_path.name, slot / "meta.json"


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _version_label(short_ver: str, build_ver: str) -> str:
    if short_ver and build_ver and short_ver != build_ver:
        return f"{short_ver} ({build_ver})"
    return short_ver or build_ver or "unknown"


def _read_bundle_version(app_path: Path) -> Tuple[str, str, str]:
    info_path = app_path / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as f:
            data = plistlib.load(f)
    except Exception:
        return "", "", ""
    short_ver = str(data.get("CFBundleShortVersionString", "") or "").strip()
    build_ver = str(data.get("CFBundleVersion", "") or "").strip()
    bundle_id = str(data.get("CFBundleIdentifier", "") or "").strip()
    return short_ver, build_ver, bundle_id


def _inspect_signature(app_path: Path) -> SignatureInfo:
    info = SignatureInfo()
    codesign_bin = shutil.which("codesign")
    if not codesign_bin:
        info.error = "codesign binary not found"
        return info
    try:
        proc = subprocess.run(
            [codesign_bin, "-dv", "--verbose=4", str(app_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as e:
        info.error = str(e)
        return info

    raw = "\n".join([proc.stdout or "", proc.stderr or ""])
    if proc.returncode != 0 and not raw.strip():
        info.error = f"codesign exited with code {proc.returncode}"
        return info

    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("Authority="):
            info.authorities.append(s.split("=", 1)[1].strip())
        elif s.startswith("TeamIdentifier="):
            info.team_identifier = s.split("=", 1)[1].strip()
        elif s.startswith("CDHash="):
            info.cdhash = s.split("=", 1)[1].strip()
        elif s.startswith("Signature=") and "adhoc" in s.lower():
            info.is_adhoc = True
        elif s.startswith("CodeDirectory") and "adhoc" in s.lower():
            info.is_adhoc = True

    return info


def _authority_hints() -> List[str]:
    raw = os.environ.get("CGP_MACOS_OFFICIAL_AUTHORITY_HINTS", "").strip()
    if not raw:
        return list(_DEFAULT_AUTHORITY_HINTS)
    return [p.strip() for p in raw.split(",") if p.strip()]


def _is_confident_official_signature(sig: SignatureInfo) -> Tuple[bool, str]:
    if sig.error:
        return False, f"cannot inspect app signature ({sig.error})"
    if sig.is_adhoc:
        return False, "current app signature is ad-hoc"
    if not sig.authorities:
        return False, "current app signature has no Authority entries"

    hints = _authority_hints()
    if not hints:
        return True, "authority hints disabled"

    joined = "\n".join(sig.authorities).lower()
    for hint in hints:
        if hint.lower() in joined:
            return True, f"authority matched hint '{hint}'"
    return False, f"authority did not match hints: {', '.join(hints)}"


def _same_snapshot_fingerprint(existing: Dict[str, Any], now: Dict[str, Any]) -> bool:
    keys = (
        "app_path",
        "bundle_id",
        "bundle_short_version",
        "bundle_build_version",
        "team_identifier",
        "cdhash",
        "authorities",
    )
    return all(existing.get(k) == now.get(k) for k in keys)


def _copy_app_bundle(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    ditto_bin = shutil.which("ditto")
    if ditto_bin:
        proc = subprocess.run(
            [ditto_bin, str(src), str(dst)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip() or f"ditto exited with code {proc.returncode}"
            raise RuntimeError(err)
        return

    shutil.copytree(src, dst, symlinks=True)


def update_official_app_snapshot(app_root: Path) -> MacOSAppSnapshotResult:
    """
    Save/refresh one latest official Cursor.app snapshot (macOS only).

    Snapshot update is conservative:
    - only runs on macOS GUI installs with detectable .app bundle
    - only refreshes when current signature is confidently official
    """
    result = MacOSAppSnapshotResult()
    if not _is_enabled():
        result.message = "macOS official app snapshot is disabled on this platform/config."
        return result

    app_path = _find_app_bundle(app_root)
    if app_path is None:
        result.enabled = True
        result.message = "macOS official app snapshot skipped: no .app bundle found."
        return result

    result.enabled = True
    result.app_path = app_path
    snapshot_app, meta_path = _snapshot_paths(app_path)
    result.snapshot_path = snapshot_app

    sig = _inspect_signature(app_path)
    ok, reason = _is_confident_official_signature(sig)
    if not ok:
        result.message = (
            f"macOS official app snapshot skipped: {reason}; "
            "keeping existing snapshot (if any)."
        )
        return result

    short_ver, build_ver, bundle_id = _read_bundle_version(app_path)
    meta: Dict[str, Any] = {
        "schema_version": 1,
        "captured_at": int(time.time()),
        "app_path": str(app_path),
        "bundle_id": bundle_id,
        "bundle_short_version": short_ver,
        "bundle_build_version": build_ver,
        "team_identifier": sig.team_identifier,
        "cdhash": sig.cdhash,
        "authorities": list(sig.authorities),
    }

    old_meta = _load_json(meta_path)
    had_existing = snapshot_app.is_dir()
    if had_existing and _same_snapshot_fingerprint(old_meta, meta):
        result.action = "kept"
        result.message = (
            "macOS official app snapshot already up-to-date "
            f"(version: {_version_label(short_ver, build_ver)})."
        )
        return result

    slot = _slot_dir_for_app(app_path)
    slot.parent.mkdir(parents=True, exist_ok=True)
    tmp_slot = slot.parent / f".{slot.name}.tmp.{os.getpid()}.{int(time.time())}"

    try:
        if tmp_slot.exists():
            shutil.rmtree(tmp_slot)
        tmp_slot.mkdir(parents=True, exist_ok=True)
        tmp_snapshot = tmp_slot / app_path.name
        tmp_meta = tmp_slot / "meta.json"
        _copy_app_bundle(app_path, tmp_snapshot)
        tmp_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=True), encoding="utf-8")

        if slot.exists():
            shutil.rmtree(slot)
        tmp_slot.rename(slot)

        result.action = "updated" if had_existing else "created"
        result.message = (
            f"macOS official app snapshot {result.action}: {snapshot_app} "
            f"(version: {_version_label(short_ver, build_ver)})."
        )
        return result
    except Exception as e:
        result.action = "error"
        result.error = str(e)
        result.message = f"macOS official app snapshot update failed: {e}"
        return result
    finally:
        if tmp_slot.exists():
            shutil.rmtree(tmp_slot, ignore_errors=True)


def restore_official_app_snapshot(app_root: Path) -> MacOSAppSnapshotResult:
    """Restore Cursor.app from saved official snapshot (macOS only)."""
    result = MacOSAppSnapshotResult()
    if not _is_enabled():
        result.message = "macOS official app snapshot is disabled on this platform/config."
        return result

    app_path = _find_app_bundle(app_root)
    if app_path is None:
        result.enabled = True
        result.message = "macOS official app snapshot restore skipped: no .app bundle found."
        return result

    result.enabled = True
    result.app_path = app_path
    snapshot_app, meta_path = _snapshot_paths(app_path)
    result.snapshot_path = snapshot_app

    if not snapshot_app.is_dir():
        result.message = (
            "macOS official app snapshot not found; fallback to file-level restore and re-sign."
        )
        return result

    meta = _load_json(meta_path)
    meta_app_path = str(meta.get("app_path", "") or "").strip()
    if meta_app_path:
        try:
            expected = Path(meta_app_path).expanduser().resolve()
            actual = app_path.resolve()
            if expected != actual:
                result.message = (
                    "macOS official app snapshot skipped: snapshot app path mismatch; "
                    "fallback to file-level restore and re-sign."
                )
                return result
        except Exception:
            pass

    parent = app_path.parent
    old_app = parent / f"{app_path.name}.cgp.old.{os.getpid()}.{int(time.time())}"
    if old_app.exists():
        shutil.rmtree(old_app, ignore_errors=True)

    try:
        if app_path.exists():
            app_path.rename(old_app)

        _copy_app_bundle(snapshot_app, app_path)

        if old_app.exists():
            shutil.rmtree(old_app)

        short_ver = str(meta.get("bundle_short_version", "") or "")
        build_ver = str(meta.get("bundle_build_version", "") or "")
        result.action = "restored"
        result.message = (
            "macOS official app snapshot restored "
            f"(version: {_version_label(short_ver, build_ver)})."
        )
        return result
    except Exception as e:
        result.action = "error"
        result.error = str(e)
        result.message = f"macOS official app snapshot restore failed: {e}"
        try:
            if app_path.exists():
                shutil.rmtree(app_path, ignore_errors=True)
            if old_app.exists():
                old_app.rename(app_path)
        except Exception:
            pass
        return result
    finally:
        if old_app.exists() and result.action == "restored":
            shutil.rmtree(old_app, ignore_errors=True)
