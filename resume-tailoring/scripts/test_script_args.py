"""Unit tests for script_args — the shared flat-namespace argv helpers.

Run from the scripts directory (or via pytest from the parent):

    python3 scripts/test_script_args.py

These helpers are the one shared arg-parsing surface for the six
resume-tailoring CLIs (the ats_* closures used to re-implement
flag reading three times with divergent error behavior — see
flag_value, the single read-without-consuming variant).
"""

# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring
# unittest/pytest method names are self-documenting.

import sys
import unittest

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from script_args import extract_common, flag_value


class FlagValueTests(unittest.TestCase):
    """flag_value: read a flag's value WITHOUT consuming it (positionals
    and later argv scans stay untouched); SystemExit with a clear message
    when the flag is present but has no value (unlike extract_flag's
    IndexError)."""

    def test_missing_flag_returns_default(self):
        self.assertIsNone(flag_value(["a", "b"], "--jd"))
        self.assertEqual(flag_value(["a"], "--jd", default="x"), "x")

    def test_returns_value_and_leaves_argv_untouched(self):
        argv = ["r.docx", "--jd", "jd.txt", "--max-words", "1200"]
        self.assertEqual(flag_value(argv, "--jd"), "jd.txt")
        self.assertEqual(flag_value(argv, "--max-words", cast=int), 1200)
        self.assertEqual(argv, ["r.docx", "--jd", "jd.txt",
                                "--max-words", "1200"])

    def test_cast_applied(self):
        self.assertEqual(flag_value(["--timeout", "300"], "--timeout",
                                    cast=int), 300)

    def test_flag_at_end_without_value_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            flag_value(["--jd"], "--jd")
        self.assertIn("need", str(cm.exception))


class ExtractCommonTests(unittest.TestCase):
    """extract_common: the standard --protect/--jd loop shared by
    measure_resume and squeeze_resume (positionals and extra single-value
    flags survive; repeatable --protect collects every occurrence)."""

    def test_protect_jd_and_positionals(self):
        argv = ["r.docx", "3", "--protect", "P1", "--jd", "jd.txt",
                "--protect", "P2"]
        protect, jd_file, kept = extract_common(argv)
        self.assertEqual(protect, ["P1", "P2"])
        self.assertEqual(jd_file, "jd.txt")
        self.assertEqual(kept, ["r.docx", "3"])
        self.assertEqual(argv, ["r.docx", "3", "--protect", "P1",
                                "--jd", "jd.txt", "--protect", "P2"])

    def test_extra_flags_consumed_but_not_returned(self):
        protect, jd_file, kept = extract_common(
            ["r.docx", "--plan-only", "--jd", "jd.txt"],
            extra_flags=("--plan-only",))
        self.assertEqual((protect, jd_file), ([], "jd.txt"))
        self.assertEqual(kept, ["r.docx"])


if __name__ == "__main__":
    unittest.main()