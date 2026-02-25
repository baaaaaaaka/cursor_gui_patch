"""Tests for cursor_gui_patch.github_release."""

from __future__ import annotations

import json
import os
import tarfile
import io
import zipfile
from pathlib import Path
from typing import Dict
from unittest import mock

import pytest

from cursor_gui_patch.github_release import (
    ReleaseInfo,
    _normalize_arch,
    _parse_version_tuple,
    build_checksums_download_url,
    build_release_download_url,
    download_and_install_release_bundle,
    fetch_latest_release,
    is_frozen_binary,
    is_version_newer,
    parse_checksums_txt,
    select_release_asset_name,
    split_repo,
)


class TestSplitRepo:
    def test_valid(self):
        assert split_repo("owner/name") == ("owner", "name")

    def test_whitespace(self):
        assert split_repo("  owner / name  ") == ("owner", "name")

    def test_invalid_no_slash(self):
        with pytest.raises(ValueError, match="Invalid"):
            split_repo("no-slash")

    def test_invalid_empty(self):
        with pytest.raises(ValueError, match="Invalid"):
            split_repo("")

    def test_invalid_missing_name(self):
        with pytest.raises(ValueError, match="Invalid"):
            split_repo("owner/")


class TestParseVersion:
    def test_simple(self):
        assert _parse_version_tuple("1.2.3") == (1, 2, 3)

    def test_v_prefix(self):
        assert _parse_version_tuple("v0.1.0") == (0, 1, 0)

    def test_rc(self):
        assert _parse_version_tuple("1.2.3-rc1") == (1, 2, 3)

    def test_empty(self):
        assert _parse_version_tuple("") is None

    def test_no_digits(self):
        assert _parse_version_tuple("abc") is None


class TestIsVersionNewer:
    def test_newer(self):
        assert is_version_newer("0.2.0", "0.1.0") is True

    def test_same(self):
        assert is_version_newer("0.1.0", "0.1.0") is False

    def test_older(self):
        assert is_version_newer("0.1.0", "0.2.0") is False

    def test_unparseable(self):
        assert is_version_newer("abc", "0.1.0") is None

    def test_different_lengths(self):
        assert is_version_newer("0.2", "0.1.0") is True


class TestNormalizeArch:
    def test_x86_64(self):
        assert _normalize_arch("x86_64") == "x86_64"
        assert _normalize_arch("AMD64") == "x86_64"

    def test_arm64(self):
        assert _normalize_arch("aarch64") == "arm64"
        assert _normalize_arch("arm64") == "arm64"

    def test_unknown(self):
        assert _normalize_arch("riscv64") == "riscv64"


class TestSelectAssetName:
    def test_linux_x86_64(self):
        assert select_release_asset_name(system="Linux", machine="x86_64") == "cgp-linux-x86_64.tar.gz"

    def test_linux_arm64(self):
        assert select_release_asset_name(system="Linux", machine="aarch64") == "cgp-linux-arm64.tar.gz"

    def test_macos_x86_64(self):
        assert select_release_asset_name(system="Darwin", machine="x86_64") == "cgp-macos-x86_64.tar.gz"

    def test_macos_arm64(self):
        assert select_release_asset_name(system="Darwin", machine="arm64") == "cgp-macos-arm64.tar.gz"

    def test_windows_x86_64(self):
        assert select_release_asset_name(system="Windows", machine="AMD64") == "cgp-windows-x86_64.zip"

    def test_unsupported_os(self):
        with pytest.raises(RuntimeError, match="Unsupported OS"):
            select_release_asset_name(system="FreeBSD", machine="x86_64")

    def test_unsupported_arch(self):
        with pytest.raises(RuntimeError, match="Unsupported"):
            select_release_asset_name(system="Linux", machine="riscv64")


class TestFetchLatestRelease:
    def test_success(self):
        body = json.dumps({"tag_name": "v0.2.0"}).encode()

        def fake_fetch(url, timeout_s, headers):
            return body

        rel = fetch_latest_release("owner/repo", fetch=fake_fetch)
        assert rel.tag == "v0.2.0"
        assert rel.version == "0.2.0"

    def test_missing_tag(self):
        body = json.dumps({"other": "data"}).encode()

        def fake_fetch(url, timeout_s, headers):
            return body

        with pytest.raises(ValueError, match="missing tag_name"):
            fetch_latest_release("owner/repo", fetch=fake_fetch)


class TestParseChecksums:
    def test_normal(self):
        h1 = "a" * 64
        h2 = "b" * 64
        txt = f"{h1}  cgp-linux-x86_64.tar.gz\n{h2}  cgp-macos-arm64.tar.gz\n"
        result = parse_checksums_txt(txt)
        assert result["cgp-linux-x86_64.tar.gz"] == h1
        assert result["cgp-macos-arm64.tar.gz"] == h2

    def test_empty(self):
        assert parse_checksums_txt("") == {}

    def test_comments(self):
        assert parse_checksums_txt("# comment\n") == {}


class TestBuildUrls:
    def test_download(self):
        url = build_release_download_url("owner/repo", tag="v1.0", asset_name="a.tar.gz")
        assert url == "https://github.com/owner/repo/releases/download/v1.0/a.tar.gz"

    def test_checksums(self):
        url = build_checksums_download_url("owner/repo", tag="v1.0")
        assert url == "https://github.com/owner/repo/releases/download/v1.0/checksums.txt"


class TestIsFrozenBinary:
    def test_not_frozen(self):
        assert is_frozen_binary() is False

    def test_frozen(self):
        with mock.patch.object(__import__("sys"), "frozen", True, create=True):
            assert is_frozen_binary() is True


class TestDownloadAndInstallBundle:
    def _make_tar_gz(self, exe_name: str = "cgp") -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            content = b"#!/bin/sh\necho ok"
            info = tarfile.TarInfo(name=f"cgp/{exe_name}")
            info.size = len(content)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(content))
        return buf.getvalue()

    def _make_zip(self, exe_name: str = "cgp.exe") -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(f"cgp/{exe_name}", "fake exe")
        return buf.getvalue()

    def test_tar_gz_install(self, tmp_path: Path):
        data = self._make_tar_gz()
        calls = {}

        def fake_fetch(url: str, timeout_s: float, headers: Dict[str, str]) -> bytes:
            calls[url] = True
            if "checksums.txt" in url:
                raise Exception("no checksums")
            return data

        install_root = tmp_path / "root"
        bin_dir = tmp_path / "bin"

        result = download_and_install_release_bundle(
            repo="owner/repo",
            tag="v0.1.0",
            asset_name="cgp-linux-x86_64.tar.gz",
            install_root=install_root,
            bin_dir=bin_dir,
            fetch=fake_fetch,
            verify_checksums=False,
        )

        assert (install_root / "versions" / "v0.1.0" / "cgp" / "cgp").exists()
        assert (install_root / "current").is_symlink()
        assert (bin_dir / "cgp").is_symlink()

    def test_zip_install(self, tmp_path: Path):
        data = self._make_zip()

        def fake_fetch(url: str, timeout_s: float, headers: Dict[str, str]) -> bytes:
            if "checksums.txt" in url:
                raise Exception("no checksums")
            return data

        install_root = tmp_path / "root"
        bin_dir = tmp_path / "bin"

        with mock.patch("cursor_gui_patch.github_release.sys") as mock_sys:
            mock_sys.platform = "win32"
            mock_sys.executable = str(tmp_path / "cgp.exe")
            result = download_and_install_release_bundle(
                repo="owner/repo",
                tag="v0.1.0",
                asset_name="cgp-windows-x86_64.zip",
                install_root=install_root,
                bin_dir=bin_dir,
                fetch=fake_fetch,
                verify_checksums=False,
            )

        assert (install_root / "versions" / "v0.1.0" / "cgp").exists()

    def test_unsupported_asset(self, tmp_path: Path):
        with pytest.raises(RuntimeError, match="unsupported bundle asset"):
            download_and_install_release_bundle(
                repo="owner/repo",
                tag="v0.1.0",
                asset_name="cgp-linux-x86_64.deb",
                install_root=tmp_path / "root",
                bin_dir=tmp_path / "bin",
                verify_checksums=False,
            )
