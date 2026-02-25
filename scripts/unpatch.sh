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

# --- Priority 1: cgp already on PATH ---

if command -v cgp >/dev/null 2>&1; then
  printf '%s\n' "Running: cgp unpatch (from PATH)"
  printf '%s\n' "---"
  cgp unpatch || EXIT_CODE=$?
  printf '%s\n' "---"
  if [ "${EXIT_CODE:-0}" = "0" ]; then
    printf '%s\n' ""
    printf '%s\n' "Removing auto-patcher extension..."
    cgp auto uninstall || true
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

  (cd "${TMP_DIR}" && "${PYTHON}" -m cursor_gui_patch unpatch) || EXIT_CODE=$?

  printf '%s\n' "---"
  if [ "${EXIT_CODE:-0}" = "0" ]; then
    printf '%s\n' ""
    printf '%s\n' "Removing auto-patcher extension..."
    (cd "${TMP_DIR}" && "${PYTHON}" -m cursor_gui_patch auto uninstall) || true
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

"${CGP}" unpatch || EXIT_CODE=$?

printf '%s\n' "---"
if [ "${EXIT_CODE:-0}" = "0" ]; then
  printf '%s\n' ""
  printf '%s\n' "Removing auto-patcher extension..."
  "${CGP}" auto uninstall || true
fi
if [ "${EXIT_CODE:-0}" != "0" ]; then
  printf '%s\n' ""
  printf '%s\n' "Unpatch failed (exit code ${EXIT_CODE:-0})."
fi

if [ ! -t 0 ] 2>/dev/null; then
  printf '%s' "Press Enter to close..."
  read -r _ 2>/dev/null || true
fi
