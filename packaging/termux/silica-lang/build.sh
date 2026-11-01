TERMUX_PKG_HOMEPAGE=https://github.com/sufiyan-sabeel/silica
TERMUX_PKG_DESCRIPTION="A small, statically typed, bytecode-compiled programming language"
TERMUX_PKG_LICENSE="MIT"
TERMUX_PKG_MAINTAINER="@sufiyan-sabeel"
TERMUX_PKG_VERSION=0.10.0
TERMUX_PKG_SRCURL=https://github.com/sufiyan-sabeel/silica/archive/refs/tags/v${TERMUX_PKG_VERSION}.tar.gz
TERMUX_PKG_SHA256=0b416fdf5a9c929553d93bfa7d44611daffb1e4d406979a30365e8107726eeba
TERMUX_PKG_DEPENDS="python"
TERMUX_PKG_BUILD_DEPENDS="python-pip"
# Pure Python: one package for every architecture Termux supports, so aarch64 and
# arm both get it without a separate build.
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true

termux_step_make() {
	# Nothing to compile: the engine is Python. The wheel is built so the
	# installed tree matches what pip users get.
	pip wheel \
		--no-deps \
		--no-build-isolation \
		--wheel-dir "${TERMUX_PKG_TMPDIR}/wheel" \
		.
}

termux_step_make_install() {
	local wheel
	wheel=$(ls "${TERMUX_PKG_TMPDIR}"/wheel/*.whl)
	pip install \
		--no-deps \
		--prefix "${TERMUX_PREFIX}" \
		--no-warn-script-location \
		"${wheel}"

	# pip writes the launcher into $PREFIX/bin with the mode it was given, but be
	# explicit: a package whose entry point is not executable is broken.
	chmod 755 "${TERMUX_PREFIX}/bin/silica"

	# Docs and examples belong in the prefix, not in the wheel.
	install -Dm644 README.md "${TERMUX_PREFIX}/share/doc/silica-lang/README.md"
	install -Dm644 CHANGELOG.md "${TERMUX_PREFIX}/share/doc/silica-lang/CHANGELOG.md"
	install -Dm644 docs/LANGUAGE_SPEC.md \
		"${TERMUX_PREFIX}/share/doc/silica-lang/LANGUAGE_SPEC.md"
	install -Dm644 docs/STANDARD_LIBRARY.md \
		"${TERMUX_PREFIX}/share/doc/silica-lang/STANDARD_LIBRARY.md"
	install -Dm644 docs/SECURITY_MODEL.md \
		"${TERMUX_PREFIX}/share/doc/silica-lang/SECURITY_MODEL.md"
	mkdir -p "${TERMUX_PREFIX}/share/silica-lang/examples"
	install -m644 examples/*.sc "${TERMUX_PREFIX}/share/silica-lang/examples/"
	install -Dm644 examples/data/sales.csv \
		"${TERMUX_PREFIX}/share/silica-lang/examples/data/sales.csv"
}
