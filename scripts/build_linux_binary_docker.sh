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
    ASSET_NAME="cgp-linux-x86_64.tar.gz"
    ;;
  arm64)
    PLATFORM="linux/arm64"
    ASSET_NAME="cgp-linux-arm64.tar.gz"
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
    tar -C /tmp/_dist -czf /out/${ASSET_NAME} cgp
    echo 'Built /out/${ASSET_NAME}'
  "

echo "Output: ${OUT_DIR}/${ASSET_NAME}"
