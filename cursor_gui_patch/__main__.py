import sys

# Use absolute import so PyInstaller frozen binaries work correctly.
# Relative imports fail when __main__.py is the entry point without
# a parent package context.
from cursor_gui_patch.cli import main

main()
