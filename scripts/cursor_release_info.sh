#!/usr/bin/env bash
set -euo pipefail

# Fetch latest Cursor release info.
#
# Output (key=value):
#   version=<cursor_version>
#   commit=<commit_hash>
#   reh_url_linux_x64=<url>
#   reh_url_linux_arm64=<url>
#   reh_url_darwin_x64=<url>
#   reh_url_darwin_arm64=<url>
#   reh_url_win32_x64=<url>

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

# Primary: Cursor download API (returns version, commitSha, rehUrl).
try_download_api() {
  local resp
  resp="$(fetch_text "https://www.cursor.com/api/download?platform=linux-x64&releaseTrack=stable" 2>/dev/null || true)"
  if [ -z "$resp" ]; then return 1; fi

  local version commit
  version="$(printf '%s' "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version',''))" 2>/dev/null || true)"
  commit="$(printf '%s' "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('commitSha',''))" 2>/dev/null || true)"

  if [ -z "$version" ] || [ -z "$commit" ]; then return 1; fi

  echo "version=$version"
  echo "commit=$commit"

  # Fetch rehUrl for each platform.
  for platform in linux-x64 linux-arm64 darwin-x64 darwin-arm64 win32-x64; do
    local key="reh_url_$(printf '%s' "$platform" | tr '-' '_')"
    local pdata
    pdata="$(fetch_text "https://www.cursor.com/api/download?platform=${platform}&releaseTrack=stable" 2>/dev/null || true)"
    if [ -n "$pdata" ]; then
      local reh_url
      reh_url="$(printf '%s' "$pdata" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('rehUrl',''))" 2>/dev/null || true)"
      if [ -n "$reh_url" ]; then
        echo "${key}=${reh_url}"
      fi
    fi
  done

  return 0
}

if try_download_api; then
  exit 0
fi

echo "Failed to fetch Cursor release info" >&2
exit 1
