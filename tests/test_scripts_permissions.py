"""Checks for executable permissions on repository shell scripts."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_all_tracked_shell_scripts_are_executable_in_worktree():
    if sys.platform == "win32":
        pytest.skip("POSIX executable bit check is not meaningful on Windows")

    if not shutil.which("git"):
        pytest.skip("git not available")

    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["git", "-c", "safe.directory=*", "ls-files", "*.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "No tracked .sh files found."

    bad = []
    for rel in lines:
        p = repo / rel
        if not p.is_file():
            bad.append(f"{rel} (missing)")
            continue
        mode = p.stat().st_mode
        if (mode & 0o111) == 0:
            bad.append(rel)

    assert not bad, "Non-executable shell scripts in worktree: " + ", ".join(bad)
