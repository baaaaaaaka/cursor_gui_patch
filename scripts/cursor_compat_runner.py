#!/usr/bin/env python3
"""Run Cursor compatibility checks against real GUI/server artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import traceback
import urllib.request
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

from cursor_gui_patch.discovery import CursorInstallation


USER_AGENT = "cursor-gui-patch-compat"
EXT_HOST_RELPATH = Path("out/vs/workbench/api/node/extensionHostProcess.js")
WINDOWS_INSTALLER_LOG = "installer.log"


class CompatError(RuntimeError):
    """Compatibility check failure."""


def _write_json(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f)


def _run(
    cmd: List[str],
    *,
    cwd: Path | None = None,
    env: Dict[str, str] | None = None,
    timeout: int = 900,
    log_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "COMMAND:\n"
            + " ".join(cmd)
            + "\n\nSTDOUT:\n"
            + proc.stdout
            + "\n\nSTDERR:\n"
            + proc.stderr,
            encoding="utf-8",
        )
    if proc.returncode != 0:
        raise CompatError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )
    return proc


def _sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _base64_sha256_nopad(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).digest()
    return base64.b64encode(digest).decode("ascii").rstrip("=")


def _load_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _find_cursor_app_root(search_root: Path) -> Path:
    for product_json in sorted(search_root.rglob("product.json")):
        try:
            data = json.loads(product_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("applicationName") == "cursor":
            return product_json.parent
    raise CompatError(f"could not find Cursor app root under {search_root}")


def _collect_snapshot(root: Path, kind: str) -> Dict[str, object]:
    inst = CursorInstallation(kind=kind, root=root, version_id="compat")
    targets = inst.target_files()
    out: Dict[str, object] = {
        "root": str(root),
        "kind": kind,
        "targets": {},
    }
    target_data: Dict[str, Dict[str, object]] = {}
    for target in targets:
        rel = _relative(target.path, root)
        target_data[rel] = {
            "extension": target.extension,
            "patch_names": list(target.patch_names),
            "sha256": _sha256_hex(target.path),
        }
    out["targets"] = target_data

    ext_host = root / EXT_HOST_RELPATH
    if ext_host.is_file():
        out["extension_host_sha256"] = _sha256_hex(ext_host)
        out["extension_host_text"] = ext_host.read_text(encoding="utf-8", errors="replace")

    product_json = root / "product.json"
    if product_json.is_file():
        out["product_json"] = _load_json(product_json)

    return out


def _status_json(root: Path, *, kind: str) -> Dict[str, object]:
    disabled = root / ".cgp-disabled-other-target"
    args = [sys.executable, "-m", "cursor_gui_patch"]
    if kind == "gui":
        args.extend(["--gui-dir", str(root), "--server-dir", str(disabled)])
    else:
        args.extend(["--server-dir", str(root), "--gui-dir", str(disabled)])
    args.extend(["status", "--json"])
    proc = _run(args)
    return json.loads(proc.stdout)


def _run_patch(root: Path, *, kind: str, command: str, log_dir: Path) -> str:
    disabled = root / ".cgp-disabled-other-target"
    args = [sys.executable, "-m", "cursor_gui_patch"]
    if kind == "gui":
        args.extend(["--gui-dir", str(root), "--server-dir", str(disabled)])
    else:
        args.extend(["--server-dir", str(root), "--gui-dir", str(disabled)])
    args.append(command)
    proc = _run(args, log_path=log_dir / f"{command}.log")
    return proc.stdout


def _assert_patched_status(status_data: Dict[str, object], *, require_backups: bool) -> int:
    files = status_data.get("files")
    if not isinstance(files, list) or not files:
        raise CompatError("status output had no target files")

    patched_count = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise CompatError("status output had malformed file entry")
        patched = entry.get("patched")
        if not isinstance(patched, dict) or not patched:
            raise CompatError(f"status output missing patched flags for {entry}")
        if not all(bool(v) for v in patched.values()):
            raise CompatError(f"some patches were not applied: {entry}")
        patched_count += sum(1 for v in patched.values() if v)
        has_backup = bool(entry.get("has_backup"))
        if require_backups and not has_backup:
            raise CompatError(f"patched file is missing backup: {entry}")
        if not require_backups and has_backup:
            raise CompatError(f"unpatched file still has backup: {entry}")
    return patched_count


def _assert_unpatched_status(status_data: Dict[str, object]) -> None:
    files = status_data.get("files")
    if not isinstance(files, list) or not files:
        raise CompatError("status output had no target files after unpatch")
    for entry in files:
        if not isinstance(entry, dict):
            raise CompatError("status output had malformed file entry after unpatch")
        patched = entry.get("patched")
        if not isinstance(patched, dict) or not patched:
            raise CompatError(f"status output missing patched flags after unpatch: {entry}")
        if any(bool(v) for v in patched.values()):
            raise CompatError(f"file remained patched after unpatch: {entry}")
        if bool(entry.get("has_backup")):
            raise CompatError(f"backup remained after unpatch: {entry}")


def _assert_snapshots_restored(before: Dict[str, object], after: Dict[str, object]) -> None:
    before_targets = before.get("targets", {})
    after_targets = after.get("targets", {})
    if not isinstance(before_targets, dict) or not isinstance(after_targets, dict):
        raise CompatError("snapshot target data missing during restore validation")
    if before_targets.keys() != after_targets.keys():
        raise CompatError("target files changed across unpatch validation")
    for rel, before_info in before_targets.items():
        after_info = after_targets.get(rel)
        if not isinstance(before_info, dict) or not isinstance(after_info, dict):
            raise CompatError("malformed target snapshot data")
        if before_info.get("sha256") != after_info.get("sha256"):
            raise CompatError(f"file was not restored by unpatch: {rel}")

    if before.get("extension_host_sha256") != after.get("extension_host_sha256"):
        raise CompatError("extensionHostProcess.js was not restored by unpatch")

    if before.get("product_json") != after.get("product_json"):
        raise CompatError("product.json was not restored by unpatch")


def _assert_gui_integrity(before: Dict[str, object], after: Dict[str, object], root: Path) -> Dict[str, object]:
    before_targets = before.get("targets", {})
    after_targets = after.get("targets", {})
    if not isinstance(before_targets, dict) or not isinstance(after_targets, dict):
        raise CompatError("snapshot target data missing during GUI validation")

    changed_targets: List[str] = []
    changed_extension_targets: List[str] = []
    changed_out_targets: List[str] = []

    ext_host_text = str(after.get("extension_host_text", ""))
    for rel, before_info in before_targets.items():
        after_info = after_targets.get(rel)
        if not isinstance(before_info, dict) or not isinstance(after_info, dict):
            raise CompatError("malformed GUI target snapshot")
        old_hash = str(before_info.get("sha256", ""))
        new_hash = str(after_info.get("sha256", ""))
        if not old_hash or not new_hash:
            raise CompatError(f"missing target hash for {rel}")
        if old_hash == new_hash:
            continue
        changed_targets.append(rel)
        rel_parts = Path(rel).parts
        if rel_parts and rel_parts[0] == "extensions":
            changed_extension_targets.append(rel)
            if new_hash not in ext_host_text:
                raise CompatError(f"extension host did not gain updated hash for {rel}")
            if old_hash in ext_host_text:
                raise CompatError(f"extension host still contains stale hash for {rel}")
        if rel_parts and rel_parts[0] == "out":
            changed_out_targets.append(rel)

    if not changed_targets:
        raise CompatError("GUI patch changed no target files")

    product_json = after.get("product_json", {})
    if not isinstance(product_json, dict):
        raise CompatError("product.json snapshot missing after GUI patch")
    checksums = product_json.get("checksums")
    if not isinstance(checksums, dict) or not checksums:
        raise CompatError("GUI product.json checksums were missing after patch")

    for rel in changed_out_targets:
        checksum_key = str(Path(rel).relative_to("out").as_posix())
        expected = _base64_sha256_nopad(root / rel)
        actual = checksums.get(checksum_key)
        if actual != expected:
            raise CompatError(
                f"product.json checksum mismatch for {checksum_key}: expected {expected}, got {actual}"
            )

    return {
        "changed_targets": changed_targets,
        "changed_extension_targets": changed_extension_targets,
        "changed_out_targets": changed_out_targets,
    }


def _extract_server_archive(archive: Path, work_dir: Path) -> Path:
    extract_dir = work_dir / "server"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        try:
            tf.extractall(extract_dir, filter="fully_trusted")
        except TypeError:
            tf.extractall(extract_dir)
    for child in extract_dir.iterdir():
        if child.is_dir():
            return child
    raise CompatError("could not find extracted Cursor server directory")


def _prepare_linux_gui(archive: Path, work_dir: Path) -> Path:
    archive.chmod(archive.stat().st_mode | stat.S_IXUSR)
    _run([str(archive), "--appimage-extract"], cwd=work_dir, log_path=work_dir / "extract.log")
    return _find_cursor_app_root(work_dir / "squashfs-root")


def _prepare_macos_gui(archive: Path, work_dir: Path) -> Path:
    mount_dir = work_dir / "mnt"
    mount_dir.mkdir(parents=True, exist_ok=True)
    copied_app = work_dir / "Cursor.app"
    try:
        _run(
            [
                "hdiutil",
                "attach",
                "-nobrowse",
                "-readonly",
                "-mountpoint",
                str(mount_dir),
                str(archive),
            ],
            log_path=work_dir / "attach.log",
        )
        source_app = mount_dir / "Cursor.app"
        if not source_app.is_dir():
            raise CompatError(f"mounted dmg did not contain Cursor.app at {source_app}")
        _run(["ditto", str(source_app), str(copied_app)], log_path=work_dir / "copy.log")
    finally:
        subprocess.run(
            ["hdiutil", "detach", str(mount_dir), "-force"],
            capture_output=True,
            text=True,
        )
    return _find_cursor_app_root(copied_app)


def _windows_install_roots(work_dir: Path) -> List[Path]:
    roots = [work_dir / "install"]
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        roots.append(Path(localappdata) / "Programs" / "cursor")
    return roots


def _prepare_windows_gui(archive: Path, work_dir: Path) -> Path:
    install_dir = work_dir / "install"
    install_dir.mkdir(parents=True, exist_ok=True)
    installer_log = work_dir / WINDOWS_INSTALLER_LOG
    args = [
        str(archive),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        "/CURRENTUSER",
        "/NOICONS",
        f"/DIR={install_dir}",
        f"/LOG={installer_log}",
    ]
    _run(args, log_path=work_dir / "install.log")
    for root in _windows_install_roots(work_dir):
        try:
            return _find_cursor_app_root(root)
        except CompatError:
            continue
    raise CompatError("could not find installed Cursor app after Windows installer ran")


def _prepare_gui_installation(platform_name: str, archive: Path, work_dir: Path) -> Path:
    if platform_name == "linux-gui":
        return _prepare_linux_gui(archive, work_dir)
    if platform_name == "macos-gui":
        return _prepare_macos_gui(archive, work_dir)
    if platform_name == "windows-gui":
        return _prepare_windows_gui(archive, work_dir)
    raise CompatError(f"unsupported GUI target: {platform_name}")


def _check_gui(target: str, archive: Path, work_dir: Path) -> Dict[str, object]:
    gui_root = _prepare_gui_installation(target, archive, work_dir)
    before = _collect_snapshot(gui_root, "gui")
    _write_json(work_dir / "before.json", before)

    patch_stdout = _run_patch(gui_root, kind="gui", command="patch", log_dir=work_dir)
    if "Patched:" not in patch_stdout:
        raise CompatError("GUI patch output did not include patched summary")

    patched_status = _status_json(gui_root, kind="gui")
    _write_json(work_dir / "status_after_patch.json", patched_status)
    patched_count = _assert_patched_status(patched_status, require_backups=True)

    after_patch = _collect_snapshot(gui_root, "gui")
    _write_json(work_dir / "after_patch.json", after_patch)
    integrity = _assert_gui_integrity(before, after_patch, gui_root)

    unpatch_stdout = _run_patch(gui_root, kind="gui", command="unpatch", log_dir=work_dir)
    if "Restored:" not in unpatch_stdout:
        raise CompatError("GUI unpatch output did not include restored summary")

    unpatched_status = _status_json(gui_root, kind="gui")
    _write_json(work_dir / "status_after_unpatch.json", unpatched_status)
    _assert_unpatched_status(unpatched_status)

    after_unpatch = _collect_snapshot(gui_root, "gui")
    _write_json(work_dir / "after_unpatch.json", after_unpatch)
    _assert_snapshots_restored(before, after_unpatch)

    return {
        "app_root": str(gui_root),
        "patched_count": patched_count,
        **integrity,
    }


def _check_server(archive: Path, work_dir: Path) -> Dict[str, object]:
    server_root = _extract_server_archive(archive, work_dir)
    before = _collect_snapshot(server_root, "server")
    _write_json(work_dir / "before.json", before)

    patch_stdout = _run_patch(server_root, kind="server", command="patch", log_dir=work_dir)
    if "Patched:" not in patch_stdout:
        raise CompatError("server patch output did not include patched summary")

    patched_status = _status_json(server_root, kind="server")
    _write_json(work_dir / "status_after_patch.json", patched_status)
    patched_count = _assert_patched_status(patched_status, require_backups=True)

    after_patch = _collect_snapshot(server_root, "server")
    _write_json(work_dir / "after_patch.json", after_patch)
    changed_targets = []
    before_targets = before.get("targets", {})
    after_targets = after_patch.get("targets", {})
    if not isinstance(before_targets, dict) or not isinstance(after_targets, dict):
        raise CompatError("snapshot target data missing during server validation")
    for rel, before_info in before_targets.items():
        after_info = after_targets.get(rel)
        if not isinstance(before_info, dict) or not isinstance(after_info, dict):
            raise CompatError("malformed server target snapshot")
        if before_info.get("sha256") != after_info.get("sha256"):
            changed_targets.append(rel)
    if not changed_targets:
        raise CompatError("server patch changed no target files")

    unpatch_stdout = _run_patch(server_root, kind="server", command="unpatch", log_dir=work_dir)
    if "Restored:" not in unpatch_stdout:
        raise CompatError("server unpatch output did not include restored summary")

    unpatched_status = _status_json(server_root, kind="server")
    _write_json(work_dir / "status_after_unpatch.json", unpatched_status)
    _assert_unpatched_status(unpatched_status)

    after_unpatch = _collect_snapshot(server_root, "server")
    _write_json(work_dir / "after_unpatch.json", after_unpatch)
    _assert_snapshots_restored(before, after_unpatch)

    return {
        "app_root": str(server_root),
        "patched_count": patched_count,
        "changed_targets": changed_targets,
    }


def _result_payload(
    *,
    target: str,
    version: str,
    commit: str,
    status: str,
    details: Dict[str, object],
) -> Dict[str, object]:
    return {
        "target": target,
        "results": {
            version: {
                "commit": commit,
                "status": status,
                "details": details,
            }
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=[
        "linux-server",
        "linux-gui",
        "macos-gui",
        "windows-gui",
    ])
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--download-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--artifacts-dir", default=None)
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve() if args.artifacts_dir else output_path.parent.resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    archive_name = Path(urlparse(args.download_url).path).name or "cursor-download.bin"
    archive_path = artifacts_dir / archive_name

    try:
        _download(args.download_url, archive_path)
        if args.target == "linux-server":
            details = _check_server(archive_path, artifacts_dir)
        else:
            details = _check_gui(args.target, archive_path, artifacts_dir)
        details["archive"] = str(archive_path)
        _write_json(
            output_path,
            _result_payload(
                target=args.target,
                version=args.version,
                commit=args.commit,
                status="pass",
                details=details,
            ),
        )
        return 0
    except Exception as exc:
        details = {
            "archive": str(archive_path),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        _write_json(
            output_path,
            _result_payload(
                target=args.target,
                version=args.version,
                commit=args.commit,
                status="fail",
                details=details,
            ),
        )
        print(traceback.format_exc(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
