from __future__ import annotations

from cursor_gui_patch.auto_extension import _generate_extension_js


def test_hot_patch_success_schedules_full_app_relaunch():
    js = _generate_extension_js()

    assert "scheduleCursorRelaunch(delayMs)" in js
    assert "workbench.action.quit" in js
    assert "refresh all windows" in js
    assert "tasklist /FI" in js
    assert "kill -0" in js

    relaunch_section = js[
        js.index("async function relaunchCursorApp"):
        js.index("async function fallbackReloadWindow")
    ]
    assert "canRelaunchCursorApp" in relaunch_section


def test_remote_hot_patch_uses_window_reload():
    js = _generate_extension_js()

    remote_section = js[
        js.index("async function handleRemoteRefreshAfterPatch"):
        js.index("async function relaunchCursorApp")
    ]
    assert "Reload Window" in remote_section
    assert "await fallbackReloadWindow()" in remote_section
    assert "Relaunch Cursor" not in remote_section
