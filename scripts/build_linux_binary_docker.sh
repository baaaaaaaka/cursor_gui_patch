#!/usr/bin/env bash
set -euo pipefail

# Build cgp Linux binary inside Docker.
#
# Environment variables:
#   CGP_LINUX_ARCH: target arch ("x86_64" or "arm64", default: x86_64)

ARCH="${CGP_LINUX_ARCH:-x86_64}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

case "${ARCH}" in
  x86_64)
    PLATFORM="linux/amd64"
    CGP_PLATFORM="linux-x86_64"
    ;;
  arm64)
    PLATFORM="linux/arm64"
    CGP_PLATFORM="linux-arm64"
    ;;
  *)
    echo "Unsupported arch: ${ARCH}" >&2
    exit 1
    ;;
esac

OUT_DIR="${PROJECT_DIR}/out"
mkdir -p "${OUT_DIR}"

# Use python:3.11-slim as the builder image.
IMAGE="python:3.11-slim"

docker run --rm \
  --platform "${PLATFORM}" \
  -v "${PROJECT_DIR}:/src:ro" \
  -v "${OUT_DIR}:/out" \
  "${IMAGE}" \
  /bin/bash -c "
    set -euxo pipefail
    apt-get update -qq && apt-get install -y -qq binutils >/dev/null 2>&1
    cd /tmp
    cp -r /src ./build
    cd ./build
    pip install -U pip setuptools wheel pyinstaller certifi >/dev/null 2>&1
    pip install -e . >/dev/null 2>&1
    python -m PyInstaller --clean -n cgp --collect-data certifi \
      --specpath /tmp/_spec --distpath /tmp/_dist --workpath /tmp/_build \
      cursor_gui_patch/__main__.py
    # Post-build: strip, create RUNTIME_VERSION, package split archives
    python scripts/post_build.py /tmp/_dist /out ${CGP_PLATFORM}
    echo 'Built archives for ${CGP_PLATFORM}'
  "

echo "Output: ${OUT_DIR}/"
ls -lh "${OUT_DIR}"/cgp*"${CGP_PLATFORM}"* 2>/dev/null || true
