"""Real macOS integration test for privacy-denial flow (non-mock)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from cursor_gui_patch.cli import main
from cursor_gui_patch.discovery import CursorInstallation
from cursor_gui_patch.macos_privacy import is_certain_macos_privacy_denial
from cursor_gui_patch.patching import patch


pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def _require_real_env_root() -> Path:
    if os.environ.get("CGP_REAL_MACOS_PRIVACY_TEST") != "1":
        pytest.skip("real macOS privacy test disabled")
    raw = os.environ.get("CGP_REAL_MACOS_PRIVACY_TEST_ROOT", "").strip()
    if not raw:
        pytest.skip("CGP_REAL_MACOS_PRIVACY_TEST_ROOT is not set")
    root = Path(raw)
    if not root.is_dir():
        pytest.skip(f"test root does not exist: {root}")
    return root


def test_real_patch_reports_certain_privacy_denial():
    root = _require_real_env_root()
    inst = CursorInstallation(kind="gui", root=root, version_id="real-macos-privacy")
    report = patch(installations=[inst], force=True)
    assert report.ok is False
    assert any("backup failed:" in msg for _, msg in report.errors)
    assert any("operation not permitted" in msg.lower() for _, msg in report.errors)
    assert is_certain_macos_privacy_denial(report.errors) is True
    summary = report.summary()
    assert "macOS privacy diagnosis:" in summary
    assert "confidence: certain" in summary


def test_real_cli_prints_detailed_privacy_context(capsys):
    root = _require_real_env_root()
    with pytest.raises(SystemExit) as ex:
        main([
            "--server-dir", "/tmp/cgp-no-server-dir",
            "--gui-dir", str(root),
            "patch",
            "--force",
        ])
    assert ex.value.code == 1
    out = capsys.readouterr().out
    assert "backup failed:" in out
    assert "Operation not permitted" in out
    assert "macOS privacy diagnosis:" in out
    assert "What happened:" in out
    assert "Privacy action:" in out
