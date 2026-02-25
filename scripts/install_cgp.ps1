# Install latest cgp release for Windows.
#
# Usage:
#   irm https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/install_cgp.ps1 | iex

$ErrorActionPreference = "Stop"

$Repo = if ($env:CGP_GITHUB_REPO) { $env:CGP_GITHUB_REPO } else { "baaaaaaaka/cursor_gui_patch" }
$Tag = if ($env:CGP_INSTALL_TAG) { $env:CGP_INSTALL_TAG } else { "latest" }
$InstallDir = if ($env:CGP_INSTALL_DEST) { $env:CGP_INSTALL_DEST } else { "$env:LOCALAPPDATA\cgp" }
$Asset = "cgp-windows-x86_64.zip"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Resolve tag
if ($Tag -eq "latest") {
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "cgp-installer" }
        $Tag = $release.tag_name
    } catch {
        Write-Host "Failed to resolve latest tag, using 'latest' redirect." -ForegroundColor Yellow
    }
}

# Download
$TmpZip = Join-Path $env:TEMP "cgp-download.zip"
if ($Tag -eq "latest") {
    $Url = "https://github.com/$Repo/releases/latest/download/$Asset"
} else {
    $Url = "https://github.com/$Repo/releases/download/$Tag/$Asset"
}

Write-Host "Downloading $Asset..."
Invoke-WebRequest -Uri $Url -OutFile $TmpZip -UseBasicParsing

# Extract
$TmpExtract = Join-Path $env:TEMP "cgp-extract"
if (Test-Path $TmpExtract) { Remove-Item -Recurse -Force $TmpExtract }
Expand-Archive -Path $TmpZip -DestinationPath $TmpExtract -Force

# Install
$Source = Join-Path $TmpExtract "cgp"
if (-not (Test-Path (Join-Path $Source "cgp.exe"))) {
    Write-Error "Invalid bundle: missing cgp/cgp.exe"
    exit 1
}

$Dest = Join-Path $InstallDir "cgp"
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
Move-Item -Path $Source -Destination $Dest -Force

# Cleanup
Remove-Item -Force $TmpZip -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $TmpExtract -ErrorAction SilentlyContinue

# Add to PATH
$ExeDir = Join-Path $InstallDir "cgp"
$UserPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($UserPath -notlike "*$ExeDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$UserPath;$ExeDir", "User")
    Write-Host "Added $ExeDir to user PATH."
}

Write-Host "Installed cgp to $ExeDir\cgp.exe"
Write-Host "Restart your terminal, then run: cgp --version"
