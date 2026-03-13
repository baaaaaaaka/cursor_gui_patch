from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import cursor_gui_patch.discovery as discovery


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only integration tests")


def _make_gui_install(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "product.json").write_text(
        json.dumps({"applicationName": "cursor"}),
        encoding="utf-8",
    )


def test_windows_ci_discovers_standard_bin_cursor_cmd_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_appdata = tmp_path / "LocalAppData"
    install_root = local_appdata / "Programs" / "Cursor"
    gui_root = install_root / "resources" / "app"
    _make_gui_install(gui_root)

    bin_dir = install_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "cursor.cmd").write_text("@echo off\r\n", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(discovery, "_native_windows_registry_cursor_exes", lambda: [])

    installations = discovery.discover_gui_installations()

    assert [inst.root for inst in installations] == [gui_root]


def test_windows_ci_dedupes_registry_and_fallback_candidates_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_appdata = tmp_path / "LocalAppData"
    install_root = local_appdata / "Programs" / "Cursor"
    gui_root = install_root / "resources" / "app"
    _make_gui_install(gui_root)

    registry_cursor = install_root / "Cursor.exe"

    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(discovery, "_native_windows_registry_cursor_exes", lambda: [registry_cursor])

    installations = discovery.discover_gui_installations()

    assert [inst.root for inst in installations] == [gui_root]
