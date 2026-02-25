# One-click patch for Cursor (Windows, no persistent install).
#
# Priority: 1) cgp on PATH  2) Python 3.9+ (source)  3) platform binary
#
# Usage:
#   irm https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/patch.ps1 | iex

$ErrorActionPreference = "Stop"
$Repo = if ($env:CGP_GITHUB_REPO) { $env:CGP_GITHUB_REPO } else { "baaaaaaaka/cursor_gui_patch" }

# --- Helpers ---

function Find-Python39 {
    foreach ($cmd in @("py", "python3", "python")) {
        try {
            if ($cmd -eq "py") {
                $result = & py -3 -c "import sys; print('OK' if sys.version_info >= (3,9) else 'NO')" 2>$null
            } else {
                $result = & $cmd -c "import sys; print('OK' if sys.version_info >= (3,9) else 'NO')" 2>$null
            }
            if ($result -eq "OK") {
                if ($cmd -eq "py") { return @("py", "-3") }
                return @($cmd)
            }
        } catch {}
    }
    return $null
}

function Invoke-PythonCmd {
    param([string[]]$PyCmds, [string[]]$Arguments)
    $allArgs = @($PyCmds | Select-Object -Skip 1) + $Arguments
    & $PyCmds[0] $allArgs
}

# --- Priority 1: cgp already on PATH ---

$ExistingCgp = Get-Command cgp -ErrorAction SilentlyContinue
if ($ExistingCgp) {
    Write-Host "Running: cgp patch (from PATH)"
    Write-Host "---"
    & cgp patch
    $ExitCode = $LASTEXITCODE
    Write-Host "---"
    if ($ExitCode -eq 0) {
        Write-Host ""
        Write-Host "Installing auto-patcher extension..."
        try { & cgp auto install } catch {}
        Write-Host ""
        Write-Host "To undo, run:"
        Write-Host "  irm https://raw.githubusercontent.com/$Repo/main/scripts/unpatch.ps1 | iex"
    } else {
        Write-Host ""
        Write-Host "Patch failed (exit code $ExitCode)."
    }
    Read-Host -Prompt "Press Enter to close"
    exit $ExitCode
}

# --- Priority 2: Python 3.9+ source mode ---

$PyCmds = Find-Python39
if ($PyCmds) {
    $TmpDir = Join-Path $env:TEMP "cgp-oneshot-$(Get-Random)"
    New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null

    try {
        $SrcAsset = "cgp-src.tar.gz"
        $Url = "https://github.com/$Repo/releases/latest/download/$SrcAsset"
        $SrcPath = Join-Path $TmpDir $SrcAsset

        Write-Host "Python 3.9+ found. Downloading source package ($SrcAsset)..."
        Invoke-WebRequest -Uri $Url -OutFile $SrcPath -UseBasicParsing

        Write-Host "Extracting..."
        # Use Python's tarfile (tar may not be available on all Windows)
        # Pass paths via sys.argv to avoid quoting issues; use filter='data' on 3.12+ to suppress DeprecationWarning
        Invoke-PythonCmd -PyCmds $PyCmds -Arguments @("-c", "import sys,tarfile;t=tarfile.open(sys.argv[1]);t.extractall(sys.argv[2],**({'filter':'data'}if hasattr(tarfile,'data_filter')else{}));t.close()", $SrcPath, $TmpDir)

        Write-Host ""
        Write-Host "Running: python -m cursor_gui_patch patch"
        Write-Host "---"

        Push-Location $TmpDir
        try {
            Invoke-PythonCmd -PyCmds $PyCmds -Arguments @("-m", "cursor_gui_patch", "patch")
            $ExitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }

        Write-Host "---"
        if ($ExitCode -eq 0) {
            Write-Host ""
            Write-Host "Installing auto-patcher extension..."
            Push-Location $TmpDir
            try { Invoke-PythonCmd -PyCmds $PyCmds -Arguments @("-m", "cursor_gui_patch", "auto", "install") } catch {}
            finally { Pop-Location }
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
    exit $ExitCode
}

# --- Priority 3: Platform binary fallback ---

$Asset = "cgp-windows-x86_64.zip"
$TmpDir = Join-Path $env:TEMP "cgp-oneshot-$(Get-Random)"
New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null

try {
    $Url = "https://github.com/$Repo/releases/latest/download/$Asset"
    $ZipPath = Join-Path $TmpDir $Asset

    Write-Host "Downloading cgp binary ($Asset)..."
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
        Write-Host "Installing auto-patcher extension..."
        try { & $Exe auto install } catch {}
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
