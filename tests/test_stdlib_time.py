"""The `time` module: two clocks with different guarantees, and one date format."""

import time as _time
import unittest

from .helpers import run


def program(body):
    return "use time\n\nsfn main() {\n" + body + "\n}\n"


def out(body):
    code, text = run(program(body))
    return text


class ClockTests(unittest.TestCase):
    def test_now_is_a_plausible_epoch(self):
        value = int(out("sprint(time.now())").strip())
        self.assertGreater(value, 1600000000)        # after 2020
        self.assertLess(value, 4102444800)           # before 2100

    def test_now_ms_is_a_thousandfold_now(self):
        seconds = int(out("sprint(time.now())").strip())
        millis = int(out("sprint(time.now_ms())").strip())
        self.assertGreater(millis, seconds * 1000 - 2000)
        self.assertLess(millis, (seconds + 2) * 1000 + 2000)

    def test_monotonic_does_not_go_backwards(self):
        self.assertEqual(out("let a: Float = time.monotonic()\n"
                             "let b: Float = time.monotonic()\n"
                             "sprint(b >= a)"), "oui\n")

    def test_monotonic_measures_elapsed_time(self):
        start = _time.monotonic()
        out("time.sleep(0.05)")
        elapsed = _time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.04)
        self.assertLess(elapsed, 2.0)


class FormatTests(unittest.TestCase):
    def test_the_epoch_formats_as_utc(self):
        self.assertEqual(out("sprint(time.iso(0))"), "1970-01-01T00:00:00Z\n")

    def test_a_known_instant(self):
        self.assertEqual(out("sprint(time.iso(1000000000))"),
                         "2001-09-09T01:46:40Z\n")

    def test_parse_iso_round_trips(self):
        self.assertEqual(out('sprint(time.parse_iso("1970-01-01T00:00:10Z"))'), "10\n")
        self.assertEqual(out('sprint(time.parse_iso("1970-01-01T00:00:00+00:00"))'),
                         "0\n")

    def test_date_parts_are_utc(self):
        self.assertEqual(out("sprint(time.year(0))"), "1970\n")
        self.assertEqual(out("sprint(time.month(0))"), "1\n")
        self.assertEqual(out("sprint(time.day(0))"), "1\n")


class SafetyTests(unittest.TestCase):
    def test_a_negative_sleep_is_refused(self):
        with self.assertRaises(Exception) as ctx:
            run(program("time.sleep(-1.0)"))
        self.assertIn("non-negative", str(ctx.exception))

    def test_an_absurd_sleep_is_refused(self):
        with self.assertRaises(Exception) as ctx:
            run(program("time.sleep(100000.0)"))
        self.assertIn("86400", str(ctx.exception))

    def test_a_bad_iso_string_is_refused(self):
        with self.assertRaises(Exception) as ctx:
            run(program('sprint(time.parse_iso("not a date"))'))
        self.assertIn("cannot read", str(ctx.exception))
        self.assertIn("ISO-8601", ctx.exception.hint or "")

    def test_a_non_integer_epoch_is_refused(self):
        with self.assertRaises(Exception) as ctx:
            run(program('sprint(time.iso("yesterday"))'))
        self.assertIn("must be Int", str(ctx.exception))

    def test_the_module_requires_no_capability(self):
        from silica.natives import MODULES
        for name, native in MODULES["time"].items():
            self.assertIsNone(native.requires, name)
