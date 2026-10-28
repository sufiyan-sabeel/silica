"""Silica Script Mode IDE: a local web application over the real toolchain.

`silica ide` serves an editor and a runner bound to 127.0.0.1. The editor is HTML
so it runs in any browser, including on a phone; the runner is Python, so `Run`
executes the actual `silica run` command and reports its real output and exit
code. See `docs/IDE.md`.
"""

from .server import IDEError, Workspace, parse_diagnostics, serve

__all__ = ["IDEError", "Workspace", "parse_diagnostics", "serve"]
