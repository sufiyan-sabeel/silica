"""Phase 1: voice licensing and the `voice.*` namespace.

Two claims are tested here, and both are the kind that rot silently if untested:

1. **Every voice carries a licence**, and the ones that are non-commercial or
   unverified are marked as such. Two voices this project offered turned out to
   be CC-BY-NC-SA — usable for personal work, not for products — and nothing in
   the code said so.
2. **`voice.*` and `speech.*` are the same implementation.** Not two copies that
   could drift: the same `Native` objects, the same capability requirements, the
   same results.
"""

import io
import os
import unittest

from silica.capabilities import SPEECH_LISTEN, SPEECH_SPEAK, CapabilitySet
from silica.natives import MODULES
from silica.voice import catalogue


def run_source(source, capabilities=None, capture=True):
    from silica.engine import compile_source, run_chunk
    out = io.StringIO()
    try:
        chunk = compile_source(source, "<test>").chunk
        run_chunk(chunk, "<test>", stdin=io.StringIO(""), stdout=out,
                  stderr=io.StringIO(), capabilities=capabilities or CapabilitySet.empty())
    except Exception as exc:  # noqa: BLE001
        return exc
    return out.getvalue() if capture else None


class LicenceAuditTests(unittest.TestCase):
    def test_every_voice_has_a_licence_entry(self):
        for name in catalogue.VOICES:
            with self.subTest(voice=name):
                entry = catalogue.licence(name)
                self.assertIn("id", entry)
                self.assertTrue(entry["id"], "licence id must not be empty")
                self.assertIn("verified", entry)
                self.assertIsInstance(entry["verified"], bool)

    def test_no_voice_is_silently_unknown(self):
        """An unlisted voice must be reported as unknown, not given a default."""
        entry = catalogue.licence("does-not-exist")
        self.assertEqual(entry["id"], "unknown")
        self.assertFalse(entry["verified"])
        self.assertIsNone(entry["commercial"])

    def test_the_non_commercial_hindi_voices_are_flagged(self):
        for name in ("hi_IN-pratham-medium", "hi_IN-priyamvada-medium"):
            with self.subTest(voice=name):
                entry = catalogue.licence(name)
                self.assertEqual(entry["id"], "CC-BY-NC-SA-4.0")
                self.assertIs(entry["commercial"], False)
                self.assertTrue(entry["verified"])
                self.assertEqual(catalogue.licence_risk(name), "licence is non-commercial")

    def test_unverified_licences_are_marked(self):
        for name in ("en_US-lessac-medium", "en_US-amy-medium", "ml_IN-meera-medium",
                     "hi_IN-rohan-medium", "te_IN-maya-medium"):
            with self.subTest(voice=name):
                self.assertFalse(catalogue.licence(name)["verified"])
                self.assertEqual(catalogue.licence_risk(name), "licence not verified")

    def test_commercially_safe_lists_only_verified_permissive_voices(self):
        safe = catalogue.commercially_safe()
        self.assertEqual(safe, ["bn_BD-google-medium", "en_GB-alba-medium",
                                "mr_IN-google-medium", "te_IN-padmavathi-medium"])
        for name in safe:
            entry = catalogue.licence(name)
            self.assertTrue(entry["verified"])
            self.assertIs(entry["commercial"], True)

    def test_attribution_is_recorded_where_required(self):
        # every verified licence here requires attribution
        for name in catalogue.commercially_safe():
            with self.subTest(voice=name):
                self.assertTrue(catalogue.licence(name)["attribution"])

    def test_catalogue_rows_carry_the_licence(self):
        for row in catalogue.catalogue():
            with self.subTest(voice=row["name"]):
                self.assertIn("licence", row)
                self.assertIn("licence_url", row)
                self.assertIn("licence_verified", row)
                self.assertIn("commercial_use", row)
                self.assertIn("licence_risk", row)

    def test_licence_is_a_copy_not_a_shared_mutable(self):
        first = catalogue.licence("hi_IN-pratham-medium")
        first["id"] = "tampered"
        self.assertEqual(catalogue.licence("hi_IN-pratham-medium")["id"],
                         "CC-BY-NC-SA-4.0")


class NamespaceTests(unittest.TestCase):
    def test_both_namespaces_exist(self):
        self.assertIn("speech", MODULES)
        self.assertIn("voice", MODULES)

    def test_they_expose_the_same_functions(self):
        self.assertEqual(sorted(MODULES["speech"]), sorted(MODULES["voice"]))

    def test_they_are_the_same_objects_not_copies(self):
        for name, native in MODULES["speech"].items():
            with self.subTest(native=name):
                self.assertIs(MODULES["voice"][name], native,
                              "voice.%s should be the same Native as speech.%s"
                              % (name, name))

    def test_capability_requirements_match(self):
        for name, native in MODULES["speech"].items():
            with self.subTest(native=name):
                self.assertEqual(MODULES["voice"][name].requires, native.requires)

    def test_equivalence_through_both_namespaces(self):
        """The same call through either name must produce the same output."""
        cases = [
            ("status", "sprint(str(%s.status()[\"default_voice\"]))"),
            ("voices", "sprint(str(len(%s.voices())))"),
            ("languages", "sprint(str(len(%s.languages()[\"speaking\"])))"),
            ("licence", "sprint(%s.licence(\"en_GB-alba-medium\")[\"id\"])"),
        ]
        for label, template in cases:
            with self.subTest(call=label):
                via_speech = run_source("use speech\nsfn main() {\n    %s\n}\n"
                                        % (template % "speech"))
                via_voice = run_source("use voice\nsfn main() {\n    %s\n}\n"
                                       % (template % "voice"))
                self.assertNotIsInstance(via_speech, Exception, via_speech)
                self.assertEqual(via_speech, via_voice)

    def test_both_namespaces_refuse_without_the_capability(self):
        for module in ("speech", "voice"):
            with self.subTest(module=module):
                error = run_source(
                    'use %s\nsfn main() {\n    %s.save("hi", "/tmp/x.wav")\n}\n'
                    % (module, module))
                self.assertIn("speech.speak", str(error))

    def test_a_grant_works_for_both_namespaces(self):
        """The grant is on the capability, not on the namespace."""
        caps = CapabilitySet.empty().grant(SPEECH_SPEAK, ".")
        for module in ("speech", "voice"):
            with self.subTest(module=module):
                error = run_source(
                    'use %s\nsfn main() {\n    %s.save("hi", "/tmp/x.wav")\n}\n'
                    % (module, module), capabilities=caps)
                # it may fail because no engine is installed here, but it must
                # not fail with a capability error
                self.assertNotIn("capability", str(error).lower())

    def test_listen_requires_the_listen_capability_in_both(self):
        for module in ("speech", "voice"):
            with self.subTest(module=module):
                error = run_source(
                    'use %s\nsfn main() {\n    %s.transcribe("/tmp/x.wav")\n}\n'
                    % (module, module))
                self.assertIn("speech.listen", str(error))
        for name in ("transcribe",):
            self.assertEqual(MODULES["voice"][name].requires, SPEECH_LISTEN)

    def test_licence_risk_is_empty_for_safe_voices(self):
        """Silica gets "" not Unit, so len(...) > 0 is the natural check."""
        output = run_source(
            'use voice\nsfn main() {\n'
            '    per row in voice.voices() {\n'
            '        sprint(row["name"] + ":" + row["licence_risk"])\n'
            '    }\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        rows = dict(line.split(":", 1) for line in output.splitlines() if ":" in line)
        self.assertEqual(rows["en_GB-alba-medium"], "")
        self.assertEqual(rows["hi_IN-pratham-medium"], "licence is non-commercial")
        self.assertEqual(rows["en_US-lessac-medium"], "licence not verified")

    def test_licence_is_available_from_silica(self):
        output = run_source(
            'use voice\nsfn main() {\n'
            '    let entry = voice.licence("hi_IN-pratham-medium")\n'
            '    sprint(entry["id"])\n'
            '    sprint(str(entry["commercial"]))\n'
            '    sprint(str(entry["verified"]))\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        self.assertEqual(output.split(), ["CC-BY-NC-SA-4.0", "nein", "oui"])

    def test_voices_report_the_licence_risk(self):
        output = run_source(
            'use voice\nsfn main() {\n'
            '    let rows = voice.voices()\n'
            '    per row in rows {\n'
            '        si row["licence_verified"] == nein {\n'
            '            sprint(row["name"])\n'
            '        }\n'
            '    }\n}\n')
        self.assertNotIsInstance(output, Exception, output)
        unverified = [line for line in output.split() if line]
        self.assertIn("en_US-lessac-medium", unverified)
        self.assertNotIn("en_GB-alba-medium", unverified)


if __name__ == "__main__":
    unittest.main()
