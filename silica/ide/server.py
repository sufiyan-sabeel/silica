"""Silica Script Mode IDE: a local web application around the real toolchain.

Why a local web app
-------------------
The repository has no desktop toolkit that works everywhere: tkinter needs a
display server (absent on Termux and on a phone), and a native mobile IDE would
mean three codebases. A browser is the one UI surface that exists on every target
the brief lists — Linux, Ubuntu, Alpine, Windows, macOS, Termux, Android, iOS —
so the editor is HTML and the process execution stays in Python.

The two halves are deliberately separate, because they have different reach:

* **the editor** — any browser, including iOS Safari.
* **the runner** — a Python process on the machine holding the files. On iOS no
  such process can exist, so the IDE can point at a runner on another machine
  instead; that is explicit and token-authenticated, never open.

Nothing here is simulated. `Run` starts `python -m silica run <file>` as a real
subprocess, and what comes back is that process's own stdout, stderr and exit
code.

Security
--------
* binds to 127.0.0.1 by default; exposing it needs an explicit `--host`
* every request needs a random per-session token
* every path is resolved and confined to the workspace root
* no shell: argument arrays only, so a filename cannot become a command
* opening a file never runs it
"""

import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
APP_HTML = os.path.join(HERE, "app.html")

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
RUN_TIMEOUT = 120.0


class IDEError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


class Workspace:
    """Files under one root, and nothing outside it."""

    def __init__(self, root):
        self.root = os.path.realpath(root)
        if not os.path.isdir(self.root):
            raise IDEError("workspace is not a directory: %s" % root)

    def resolve(self, relative):
        """Turn a client-supplied path into an absolute one inside the root."""
        if not isinstance(relative, str) or not relative:
            raise IDEError("a path is required")
        if "\x00" in relative:
            raise IDEError("invalid path")
        candidate = os.path.realpath(os.path.join(self.root, relative))
        root = self.root
        if candidate != root and not candidate.startswith(root + os.sep):
            raise IDEError("path escapes the workspace: %s" % relative, 403)
        return candidate

    def relative(self, absolute):
        return os.path.relpath(absolute, self.root)

    def list_scripts(self, limit=500):
        found = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames
                                 if not d.startswith(".") and d != "__pycache__")
            for name in sorted(filenames):
                if not name.endswith(".sc"):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                found.append({"path": self.relative(full), "size": stat.st_size,
                              "mtime": int(stat.st_mtime)})
                if len(found) >= limit:
                    return found
        return found

    def read(self, relative):
        path = self.resolve(relative)
        if not os.path.isfile(path):
            raise IDEError("no such file: %s" % relative, 404)
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise IDEError("file is too large for the editor", 413)
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read()
        except UnicodeDecodeError:
            raise IDEError("file is not valid UTF-8", 415)

    def write(self, relative, text):
        if not isinstance(text, str):
            raise IDEError("text must be a string")
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise IDEError("file is too large for the editor", 413)
        path = self.resolve(relative)
        if not path.endswith(".sc"):
            raise IDEError("only .sc files can be written", 400)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return {"path": self.relative(path), "size": len(text.encode("utf-8"))}


class Run:
    """One execution of one script, through the real CLI."""

    def __init__(self, run_id, path, relative):
        self.id = run_id
        self.path = path
        self.relative = relative
        self.process = None
        self.stdout = ""
        self.stderr = ""
        self.exit_code = None
        self.status = "starting"
        self.started = time.time()
        self.finished = None
        self.stopped = False
        self._lock = threading.Lock()

    def snapshot(self):
        with self._lock:
            return {
                "id": self.id,
                "path": self.relative,
                "status": self.status,
                "stdout": self.stdout,
                "stderr": self.stderr,
                "exit_code": self.exit_code,
                "seconds": round((self.finished or time.time()) - self.started, 3),
                "stopped": self.stopped,
            }

    def append(self, stream, text):
        with self._lock:
            if stream == "out":
                self.stdout = (self.stdout + text)[-MAX_OUTPUT_BYTES:]
            else:
                self.stderr = (self.stderr + text)[-MAX_OUTPUT_BYTES:]


class Runner:
    """Starts and tracks script runs. Argument arrays only; never a shell."""

    def __init__(self, workspace):
        self.workspace = workspace
        self.runs = {}
        self._lock = threading.Lock()
        self._counter = 0

    def start(self, relative):
        path = self.workspace.resolve(relative)
        if not os.path.isfile(path):
            raise IDEError("no such file: %s" % relative, 404)
        with self._lock:
            self._counter += 1
            run_id = str(self._counter)
        run = Run(run_id, path, self.workspace.relative(path))
        self.runs[run_id] = run
        threading.Thread(target=self._execute, args=(run,), daemon=True).start()
        return run.snapshot()

    def _toolchain_env(self):
        """Make `python -m silica` work whether installed or run from a checkout.

        From a checkout the package is not on sys.path, so the run would fail with
        "No module named silica" — which looks like a broken IDE rather than a
        path problem. The package's parent directory is prepended; when installed
        that path is already on sys.path and the addition is harmless.
        """
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        package_parent = os.path.dirname(os.path.dirname(HERE))
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (package_parent if not existing
                             else package_parent + os.pathsep + existing)
        return env

    def _execute(self, run):
        command = [sys.executable, "-m", "silica", "run", run.path]
        try:
            run.process = subprocess.Popen(
                command,
                cwd=self.workspace.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self._toolchain_env(),
            )
        except OSError as exc:
            with run._lock:
                run.status = "failed"
                run.stderr = "cannot start the Silica toolchain: %s" % exc
                run.exit_code = -1
                run.finished = time.time()
            return

        run.status = "running"
        readers = [
            threading.Thread(target=self._pump, args=(run, run.process.stdout, "out"),
                             daemon=True),
            threading.Thread(target=self._pump, args=(run, run.process.stderr, "err"),
                             daemon=True),
        ]
        for reader in readers:
            reader.start()

        deadline = time.time() + RUN_TIMEOUT
        while run.process.poll() is None:
            if time.time() > deadline:
                run.stopped = True
                run.process.kill()
                break
            time.sleep(0.02)

        for reader in readers:
            reader.join(timeout=5)

        with run._lock:
            run.exit_code = run.process.returncode
            run.status = "stopped" if run.stopped else "finished"
            run.finished = time.time()

    def _pump(self, run, stream, which):
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                run.append(which, line)
        except (ValueError, OSError):
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def stop(self, run_id):
        run = self.runs.get(run_id)
        if run is None:
            raise IDEError("no such run: %s" % run_id, 404)
        if run.process is not None and run.process.poll() is None:
            run.stopped = True
            run.process.terminate()
            try:
                run.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                run.process.kill()
                run.process.wait(timeout=3)
        # Record the outcome here rather than waiting for the executor thread to
        # notice: otherwise stop() can return "running" after it has already
        # killed the process, which is a race the caller would see.
        with run._lock:
            if run.status not in ("finished", "failed"):
                run.status = "stopped"
            if run.exit_code is None:
                run.exit_code = run.process.returncode if run.process else -1
            run.finished = run.finished or time.time()
        return run.snapshot()

    def get(self, run_id):
        run = self.runs.get(run_id)
        if run is None:
            raise IDEError("no such run: %s" % run_id, 404)
        return run.snapshot()


def metadata(workspace):
    """Facts the editor needs, taken from the implementation, not guessed."""
    from .. import __version__
    from ..natives import MODULES, PLANNED_MODULES
    from ..tokens import BUILTIN_TYPES, KEYWORDS
    return {
        "version": __version__,
        "keywords": sorted(KEYWORDS),
        "types": sorted(BUILTIN_TYPES),
        "modules": sorted(MODULES),
        "planned_modules": sorted(PLANNED_MODULES),
        "workspace": workspace.root,
        "platform": sys.platform,
        "python": sys.version.split()[0],
    }


def _diagnostic_pattern():
    # "file.sc:12:4: parse error: ..." and "file.sc:12: runtime error: ..."
    return re.compile(r"^(?P<path>[^\s:]+\.sc):(?P<line>\d+)(?::(?P<col>\d+))?:\s*"
                      r"(?P<kind>[a-z ]*error):\s*(?P<message>.*)$")


def parse_diagnostics(stderr):
    """Turn compiler/runtime stderr into structured diagnostics."""
    pattern = _diagnostic_pattern()
    found = []
    for line in stderr.splitlines():
        match = pattern.match(line.strip())
        if match:
            found.append({
                "path": match.group("path"),
                "line": int(match.group("line")),
                "col": int(match.group("col") or 0),
                "kind": match.group("kind").strip(),
                "message": match.group("message"),
            })
    return found


class Handler(BaseHTTPRequestHandler):
    server_version = "SilicaIDE/1.0"
    workspace = None
    runner = None
    token = None
    quiet = True

    # -- plumbing -------------------------------------------------------------
    def log_message(self, fmt, *args):
        if not self.quiet:
            BaseHTTPRequestHandler.log_message(self, fmt, *args)

    def _authorised(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        supplied = (query.get("token") or [None])[0] or self.headers.get("X-Silica-Token")
        return bool(self.token) and secrets.compare_digest(str(supplied), str(self.token))

    def _send(self, status, body, content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_FILE_BYTES + 1024:
            raise IDEError("request body is too large", 413)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise IDEError("request body is not valid JSON")

    # -- routes ---------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            if not self._authorised():
                return self._send(401, {"error": "missing or wrong token"})
            with open(APP_HTML, encoding="utf-8") as handle:
                page = handle.read()
            page = page.replace("__SILICA_TOKEN__", self.token)
            return self._send(200, page, "text/html; charset=utf-8")
        if not self._authorised():
            return self._send(401, {"error": "missing or wrong token"})
        try:
            query = urllib.parse.parse_qs(parsed.query)
            if path == "/api/meta":
                return self._send(200, metadata(self.workspace))
            if path == "/api/files":
                return self._send(200, {"files": self.workspace.list_scripts()})
            if path == "/api/file":
                relative = (query.get("path") or [""])[0]
                return self._send(200, {"path": relative,
                                        "text": self.workspace.read(relative)})
            if path == "/api/run":
                run_id = (query.get("id") or [""])[0]
                snapshot = self.runner.get(run_id)
                snapshot["diagnostics"] = parse_diagnostics(snapshot["stderr"])
                return self._send(200, snapshot)
            return self._send(404, {"error": "no such endpoint"})
        except IDEError as exc:
            return self._send(exc.status, {"error": exc.message})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if not self._authorised():
            return self._send(401, {"error": "missing or wrong token"})
        try:
            body = self._body()
            if parsed.path == "/api/file":
                result = self.workspace.write(body.get("path"), body.get("text", ""))
                return self._send(200, result)
            if parsed.path == "/api/run":
                return self._send(200, self.runner.start(body.get("path")))
            if parsed.path == "/api/stop":
                return self._send(200, self.runner.stop(body.get("id")))
            return self._send(404, {"error": "no such endpoint"})
        except IDEError as exc:
            return self._send(exc.status, {"error": exc.message})

    def do_PUT(self):
        return self.do_POST()


def serve(root, port=0, host="127.0.0.1", open_browser=True, quiet=True):
    """Start the IDE. Returns (server, url). Caller decides when to stop it."""
    workspace = Workspace(root)
    if not os.path.exists(APP_HTML):
        raise IDEError("the IDE assets are missing: %s" % APP_HTML)

    handler = type("BoundHandler", (Handler,), {
        "workspace": workspace,
        "runner": Runner(workspace),
        "token": secrets.token_urlsafe(24),
        "quiet": quiet,
    })
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    actual_port = httpd.server_address[1]
    url = "http://%s:%d/?token=%s" % (
        "127.0.0.1" if host in ("0.0.0.0", "") else host, actual_port,
        handler.token)
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # pragma: no cover - headless machines
            pass
    return httpd, url
