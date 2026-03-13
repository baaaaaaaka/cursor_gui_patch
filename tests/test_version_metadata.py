"""Tests for package version metadata."""

from importlib.metadata import version

from cursor_gui_patch import __version__


def test_installed_metadata_matches_module_version():
    assert version("cursor-gui-patch") == __version__
