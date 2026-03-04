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
    IMAGE="quay.io/pypa/manylinux_2_28_x86_64"
    ;;
  arm64)
    PLATFORM="linux/arm64"
    CGP_PLATFORM="linux-arm64"
    IMAGE="quay.io/pypa/manylinux_2_28_aarch64"
    ;;
  *)
    echo "Unsupported arch: ${ARCH}" >&2
    exit 1
    ;;
esac

OUT_DIR="${PROJECT_DIR}/out"
mkdir -p "${OUT_DIR}"

PYBIN="/opt/python/cp311-cp311/bin"

docker run --rm \
  --platform "${PLATFORM}" \
  -v "${PROJECT_DIR}:/src:ro" \
  -v "${OUT_DIR}:/out" \
  "${IMAGE}" \
  /bin/bash -c "
    set -euxo pipefail
    ${PYBIN}/python --version
    cd /tmp
    cp -r /src ./build
    cd ./build
    ${PYBIN}/python -m pip install -U pip setuptools wheel pyinstaller certifi >/dev/null 2>&1
    ${PYBIN}/python -m pip install -e . >/dev/null 2>&1
    ${PYBIN}/python -m PyInstaller --clean -n cgp --collect-data certifi \
      --specpath /tmp/_spec --distpath /tmp/_dist --workpath /tmp/_build \
      cursor_gui_patch/__main__.py
    # Post-build: strip, create RUNTIME_VERSION, package split archives
    ${PYBIN}/python scripts/post_build.py /tmp/_dist /out ${CGP_PLATFORM}
    echo 'Built archives for ${CGP_PLATFORM}'
  "

echo "Output: ${OUT_DIR}/"
ls -lh "${OUT_DIR}"/cgp*"${CGP_PLATFORM}"* 2>/dev/null || true
