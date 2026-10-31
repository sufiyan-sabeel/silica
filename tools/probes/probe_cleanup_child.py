"""Child-process probes for Silica TUI terminal cleanup.

Run by probe_tui.py inside a real pty. Each scenario prints machine-readable
markers to stderr (a pipe, not the tty) so the parent can assert on behaviour
rather than on rendered screen contents.

Note: in this codebase `tui.render()` only paints when a screen is already
open; `tui.poll()` is what initialises curses. Probes therefore open with
`tui.poll(app, timeout=0)` so nothing blocks waiting for a keypress.

    python probe_tui_child.py <scenario>
"""

import os
import sys
import traceback

# Resolve the Silica checkout: an explicit SILICA_ROOT wins, otherwise this file
# is assumed to live in <repo>/tools/probes/.
SILICA_ROOT = os.environ.get("SILICA_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SILICA_ROOT)

from silica import tui


def say(*parts):
    sys.stderr.write("PROBE " + " ".join(str(p) for p in parts) + "\n")
    sys.stderr.flush()


def build_app(title="probe"):
    app = tui.App(title)
    app.add(tui.Node("text", "hello"))
    app.add(tui.Node("button", "Save"))
    return app


def open_app(app):
    """Initialise the terminal without blocking for input."""
    tui.poll(app, timeout=0)
    return app


def report_state(app, label):
    say(label, "closed=%s" % app.closed,
        "screen_open=%s" % (app._screen is not None),
        "in_open_list=%s" % (app in tui._OPEN_APPS),
        "open_apps=%d" % len(tui._OPEN_APPS),
        "colour_mode=%s" % getattr(app, "_colour_mode", "?"))


def scenario_normal_exit():
    app = build_app()
    open_app(app)
    report_state(app, "after_open")
    tui.close(app)
    report_state(app, "after_close")
    say("done")


def scenario_double_close():
    app = build_app()
    open_app(app)
    tui.close(app)
    try:
        tui.close(app)
        tui.close(app)
        say("repeated_close", "no_exception")
    except Exception as exc:
        say("repeated_close", "raised", type(exc).__name__, str(exc)[:100])
    report_state(app, "after_repeats")
    say("done")


def scenario_exception_inside_run():
    app = build_app()
    original_poll = tui.poll
    calls = {"n": 0}

    def poll_opens_then_fails(a, timeout=None):
        # first call: open the terminal for real; second: raise from the loop
        calls["n"] += 1
        if calls["n"] == 1:
            return original_poll(a, timeout=0)
        raise ValueError("original failure")

    tui.poll = poll_opens_then_fails
    try:
        tui.run(app, "q")
    except Exception as exc:
        say("caught", type(exc).__name__, str(exc)[:100])
    finally:
        tui.poll = original_poll
    report_state(app, "after_run_exception")
    say("done")


def scenario_exception_outside_run():
    app = build_app()
    open_app(app)
    report_state(app, "before_raise")
    raise RuntimeError("escaped without run()")


def scenario_two_apps():
    first = build_app("first")
    second = build_app("second")
    open_app(first)
    report_state(first, "first_open")
    try:
        open_app(second)
        report_state(second, "second_open")
        say("second_open", "ok")
    except Exception as exc:
        say("second_open", "raised", type(exc).__name__, str(exc)[:120])
    try:
        tui.close(first)
        report_state(first, "first_closed")
        open_app(second)
        report_state(second, "second_after_first_close")
        say("second_after_first_close", "ok")
    except Exception as exc:
        say("second_after_first_close", "raised", type(exc).__name__, str(exc)[:120])
    for app in list(tui._OPEN_APPS):
        try:
            tui.close(app)
        except Exception as exc:
            say("final_close_raised", type(exc).__name__, str(exc)[:100])
    say("done")


def scenario_partial_init():
    # initscr() succeeds, then a later init step fails.
    curses = tui._curses()
    original = curses.noecho

    def failing_noecho():
        raise RuntimeError("simulated failure after initscr")

    curses.noecho = failing_noecho
    app = build_app()
    try:
        open_app(app)
        say("init_failed", "no_exception_raised")
    except Exception as exc:
        say("init_failed", type(exc).__name__, str(exc)[:140])
    finally:
        curses.noecho = original
    report_state(app, "after_partial_init")
    say("done")


def scenario_cleanup_raises():
    # Does a failure during teardown mask the original exception?
    curses = tui._curses()
    app = build_app()
    open_app(app)
    original_endwin = curses.endwin

    def failing_endwin():
        raise RuntimeError("endwin failed")

    curses.endwin = failing_endwin
    try:
        try:
            raise ValueError("original failure")
        finally:
            tui._close(app)
    except Exception as exc:
        say("escaped", type(exc).__name__, str(exc)[:120])
    finally:
        curses.endwin = original_endwin
    app._screen = None
    if app in tui._OPEN_APPS:
        tui._OPEN_APPS.remove(app)
    say("done")


SCENARIOS = {
    "normal_exit": scenario_normal_exit,
    "double_close": scenario_double_close,
    "exception_inside_run": scenario_exception_inside_run,
    "exception_outside_run": scenario_exception_outside_run,
    "two_apps": scenario_two_apps,
    "partial_init": scenario_partial_init,
    "cleanup_raises": scenario_cleanup_raises,
}


def main():
    name = sys.argv[1]
    try:
        SCENARIOS[name]()
    except BaseException as exc:      # noqa: BLE001 - probes report, never hide
        say("uncaught", type(exc).__name__, str(exc)[:160])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
