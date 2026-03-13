"""Sanity checks for the release workflow."""

from pathlib import Path


def test_release_workflow_validates_tag_version_before_publish():
    text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "validate-release-version:" in text
    assert 'TAG_VERSION="${GITHUB_REF_NAME#v}"' in text
    assert "from cursor_gui_patch import __version__" in text
    assert '"$PKG_VERSION"-rc*' in text
    assert 'needs.validate-release-version.result == \'success\'' in text
    assert "prerelease: ${{ contains(github.ref_name, '-rc') }}" in text


def test_release_workflow_smoke_installs_linux_bundle_on_old_distros():
    text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "smoke-install:" in text
    assert 'ubuntu:20.04' in text
    assert 'ubuntu:22.04' in text
    assert 'rockylinux:8' in text
    assert 'if ! command -v tar >/dev/null 2>&1 || ! command -v sha256sum >/dev/null 2>&1; then' in text


def test_linux_release_builder_pins_manylinux_baseline():
    text = Path("scripts/build_linux_binary_docker.sh").read_text(encoding="utf-8")

    assert 'IMAGE="rockylinux:8"' in text
    assert 'PYBIN="python3.9"' in text
    assert 'dnf install -y -q python39 python39-devel python39-pip binutils tar gzip' in text
