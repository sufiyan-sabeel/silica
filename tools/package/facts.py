"""Collect packaging facts for the Silica verifier.

This is the *only* Python in the packaging check, and it is deliberately dumb: it
builds (optionally), lists archive members, hashes files and writes JSON. It makes
no decisions about whether a package is correct — `tools/package/verify.sc` does
that, in Silica.

Why the split: Silica has no zip reader, no tar reader and no SHA-256 (its `crypto`
module is still planned), and it cannot start a process. Those four operations are
the entire reason this file exists. Everything downstream of them — metadata
consistency, manifest policy, checksum verification, release gating — is Silica
source in `verify.sc`.

What this does NOT do: no network access, no arbitrary command execution, no
downloading, no publishing, no credentials. It runs a fixed `python -m build` when
asked, and otherwise only reads files.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile

#: Modules the wheel must contain for Silica to actually work after install.
REQUIRED_WHEEL = [
    "silica/cli.py",
    "silica/vm.py",
    "silica/checker.py",
    "silica/compiler.py",
    "silica/parser.py",
    "silica/bytecode.py",
    "silica/natives.py",
    "silica/capabilities.py",
    "silica/interop/worker_main.py",
    "silica/interop/providers/python_worker.py",
    "silica/stdlib_path.py",
    "silica/stdlib_time.py",
    "silica/stdlib_random.py",
    "silica/ide/app.html",
]

#: Source-only trees that must not leak into the wheel.
FORBIDDEN_WHEEL_PREFIXES = ["tests/", "examples/", "docs/", "benchmarks/",
                            "editors/", "packaging/"]

#: Things a source distribution must carry, because it is the source.
REQUIRED_SDIST_SUFFIXES = [
    "examples/stdlib_tour.sc",
    "examples/data/sales.csv",
    "docs/APPLICATIONS.md",
    "docs/SECURITY_MODEL.md",
    "tests/test_interop.py",
    "install.sh",
    "uninstall.sh",
    "MANIFEST.in",
]


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wheel_members(path):
    with zipfile.ZipFile(path) as archive:
        return sorted(archive.namelist())


def sdist_members(path):
    with tarfile.open(path) as archive:
        return sorted(m.name.split("/", 1)[-1] for m in archive.getmembers()
                      if m.isfile())


def read_sums(directory):
    """`SHA256SUMS.txt` as {filename: digest}, or {} when there is none."""
    path = os.path.join(directory, "SHA256SUMS.txt")
    if not os.path.exists(path):
        return {}
    sums = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) == 2:
                sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def tracked_files(repo):
    """Files git tracks, or None when there is no repository (an unpacked sdist).

    The sdist is built from the *working tree*, so an untracked scratch file that
    matches a MANIFEST.in pattern lands in it. Comparing against `git ls-files` is
    how that is caught.
    """
    try:
        out = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                             text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return sorted(line for line in out.stdout.splitlines() if line)


def pick(directory, suffix):
    names = sorted(n for n in os.listdir(directory) if n.endswith(suffix))
    return os.path.join(directory, names[-1]) if names else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", default="dist")
    parser.add_argument("--out", default=os.path.join("build", "packaging",
                                                      "facts.json"))
    parser.add_argument("--build", action="store_true",
                        help="run `python -m build` first (fixed command, no shell)")
    parser.add_argument("--repo", default=".", help="repository root")
    parser.add_argument("--version", default=None,
                        help="the version this release is meant to be; "
                             "defaults to the one in pyproject.toml")
    args = parser.parse_args(argv)

    if args.build:
        subprocess.run([sys.executable, "-m", "build"], cwd=args.repo, check=True)

    dist = os.path.join(args.repo, args.dist_dir)
    wheel = pick(dist, ".whl")
    sdist = pick(dist, ".tar.gz")
    if not wheel or not sdist:
        print("no wheel/sdist found in %s" % dist, file=sys.stderr)
        return 2

    version = args.version
    source = "--version"
    if version is None:
        with open(os.path.join(args.repo, "pyproject.toml"), encoding="utf-8") as fh:
            for line in fh:
                if line.strip().startswith("version ="):
                    version = line.split("=", 1)[1].strip().strip('"')
                    break
        source = "pyproject.toml"

    facts = {
        "distribution": "silica-lang",
        "version": version,
        "version_source": source,
        "entry_point": "silica",
        "wheel": {
            "name": os.path.basename(wheel),
            "sha256": sha256_of(wheel),
            "files": wheel_members(wheel),
        },
        "sdist": {
            "name": os.path.basename(sdist),
            "sha256": sha256_of(sdist),
            "files": sdist_members(sdist),
        },
        "sums": read_sums(dist),
        "tracked": tracked_files(args.repo),
        "required_wheel": REQUIRED_WHEEL,
        "forbidden_wheel_prefixes": FORBIDDEN_WHEEL_PREFIXES,
        "required_sdist_suffixes": REQUIRED_SDIST_SUFFIXES,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(facts, handle, indent=2, sort_keys=True)
    print("facts written to %s (%d wheel files, %d sdist files)"
          % (args.out, len(facts["wheel"]["files"]), len(facts["sdist"]["files"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
