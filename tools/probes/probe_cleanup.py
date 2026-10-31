"""Parent harness: run each cleanup probe inside a real pty and report.

For every scenario it captures:
  * the probe's own markers (stderr),
  * how many times the terminal entered (smcup) and left (rmcup) the alternate
    screen — entering without leaving is direct evidence of a leaked terminal,
  * whether the tty's termios still has ECHO and ICANON set (sane) afterwards,
  * the child's exit status.

Every scenario is killed after a hard timeout so a hang can never hide results.
"""

import os
import pty
import re
import select
import subprocess
import sys
import termios
import time

# Resolve the Silica checkout: an explicit SILICA_ROOT wins, otherwise this file
# is assumed to live in <repo>/tools/probes/.
SILICA_ROOT = os.environ.get("SILICA_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "probe_cleanup_child.py")
SCENARIOS = ["normal_exit", "double_close", "exception_inside_run",
             "exception_outside_run", "two_apps", "partial_init",
             "cleanup_raises"]
HARD_TIMEOUT = 20

ENTER_ALT = re.compile(rb"\x1b\[\?1049h")
LEAVE_ALT = re.compile(rb"\x1b\[\?1049l")
SHOW_CURSOR = re.compile(rb"\x1b\[\?25h")


def drain(fd, first=1.5, quiet=0.3):
    chunks = []
    timeout = first
    while True:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            break
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
        timeout = quiet
    return b"".join(chunks)


def run_scenario(name):
    master, slave = pty.openpty()
    env = dict(os.environ)
    env.update({"TERM": "xterm-256color", "LINES": "24", "COLUMNS": "80",
                "PYTHONPATH": SILICA_ROOT})
    proc = subprocess.Popen([sys.executable, "-u", CHILD, name], stdin=slave,
                            stdout=slave, stderr=subprocess.PIPE, env=env,
                            close_fds=True)
    os.close(slave)
    started = time.time()
    tty_output = drain(master)
    timed_out = False
    while proc.poll() is None:
        if time.time() - started > HARD_TIMEOUT:
            proc.kill()
            timed_out = True
            break
        tty_output += drain(master, 0.2, 0.1)
        time.sleep(0.05)
    stderr = proc.stderr.read().decode("utf-8", "replace")
    proc.wait(timeout=10)
    try:
        attrs = termios.tcgetattr(master)
        lflag = attrs[3]
        sane = bool(lflag & termios.ICANON) and bool(lflag & termios.ECHO)
    except Exception:
        sane = None
    os.close(master)

    markers = [line[6:] for line in stderr.splitlines() if line.startswith("PROBE ")]
    return {
        "scenario": name,
        "exit": proc.returncode,
        "timed_out": timed_out,
        "entered_alt": len(ENTER_ALT.findall(tty_output)),
        "left_alt": len(LEAVE_ALT.findall(tty_output)),
        "cursor_shown": bool(SHOW_CURSOR.search(tty_output)),
        "tty_sane": sane,
        "markers": markers,
    }


def main():
    for name in SCENARIOS:
        r = run_scenario(name)
        leaked = r["entered_alt"] > r["left_alt"]
        print("=" * 78, flush=True)
        print("SCENARIO %s  exit=%s%s  alt_screen enter/leave=%d/%d  LEAKED=%s  "
              "tty_sane=%s  cursor_restored=%s"
              % (r["scenario"], r["exit"], " TIMEOUT" if r["timed_out"] else "",
                 r["entered_alt"], r["left_alt"], leaked, r["tty_sane"],
                 r["cursor_shown"]), flush=True)
        for m in r["markers"]:
            print("   |", m, flush=True)
    print("=" * 78, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
