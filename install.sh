#!/bin/sh
# Silica installer for Linux and Termux.
#
#   curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/install.sh | sh
#
# What it does, in order:
#   1. detects the platform (Termux vs desktop Linux) and CPU architecture
#   2. checks for Python 3.9+ and the venv module
#   3. downloads the release wheel and its SHA-256, and verifies the checksum
#   4. installs into an isolated virtual environment
#   5. puts a `silica` launcher on PATH
#   6. records what it created, so uninstall.sh removes exactly that
#
# Trust model: piping a script into a shell means you trust this file and the
# release it downloads. Nothing here is risk-free, so the script is short enough
# to read, it downloads only from this repository's releases, and it refuses to
# install anything whose SHA-256 does not match the published checksum.
#
# Environment overrides (all optional):
#   SILICA_VERSION   release to install            (default: 0.5.0)
#   SILICA_HOME      where the venv lives          (default: ~/.local/share/silica)
#   SILICA_BIN       where the launcher goes       (default: ~/.local/bin)
#   SILICA_ARTIFACT  install from a local wheel instead of downloading
#   SILICA_BASE_URL  release base URL (default: this repository's releases)
#   SILICA_SYSTEM=1  install system-wide (needs root; the only path that may sudo)
#   SILICA_YES=1     do not prompt

set -eu

REPO="sufiyan-sabeel/silica"
VERSION="${SILICA_VERSION:-0.5.0}"
DIST_NAME="silica_lang"

say() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- 1. platform ------------------------------------------------------------
detect_platform() {
    if [ -n "${TERMUX_VERSION:-}" ] \
        || [ "$(uname -o 2>/dev/null || true)" = "Android" ] \
        || printf '%s' "${PREFIX:-}" | grep -q 'com\.termux'; then
        PLATFORM="termux"
    else
        PLATFORM="linux"
    fi

    case "$(uname -s 2>/dev/null || echo unknown)" in
        Linux) ;;
        *) die "this installer supports Linux and Termux only; detected $(uname -s)" ;;
    esac

    case "$(uname -m 2>/dev/null || echo unknown)" in
        x86_64|amd64|aarch64|arm64|armv7l|armv8l|i686|i386|riscv64|ppc64le|s390x)
            ARCH="$(uname -m)" ;;
        *) die "unsupported CPU architecture: $(uname -m)" ;;
    esac

    if [ "$PLATFORM" = "termux" ]; then
        # Termux puts everything under $PREFIX, and $PREFIX/bin is already on PATH
        : "${PREFIX:=/data/data/com.termux/files/usr}"
        HOME_DIR="${SILICA_HOME:-$HOME/.local/share/silica}"
        BIN_DIR="${SILICA_BIN:-$PREFIX/bin}"
    else
        HOME_DIR="${SILICA_HOME:-$HOME/.local/share/silica}"
        BIN_DIR="${SILICA_BIN:-$HOME/.local/bin}"
    fi

    if [ "${SILICA_SYSTEM:-0}" = "1" ]; then
        [ "$(id -u)" = "0" ] || die "SILICA_SYSTEM=1 needs root; run it with sudo or drop the flag"
        HOME_DIR="${SILICA_HOME:-/opt/silica}"
        BIN_DIR="${SILICA_BIN:-/usr/local/bin}"
    fi
}

# --- 2. python --------------------------------------------------------------
find_python() {
    for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
                PYTHON="$(command -v "$candidate")"
                return 0
            fi
        fi
    done
    return 1
}

check_python() {
    if ! find_python; then
        if [ "$PLATFORM" = "termux" ]; then
            die "Python 3.9+ not found. Install it with: pkg install python"
        fi
        die "Python 3.9+ not found. Install it with your package manager, e.g.:
  Debian/Ubuntu : sudo apt install python3 python3-venv
  Fedora        : sudo dnf install python3
  Arch          : sudo pacman -S python"
    fi

    if ! "$PYTHON" -c 'import venv, ensurepip' 2>/dev/null; then
        if [ "$PLATFORM" = "termux" ]; then
            die "the Python venv module is unavailable. Install it with: pkg install python"
        fi
        die "the Python venv module is missing. On Debian/Ubuntu: sudo apt install python3-venv"
    fi

    PY_VERSION="$("$PYTHON" -c 'import platform; print(platform.python_version())')"
    say "  python      : $PY_VERSION ($PYTHON)"
}

# --- 3. download and verify -------------------------------------------------
sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d' ' -f1
    else
        "$PYTHON" - "$1" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as handle:
    for block in iter(lambda: handle.read(65536), b""):
        h.update(block)
print(h.hexdigest())
PY
    fi
}

fetch() {
    url="$1"
    dest="$2"
    if command -v curl >/dev/null 2>&1; then
        if [ -n "${SILICA_BASE_URL:-}" ]; then
            # an explicit base URL is a deliberate override: local mirrors and
            # air-gapped installs cannot be HTTPS-only. The default release URL
            # below is still pinned to HTTPS.
            curl -fsSL -o "$dest" "$url"
        else
            curl -fsSL --proto '=https' --tlsv1.2 -o "$dest" "$url"
        fi
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$dest" "$url"
    else
        die "neither curl nor wget is available"
    fi
}

obtain_artifact() {
    TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t silica)"
    trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

    if [ -n "${SILICA_ARTIFACT:-}" ]; then
        [ -f "$SILICA_ARTIFACT" ] || die "SILICA_ARTIFACT is not a file: $SILICA_ARTIFACT"
        WHEEL="$SILICA_ARTIFACT"
        say "  artifact    : $WHEEL (local, checksum not verified)"
        return 0
    fi

    BASE="${SILICA_BASE_URL:-https://github.com/$REPO/releases/download/v$VERSION}"
    WHEEL_NAME="$DIST_NAME-$VERSION-py3-none-any.whl"
    WHEEL="$TMP_DIR/$WHEEL_NAME"
    SUMS="$TMP_DIR/SHA256SUMS.txt"

    say "  release     : v$VERSION"
    fetch "$BASE/SHA256SUMS.txt" "$SUMS" \
        || die "cannot download the checksum file for v$VERSION.
Is v$VERSION published? See https://github.com/$REPO/releases"
    fetch "$BASE/$WHEEL_NAME" "$WHEEL" \
        || die "cannot download $WHEEL_NAME for v$VERSION"

    expected="$(grep -E "[[:space:]]\*?$WHEEL_NAME\$" "$SUMS" | cut -d' ' -f1 | head -n1)"
    [ -n "$expected" ] || die "SHA256SUMS.txt has no entry for $WHEEL_NAME; refusing to install"
    actual="$(sha256_of "$WHEEL")"
    if [ "$expected" != "$actual" ]; then
        die "checksum mismatch for $WHEEL_NAME
  expected: $expected
  actual  : $actual
Refusing to install. The download may be corrupt or tampered with."
    fi
    say "  checksum    : verified (sha256 $(printf '%s' "$expected" | cut -c1-16)...)"
}

# --- 4. install -------------------------------------------------------------
install_into_venv() {
    VENV="$HOME_DIR/venv"

    if [ ! -d "$VENV" ]; then
        say "  creating    : $VENV"
        "$PYTHON" -m venv "$VENV" || die "could not create a virtual environment at $VENV"
    else
        say "  reusing     : $VENV"
    fi

    VENV_PY="$VENV/bin/python"
    [ -x "$VENV_PY" ] || die "the virtual environment at $VENV is broken; remove it and re-run"

    # --upgrade --force-reinstall makes a rerun an upgrade rather than a failure.
    # The env prefix matters: an exported PIP_USER=1 makes pip refuse to install
    # into a virtualenv, and a stray PYTHONPATH can shadow the package. Both are
    # common on real machines, so they are neutralised here rather than assumed.
    env PYTHONPATH= PIP_USER=0 PIP_CONFIG_FILE=/dev/null \
        "$VENV_PY" -m pip install --quiet --disable-pip-version-check \
        --upgrade --force-reinstall "$WHEEL" \
        || die "pip could not install $WHEEL"

    printf '%s\n' "$VERSION" > "$HOME_DIR/VERSION"
}

place_launcher() {
    mkdir -p "$BIN_DIR"
    LAUNCHER="$BIN_DIR/silica"

    if [ -e "$LAUNCHER" ] && [ ! -L "$LAUNCHER" ]; then
        # only replace a file we created
        if ! grep -q "silica-managed-launcher" "$LAUNCHER" 2>/dev/null; then
            die "$LAUNCHER already exists and was not created by this installer.
Move it aside and re-run, or set SILICA_BIN to another directory."
        fi
        rm -f "$LAUNCHER"
    fi

    cat > "$LAUNCHER.tmp.$$" <<EOF
#!/bin/sh
# silica-managed-launcher — created by install.sh, removed by uninstall.sh
exec "$VENV/bin/silica" "\$@"
EOF
    chmod 755 "$LAUNCHER.tmp.$$"
    mv -f "$LAUNCHER.tmp.$$" "$LAUNCHER"
    say "  launcher    : $LAUNCHER"
}

write_manifest() {
    MANIFEST="$HOME_DIR/install-manifest.txt"
    {
        printf '%s\n' "# created by install.sh; read by uninstall.sh"
        printf 'version %s\n' "$VERSION"
        printf 'venv %s\n' "$VENV"
        printf 'launcher %s\n' "$LAUNCHER"
        printf 'home %s\n' "$HOME_DIR"
    } > "$MANIFEST"
}

check_path() {
    case ":${PATH:-}:" in
        *":$BIN_DIR:"*) return 0 ;;
    esac
    warn "$BIN_DIR is not on your PATH, so \`silica\` will not be found yet."
    say ""
    say "Add it by appending this line to your shell profile:"
    say ""
    if [ "$PLATFORM" = "termux" ]; then
        say "    export PATH=\"$BIN_DIR:\$PATH\""
    else
        say "    export PATH=\"$BIN_DIR:\$PATH\""
        say ""
        say "For bash that is ~/.bashrc, for zsh ~/.zshrc. Then restart the shell,"
        say "or run: export PATH=\"$BIN_DIR:\$PATH\""
    fi
    say ""
}

# --- 5. run -----------------------------------------------------------------
say "Silica installer"
say ""
detect_platform
say "  platform    : $PLATFORM ($ARCH)"
check_python
obtain_artifact
install_into_venv
place_launcher
write_manifest

say ""
say "Silica $VERSION installed."
say ""
"$LAUNCHER" --version || die "the installed launcher does not run"
check_path
say "Try it:"
say "    silica                      # interactive interpreter"
say "    silica examples/hello.sc    # run a file"
say ""
say "Upgrade : re-run this installer, optionally with SILICA_VERSION=x.y.z"
say "Remove  : curl -fsSL https://raw.githubusercontent.com/$REPO/main/uninstall.sh | sh"
