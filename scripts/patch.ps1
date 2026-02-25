# One-click patch for Cursor (Windows, no persistent install).
#
# Usage:
#   irm https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/patch.ps1 | iex

$ErrorActionPreference = "Stop"
$Repo = if ($env:CGP_GITHUB_REPO) { $env:CGP_GITHUB_REPO } else { "baaaaaaaka/cursor_gui_patch" }
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
    Write-Host "Running: cgp patch"
    Write-Host "---"

    & $Exe patch
    $ExitCode = $LASTEXITCODE

    Write-Host "---"
    if ($ExitCode -eq 0) {
        Write-Host ""
        Write-Host "To undo, run:"
        Write-Host "  irm https://raw.githubusercontent.com/$Repo/main/scripts/unpatch.ps1 | iex"
    } else {
        Write-Host ""
        Write-Host "Patch failed (exit code $ExitCode)."
        Write-Host "Try running PowerShell as Administrator."
    }
} finally {
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}

Read-Host -Prompt "Press Enter to close"
