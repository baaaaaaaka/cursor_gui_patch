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
        with mock.patch("cursor_gui_patch.cli.patch", return_value=report):
            with pytest.raises(SystemExit) as ex:
                main(["patch"])
        assert ex.value.code == 1

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
