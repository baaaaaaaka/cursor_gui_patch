"""Real macOS integration tests for codesign identity behavior."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from cursor_gui_patch.codesign import codesign_app


pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def _make_minimal_app(tmp_path: Path) -> tuple[Path, Path]:
    app_bundle = tmp_path / "CGPCodeSignTest.app"
    app_root = app_bundle / "Contents" / "Resources" / "app"
    macos_dir = app_bundle / "Contents" / "MacOS"
    app_root.mkdir(parents=True)
    macos_dir.mkdir(parents=True)
    (app_bundle / "Contents" / "Info.plist").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleIdentifier</key><string>dev.cgp.test</string></dict></plist>
""",
        encoding="utf-8",
    )
    # A tiny binary/script payload is enough for signing test.
    payload = macos_dir / "CGPCodeSignTest"
    payload.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    payload.chmod(0o755)
    return app_root, app_bundle


def _codesign_verify(app_bundle: Path) -> bool:
    proc = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app_bundle)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.returncode == 0


def test_real_codesign_with_explicit_adhoc_identity(monkeypatch, tmp_path: Path):
    app_root, app_bundle = _make_minimal_app(tmp_path)
    monkeypatch.setenv("CGP_CODESIGN_IDENTITY", "-")
    res = codesign_app(app_root)
    assert res.success is True
    assert res.identity_used == "-"
    assert _codesign_verify(app_bundle) is True


def test_real_codesign_falls_back_to_adhoc_when_identity_invalid(monkeypatch, tmp_path: Path):
    app_root, app_bundle = _make_minimal_app(tmp_path)
    monkeypatch.setenv("CGP_CODESIGN_IDENTITY", "__CGP_INVALID_IDENTITY__")
    res = codesign_app(app_root)
    assert res.success is True
    assert res.identity_requested == "__CGP_INVALID_IDENTITY__"
    assert res.identity_used == "-"
    assert "fell back to ad-hoc" in res.warning
    assert _codesign_verify(app_bundle) is True

