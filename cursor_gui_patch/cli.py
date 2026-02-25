"""CLI interface: cgp patch / unpatch / status."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .patching import patch, unpatch, status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cgp",
        description="Cursor GUI & Server Patch Tool",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--server-dir", metavar="DIR", default=None,
        help="Explicit Cursor server directory (overrides auto-discovery)",
    )
    parser.add_argument(
        "--gui-dir", metavar="DIR", default=None,
        help="Explicit Cursor GUI directory (overrides auto-discovery)",
    )

    sub = parser.add_subparsers(dest="command")

    # patch
    p_patch = sub.add_parser("patch", help="Apply patches")
    p_patch.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    p_patch.add_argument("--force", action="store_true", help="Ignore cache, re-scan all files")
    p_patch.add_argument("--only-autorun", action="store_true", help="Only apply auto-run patch")
    p_patch.add_argument("--only-models", action="store_true", help="Only apply models patch")

    # unpatch
    p_unpatch = sub.add_parser("unpatch", help="Restore original files from backups")
    p_unpatch.add_argument("--dry-run", action="store_true", help="Preview changes without writing")

    # status
    p_status = sub.add_parser("status", help="Show installation and patch status")
    p_status.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    # Auto-update for frozen binaries (before parsing args).
    try:
        from .update import auto_update_if_needed

        auto_update_if_needed(sys.argv)
    except Exception:
        pass

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    server_dir = args.server_dir
    gui_dir = args.gui_dir

    if args.command == "patch":
        only_patches = None
        if args.only_autorun or args.only_models:
            only_patches = set()
            if args.only_autorun:
                only_patches.add("autorun")
            if args.only_models:
                only_patches.add("models")

        report = patch(
            server_dir=server_dir,
            gui_dir=gui_dir,
            dry_run=args.dry_run,
            force=args.force,
            only_patches=only_patches,
        )

        if args.dry_run:
            print("[DRY RUN]")
        print(report.summary())
        if not report.ok:
            sys.exit(1)

    elif args.command == "unpatch":
        report = unpatch(
            server_dir=server_dir,
            gui_dir=gui_dir,
            dry_run=args.dry_run,
        )

        if args.dry_run:
            print("[DRY RUN]")
        print(report.summary())
        if not report.ok:
            sys.exit(1)

    elif args.command == "status":
        report = status(
            server_dir=server_dir,
            gui_dir=gui_dir,
        )

        if args.json_output:
            data = {
                "installations": report.installations,
                "files": [
                    {
                        "path": str(f.path),
                        "extension": f.extension,
                        "patch_names": f.patch_names,
                        "patched": f.patched,
                        "has_backup": f.has_backup,
                        "error": f.error,
                    }
                    for f in report.files
                ],
            }
            print(json.dumps(data, indent=2))
        else:
            print(report.summary())
