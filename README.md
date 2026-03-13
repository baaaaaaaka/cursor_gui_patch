# cgp — Cursor GUI Patch

Patch tool for Cursor IDE: unlock all models and disable admin auto-run restrictions.

## What it does

- **Models patch**: Redirects `getUsableModels` to `availableModels`, making all models visible
- **Auto-run patch**: Disables team admin auto-run controls so you keep full control

## Quick Start

### One-click patch (no install needed)

**Linux / macOS / WSL:**

```bash
curl -fsSL https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/patch.sh | sh
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/patch.ps1 | iex
```

### One-click unpatch

**Linux / macOS / WSL:**

```bash
curl -fsSL https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/unpatch.sh | sh
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/unpatch.ps1 | iex
```

## Install (persistent)

If you want `cgp` available as a command:

**Linux / macOS / WSL:**

```bash
curl -fsSL https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/install_cgp.sh | sh
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/install_cgp.ps1 | iex
```

**From source (pip):**

```bash
pip install git+https://github.com/baaaaaaaka/cursor_gui_patch.git
```

## Commands

```
cgp patch          Apply all patches
cgp patch --dry-run    Preview without writing
cgp patch --force      Ignore cache, re-scan all files
cgp patch --only-models    Only apply models patch
cgp patch --only-autorun   Only apply auto-run patch

cgp unpatch        Restore original files from backups

cgp status         Show installation and patch status
cgp status --json  Output as JSON

cgp auto install   Install auto-patcher extension
cgp auto status    Show auto-patcher extension status
cgp auto uninstall Remove auto-patcher extension

cgp --version      Show version
```

### Global options

```
--server-dir DIR   Explicit Cursor server directory (skip auto-discovery)
--gui-dir DIR      Explicit Cursor GUI directory (skip auto-discovery)
```

### Auto-patcher relaunch behavior

After a successful auto-patch, you can control whether Cursor relaunches automatically:

```bash
cgp auto install --reload-mode prompt              # default, asks before relaunch
cgp auto install --reload-mode auto                # auto relaunch after patch
cgp auto install --reload-mode auto --reload-delay-ms 1500
cgp auto install --reload-mode off                 # never relaunch automatically
```

- `prompt`: safest default for active coding sessions
- `auto`: best for users who want zero-click recovery after Cursor updates
- `off`: only patch and notify; relaunch manually later
- If `cgp` is missing and network download fails repeatedly, the auto-patcher will fallback to local cached cgp bundles.

## Auto-update

When installed as a binary (not pip), cgp checks for updates on each run and
automatically updates itself. Disable with:

```bash
export CGP_NO_AUTO_UPDATE=1
```

## Supported platforms

| Platform | Architecture |
|----------|-------------|
| Linux | x86_64, arm64 |
| macOS | x86_64 (Intel), arm64 (Apple Silicon) |
| Windows | x86_64 |

## Troubleshooting

### Permission denied

```
sudo cgp patch        # Linux/macOS
```

On Windows, run PowerShell as Administrator.

### macOS code signing

cgp automatically re-signs Cursor.app after patching. If it fails:

```bash
sudo codesign --force --deep --sign - /Applications/Cursor.app
```

### Patch doesn't work after Cursor update

Cursor updates replace patched files. Re-run `cgp patch` after each update.

### Reverting patches

```bash
cgp unpatch
```

This restores all original files from `.cgp.bak` backups created during patching.

## Cursor compatibility

See [docs/cursor_compatibility.md](docs/cursor_compatibility.md) for tested Cursor versions.

## License

MIT
