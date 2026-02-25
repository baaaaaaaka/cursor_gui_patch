#!/usr/bin/env bash
set -euo pipefail

# Fetch latest Cursor release info.
#
# Output (key=value):
#   version=<cursor_version>
#   commit=<commit_hash>
#
# Tries multiple sources to find the latest Cursor version.

fetch_text() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" 2>/dev/null
    return $?
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -qO - "$url" 2>/dev/null
    return $?
  fi
  return 1
}

# Try the Cursor update API.
try_update_api() {
  local resp
  resp="$(fetch_text "https://api2.cursor.sh/updates/api/update/linux-x64/stable/latest" 2>/dev/null || true)"
  if [ -z "$resp" ]; then return 1; fi

  local version commit
  version="$(printf '%s' "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('productVersion',''))" 2>/dev/null || true)"
  commit="$(printf '%s' "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version',''))" 2>/dev/null || true)"

  if [ -n "$version" ] && [ -n "$commit" ]; then
    echo "version=$version"
    echo "commit=$commit"
    return 0
  fi
  return 1
}

if try_update_api; then
  exit 0
fi

echo "Failed to fetch Cursor release info" >&2
exit 1
