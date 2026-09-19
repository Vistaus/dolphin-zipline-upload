#!/usr/bin/env bash
# Install the Zipline Upload service menu for Dolphin (KDE Plasma 6).
# Installs per-user only — no root required.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || true)"
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
MENUDIR="$SHARE/kio/servicemenus"
APPDIR="$SHARE/zipline-upload"

if [[ -z "$PYTHON" ]]; then
    echo "error: python3 not found in PATH" >&2
    exit 1
fi
if ! command -v kdialog >/dev/null; then
    echo "warning: kdialog not found — the settings GUI and progress bar need it" >&2
fi

mkdir -p "$APPDIR" "$MENUDIR"
install -m 755 "$REPO/zipline-upload.py" "$APPDIR/zipline-upload.py"
install -m 755 "$REPO/zipline_gui.py" "$APPDIR/zipline_gui.py"

# Optional: the windowed settings GUI needs PySide6. Install it into a
# private venv (best-effort, needs network once). Without it the addon
# falls back to kdialog menus automatically.
if [[ ! -x "$APPDIR/venv/bin/python" ]]; then
    VENV_PY=/usr/bin/python3
    [[ -x "$VENV_PY" ]] || VENV_PY="$PYTHON"
    if "$VENV_PY" -m venv "$APPDIR/venv" 2>/dev/null \
       && "$APPDIR/venv/bin/pip" install --quiet PySide6-Essentials; then
        echo "Windowed settings GUI: ready (PySide6 in private venv)"
    else
        echo "Windowed settings GUI: PySide6 setup skipped — the settings"
        echo "UI will use kdialog menus instead (everything else works)."
    fi
fi

sed -e "s|@PYTHON@|$PYTHON|g" \
    -e "s|@SCRIPT@|$APPDIR/zipline-upload.py|g" \
    "$REPO/servicemenus/zipline-upload.desktop.in" \
    > "$MENUDIR/zipline-upload.desktop"
chmod +x "$MENUDIR/zipline-upload.desktop"

if command -v desktop-file-validate >/dev/null; then
    if ! desktop-file-validate "$MENUDIR/zipline-upload.desktop"; then
        echo "warning: desktop-file-validate reported issues (usually harmless)" >&2
    fi
fi

# Refresh KDE's service cache so the menu appears immediately.
if command -v kbuildsycoca6 >/dev/null; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi

echo "Installed:"
echo "  $APPDIR/zipline-upload.py"
echo "  $APPDIR/zipline_gui.py"
echo "  $MENUDIR/zipline-upload.desktop"
echo
echo "Right-click any file in Dolphin → Zipline → Upload to Zipline."
echo "Configure first with: $PYTHON $APPDIR/zipline-upload.py --configure"
