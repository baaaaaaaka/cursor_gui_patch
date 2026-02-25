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
    download_and_install_release_bundle,
    fetch_latest_release,
    get_github_repo,
    get_install_bin_dir,
    get_install_root_dir,
    is_frozen_binary,
    is_version_newer,
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


def perform_update(
    *,
    asset_name: Optional[str] = None,
    timeout_s: float = 30.0,
    fetch: Optional[Fetch] = None,
) -> Tuple[bool, str]:
    """Download and install the latest release. Returns (ok, message)."""
    if not is_frozen_binary():
        return False, "not a frozen binary"

    repo = get_github_repo()
    try:
        kwargs = {"timeout_s": timeout_s}
        if fetch is not None:
            kwargs["fetch"] = fetch
        rel = fetch_latest_release(repo, **kwargs)

        if not (isinstance(asset_name, str) and asset_name.strip()):
            asset_name = select_release_asset_name()

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
