#!/usr/bin/env sh
set -eu

# One-click patch for Cursor (no persistent install).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/patch.sh | sh

REPO="${CGP_GITHUB_REPO:-baaaaaaaka/cursor_gui_patch}"

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
    exit 2
    ;;
esac

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "${TMP_DIR}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

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

printf '%s\n' "Downloading cgp (${ASSET})..."
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
printf '%s\n' "Running: cgp patch"
printf '%s\n' "---"

"${CGP}" patch || EXIT_CODE=$?

printf '%s\n' "---"
if [ "${EXIT_CODE:-0}" = "0" ]; then
  printf '%s\n' ""
  printf '%s\n' "To undo, run:"
  printf '%s\n' "  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/scripts/unpatch.sh | sh"
else
  printf '%s\n' ""
  printf '%s\n' "Patch failed (exit code ${EXIT_CODE:-0})."
  printf '%s\n' "Try running with sudo:"
  printf '%s\n' "  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/scripts/patch.sh | sudo sh"
fi

# Keep window open if not in a terminal.
if [ ! -t 0 ] 2>/dev/null; then
  printf '%s' "Press Enter to close..."
  read -r _ 2>/dev/null || true
fi
