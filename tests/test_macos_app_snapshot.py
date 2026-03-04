"""Tests for macOS official app snapshot helpers."""

from __future__ import annotations

import json
import plistlib
import shutil
from pathlib import Path
from unittest import mock

from cursor_gui_patch.macos_app_snapshot import (
    SignatureInfo,
    restore_official_app_snapshot,
    update_official_app_snapshot,
)


def _make_app_bundle(tmp_path: Path) -> tuple[Path, Path]:
    app_bundle = tmp_path / "Cursor.app"
    app_root = app_bundle / "Contents" / "Resources" / "app"
    app_root.mkdir(parents=True)
    (app_bundle / "Contents").mkdir(parents=True, exist_ok=True)
    with (app_bundle / "Contents" / "Info.plist").open("wb") as f:
        plistlib.dump(
            {
                "CFBundleIdentifier": "com.cursor.test",
                "CFBundleShortVersionString": "1.2.3",
                "CFBundleVersion": "123",
            },
            f,
        )
    (app_root / "product.json").write_text(
        json.dumps({"applicationName": "cursor", "serverDataFolderName": ".cursor-server"}),
        encoding="utf-8",
    )
    return app_root, app_bundle


class TestUpdateOfficialAppSnapshot:
    def test_disabled_on_non_macos(self, tmp_path: Path):
        app_root, _ = _make_app_bundle(tmp_path)
        with mock.patch("cursor_gui_patch.macos_app_snapshot.sys.platform", "linux"):
            res = update_official_app_snapshot(app_root)
        assert res.enabled is False
        assert res.action == "skipped"

    def test_skips_when_signature_not_confident(self, tmp_path: Path, monkeypatch):
        app_root, _ = _make_app_bundle(tmp_path)
        monkeypatch.setenv("CGP_MACOS_APP_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
        with mock.patch("cursor_gui_patch.macos_app_snapshot.sys.platform", "darwin"), \
             mock.patch(
                 "cursor_gui_patch.macos_app_snapshot._inspect_signature",
                 return_value=SignatureInfo(is_adhoc=True),
             ):
            res = update_official_app_snapshot(app_root)
        assert res.enabled is True
        assert res.action == "skipped"
        assert "ad-hoc" in res.message

    def test_creates_snapshot_when_signature_confident(self, tmp_path: Path, monkeypatch):
        app_root, app_bundle = _make_app_bundle(tmp_path)
        snapshots_dir = tmp_path / "snapshots"
        monkeypatch.setenv("CGP_MACOS_APP_SNAPSHOT_DIR", str(snapshots_dir))

        def fake_copy(src: Path, dst: Path) -> None:
            shutil.copytree(src, dst, symlinks=True)

        with mock.patch("cursor_gui_patch.macos_app_snapshot.sys.platform", "darwin"), \
             mock.patch(
                 "cursor_gui_patch.macos_app_snapshot._inspect_signature",
                 return_value=SignatureInfo(
                     is_adhoc=False,
                     authorities=["Developer ID Application: Anysphere, Inc."],
                     team_identifier="TEAMID",
                     cdhash="abc123",
                 ),
             ), \
             mock.patch("cursor_gui_patch.macos_app_snapshot._copy_app_bundle", side_effect=fake_copy):
            res = update_official_app_snapshot(app_root)

        assert res.action == "created"
        assert res.snapshot_path is not None
        assert res.snapshot_path.is_dir()
        assert (res.snapshot_path / "Contents" / "Info.plist").is_file()
        assert app_bundle.is_dir()

    def test_keeps_existing_snapshot_when_fingerprint_matches(self, tmp_path: Path, monkeypatch):
        app_root, _ = _make_app_bundle(tmp_path)
        snapshots_dir = tmp_path / "snapshots"
        monkeypatch.setenv("CGP_MACOS_APP_SNAPSHOT_DIR", str(snapshots_dir))
        sig = SignatureInfo(
            is_adhoc=False,
            authorities=["Developer ID Application: Anysphere, Inc."],
            team_identifier="TEAMID",
            cdhash="abc123",
        )

        def fake_copy(src: Path, dst: Path) -> None:
            shutil.copytree(src, dst, symlinks=True)

        with mock.patch("cursor_gui_patch.macos_app_snapshot.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.macos_app_snapshot._inspect_signature", return_value=sig), \
             mock.patch("cursor_gui_patch.macos_app_snapshot._copy_app_bundle", side_effect=fake_copy):
            first = update_official_app_snapshot(app_root)
            second = update_official_app_snapshot(app_root)

        assert first.action == "created"
        assert second.action == "kept"


class TestRestoreOfficialAppSnapshot:
    def test_restore_skips_without_snapshot(self, tmp_path: Path, monkeypatch):
        app_root, _ = _make_app_bundle(tmp_path)
        monkeypatch.setenv("CGP_MACOS_APP_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
        with mock.patch("cursor_gui_patch.macos_app_snapshot.sys.platform", "darwin"):
            res = restore_official_app_snapshot(app_root)
        assert res.action == "skipped"
        assert "not found" in res.message

    def test_restore_replaces_current_app_bundle(self, tmp_path: Path, monkeypatch):
        app_root, app_bundle = _make_app_bundle(tmp_path)
        snapshots_dir = tmp_path / "snapshots"
        monkeypatch.setenv("CGP_MACOS_APP_SNAPSHOT_DIR", str(snapshots_dir))

        snapshot_source = tmp_path / "snapshot_source" / "Cursor.app"
        shutil.copytree(app_bundle, snapshot_source)
        (snapshot_source / "Contents" / "Resources" / "app" / "marker.txt").write_text(
            "official",
            encoding="utf-8",
        )

        # Corrupt current app to verify restore actually replaces it.
        shutil.rmtree(app_bundle)
        app_root.mkdir(parents=True, exist_ok=True)
        (app_root / "product.json").write_text(
            json.dumps({"applicationName": "cursor", "serverDataFolderName": ".cursor-server"}),
            encoding="utf-8",
        )

        with mock.patch("cursor_gui_patch.macos_app_snapshot.sys.platform", "darwin"), \
             mock.patch(
                 "cursor_gui_patch.macos_app_snapshot._find_app_bundle",
                 return_value=app_bundle,
             ), \
             mock.patch("cursor_gui_patch.macos_app_snapshot._copy_app_bundle", side_effect=shutil.copytree):
            # Seed snapshot structure expected by restore helper.
            slot_root = snapshots_dir / "Cursor.app-0f0f0f0f0f0f0f0f"
            with mock.patch(
                "cursor_gui_patch.macos_app_snapshot._slot_dir_for_app",
                return_value=slot_root,
            ):
                slot_root.mkdir(parents=True, exist_ok=True)
                shutil.copytree(snapshot_source, slot_root / "Cursor.app")
                (slot_root / "meta.json").write_text(
                    json.dumps({"app_path": str(app_bundle), "bundle_short_version": "1.2.3"}),
                    encoding="utf-8",
                )
                res = restore_official_app_snapshot(app_root)

        assert res.action == "restored"
        assert (app_bundle / "Contents" / "Resources" / "app" / "marker.txt").read_text(encoding="utf-8") == "official"
