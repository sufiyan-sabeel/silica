TERMUX_PKG_HOMEPAGE=https://github.com/sufiyan-sabeel/silica
TERMUX_PKG_DESCRIPTION="A small, statically typed, bytecode-compiled programming language"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@sufiyan-sabeel"
TERMUX_PKG_VERSION="0.10.0"
TERMUX_PKG_REVISION=1
TERMUX_PKG_SRCURL="https://github.com/sufiyan-sabeel/silica/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz"
TERMUX_PKG_SHA256=0b416fdf5a9c929553d93bfa7d44611daffb1e4d406979a30365e8107726eeba
TERMUX_PKG_AUTO_UPDATE=true
TERMUX_PKG_UPDATE_VERSION_REGEXP='\d+(?:\.\d+){1,2}'
TERMUX_PKG_DEPENDS="python, python-pip"
# Pure Python: no compiled extensions and no native libraries, so one package
# serves every architecture Termux builds (aarch64, arm, i686, x86_64).
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_SETUP_PYTHON=true

termux_step_make() {
	# Nothing to compile. Installation is the build step for a Python package.
	:
}

termux_step_make_install() {
	# cross-pip is the crossenv pip that the Termux build system prepares when
	# TERMUX_PKG_SETUP_PYTHON=true; plain `pip` would install for the host.
	cross-pip install --no-deps --prefix="$TERMUX_PREFIX" "$TERMUX_PKG_SRCDIR"

	# The launcher must be executable; an entry point that cannot run is broken.
	chmod 755 "$TERMUX_PREFIX/bin/silica"

	# Docs and examples belong in the prefix, not inside site-packages.
	install -Dm644 README.md "$TERMUX_PREFIX/share/doc/silica-lang/README.md"
	install -Dm644 CHANGELOG.md "$TERMUX_PREFIX/share/doc/silica-lang/CHANGELOG.md"
	install -Dm644 docs/LANGUAGE_SPEC.md "$TERMUX_PREFIX/share/doc/silica-lang/LANGUAGE_SPEC.md"
	install -Dm644 docs/STANDARD_LIBRARY.md "$TERMUX_PREFIX/share/doc/silica-lang/STANDARD_LIBRARY.md"
	install -Dm644 docs/SECURITY_MODEL.md "$TERMUX_PREFIX/share/doc/silica-lang/SECURITY_MODEL.md"
	install -Dm644 docs/APPLICATIONS.md "$TERMUX_PREFIX/share/doc/silica-lang/APPLICATIONS.md"

	mkdir -p "$TERMUX_PREFIX/share/silica-lang/examples/data"
	install -m644 examples/*.sc "$TERMUX_PREFIX/share/silica-lang/examples/"
	install -m644 examples/data/*.csv "$TERMUX_PREFIX/share/silica-lang/examples/data/"
}
