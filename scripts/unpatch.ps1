# One-click unpatch for Cursor (Windows, no persistent install).
#
# Usage:
#   irm https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/unpatch.ps1 | iex

$ErrorActionPreference = "Stop"
$Repo = if ($env:CGP_GITHUB_REPO) { $env:CGP_GITHUB_REPO } else { "baaaaaaaka/cursor_gui_patch" }

# If cgp is already on PATH, use it directly.
$ExistingCgp = Get-Command cgp -ErrorAction SilentlyContinue
if ($ExistingCgp) {
    Write-Host "Running: cgp unpatch"
    Write-Host "---"
    & cgp unpatch
    Write-Host "---"
    Read-Host -Prompt "Press Enter to close"
    exit $LASTEXITCODE
}

$Asset = "cgp-windows-x86_64.zip"
$TmpDir = Join-Path $env:TEMP "cgp-oneshot-$(Get-Random)"
New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null

try {
    $Url = "https://github.com/$Repo/releases/latest/download/$Asset"
    $ZipPath = Join-Path $TmpDir $Asset

    Write-Host "Downloading cgp ($Asset)..."
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing

    Write-Host "Extracting..."
    Expand-Archive -Path $ZipPath -DestinationPath $TmpDir -Force

    $Exe = Join-Path $TmpDir "cgp\cgp.exe"
    if (-not (Test-Path $Exe)) {
        Write-Error "Error: cgp.exe not found in bundle."
        exit 1
    }

    Write-Host ""
    Write-Host "Running: cgp unpatch"
    Write-Host "---"

    & $Exe unpatch
    $ExitCode = $LASTEXITCODE

    Write-Host "---"
    if ($ExitCode -ne 0) {
        Write-Host ""
        Write-Host "Unpatch failed (exit code $ExitCode)."
    }
} finally {
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}

Read-Host -Prompt "Press Enter to close"
