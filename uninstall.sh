#!/bin/sh
# Silica uninstaller.
#
#   curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/uninstall.sh | sh
#
# It removes exactly what install.sh created, using the manifest that installer
# wrote. It refuses to delete anything it cannot prove it owns, and it never
# touches a Python installation, a virtual environment it did not create, or a
# `silica` launcher that was not created by install.sh.
#
# Environment overrides:
#   SILICA_HOME   where the venv lives      (default: ~/.local/share/silica)
#   SILICA_BIN    where the launcher goes   (default: ~/.local/bin)
#   SILICA_YES=1  do not prompt

set -eu

REPO="sufiyan-sabeel/silica"
HOME_DIR="${SILICA_HOME:-$HOME/.local/share/silica}"
BIN_DIR="${SILICA_BIN:-$HOME/.local/bin}"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

if [ -n "${TERMUX_VERSION:-}" ] || printf '%s' "${PREFIX:-}" | grep -q 'com\.termux'; then
    : "${PREFIX:=/data/data/com.termux/files/usr}"
    BIN_DIR="${SILICA_BIN:-$PREFIX/bin}"
fi

MANIFEST="$HOME_DIR/install-manifest.txt"
LAUNCHER="$BIN_DIR/silica"

say "Silica uninstaller"
say ""

if [ ! -f "$MANIFEST" ]; then
    say "No manifest at $MANIFEST — Silica does not look installed there."
    if [ -L "$LAUNCHER" ] || [ -f "$LAUNCHER" ]; then
        say "A launcher exists at $LAUNCHER but without a manifest it may not be ours."
        say "Remove it by hand if you are sure, then delete $HOME_DIR."
    fi
    exit 0
fi

# read the manifest rather than trusting the current environment
MANIFEST_VENV=""
while read -r key value; do
    case "$key" in
        venv) MANIFEST_VENV="$value" ;;
        launcher) LAUNCHER="$value" ;;
        version) INSTALLED_VERSION="$value" ;;
    esac
done < "$MANIFEST"

say "  installed   : ${INSTALLED_VERSION:-unknown}"
say "  venv        : ${MANIFEST_VENV:-$HOME_DIR/venv}"
say "  launcher    : $LAUNCHER"
say ""

if [ "${SILICA_YES:-0}" != "1" ]; then
    printf 'Remove these? [y/N] '
    read -r answer || answer=""
    case "$answer" in
        y|Y|yes|YES) ;;
        *) say "Cancelled."; exit 0 ;;
    esac
fi

# the launcher: only if it carries our marker
if [ -f "$LAUNCHER" ] && grep -q "silica-managed-launcher" "$LAUNCHER" 2>/dev/null; then
    rm -f "$LAUNCHER"
    say "removed launcher $LAUNCHER"
elif [ -L "$LAUNCHER" ]; then
    target="$(readlink "$LAUNCHER" 2>/dev/null || true)"
    case "$target" in
        *"$HOME_DIR"*) rm -f "$LAUNCHER"; say "removed launcher $LAUNCHER" ;;
        *) say "left $LAUNCHER alone: it points outside $HOME_DIR" ;;
    esac
elif [ -e "$LAUNCHER" ]; then
    say "left $LAUNCHER alone: it was not created by install.sh"
fi

# the venv: only inside the Silica home directory
if [ -n "$MANIFEST_VENV" ] && [ -d "$MANIFEST_VENV" ]; then
    case "$MANIFEST_VENV" in
        "$HOME_DIR"/*) rm -rf "$MANIFEST_VENV"; say "removed venv $MANIFEST_VENV" ;;
        *) die "refusing to delete $MANIFEST_VENV: it is outside $HOME_DIR" ;;
    esac
fi

rm -f "$MANIFEST"
rm -f "$HOME_DIR/VERSION"
rmdir "$HOME_DIR" 2>/dev/null && say "removed $HOME_DIR" || say "left $HOME_DIR (not empty)"

say ""
say "Silica uninstalled."
say "Reinstall with: curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | sh"
