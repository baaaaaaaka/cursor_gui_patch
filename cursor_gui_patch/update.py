"""Auto-update module for cgp frozen binaries."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__
from .github_release import (
    ENV_CGP_INSTALL_DEST,
    ENV_CGP_INSTALL_ROOT,
    Fetch,
    download_and_install_app_only,
    download_and_install_release_bundle,
    fetch_latest_release,
    fetch_remote_runtime_version,
    get_github_repo,
    get_install_bin_dir,
    get_install_root_dir,
    is_frozen_binary,
    is_version_newer,
    read_local_runtime_version,
    select_app_asset_name,
    select_release_asset_name,
)

UPDATE_CHECK_INTERVAL_S = 300  # 5 minutes


@dataclass(frozen=True)
class UpdateStatus:
    supported: bool
    method: Optional[str] = None
    installed_version: Optional[str] = None
    remote_version: Optional[str] = None
    repo: Optional[str] = None
    asset_name: Optional[str] = None
    update_available: bool = False
    error: Optional[str] = None


def _last_check_path() -> Path:
    root = get_install_root_dir()
    return root / ".last-update-check"


def _should_check_update() -> bool:
    """Return True if enough time has passed since the last update check."""
    p = _last_check_path()
    try:
        if p.exists():
            ts = float(p.read_text(encoding="utf-8").strip())
            if (time.time() - ts) < UPDATE_CHECK_INTERVAL_S:
                return False
    except Exception:
        pass
    return True


def _record_check_time() -> None:
    p = _last_check_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


def check_for_update(
    *,
    timeout_s: float = 3.0,
    fetch: Optional[Fetch] = None,
) -> Optional[UpdateStatus]:
    """Check GitHub for a newer release. Returns None on network failure."""
    if not is_frozen_binary():
        return UpdateStatus(supported=False, error="not a frozen binary")

    repo = get_github_repo()
    try:
        kwargs = {"timeout_s": timeout_s}
        if fetch is not None:
            kwargs["fetch"] = fetch
        rel = fetch_latest_release(repo, **kwargs)
    except Exception as e:
        _record_check_time()
        return UpdateStatus(
            supported=False,
            method="github_release",
            repo=repo,
            installed_version=__version__,
            error=str(e),
        )

    try:
        asset_name = select_release_asset_name()
    except Exception as e:
        _record_check_time()
        return UpdateStatus(
            supported=False,
            method="github_release",
            repo=repo,
            installed_version=__version__,
            remote_version=rel.version,
            error=str(e),
        )

    _record_check_time()

    newer = is_version_newer(rel.version, __version__)
    return UpdateStatus(
        supported=newer is not None,
        method="github_release",
        repo=repo,
        installed_version=__version__,
        remote_version=rel.version,
        asset_name=asset_name,
        update_available=bool(newer),
        error=None if newer is not None else "failed to parse version",
    )


def _resolve_install_dirs(
    fetch_fn: Optional[Fetch],
) -> Tuple[Path, Path]:
    """Resolve bin_dir and root_dir for the current installation."""
    bin_dir = get_install_bin_dir()
    root_dir = get_install_root_dir()

    env_dest = os.environ.get(ENV_CGP_INSTALL_DEST)
    env_root = os.environ.get(ENV_CGP_INSTALL_ROOT)

    if not (isinstance(env_dest, str) and env_dest.strip()):
        try:
            which = shutil.which("cgp")
            if which:
                bin_dir = Path(which).expanduser().parent
        except Exception:
            pass

    if not (isinstance(env_root, str) and env_root.strip()):
        try:
            exe = Path(sys.executable).resolve()
            exe_name = "cgp.exe" if sys.platform == "win32" else "cgp"
            if exe.name == exe_name and exe.parent.name == "cgp":
                if exe.parent.parent.name == "current":
                    root_dir = exe.parent.parent.parent
                elif exe.parent.parent.parent.name == "versions":
                    root_dir = exe.parent.parent.parent.parent
        except Exception:
            pass

    return bin_dir, root_dir


def _try_app_only_update(
    *,
    repo: str,
    tag: str,
    bin_dir: Path,
    root_dir: Path,
    timeout_s: float,
    fetch_fn: Optional[Fetch],
) -> Optional[str]:
    """Try an app-only update. Returns version string on success, None if not possible."""
    # Check if we have a local runtime with RUNTIME_VERSION
    local_rv = read_local_runtime_version()
    if not local_rv:
        return None

    # Fetch the remote runtime version
    fetch_kwargs = {"timeout_s": min(timeout_s, 5.0)}
    if fetch_fn is not None:
        fetch_kwargs["fetch"] = fetch_fn
    remote_rv = fetch_remote_runtime_version(repo, tag=tag, **fetch_kwargs)
    if not remote_rv:
        # Remote doesn't have runtime_version.txt — fall back to full update
        return None

    if local_rv != remote_rv:
        # Runtime changed — need full update
        return None

    # Runtime matches! Do app-only update.
    try:
        app_asset = select_app_asset_name()
    except Exception:
        return None

    # Find the existing _internal/ directory
    try:
        exe = Path(sys.executable).resolve()
        existing_internal = exe.parent / "_internal"
        if not existing_internal.is_dir():
            return None
    except Exception:
        return None

    dl_kwargs = {
        "repo": repo,
        "tag": tag,
        "app_asset_name": app_asset,
        "existing_internal": existing_internal,
        "install_root": root_dir,
        "bin_dir": bin_dir,
        "timeout_s": timeout_s,
        "verify_checksums": True,
    }
    if fetch_fn is not None:
        dl_kwargs["fetch"] = fetch_fn

    download_and_install_app_only(**dl_kwargs)
    return "app-only"


def perform_update(
    *,
    asset_name: Optional[str] = None,
    timeout_s: float = 30.0,
    fetch: Optional[Fetch] = None,
) -> Tuple[bool, str]:
    """Download and install the latest release. Returns (ok, message).

    Prefers app-only update (~1MB) when the local runtime matches the remote.
    Falls back to full update (~4MB) otherwise.
    """
    if not is_frozen_binary():
        return False, "not a frozen binary"

    repo = get_github_repo()
    try:
        kwargs = {"timeout_s": timeout_s}
        if fetch is not None:
            kwargs["fetch"] = fetch
        rel = fetch_latest_release(repo, **kwargs)

        bin_dir, root_dir = _resolve_install_dirs(fetch)

        # Try app-only update first (fast path)
        try:
            mode = _try_app_only_update(
                repo=repo,
                tag=rel.tag,
                bin_dir=bin_dir,
                root_dir=root_dir,
                timeout_s=timeout_s,
                fetch_fn=fetch,
            )
            if mode:
                return True, f"updated to {rel.version} ({mode})"
        except Exception:
            pass  # Fall through to full update

        # Full update (slow path)
        if not (isinstance(asset_name, str) and asset_name.strip()):
            asset_name = select_release_asset_name()

        dl_kwargs = {
            "repo": repo,
            "tag": rel.tag,
            "asset_name": asset_name,
            "install_root": root_dir,
            "bin_dir": bin_dir,
            "timeout_s": timeout_s,
            "verify_checksums": True,
        }
        if fetch is not None:
            dl_kwargs["fetch"] = fetch

        download_and_install_release_bundle(**dl_kwargs)
        return True, f"updated to {rel.version}"
    except Exception as e:
        return False, str(e)


def auto_update_if_needed(argv: List[str]) -> None:
    """Call at CLI entry point. Auto-updates and re-execs if a new version is available."""
    if not is_frozen_binary():
        return
    if os.environ.get("CGP_NO_AUTO_UPDATE"):
        return
    if os.environ.get("_CGP_UPDATED"):
        return
    if not _should_check_update():
        return

    status = check_for_update(timeout_s=3.0)
    if not status or not status.update_available:
        return

    print(
        f"Updating cgp {__version__} \u2192 {status.remote_version}...",
        file=sys.stderr,
    )
    ok, msg = perform_update(asset_name=status.asset_name)
    if not ok:
        print(f"Update failed: {msg}", file=sys.stderr)
        return

    os.environ["_CGP_UPDATED"] = "1"
    if sys.platform == "win32":
        r = subprocess.call([sys.executable] + argv[1:])
        sys.exit(r)
    else:
        os.execvp(sys.executable, [sys.executable] + argv[1:])
