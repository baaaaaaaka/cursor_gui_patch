"""Runtime smoke tests for scripts/unpatch.sh behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_unpatch_script_with_fake_cgp(tmp_path: Path, *, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    repo = Path(__file__).resolve().parents[1]
    script = repo / "scripts" / "unpatch.sh"

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    fake_cgp = fake_bin / "cgp"
    fake_cgp.write_text(
        "#!/usr/bin/env sh\n"
        "set -eu\n"
        "if [ \"${1:-}\" = \"unpatch\" ]; then\n"
        "  printf '%s\\n' 'Restored: 0'\n"
        "  printf '%s\\n' 'No backup: 5'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = \"auto\" ] && [ \"${2:-}\" = \"uninstall\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_cgp.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    if env_extra:
        env.update(env_extra)

    return subprocess.run(
        ["sh", str(script)],
        cwd=repo,
        env=env,
        input="\n",
        text=True,
        capture_output=True,
        timeout=30,
    )


@pytest.mark.skipif(sys.platform in ("darwin", "win32"), reason="non-macOS POSIX shell test")
def test_unpatch_script_non_macos_does_not_trigger_official_reinstall(tmp_path: Path):
    proc = _run_unpatch_script_with_fake_cgp(tmp_path)

    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "Running: cgp unpatch (from PATH)" in out
    assert "Auto reinstall mode enabled." not in out


@pytest.mark.skipif(sys.platform in ("darwin", "win32"), reason="non-macOS POSIX shell test")
def test_unpatch_script_non_macos_ignores_always_mode(tmp_path: Path):
    proc = _run_unpatch_script_with_fake_cgp(
        tmp_path,
        env_extra={"CGP_UNPATCH_INSTALL_OFFICIAL_APP": "always"},
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "Auto reinstall mode enabled." not in out
