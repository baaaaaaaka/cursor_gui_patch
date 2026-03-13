from __future__ import annotations

import hashlib
import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest


def _write_fake_release_bundle(bundle_path: Path) -> None:
    payload = b"#!/bin/sh\nprintf 'fake-cgp 0.0.0\\n'\n"

    with tarfile.open(bundle_path, "w:gz") as tf:
        info = tarfile.TarInfo("cgp/cgp")
        info.mode = 0o755
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))


@pytest.mark.skipif(os.name == "nt", reason="install_cgp.sh is a Unix shell script")
def test_install_cgp_sh_installs_offline_bundle(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    bundle_path = dist_dir / "cgp-linux-x86_64.tar.gz"
    _write_fake_release_bundle(bundle_path)

    checksum = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    (dist_dir / "checksums.txt").write_text(
        f"{checksum}  {bundle_path.name}\n",
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    root_dir = tmp_path / "root"
    env = os.environ.copy()
    env.update(
        {
            "CGP_INSTALL_FROM_DIR": str(dist_dir),
            "CGP_INSTALL_DEST": str(bin_dir),
            "CGP_INSTALL_ROOT": str(root_dir),
            "CGP_INSTALL_OS": "Linux",
            "CGP_INSTALL_ARCH": "x86_64",
        }
    )

    result = subprocess.run(
        ["sh", "scripts/install_cgp.sh"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    installed = bin_dir / "cgp"
    assert installed.is_symlink()
    assert os.stat(installed).st_mode & stat.S_IXUSR
    assert "Installed cgp-linux-x86_64.tar.gz" in result.stdout

    version = subprocess.run(
        [str(installed)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert version.stdout.strip() == "fake-cgp 0.0.0"
