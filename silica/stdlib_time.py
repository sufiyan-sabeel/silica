"""The `time` module: clock reads, sleeping and ISO-8601 formatting.

No capability. Reading a clock touches no file, no network and no other process,
and `time.sleep` only stops the calling program — the capability model exists to
gate access to the machine's resources, and there is nothing here to gate.

Two clocks, and they mean different things:

* `time.now` / `time.now_ms` — **wall clock**, Unix epoch, UTC. It can jump
  backwards (NTP, a manual change), so it is for timestamps, not for measuring.
* `time.monotonic` — a **monotonic** clock with an arbitrary origin. Use it for
  elapsed time: `let start = time.monotonic()` … `time.monotonic() - start`.

`time.iso` formats a wall-clock value as ISO-8601 UTC (`2026-11-01T10:00:00Z`).
There is no `strftime` on purpose: a format string is a formatting language of its
own, and one fixed, unambiguous output is more useful than a partial one.
"""

import datetime
import time as _time

from .natives import _fail, i64


def _type_of(value):
    from .natives import type_name
    return type_name(value)


def _need_int(what, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("%s expects an Int, found %s" % (what, _type_of(value)))
    return value


def _need_seconds(what, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("%s expects a number of seconds, found %s" % (what, _type_of(value)))
    seconds = float(value)
    if seconds != seconds:                       # NaN
        _fail("%s refuses NaN" % what)
    if seconds < 0:
        _fail("%s expects a non-negative number of seconds" % what)
    if seconds > 86400:
        _fail("%s refuses to sleep longer than 86400 seconds (one day)" % what,
              hint="a longer pause is a scheduling decision, not a language one")
    return seconds


def _n_now(ctx, args):
    return i64(int(_time.time()))


def _n_now_ms(ctx, args):
    return i64(int(_time.time() * 1000))


def _n_monotonic(ctx, args):
    return float(_time.monotonic())


def _n_sleep(ctx, args):
    _time.sleep(_need_seconds("time.sleep", args[0]))
    return None


def _n_iso(ctx, args):
    epoch = _need_int("time.iso", args[0])
    try:
        moment = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        _fail("time.iso cannot represent %d as a date" % epoch,
              hint="the value must be seconds since 1970 in a range the host "
                   "calendar can represent")
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _n_parse_iso(ctx, args):
    text = args[0]
    if not isinstance(text, str):
        _fail("time.parse_iso expects a String, found %s" % _type_of(text))
    candidate = text.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        moment = datetime.datetime.fromisoformat(candidate)
    except ValueError:
        _fail("time.parse_iso cannot read %r" % text,
              hint="expected ISO-8601, e.g. 2026-11-01T10:00:00Z")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return i64(int(moment.timestamp()))


def _n_year(ctx, args):
    return _part(args, "time.year", "%Y")


def _n_month(ctx, args):
    return _part(args, "time.month", "%m")


def _n_day(ctx, args):
    return _part(args, "time.day", "%d")


def _part(args, what, pattern):
    epoch = _need_int(what, args[0])
    try:
        moment = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        _fail("%s cannot represent %d as a date" % (what, epoch))
    return int(moment.strftime(pattern))


# (name, params, ret, implementation, requires, path_arg, min_args)
FUNCTIONS = (
    ("now", [], "Int", _n_now, None, None, 0),
    ("now_ms", [], "Int", _n_now_ms, None, None, 0),
    ("monotonic", [], "Float", _n_monotonic, None, None, 0),
    ("sleep", ["Float"], "Unit", _n_sleep, None, None, 1),
    ("iso", ["Int"], "String", _n_iso, None, None, 1),
    ("parse_iso", ["String"], "Int", _n_parse_iso, None, None, 1),
    ("year", ["Int"], "Int", _n_year, None, None, 1),
    ("month", ["Int"], "Int", _n_month, None, None, 1),
    ("day", ["Int"], "Int", _n_day, None, None, 1),
)
