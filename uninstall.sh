#!/usr/bin/env bash
# Remove the Zipline Upload service menu (keeps your settings and history).
set -euo pipefail

SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
# Safety guard: never operate on an empty/root/unexpected data directory.
if [[ -z "$SHARE" || "$SHARE" == "/" || ! -d "$SHARE" ]]; then
    echo "error: refusing to uninstall from unexpected data dir: '$SHARE'" >&2
    exit 1
fi
rm -f "$SHARE/kio/servicemenus/zipline-upload.desktop"
rm -f "$SHARE/kio/servicemenus/zipline-upload.py" \
      "$SHARE/kio/servicemenus/zipline_gui.py"   # store/GHNS installs
rm -rf "$SHARE/zipline-upload"   # install.sh layout + optional PySide6 venv

if command -v kbuildsycoca6 >/dev/null; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi

echo "Removed the Zipline service menu (scripts and GUI venv)."
echo "Your settings remain in ~/.config/zipline-upload/ (delete to reset)."
