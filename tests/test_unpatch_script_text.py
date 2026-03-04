"""Regression checks for scripts/unpatch.sh user-facing reinstall flow."""

from __future__ import annotations

from pathlib import Path


def test_unpatch_script_includes_optional_official_reinstall_mode():
    script = Path(__file__).resolve().parents[1] / "scripts" / "unpatch.sh"
    text = script.read_text(encoding="utf-8")
    assert "CGP_UNPATCH_INSTALL_OFFICIAL_APP" in text
    assert "mode=\"auto\"" in text
    assert "0|false|no|off|disabled" in text
    assert "Auto reinstall mode enabled. Attempting official Cursor install..." in text
    assert "Operation failed without elevated privileges; retrying with sudo..." in text
    assert "https://www.cursor.com/api/download?platform=" in text
    assert "-mountpoint" in text
    assert "Official Cursor installed at ${TARGET}" in text
