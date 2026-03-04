"""Real macOS integration test for official-app snapshot update/restore."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from cursor_gui_patch.macos_app_snapshot import (
    SignatureInfo,
    restore_official_app_snapshot,
    update_official_app_snapshot,
)


pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def _require_real_env_root() -> Path:
    if os.environ.get("CGP_REAL_MACOS_SNAPSHOT_TEST") != "1":
        pytest.skip("real macOS snapshot test disabled")
    raw = os.environ.get("CGP_REAL_MACOS_SNAPSHOT_TEST_ROOT", "").strip()
    if not raw:
        pytest.skip("CGP_REAL_MACOS_SNAPSHOT_TEST_ROOT is not set")
    root = Path(raw)
    if not root.is_dir():
        pytest.skip(f"test root does not exist: {root}")
    return root


def test_real_update_and_restore_snapshot_flow(monkeypatch, tmp_path: Path):
    root = _require_real_env_root()
    marker = root / "snapshot-marker.txt"
    if not marker.is_file():
        pytest.skip(f"missing marker file in fixture: {marker}")

    original = marker.read_text(encoding="utf-8")

    monkeypatch.setenv("CGP_MACOS_APP_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setattr(
        "cursor_gui_patch.macos_app_snapshot._inspect_signature",
        lambda _app: SignatureInfo(
            is_adhoc=False,
            authorities=["Developer ID Application: Anysphere, Inc."],
            team_identifier="TEAMID",
            cdhash="test-cdhash",
        ),
    )

    up = update_official_app_snapshot(root)
    assert up.action in {"created", "updated", "kept"}

    marker.write_text("mutated-by-test", encoding="utf-8")
    assert marker.read_text(encoding="utf-8") == "mutated-by-test"

    restored = restore_official_app_snapshot(root)
    assert restored.action == "restored"
    assert marker.read_text(encoding="utf-8") == original
