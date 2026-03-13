"""Tests for cursor_gui_patch.report."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from cursor_gui_patch.report import CodesignInfo, PatchReport, StatusReport, UnpatchReport


class TestPatchReportSummary:
    def test_includes_permission_hint_on_linux(self):
        report = PatchReport(errors=[(Path("/tmp/main.js"), "Permission denied")])
        with mock.patch("cursor_gui_patch.report.sys.platform", "linux"):
            s = report.summary()
        assert "sudo cgp patch" in s

    def test_includes_permission_hint_on_windows(self):
        report = PatchReport(errors=[(Path("C:/x.js"), "Access is denied")])
        with mock.patch("cursor_gui_patch.report.sys.platform", "win32"):
            s = report.summary()
        assert "Run as Administrator" in s

    def test_includes_codesign_failure_fix(self):
        report = PatchReport(
            codesign=[CodesignInfo(app_path="/Applications/Cursor.app", success=False, error="codesign failed")]
        )
        s = report.summary()
        assert "Codesign FAILED" in s
        assert "sudo codesign --force --deep --sign -" in s

    def test_includes_relaunch_hint_when_successful(self):
        report = PatchReport(patched=[Path("/tmp/main.js")])
        s = report.summary()
        assert "fully relaunch Cursor now" in s
        assert "cgp unpatch" in s

    def test_omits_relaunch_hint_when_nothing_was_written(self):
        report = PatchReport()
        s = report.summary()
        assert "fully relaunch Cursor now" not in s
        assert "cgp unpatch" not in s

    def test_omits_relaunch_hint_for_dry_run(self):
        report = PatchReport(patched=[Path("/tmp/main.js")], dry_run=True)
        s = report.summary()
        assert "fully relaunch Cursor now" not in s


class TestUnpatchReportSummary:
    def test_includes_permission_hint_on_linux(self):
        report = UnpatchReport(errors=[(Path("/tmp/main.js"), "errno 13")])
        with mock.patch("cursor_gui_patch.report.sys.platform", "linux"):
            s = report.summary()
        assert "sudo cgp unpatch" in s


class TestStatusReportSummary:
    def test_no_installations_message(self):
        report = StatusReport()
        assert report.summary() == "No Cursor installations found."
