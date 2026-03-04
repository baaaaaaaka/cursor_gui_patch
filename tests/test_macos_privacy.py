"""Tests for cursor_gui_patch.macos_privacy."""

from __future__ import annotations

from pathlib import PurePosixPath
from unittest import mock

from cursor_gui_patch.macos_privacy import (
    ProcessContext,
    detect_current_process_context,
    diagnose_macos_privacy_denial,
    is_certain_macos_privacy_denial,
    maybe_open_privacy_settings,
    open_privacy_settings_with_status,
)


def _errors(msg: str):
    return [(
        PurePosixPath("/Applications/Cursor.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js"),
        msg,
    )]


class TestMacOSPrivacyDetection:
    def test_diagnosis_counts_and_likely(self):
        errors = _errors("backup failed: [Errno 1] Operation not permitted")
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"):
            diag = diagnose_macos_privacy_denial(errors)
        assert diag.total_errors == 1
        assert diag.app_bundle_errors == 1
        assert diag.backup_failed_errors == 1
        assert diag.operation_not_permitted_errors == 1
        assert diag.errno1_errors == 1
        assert diag.likely is True
        assert diag.certain is True

    def test_certain_denial_requires_darwin(self):
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "linux"):
            assert is_certain_macos_privacy_denial(_errors("[Errno 1] Operation not permitted")) is False

    def test_certain_denial_requires_errno_1_and_op_not_permitted(self):
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"):
            assert is_certain_macos_privacy_denial(_errors("[Errno 1] Operation not permitted")) is True
            assert is_certain_macos_privacy_denial(_errors("operation not permitted")) is False
            assert is_certain_macos_privacy_denial(_errors("[Errno 13] Permission denied")) is False

    def test_certain_denial_requires_app_bundle_path(self):
        errors = [(PurePosixPath("/tmp/x.js"), "[Errno 1] Operation not permitted")]
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"):
            assert is_certain_macos_privacy_denial(errors) is False


class TestProcessContextDetection:
    def test_prefers_term_program_when_present(self):
        with mock.patch.dict(
            "cursor_gui_patch.macos_privacy.os.environ",
            {"TERM_PROGRAM": "iTerm.app"},
            clear=False,
        ), \
             mock.patch("cursor_gui_patch.macos_privacy.os.getpid", return_value=100), \
             mock.patch("cursor_gui_patch.macos_privacy._ps_value", return_value="/usr/bin/python3"):
            ctx = detect_current_process_context()
        assert isinstance(ctx, ProcessContext)
        assert ctx.current_process == "python3"
        assert ctx.terminal_process == "iTerm"
        assert ctx.terminal_source == "TERM_PROGRAM"

    def test_uses_parent_chain_when_term_program_missing(self):
        def fake_ps_value(pid: int, field: str) -> str:
            table = {
                (100, "comm"): "/usr/bin/python3",
                (100, "ppid"): "90",
                (90, "comm"): "/bin/zsh",
                (90, "ppid"): "80",
                (80, "comm"): "/Applications/iTerm.app/Contents/MacOS/iTerm2",
                (80, "ppid"): "1",
            }
            return table.get((pid, field), "")

        with mock.patch.dict(
            "cursor_gui_patch.macos_privacy.os.environ",
            {},
            clear=True,
        ), \
             mock.patch("cursor_gui_patch.macos_privacy.os.getpid", return_value=100), \
             mock.patch("cursor_gui_patch.macos_privacy.os.getppid", return_value=90), \
             mock.patch("cursor_gui_patch.macos_privacy._ps_value", side_effect=fake_ps_value):
            ctx = detect_current_process_context()
        assert ctx.current_process == "python3"
        assert ctx.terminal_process == "iTerm2"
        assert ctx.terminal_source == "parent process chain"

    def test_returns_safe_unknown_on_unexpected_exception(self):
        with mock.patch(
            "cursor_gui_patch.macos_privacy.os.getpid",
            side_effect=RuntimeError("boom"),
        ):
            ctx = detect_current_process_context()
        assert ctx.current_process == "unknown"
        assert ctx.terminal_process == "unknown"


class TestMacOSPrivacyOpen:
    def test_no_open_when_not_certain(self):
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.macos_privacy.shutil.which", return_value="/usr/bin/open"), \
             mock.patch("cursor_gui_patch.macos_privacy.subprocess.run") as run_mock:
            opened = maybe_open_privacy_settings(_errors("backup failed"))
        assert opened is False
        run_mock.assert_not_called()
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"):
            assert open_privacy_settings_with_status(_errors("backup failed")) == "not_certain"

    def test_open_when_certain(self):
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.macos_privacy.shutil.which", return_value="/usr/bin/open"), \
             mock.patch("cursor_gui_patch.macos_privacy.subprocess.run", return_value=None) as run_mock:
            opened = maybe_open_privacy_settings(_errors("backup failed: [Errno 1] Operation not permitted"))
        assert opened is True
        run_mock.assert_called()

    def test_tries_detected_app_management_key_first(self):
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.macos_privacy._detected_app_management_privacy_key", return_value="Privacy_AppBundles"), \
             mock.patch("cursor_gui_patch.macos_privacy._run_open", side_effect=[True]) as open_mock:
            status = open_privacy_settings_with_status(
                _errors("backup failed: [Errno 1] Operation not permitted")
            )
        assert status == "opened"
        first_arg = open_mock.call_args_list[0].args[0][0]
        assert "Privacy_AppBundles" in first_arg

    def test_status_open_failed_when_open_command_fails(self):
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"), \
             mock.patch("cursor_gui_patch.macos_privacy.shutil.which", return_value="/usr/bin/open"), \
             mock.patch("cursor_gui_patch.macos_privacy.subprocess.run", side_effect=RuntimeError("open failed")):
            status = open_privacy_settings_with_status(
                _errors("backup failed: [Errno 1] Operation not permitted")
            )
        assert status == "open_failed"

    def test_respects_disable_env(self):
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"), \
             mock.patch.dict("cursor_gui_patch.macos_privacy.os.environ", {"CGP_NO_OPEN_SETTINGS": "1"}, clear=False), \
             mock.patch("cursor_gui_patch.macos_privacy.subprocess.run") as run_mock:
            opened = maybe_open_privacy_settings(_errors("backup failed: [Errno 1] Operation not permitted"))
        assert opened is False
        run_mock.assert_not_called()
        with mock.patch("cursor_gui_patch.macos_privacy.sys.platform", "darwin"), \
             mock.patch.dict("cursor_gui_patch.macos_privacy.os.environ", {"CGP_NO_OPEN_SETTINGS": "1"}, clear=False):
            assert open_privacy_settings_with_status(
                _errors("backup failed: [Errno 1] Operation not permitted")
            ) == "disabled"
