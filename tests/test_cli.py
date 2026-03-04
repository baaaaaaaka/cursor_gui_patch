"""Tests for cursor_gui_patch.cli."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from cursor_gui_patch.cli import main
from cursor_gui_patch.report import FileStatus, PatchReport, StatusReport, UnpatchReport


class TestCli:
    def test_no_command_exits_with_help(self, capsys):
        with pytest.raises(SystemExit) as ex:
            main([])
        assert ex.value.code == 1
        out = capsys.readouterr().out
        assert "usage:" in out

    def test_patch_exits_nonzero_when_report_not_ok(self):
        report = PatchReport()
        report.errors.append((Path("/tmp/x.js"), "boom"))
        with mock.patch("cursor_gui_patch.cli.patch", return_value=report), \
             mock.patch("cursor_gui_patch.cli.open_privacy_settings_with_status", return_value="not_certain"):
            with pytest.raises(SystemExit) as ex:
                main(["patch"])
        assert ex.value.code == 1

    def test_patch_attempts_open_settings_on_error(self):
        report = PatchReport()
        report.errors.append((
            Path("/Applications/Cursor.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js"),
            "backup failed: [Errno 1] Operation not permitted",
        ))
        with mock.patch("cursor_gui_patch.cli.patch", return_value=report), \
             mock.patch("cursor_gui_patch.cli.open_privacy_settings_with_status", return_value="opened") as open_mock:
            with pytest.raises(SystemExit):
                main(["patch"])
        open_mock.assert_called_once_with(report.errors)

    def test_patch_prints_privacy_action_when_likely(self, capsys):
        report = PatchReport()
        report.errors.append((
            Path("/Applications/Cursor.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js"),
            "backup failed: [Errno 1] Operation not permitted",
        ))
        with mock.patch("cursor_gui_patch.cli.patch", return_value=report), \
             mock.patch("cursor_gui_patch.cli.open_privacy_settings_with_status", return_value="open_failed"), \
             mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"):
            with pytest.raises(SystemExit):
                main(["patch"])
        out = capsys.readouterr().out
        assert "Privacy action:" in out
        assert "Could not open settings automatically" in out

    def test_patch_does_not_print_privacy_action_on_non_macos(self, capsys):
        report = PatchReport()
        report.errors.append((
            Path("/Applications/Cursor.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js"),
            "backup failed: [Errno 1] Operation not permitted",
        ))
        with mock.patch("cursor_gui_patch.cli.patch", return_value=report), \
             mock.patch("cursor_gui_patch.cli.open_privacy_settings_with_status", return_value="not_certain"), \
             mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "linux"):
            with pytest.raises(SystemExit):
                main(["patch"])
        out = capsys.readouterr().out
        assert "Privacy action:" not in out

    def test_unpatch_dry_run_prints_marker(self, capsys):
        report = UnpatchReport()
        with mock.patch("cursor_gui_patch.cli.unpatch", return_value=report):
            main(["unpatch", "--dry-run"])
        out = capsys.readouterr().out
        assert "[DRY RUN]" in out

    def test_status_json_output(self, capsys):
        report = StatusReport(
            installations=[{"kind": "gui", "root": "/tmp/app", "version_id": "abc"}],
            files=[
                FileStatus(
                    path=Path("/tmp/app/extensions/cursor-agent-exec/dist/main.js"),
                    extension="cursor-agent-exec",
                    patch_names=["autorun"],
                    patched={"autorun": True},
                    has_backup=True,
                    error="",
                )
            ],
        )
        with mock.patch("cursor_gui_patch.cli.status", return_value=report):
            main(["status", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert data["installations"][0]["kind"] == "gui"
        assert data["files"][0]["patched"]["autorun"] is True
