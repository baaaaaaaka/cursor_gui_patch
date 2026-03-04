#!/usr/bin/env sh
set -eu

# One-click unpatch for Cursor (no persistent install).
#
# Priority: 1) cgp on PATH  2) Python 3.9+ (source)  3) platform binary
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/unpatch.sh | sh

REPO="${CGP_GITHUB_REPO:-baaaaaaaka/cursor_gui_patch}"

# --- Helpers ---

find_python39() {
  for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
      if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
        printf '%s' "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

fetch_to() {
  src="$1"; out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${src}" -o "${out}"; return 0
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -qO "${out}" "${src}"; return 0
  fi
  printf '%s\n' "Need curl or wget to download." 1>&2
  exit 3
}

run_with_optional_sudo() {
  if "$@"; then
    return 0
  fi
  status=$?
  if [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1; then
    printf '%s\n' "Operation failed without elevated privileges; retrying with sudo..."
    sudo "$@"
    return $?
  fi
  return "${status}"
}

json_extract() {
  key="$1"; file="$2"
  v="$(sed -n "s/.*\"${key}\":\"\\([^\"]*\\)\".*/\\1/p" "${file}" | head -n 1)"
  printf '%s' "${v}" | sed 's#\\/#/#g'
}

should_install_official_after_unpatch() {
  out_file="$1"
  mode="$(printf '%s' "${CGP_UNPATCH_INSTALL_OFFICIAL_APP:-}" | tr '[:upper:]' '[:lower:]')"
  if [ -z "${mode}" ] && [ "$(uname -s 2>/dev/null || true)" = "Darwin" ]; then
    mode="auto"
  fi

  case "${mode}" in
    0|false|no|off|disabled) return 1 ;;
    1|true|yes|on|always) return 0 ;;
    auto)
      if grep -Eq '^Restored: 0$' "${out_file}" && grep -Eq '^No backup: [1-9][0-9]*$' "${out_file}"; then
        return 0
      fi
      if grep -Fq 'No snapshot/backup restore was applied' "${out_file}"; then
        return 0
      fi
      return 1
      ;;
    *) return 1 ;;
  esac
}

install_official_cursor_macos() (
  set -eu

  ARCH="$(uname -m | tr '[:upper:]' '[:lower:]')"
  case "${ARCH}" in
    arm64|aarch64) PLATFORM="darwin-arm64" ;;
    x86_64|amd64) PLATFORM="darwin-x64" ;;
    *)
      printf '%s\n' "Unsupported macOS arch for official reinstall: ${ARCH}" 1>&2
      return 1
      ;;
  esac

  if ! command -v hdiutil >/dev/null 2>&1; then
    printf '%s\n' "hdiutil not found; cannot install official Cursor.app automatically." 1>&2
    return 1
  fi

  TMP_INSTALL="$(mktemp -d)"
  API_JSON="${TMP_INSTALL}/download.json"
  DMG_PATH="${TMP_INSTALL}/Cursor.dmg"
  ATTACH_LOG="${TMP_INSTALL}/attach.log"
  MOUNT_POINT="${TMP_INSTALL}/mnt"
  mkdir -p "${MOUNT_POINT}"

  cleanup_install() {
    if [ -n "${MOUNT_POINT}" ] && [ -d "${MOUNT_POINT}" ]; then
      hdiutil detach "${MOUNT_POINT}" -quiet >/dev/null 2>&1 || true
    fi
    rm -rf "${TMP_INSTALL}" >/dev/null 2>&1 || true
  }
  trap cleanup_install EXIT INT TERM

  API_URL="https://www.cursor.com/api/download?platform=${PLATFORM}&releaseTrack=stable"
  fetch_to "${API_URL}" "${API_JSON}"

  DMG_URL="$(json_extract "downloadUrl" "${API_JSON}")"
  VERSION="$(json_extract "version" "${API_JSON}")"
  if [ -z "${DMG_URL}" ]; then
    printf '%s\n' "Failed to get official Cursor download URL from API." 1>&2
    return 1
  fi

  printf '%s\n' "Downloading official Cursor installer (${PLATFORM}${VERSION:+, version ${VERSION}})..."
  fetch_to "${DMG_URL}" "${DMG_PATH}"

  if ! hdiutil attach "${DMG_PATH}" -nobrowse -readonly -mountpoint "${MOUNT_POINT}" >"${ATTACH_LOG}" 2>&1; then
    cat "${ATTACH_LOG}" 1>&2 || true
    return 1
  fi

  if [ -z "${MOUNT_POINT}" ] || [ ! -d "${MOUNT_POINT}" ]; then
    cat "${ATTACH_LOG}" 1>&2 || true
    printf '%s\n' "Failed to detect mounted DMG path." 1>&2
    return 1
  fi

  APP_SRC="$(find "${MOUNT_POINT}" -maxdepth 2 -type d -name "Cursor.app" 2>/dev/null | head -n 1)"
  if [ -z "${APP_SRC}" ]; then
    APP_SRC="$(find "${MOUNT_POINT}" -maxdepth 2 -type d -name "*.app" 2>/dev/null | head -n 1)"
  fi
  if [ -z "${APP_SRC}" ] || [ ! -d "${APP_SRC}" ]; then
    printf '%s\n' "Cursor.app not found in mounted installer image." 1>&2
    return 1
  fi

  TARGET="/Applications/Cursor.app"
  STAGE="/Applications/.Cursor.app.cgp.new.$$"
  OLD="/Applications/.Cursor.app.cgp.old.$$"

  if [ "$(id -u)" != "0" ]; then
    printf '%s\n' "Installing to /Applications. Will request sudo only if needed."
  fi

  run_with_optional_sudo rm -rf "${STAGE}" "${OLD}" || true
  run_with_optional_sudo /usr/bin/ditto "${APP_SRC}" "${STAGE}"
  if [ -d "${TARGET}" ]; then
    run_with_optional_sudo mv "${TARGET}" "${OLD}"
  fi

  if ! run_with_optional_sudo mv "${STAGE}" "${TARGET}"; then
    run_with_optional_sudo rm -rf "${STAGE}" || true
    if [ -d "${OLD}" ]; then
      run_with_optional_sudo mv "${OLD}" "${TARGET}" || true
    fi
    printf '%s\n' "Failed to replace ${TARGET} with official app bundle." 1>&2
    return 1
  fi

  run_with_optional_sudo rm -rf "${OLD}" || true
  printf '%s\n' "Official Cursor installed at ${TARGET}${VERSION:+ (version ${VERSION})}."
)

maybe_install_official_after_unpatch() {
  out_file="$1"
  if [ "$(uname -s 2>/dev/null || true)" != "Darwin" ]; then
    return 0
  fi
  if ! should_install_official_after_unpatch "${out_file}"; then
    return 0
  fi
  printf '%s\n' ""
  printf '%s\n' "Auto reinstall mode enabled. Attempting official Cursor install..."
  install_official_cursor_macos
}

# --- Priority 1: cgp already on PATH ---

if command -v cgp >/dev/null 2>&1; then
  OUT_FILE="$(mktemp)"
  cleanup_out() { rm -f "${OUT_FILE}" 2>/dev/null || true; }
  trap cleanup_out EXIT INT TERM
  printf '%s\n' "Running: cgp unpatch (from PATH)"
  printf '%s\n' "---"
  cgp unpatch >"${OUT_FILE}" 2>&1 || EXIT_CODE=$?
  cat "${OUT_FILE}"
  printf '%s\n' "---"
  if [ "${EXIT_CODE:-0}" = "0" ]; then
    printf '%s\n' ""
    printf '%s\n' "Removing auto-patcher extension..."
    cgp auto uninstall || true
    maybe_install_official_after_unpatch "${OUT_FILE}" || EXIT_CODE=$?
  fi
  if [ "${EXIT_CODE:-0}" != "0" ]; then
    printf '%s\n' ""
    printf '%s\n' "Unpatch failed (exit code ${EXIT_CODE:-0})."
  fi
  if [ ! -t 0 ] 2>/dev/null; then
    printf '%s' "Press Enter to close..."
    read -r _ 2>/dev/null || true
  fi
  cleanup_out
  exit "${EXIT_CODE:-0}"
fi

# --- Priority 2: Python 3.9+ source mode ---

PYTHON="$(find_python39)" || PYTHON=""
if [ -n "${PYTHON}" ]; then
  TMP_DIR="$(mktemp -d)"
  cleanup() { rm -rf "${TMP_DIR}" 2>/dev/null || true; }
  trap cleanup EXIT INT TERM

  SRC_ASSET="cgp-src.tar.gz"
  URL="https://github.com/${REPO}/releases/latest/download/${SRC_ASSET}"

  printf '%s\n' "Python 3.9+ found (${PYTHON}). Downloading source package (${SRC_ASSET})..."
  fetch_to "${URL}" "${TMP_DIR}/${SRC_ASSET}"

  printf '%s\n' "Extracting..."
  tar -xzf "${TMP_DIR}/${SRC_ASSET}" -C "${TMP_DIR}"

  printf '%s\n' ""
  printf '%s\n' "Running: ${PYTHON} -m cursor_gui_patch unpatch"
  printf '%s\n' "---"

  OUT_FILE="${TMP_DIR}/unpatch.out"
  (cd "${TMP_DIR}" && "${PYTHON}" -m cursor_gui_patch unpatch) >"${OUT_FILE}" 2>&1 || EXIT_CODE=$?
  cat "${OUT_FILE}"

  printf '%s\n' "---"
  if [ "${EXIT_CODE:-0}" = "0" ]; then
    printf '%s\n' ""
    printf '%s\n' "Removing auto-patcher extension..."
    (cd "${TMP_DIR}" && "${PYTHON}" -m cursor_gui_patch auto uninstall) || true
    maybe_install_official_after_unpatch "${OUT_FILE}" || EXIT_CODE=$?
  fi
  if [ "${EXIT_CODE:-0}" != "0" ]; then
    printf '%s\n' ""
    printf '%s\n' "Unpatch failed (exit code ${EXIT_CODE:-0})."
  fi

  if [ ! -t 0 ] 2>/dev/null; then
    printf '%s' "Press Enter to close..."
    read -r _ 2>/dev/null || true
  fi
  exit "${EXIT_CODE:-0}"
fi

# --- Priority 3: Platform binary fallback ---

OS="$(uname -s)"
ARCH="$(uname -m)"

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
    printf '%s\n' "Unsupported platform: ${OS} ${ARCH}"
    printf '%s\n' "Install Python 3.9+ and try again."
    exit 2
    ;;
esac

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "${TMP_DIR}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

printf '%s\n' "Downloading cgp binary (${ASSET})..."
URL="https://github.com/${REPO}/releases/latest/download/${ASSET}"
fetch_to "${URL}" "${TMP_DIR}/${ASSET}"

printf '%s\n' "Extracting..."
tar -xzf "${TMP_DIR}/${ASSET}" -C "${TMP_DIR}"

CGP="${TMP_DIR}/cgp/cgp"
if [ ! -f "${CGP}" ]; then
  printf '%s\n' "Error: cgp binary not found in bundle."
  exit 4
fi
chmod +x "${CGP}" 2>/dev/null || true

printf '%s\n' ""
printf '%s\n' "Running: cgp unpatch"
printf '%s\n' "---"

OUT_FILE="${TMP_DIR}/unpatch.out"
"${CGP}" unpatch >"${OUT_FILE}" 2>&1 || EXIT_CODE=$?
cat "${OUT_FILE}"

printf '%s\n' "---"
if [ "${EXIT_CODE:-0}" = "0" ]; then
  printf '%s\n' ""
  printf '%s\n' "Removing auto-patcher extension..."
  "${CGP}" auto uninstall || true
  maybe_install_official_after_unpatch "${OUT_FILE}" || EXIT_CODE=$?
fi
if [ "${EXIT_CODE:-0}" != "0" ]; then
  printf '%s\n' ""
  printf '%s\n' "Unpatch failed (exit code ${EXIT_CODE:-0})."
fi

if [ ! -t 0 ] 2>/dev/null; then
  printf '%s' "Press Enter to close..."
  read -r _ 2>/dev/null || true
fi
