#!/usr/bin/env python3
"""Post-build script: strip binaries, create RUNTIME_VERSION, package split archives.

Usage:
    python scripts/post_build.py <dist_dir> <output_dir> <platform>

    <dist_dir>:   PyInstaller --onedir output dir (contains cgp/cgp + cgp/_internal/)
    <output_dir>: Where to write the .tar.gz / .zip files
    <platform>:   One of: linux-x86_64, linux-arm64, macos-x86_64, macos-arm64, windows-x86_64

Produces:
    cgp-<platform>.tar.gz           Full bundle (backward-compatible)
    cgp-app-<platform>.tar.gz      App-only (just the executable)
    cgp-runtime-<platform>.tar.gz  Runtime-only (just _internal/)

Also writes RUNTIME_VERSION into _internal/ before packaging.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path


VALID_PLATFORMS = {
    "linux-x86_64",
    "linux-arm64",
    "macos-x86_64",
    "macos-arm64",
    "windows-x86_64",
}


def strip_binaries(dist_dir: Path) -> None:
    """Strip debug symbols from all .so/.dylib files and the main executable."""
    if sys.platform == "win32":
        return  # strip not available on Windows

    if not _has_strip():
        print("  [skip] strip not found in PATH", file=sys.stderr)
        return

    targets = []
    internal = dist_dir / "cgp" / "_internal"
    if internal.exists():
        for f in internal.rglob("*"):
            if f.is_file() and (f.suffix in (".so", ".dylib") or ".so." in f.name):
                targets.append(f)

    exe = dist_dir / "cgp" / "cgp"
    if exe.exists() and exe.is_file():
        targets.append(exe)

    for t in targets:
        try:
            subprocess.run(
                ["strip", str(t)],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

    print(f"  Stripped {len(targets)} files", file=sys.stderr)


def _has_strip() -> bool:
    try:
        r = subprocess.run(
            ["strip", "--version"],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def compute_runtime_version(internal_dir: Path) -> str:
    """Compute a hash of all runtime files (names + sizes) to detect changes."""
    entries = []
    for f in sorted(internal_dir.rglob("*")):
        if f.is_file() and f.name != "RUNTIME_VERSION":
            rel = f.relative_to(internal_dir)
            size = f.stat().st_size
            entries.append(f"{rel}:{size}")

    content = "\n".join(entries)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def write_runtime_version(internal_dir: Path) -> str:
    """Write RUNTIME_VERSION file and return the version string."""
    version = compute_runtime_version(internal_dir)
    rv_file = internal_dir / "RUNTIME_VERSION"
    rv_file.write_text(version + "\n", encoding="utf-8")
    print(f"  RUNTIME_VERSION: {version}", file=sys.stderr)
    return version


def package_full(dist_dir: Path, output_dir: Path, platform: str) -> Path:
    """Package the full bundle (cgp/ directory with everything)."""
    is_windows = "windows" in platform
    if is_windows:
        name = f"cgp-{platform}.zip"
        out = output_dir / name
        _create_zip(dist_dir, out, "cgp")
    else:
        name = f"cgp-{platform}.tar.gz"
        out = output_dir / name
        _create_tar_gz(dist_dir, out, "cgp")
    print(f"  Full:    {name} ({_human_size(out)})", file=sys.stderr)
    return out


def package_app(dist_dir: Path, output_dir: Path, platform: str) -> Path:
    """Package app-only (just the executable)."""
    is_windows = "windows" in platform
    if is_windows:
        name = f"cgp-app-{platform}.zip"
        out = output_dir / name
        _create_zip_filtered(dist_dir, out, "cgp", include_internal=False)
    else:
        name = f"cgp-app-{platform}.tar.gz"
        out = output_dir / name
        _create_tar_gz_filtered(dist_dir, out, "cgp", include_internal=False)
    print(f"  App:     {name} ({_human_size(out)})", file=sys.stderr)
    return out


def package_runtime(dist_dir: Path, output_dir: Path, platform: str) -> Path:
    """Package runtime-only (just _internal/)."""
    is_windows = "windows" in platform
    if is_windows:
        name = f"cgp-runtime-{platform}.zip"
        out = output_dir / name
        _create_zip_filtered(dist_dir, out, "cgp", include_exe=False)
    else:
        name = f"cgp-runtime-{platform}.tar.gz"
        out = output_dir / name
        _create_tar_gz_filtered(dist_dir, out, "cgp", include_exe=False)
    print(f"  Runtime: {name} ({_human_size(out)})", file=sys.stderr)
    return out


def _create_tar_gz(base_dir: Path, out_path: Path, top_dir: str) -> None:
    """Create a tar.gz of base_dir/top_dir/."""
    with tarfile.open(str(out_path), "w:gz") as tf:
        src = base_dir / top_dir
        for f in sorted(src.rglob("*")):
            arcname = str(Path(top_dir) / f.relative_to(src))
            tf.add(str(f), arcname=arcname)


def _create_tar_gz_filtered(
    base_dir: Path, out_path: Path, top_dir: str,
    *, include_internal: bool = True, include_exe: bool = True,
) -> None:
    """Create a filtered tar.gz."""
    with tarfile.open(str(out_path), "w:gz") as tf:
        src = base_dir / top_dir
        for f in sorted(src.rglob("*")):
            rel = f.relative_to(src)
            parts = rel.parts

            # Filter based on flags
            if not include_internal and len(parts) > 0 and parts[0] == "_internal":
                continue
            if not include_exe and f.is_file() and len(parts) == 1 and parts[0] != "_internal":
                # Skip the top-level executable
                continue

            arcname = str(Path(top_dir) / rel)
            tf.add(str(f), arcname=arcname)


def _create_zip(base_dir: Path, out_path: Path, top_dir: str) -> None:
    """Create a zip of base_dir/top_dir/."""
    with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
        src = base_dir / top_dir
        for f in sorted(src.rglob("*")):
            if f.is_file():
                arcname = str(Path(top_dir) / f.relative_to(src))
                zf.write(str(f), arcname=arcname)


def _create_zip_filtered(
    base_dir: Path, out_path: Path, top_dir: str,
    *, include_internal: bool = True, include_exe: bool = True,
) -> None:
    """Create a filtered zip."""
    with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
        src = base_dir / top_dir
        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src)
            parts = rel.parts

            if not include_internal and len(parts) > 0 and parts[0] == "_internal":
                continue
            if not include_exe and len(parts) == 1 and parts[0] != "_internal":
                continue

            arcname = str(Path(top_dir) / rel)
            zf.write(str(f), arcname=arcname)


def _human_size(path: Path) -> str:
    size = path.stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def main() -> None:
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <dist_dir> <output_dir> <platform>", file=sys.stderr)
        print(f"  Platforms: {', '.join(sorted(VALID_PLATFORMS))}", file=sys.stderr)
        sys.exit(1)

    dist_dir = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()
    platform = sys.argv[3]

    if platform not in VALID_PLATFORMS:
        print(f"Invalid platform: {platform}", file=sys.stderr)
        print(f"  Valid: {', '.join(sorted(VALID_PLATFORMS))}", file=sys.stderr)
        sys.exit(1)

    cgp_dir = dist_dir / "cgp"
    internal_dir = cgp_dir / "_internal"

    if not cgp_dir.exists():
        print(f"Error: {cgp_dir} not found", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    print("Post-build:", file=sys.stderr)

    # 1. Strip debug symbols
    strip_binaries(dist_dir)

    # 2. Write RUNTIME_VERSION
    if internal_dir.exists():
        write_runtime_version(internal_dir)

    # 3. Package archives
    package_full(dist_dir, output_dir, platform)
    package_app(dist_dir, output_dir, platform)
    package_runtime(dist_dir, output_dir, platform)

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
