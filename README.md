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

### Auto-patcher reload behavior

After a successful auto-patch, you can control whether Cursor reloads automatically:

```bash
cgp auto install --reload-mode prompt              # default, asks before reload
cgp auto install --reload-mode auto                # auto reload after patch
cgp auto install --reload-mode auto --reload-delay-ms 1500
cgp auto install --reload-mode off                 # never reload automatically
```

- `prompt`: safest default for active coding sessions
- `auto`: best for users who want zero-click recovery after Cursor updates
- `off`: only patch and notify; reload manually later
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

To reduce repeated Keychain prompts after patching, prefer a fixed signing identity
instead of ad-hoc signing:

```bash
export CGP_CODESIGN_IDENTITY="CGP Cursor Patch"
cgp patch
```

Notes:
- macOS only; non-macOS platforms ignore this setting.
- If the preferred identity fails, cgp falls back to ad-hoc signing (`-`) to avoid blocking patch.
- You can also control auto-detection name with `CGP_CODESIGN_STABLE_IDENTITY_NAME`
  (default: `CGP Cursor Patch`).

### macOS official-signature restore (snapshot mode)

On macOS GUI installs, cgp now keeps **one latest full-app snapshot** to restore
official signature without reinstalling:

- `cgp patch`: before patching, if current app signature is confidently official,
  cgp refreshes a single snapshot copy (old snapshot is replaced).
- `cgp unpatch`: cgp first tries full-app snapshot restore.
  If successful, official signature is restored and re-sign is skipped.
- If no usable snapshot exists, cgp falls back to file-level `.cgp.bak` restore
  and then re-signs as before.

Scope and storage:
- macOS GUI only; server installs and non-macOS are unchanged.
- Extra disk usage: about one additional `Cursor.app` size (single latest version).
- Default snapshot directory: `~/.cursor_gui_patch/macos_official_app_snapshots`.

Advanced env:
- `CGP_DISABLE_MACOS_APP_SNAPSHOT=1`: disable snapshot mode.
- `CGP_MACOS_APP_SNAPSHOT_DIR=/path/to/dir`: override snapshot storage location.
- `CGP_MACOS_OFFICIAL_AUTHORITY_HINTS=Anysphere`: signature authority hints used
  to decide whether app is "official enough" to refresh snapshot.

================ macOS Keychain / Signature ================

After patch/unpatch on macOS, you may see prompts like:
`Cursor wants to use your confidential information stored in "Cursor Safe Storage"`.

Why prompts happen:
- Keychain permission is tied to code-sign identity.
- Cursor auto-update restores official signature.
- cgp patch/unpatch re-signs app bundle, so identity may switch.

Best practice:
- Use one fixed signing identity (`CGP_CODESIGN_IDENTITY`) for all runs.
- Confirm requester path is `/Applications/Cursor.app`, then click `Always Allow`.
- If prompts repeat, inspect `Cursor Safe Storage` rules in Keychain Access.

Password prompts (typical):
- Usually `0-2` prompts around update/patch cycles.
- Each prompt may ask your macOS login password once.

Official signature after `unpatch`:
- If snapshot restore succeeds, official signature is restored from saved app snapshot.
- If snapshot restore is unavailable, cgp uses file-level restore + re-sign (not vendor signature).
- For older cgp versions (before snapshot mode) with no app snapshot, use official installer/update path.

TLDR >>> macOS now prefers one-latest official app snapshot for unpatch restore; if trusted prompt path is `/Applications/Cursor.app`, click `Always Allow` (or equivalent) and keep a fixed signing identity to minimize fallback re-sign prompts.

### Patch doesn't work after Cursor update

Cursor updates replace patched files. Re-run `cgp patch` after each update.

### Reverting patches

```bash
cgp unpatch
```

This restores all original files from `.cgp.bak` backups created during patching.

macOS one-click script can also auto-install official Cursor.app (optional):

```bash
CGP_UNPATCH_INSTALL_OFFICIAL_APP=auto \
  curl -fsSL https://raw.githubusercontent.com/baaaaaaaka/cursor_gui_patch/main/scripts/unpatch.sh | sh
```

- `CGP_UNPATCH_INSTALL_OFFICIAL_APP=auto`: only when unpatch restored nothing (`Restored: 0` and `No backup > 0`).
- `CGP_UNPATCH_INSTALL_OFFICIAL_APP=always`: always reinstall official app after successful unpatch.
- default on macOS (unset): `auto`.
- `CGP_UNPATCH_INSTALL_OFFICIAL_APP=off`: disable this behavior.
- Installer step tries without sudo first and only prompts for sudo if needed.

## Cursor compatibility

See [docs/cursor_compatibility.md](docs/cursor_compatibility.md) for tested Cursor versions.

## License

MIT
