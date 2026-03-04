"""Regression checks for scripts/patch.sh user-facing messaging."""

from __future__ import annotations

from pathlib import Path


def test_patch_script_includes_macos_keychain_note():
    script = Path(__file__).resolve().parents[1] / "scripts" / "patch.sh"
    text = script.read_text(encoding="utf-8")
    assert "macOS Keychain / Signature" in text
    assert "Best practice:" in text
    assert "CGP_CODESIGN_IDENTITY" in text
    assert "Usually 0-2 prompts around update/patch cycles." in text
    assert "TLDR >>> prompts after update+patch are expected;" in text
    assert "click Always Allow (or equivalent)" in text
