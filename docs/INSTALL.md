# Installing Silica

Silica is a Python package with one console entry point, `silica`. There is no
compiled component and no runtime dependency beyond Python 3.9 or newer, so
installation is the same everywhere: put the package in a Python environment and
make its `silica` script reachable on `PATH`.

Three supported ways in, in order of how much you should trust them.

---

## 1. The installer (Linux and Termux)

```bash
curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/install.sh | sh
```

This downloads `install.sh` from `main` and runs it. It then:

1. detects the platform (Termux or desktop Linux) and the CPU architecture;
2. finds Python 3.9+ and checks the `venv` module;
3. downloads the release wheel **and** `SHA256SUMS.txt`, and refuses to continue
   if the checksum does not match;
4. installs into a virtual environment at `~/.local/share/silica/venv`;
5. writes a `silica` launcher to `~/.local/bin` (or `$PREFIX/bin` on Termux);
6. tells you exactly what to add to your shell profile if that directory is not
   on `PATH`;
7. records what it created, so `uninstall.sh` can remove precisely that.

It never runs `sudo` unless you ask for it, never writes outside those
directories, and is safe to run twice — a second run is an upgrade.

### Picking a version

```bash
SILICA_VERSION=0.2.1 sh install.sh      # a specific published release
```

The version must exist as a GitHub release with the wheel and checksum attached.
`install.sh` will not fall back to `main` if the version is missing; it stops and
tells you the release could not be found.

### If `silica` is not found afterwards

The installer prints the exact line to add. In short:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add that to `~/.bashrc` (bash) or `~/.zshrc` (zsh) and restart the shell. On
Termux the launcher goes to `$PREFIX/bin`, which is already on `PATH`.

### Upgrading

Re-run the installer. It reuses the existing virtual environment and replaces the
package in place.

```bash
curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/install.sh | sh
```

### Uninstalling

```bash
curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/uninstall.sh | sh
```

It reads the manifest written at install time and removes only those paths. It
refuses to delete a `silica` launcher it did not create, and refuses to delete a
virtual environment outside the Silica home directory. It never touches your
Python installation.

### The trust model, stated plainly

Piping a script into a shell means you trust that script and whatever it fetches.
That is not risk-free, and this project does not pretend otherwise. What is done
to keep the risk small:

* `install.sh` is short and readable; read it before running it.
* It downloads only from this repository's GitHub releases, over HTTPS
  (`curl --proto '=https' --tlsv1.2`).
* It verifies the wheel's SHA-256 against `SHA256SUMS.txt` from the same release
  and aborts on any mismatch.
* It does not use `sudo` unless you set `SILICA_SYSTEM=1`, and that path requires
  you to be root already.
* It installs into a virtual environment, so nothing touches the system Python.

The weaker link is the checksum file: it comes from the same release as the
wheel, so it protects against a corrupt or truncated download and against a
tampered asset, not against a compromised GitHub account. If you need more than
that, install from a source archive you verify yourself (option 3).

---

## 2. Termux (native, no Ubuntu, no proot, no sudo)

Silica runs natively in Termux. Do **not** use `proot-distro` and do not expect
`sudo` to work — Termux is not a Linux distribution with root.

```bash
pkg update
pkg install python git curl
```

Then either install from a release:

```bash
curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/install.sh | sh
```

…which detects Termux and puts the launcher in `$PREFIX/bin`, or install from a
clone:

```bash
git clone https://github.com/sufiyan-sabeel/silica.git
cd silica
python -m pip install --user .
```

`pip install --user .` puts the `silica` script in Termux's user base, which is
`$PREFIX/bin` on most installs. Check where it landed with:

```bash
python -c "import site; print(site.USER_BASE)"
ls "$(python -c 'import site; print(site.USER_BASE)')/bin"
```

If `silica` is still not found, add that `bin` directory to `PATH` in
`~/.bashrc`.

### Honest status of Termux support

The installer's Termux branch is covered by automated tests that set the
environment variables Termux sets (`TERMUX_VERSION`, `PREFIX`) and assert the
launcher lands in `$PREFIX/bin`. **It has not been run on a real Android device
as part of this work** — no Termux environment was available. The pieces it
relies on (`python`, `venv`, `pip`, `sha256sum`) are all provided by
`pkg install python`, and Silica has no compiled extensions, so there is nothing
architecture-specific to build. Treat that as a strong expectation, not a
verified claim, and report anything that fails.

Silica is **not** available through `pkg`. There is no Termux package recipe yet;
`docs/ROADMAP.md` records that as unstarted work.

---

## 3. From source, without the installer

Most auditable, and the right choice if you want to read exactly what you run.

```bash
git clone https://github.com/sufiyan-sabeel/silica.git
cd silica

python3 -m venv .venv
. .venv/bin/activate
pip install .

silica --version
silica examples/hello.sc
```

Or run it straight from the checkout with no install at all:

```bash
python3 -m silica examples/hello.sc
sh bin/silica examples/hello.sc
```

### Installing the built artifacts

```bash
python3 -m build                       # writes dist/*.whl and dist/*.tar.gz
pip install dist/silica_lang-0.3.0-py3-none-any.whl
```

---

## 4. System-wide installation

Only if you want `silica` available to every user. This is the one path that uses
root:

```bash
curl -fsSL https://raw.githubusercontent.com/sufiyan-sabeel/silica/main/install.sh \
  | sudo SILICA_SYSTEM=1 sh
```

It installs to `/opt/silica` and links `/usr/local/bin/silica`. Uninstall with the
same variables:

```bash
sudo SILICA_SYSTEM=1 SILICA_HOME=/opt/silica SILICA_BIN=/usr/local/bin \
  sh uninstall.sh
```

The default, non-root installation is safer and is what the documentation assumes.

---

## Verifying an installation

```bash
silica --version                 # silica 0.3.0
silica                           # the interpreter; Ctrl+D to leave
silica examples/hello.sc         # Hello from Silica
silica run examples/hello.sc     # same thing, explicit form
```

`silica hello.sc` and `silica run hello.sc` are the same code path; use whichever
you prefer.

---

## Supported platforms

| Platform | Status |
|---|---|
| Debian / Ubuntu (x86_64, aarch64) | Tested in CI and by hand |
| Other Linux with Python 3.9+ | Expected to work; the installer only checks `uname` and Python |
| Termux (Android, aarch64) | Termux code path tested; **not run on a device** |
| macOS | Not supported by `install.sh` (it exits early). `pip install .` should work |
| Windows | Not supported. No installer, no testing |

Python 3.9 through 3.13 are tested in CI.

---

## Troubleshooting

**`silica: command not found`** — the launcher's directory is not on `PATH`. The
installer prints the line to add; see above.

**`error: Python 3.9+ not found`** — install Python, and on Debian/Ubuntu also
`python3-venv`:

```bash
sudo apt install python3 python3-venv
```

**`error: the Python venv module is missing`** — `sudo apt install python3-venv`
on Debian/Ubuntu, `pkg install python` on Termux.

**`error: checksum mismatch`** — the download was corrupted or altered. Re-run.
If it persists, do not install; verify the release yourself with
`docs/RELEASING.md`.

**`error: cannot download the checksum file for vX`** — that version is not a
published release. Check the releases page.

**`$HOME/.local/bin/silica already exists and was not created by this installer`**
— something else owns that path. Move it aside, or install somewhere else with
`SILICA_BIN=/some/other/bin`.

**The interpreter prints `> ` instead of `¢`** — your terminal's encoding is not
UTF-8, so the installer's prompt fell back. Set `LANG=C.UTF-8` or
`LC_ALL=C.UTF-8`.
