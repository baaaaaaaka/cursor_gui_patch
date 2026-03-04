"""Tests for cursor_gui_patch.report."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from unittest import mock

from cursor_gui_patch.macos_privacy import ProcessContext
from cursor_gui_patch.report import CodesignInfo, PatchReport, StatusReport, UnpatchReport


def _app_js() -> PurePosixPath:
    return PurePosixPath(
        "/Applications/Cursor.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js"
    )


def _app_ext_js() -> PurePosixPath:
    return PurePosixPath(
        "/Applications/Cursor.app/Contents/Resources/app/extensions/cursor-agent-exec/dist/main.js"
    )


class TestPatchReportSummary:
    def test_includes_notes_block(self):
        report = PatchReport(notes=["macOS official app snapshot updated."])
        s = report.summary()
        assert "Notes:" in s
        assert "snapshot updated" in s

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

    def test_includes_codesign_identity_and_warning(self):
        report = PatchReport(
            codesign=[CodesignInfo(
                app_path="/Applications/Cursor.app",
                success=True,
                identity="-",
                warning="preferred identity failed; fell back to ad-hoc signature",
            )]
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "darwin"):
            s = report.summary()
        assert "identity: -" in s
        assert "Codesign TIP: set CGP_CODESIGN_IDENTITY" in s
        assert "Codesign NOTE:" in s

    def test_includes_macos_keychain_popup_note_after_codesign_success(self):
        report = PatchReport(
            codesign=[CodesignInfo(
                app_path="/Applications/Cursor.app",
                success=True,
                identity="CGP Cursor Patch",
            )]
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "darwin"):
            s = report.summary()
        assert "macOS Keychain / Signature" in s
        assert "Best practice:" in s
        assert "CGP_CODESIGN_IDENTITY" in s
        assert "Usually 0-2 prompts around update/patch cycles." in s
        assert "TLDR >>>" in s
        assert "click Always Allow (or equivalent)" in s

    def test_no_macos_keychain_popup_note_on_non_macos(self):
        report = PatchReport(
            codesign=[CodesignInfo(
                app_path="/Applications/Cursor.app",
                success=True,
                identity="CGP Cursor Patch",
            )]
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "linux"):
            s = report.summary()
        assert "macOS Keychain / Signature" not in s

    def test_includes_brief_macos_keychain_note_when_already_patched(self):
        report = PatchReport(
            patched=[],
            already_patched=5,
            errors=[],
            codesign=[],
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "darwin"):
            s = report.summary()
        assert "macOS Keychain note:" in s
        assert "not re-signed" in s

    def test_unpatch_includes_official_signature_restore_note(self):
        report = UnpatchReport(
            restored=[Path("/Applications/Cursor.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js")],
            codesign=[CodesignInfo(
                app_path="/Applications/Cursor.app",
                success=True,
                identity="-",
            )],
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "darwin"):
            s = report.summary()
        assert "Official signature restore:" in s
        assert "file-level restore + re-sign" in s
        assert "snapshot or reinstall/update Cursor" in s
        assert "TLDR >>> fallback unpatch does not restore vendor signature" in s
        assert "click Always Allow (or equivalent)" in s

    def test_includes_macos_privacy_hint_for_backup_failures(self):
        report = PatchReport(
            errors=[(
                _app_js(),
                "backup failed: [Errno 1] Operation not permitted",
            )]
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"), \
             mock.patch(
                 "cursor_gui_patch.report.detect_current_process_context",
                 return_value=ProcessContext(
                     current_process="python3",
                     terminal_process="iTerm",
                     terminal_source="TERM_PROGRAM",
                 ),
             ):
            s = report.summary()
        assert "macOS privacy diagnosis:" in s
        assert "confidence: certain" in s
        assert "current process: python3" in s
        assert "detected terminal app: iTerm (source: TERM_PROGRAM)" in s
        assert "detection may be inaccurate" in s
        assert "macOS privacy protections likely blocked writes" in s
        assert "App Management" in s
        assert "sudo cgp patch" in s

    def test_does_not_treat_operation_not_permitted_as_generic_permission_on_linux(self):
        report = PatchReport(errors=[(Path("/tmp/main.js"), "operation not permitted")])
        with mock.patch("cursor_gui_patch.report.sys.platform", "linux"):
            s = report.summary()
        assert "Fix: Run with elevated permissions" not in s


class TestUnpatchReportSummary:
    def test_includes_notes_block(self):
        report = UnpatchReport(notes=["macOS official app snapshot restored (version: 1.2.3)."])
        s = report.summary()
        assert "Notes:" in s
        assert "snapshot restored" in s

    def test_includes_macos_no_snapshot_no_backup_hint(self):
        report = UnpatchReport(
            restored=[],
            no_backup=[_app_ext_js()],
            errors=[],
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "darwin"):
            s = report.summary()
        assert "macOS restore hint:" in s
        assert "older cgp versions" in s
        assert "official installer" in s

    def test_macos_restore_hint_not_shown_for_non_app_paths(self):
        report = UnpatchReport(
            restored=[],
            no_backup=[Path("/tmp/not-cursor/main.js")],
            errors=[],
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "darwin"):
            s = report.summary()
        assert "macOS restore hint:" not in s

    def test_macos_restore_hint_not_shown_on_windows(self):
        report = UnpatchReport(
            restored=[],
            no_backup=[_app_ext_js()],
            errors=[],
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "win32"):
            s = report.summary()
        assert "macOS restore hint:" not in s

    def test_includes_permission_hint_on_linux(self):
        report = UnpatchReport(errors=[(Path("/tmp/main.js"), "errno 13")])
        with mock.patch("cursor_gui_patch.report.sys.platform", "linux"):
            s = report.summary()
        assert "sudo cgp unpatch" in s

    def test_includes_macos_privacy_hint_for_operation_not_permitted(self):
        report = UnpatchReport(
            errors=[(
                _app_js(),
                "operation not permitted: [Errno 1] Operation not permitted",
            )]
        )
        with mock.patch("cursor_gui_patch.report.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"), \
             mock.patch(
                 "cursor_gui_patch.report.detect_current_process_context",
                 return_value=ProcessContext(
                     current_process="python3",
                     terminal_process="Terminal",
                     terminal_source="parent process chain",
                 ),
             ):
            s = report.summary()
        assert "macOS privacy diagnosis:" in s
        assert "current process: python3" in s
        assert "macOS privacy protections likely blocked writes" in s
        assert "Full Disk Access" in s
        assert "sudo cgp unpatch" in s


class TestStatusReportSummary:
    def test_no_installations_message(self):
        report = StatusReport()
        assert report.summary() == "No Cursor installations found."
