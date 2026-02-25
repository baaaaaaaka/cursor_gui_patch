#!/usr/bin/env sh
set -eu

# Install latest cgp release bundle and create convenient symlinks.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/install_cgp.sh | sh
#
# Customization via env vars:
# - CGP_GITHUB_REPO: "owner/name" (default: baaaaaaaka/cursor_gui_patch)
# - CGP_INSTALL_TAG: release tag like "v0.1.0" (default: latest)
# - CGP_INSTALL_DEST: install dir (default: ~/.local/bin)
# - CGP_INSTALL_ROOT: extracted bundle root (default: ~/.local/lib/cgp)
# - CGP_INSTALL_FROM_DIR: local dir containing assets + checksums.txt (for offline/test)
# - CGP_INSTALL_OS / CGP_INSTALL_ARCH: override uname detection (for test)

REPO="${CGP_GITHUB_REPO:-baaaaaaaka/cursor_gui_patch}"
TAG="${CGP_INSTALL_TAG:-latest}"
DEST_DIR="${CGP_INSTALL_DEST:-${HOME}/.local/bin}"
ROOT_DIR="${CGP_INSTALL_ROOT:-${HOME}/.local/lib/cgp}"
ASSET_URL_EFFECTIVE=""

OS="${CGP_INSTALL_OS:-$(uname -s)}"
ARCH="${CGP_INSTALL_ARCH:-$(uname -m)}"

case "$(printf '%s' "$ARCH" | tr '[:upper:]' '[:lower:]')" in
  x86_64|amd64) ARCH_NORM="x86_64" ;;
  aarch64|arm64) ARCH_NORM="arm64" ;;
  *) ARCH_NORM="$(printf '%s' "$ARCH" | tr '[:upper:]' '[:lower:]')" ;;
esac

ASSET=""
case "${OS}-${ARCH_NORM}" in
  Linux-x86_64) ASSET="cgp-linux-x86_64.tar.gz" ;;
  Linux-arm64)  ASSET="cgp-linux-arm64.tar.gz" ;;
  Darwin-x86_64) ASSET="cgp-macos-x86_64.tar.gz" ;;
  Darwin-arm64)  ASSET="cgp-macos-arm64.tar.gz" ;;
  *)
    printf '%s\n' "Unsupported platform: ${OS} ${ARCH}" 1>&2
    exit 2
    ;;
esac

mkdir -p "${DEST_DIR}"
mkdir -p "${ROOT_DIR%/}/versions"

# Cross-process install lock.
LOCK_DIR="${ROOT_DIR%/}/.cgp.lock"
LOCK_ACQUIRED="0"
if mkdir "${LOCK_DIR}" 2>/dev/null; then
  LOCK_ACQUIRED="1"
  {
    printf 'pid=%s\n' "$$"
    printf 'host=%s\n' "$(hostname 2>/dev/null || echo unknown)"
  } > "${LOCK_DIR%/}/owner.txt" 2>/dev/null || true
else
  printf '%s\n' "Another cgp install/upgrade is in progress (lock: ${LOCK_DIR})." 1>&2
  printf '%s\n' "If this is stale, remove it and retry: rm -rf ${LOCK_DIR}" 1>&2
  exit 8
fi

TMP_BIN="$(mktemp "${DEST_DIR%/}/.cgp.asset.XXXXXX")"
TMP_SUM="$(mktemp "${DEST_DIR%/}/.cgp.sums.XXXXXX")"
TMP_DIR=""
cleanup() {
  rm -f "${TMP_BIN}" "${TMP_SUM}" 2>/dev/null || true
  if [ -n "${TMP_DIR}" ] && [ -d "${TMP_DIR}" ]; then
    rm -rf "${TMP_DIR}" 2>/dev/null || true
  fi
  if [ "${LOCK_ACQUIRED}" = "1" ] && [ -d "${LOCK_DIR}" ]; then
    rm -rf "${LOCK_DIR}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

is_runnable_cgp() {
  TARGET="${CURRENT_LINK%/}/cgp/cgp"
  if [ ! -f "${TARGET}" ]; then return 1; fi
  if [ ! -x "${TARGET}" ]; then return 1; fi
  if [ -L "${TARGET}" ]; then return 1; fi
  return 0
}

install_once() {
  TAG_RESOLVED="$(resolve_tag)"
  VERSIONS_DIR="${ROOT_DIR%/}/versions"
  if [ "${TAG_RESOLVED}" = "latest" ] && [ -z "${CGP_INSTALL_FROM_DIR:-}" ]; then
    TAG_RESOLVED="latest-$(date +%s)"
  fi
  FINAL_DIR="${VERSIONS_DIR%/}/${TAG_RESOLVED}"
  CURRENT_LINK="${ROOT_DIR%/}/current"

  TMP_DIR="$(mktemp -d "${VERSIONS_DIR%/}/.cgp.extract.XXXXXX")"
  if command -v tar >/dev/null 2>&1; then
    tar -xzf "${TMP_BIN}" -C "${TMP_DIR}"
  else
    printf '%s\n' "Need tar to extract the release bundle." 1>&2
    exit 5
  fi

  if [ ! -f "${TMP_DIR%/}/cgp/cgp" ]; then
    printf '%s\n' "Invalid bundle: missing cgp/cgp in ${ASSET}" 1>&2
    exit 6
  fi
  chmod 755 "${TMP_DIR%/}/cgp/cgp" 2>/dev/null || true

  rm -rf "${FINAL_DIR}" 2>/dev/null || true
  if [ -e "${FINAL_DIR}" ]; then
    FINAL_DIR="${FINAL_DIR}.$(date +%s)"
  fi
  mv "${TMP_DIR}" "${FINAL_DIR}"
  TMP_DIR=""

  TMP_CUR="${ROOT_DIR%/}/.cgp.current.$$"
  rm -f "${TMP_CUR}" 2>/dev/null || true
  ln -s "${FINAL_DIR}" "${TMP_CUR}"
  if [ -L "${CURRENT_LINK}" ]; then
    rm -f "${CURRENT_LINK}" 2>/dev/null || true
  elif [ -d "${CURRENT_LINK}" ]; then
    rm -rf "${CURRENT_LINK}" 2>/dev/null || true
  elif [ -e "${CURRENT_LINK}" ]; then
    rm -f "${CURRENT_LINK}" 2>/dev/null || true
  fi
  mv -f "${TMP_CUR}" "${CURRENT_LINK}"

  TARGET="${CURRENT_LINK%/}/cgp/cgp"
  DEST="${DEST_DIR%/}/cgp"
  if [ -d "${DEST}" ] && [ ! -L "${DEST}" ]; then
    printf '%s\n' "Install failed: ${DEST} is a directory; cannot create cgp symlink there." 1>&2
    exit 9
  fi
  ln -sf "${TARGET}" "${DEST}" 2>/dev/null || true

  if is_runnable_cgp; then
    printf '%s\n' "Installed ${ASSET} -> ${DEST}"
    printf '%s\n' "Bundle: ${CURRENT_LINK} -> ${FINAL_DIR}"
    printf '%s\n' "Tip: ensure ${DEST_DIR} is on your PATH."
    return 0
  fi
  return 1
}

fetch_to() {
  src="$1"
  out="$2"
  if [ -n "${CGP_INSTALL_FROM_DIR:-}" ]; then
    cp "${CGP_INSTALL_FROM_DIR%/}/${src}" "${out}"
    return 0
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${src}" -o "${out}"
    return 0
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -qO "${out}" "${src}"
    return 0
  fi
  printf '%s\n' "Need curl or wget to download." 1>&2
  exit 3
}

fetch_text() {
  url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${url}"
    return 0
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -qO - "${url}"
    return 0
  fi
  return 1
}

resolve_tag() {
  if [ "${TAG}" != "latest" ]; then
    printf '%s' "${TAG}"
    return 0
  fi
  if [ -n "${CGP_INSTALL_FROM_DIR:-}" ]; then
    printf '%s' "latest"
    return 0
  fi
  api="https://api.github.com/repos/${REPO}/releases/latest"
  txt="$(fetch_text "${api}" 2>/dev/null || true)"
  if [ -z "${txt}" ]; then
    printf '%s' "latest"
    return 0
  fi
  tag="$(printf '%s' "${txt}" | tr -d '\n' | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
  if [ -n "${tag}" ]; then
    printf '%s' "${tag}"
  else
    printf '%s' "latest"
  fi
}

if [ -n "${CGP_INSTALL_FROM_DIR:-}" ]; then
  fetch_to "${ASSET}" "${TMP_BIN}"
  if [ -f "${CGP_INSTALL_FROM_DIR%/}/checksums.txt" ]; then
    fetch_to "checksums.txt" "${TMP_SUM}"
  else
    : > "${TMP_SUM}"
  fi
else
  if [ "${TAG}" = "latest" ]; then
    BASE="https://github.com/${REPO}/releases/latest/download"
    if command -v curl >/dev/null 2>&1; then
      ASSET_URL_EFFECTIVE="$(curl -fsSL -o "${TMP_BIN}" -w "%{url_effective}" "${BASE}/${ASSET}")"
    else
      fetch_to "${BASE}/${ASSET}" "${TMP_BIN}"
    fi
    if fetch_to "${BASE}/checksums.txt" "${TMP_SUM}" 2>/dev/null; then
      :
    else
      : > "${TMP_SUM}"
    fi
  else
    BASE="https://github.com/${REPO}/releases/download/${TAG}"
    fetch_to "${BASE}/${ASSET}" "${TMP_BIN}"
    if fetch_to "${BASE}/checksums.txt" "${TMP_SUM}" 2>/dev/null; then
      :
    else
      : > "${TMP_SUM}"
    fi
  fi
fi

# Verify checksum.
if [ -s "${TMP_SUM}" ]; then
  EXPECTED="$(awk -v f="${ASSET}" '$NF==f {print $1; exit 0}' "${TMP_SUM}" | tr '[:upper:]' '[:lower:]' || true)"
  if [ -n "${EXPECTED}" ]; then
    ACTUAL=""
    if command -v sha256sum >/dev/null 2>&1; then
      ACTUAL="$(sha256sum "${TMP_BIN}" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')"
    elif command -v shasum >/dev/null 2>&1; then
      ACTUAL="$(shasum -a 256 "${TMP_BIN}" | awk '{print $1}' | tr '[:upper:]' '[:lower:]')"
    fi
    if [ -n "${ACTUAL}" ] && [ "${ACTUAL}" != "${EXPECTED}" ]; then
      printf '%s\n' "Checksum mismatch for ${ASSET}: expected ${EXPECTED}, got ${ACTUAL}" 1>&2
      exit 4
    fi
  fi
fi

if install_once; then
  exit 0
fi

# Auto-repair on broken installs.
printf '%s\n' "Detected a broken cgp install; attempting automatic cleanup and reinstall..." 1>&2
rm -rf "${ROOT_DIR%/}/current" "${ROOT_DIR%/}/versions" 2>/dev/null || true
mkdir -p "${ROOT_DIR%/}/versions"

if install_once; then
  exit 0
fi

printf '%s\n' "Install failed: ${TARGET} is not a runnable executable." 1>&2
printf '%s\n' "Tip: remove ${ROOT_DIR%/} and re-run the installer." 1>&2
exit 7
