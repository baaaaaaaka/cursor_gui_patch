"""Sanity checks for the release workflow."""

from pathlib import Path


def test_release_workflow_validates_tag_version_before_publish():
    text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "validate-release-version:" in text
    assert 'TAG_VERSION="${GITHUB_REF_NAME#v}"' in text
    assert "from cursor_gui_patch import __version__" in text
    assert 'needs.validate-release-version.result == \'success\'' in text
