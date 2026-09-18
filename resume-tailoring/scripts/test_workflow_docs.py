"""Contract checks for the resume-tailoring workflow documentation.

These checks keep the executable source-JD and word-count contracts visible
in the skill and API reference while the behavioral tests cover the scripts.
Run from the scripts directory with ``python3 -m unittest test_workflow_docs``.
"""

# pylint: disable=missing-function-docstring,missing-class-docstring

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class WorkflowDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.api = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")

    def test_source_jd_contract_is_documented(self):
        for text in (self.skill, self.api):
            self.assertIn("jd_<target>_source.txt", text)
            self.assertIn("--source-jd", text)

    def test_canonical_external_scan_command_is_documented(self):
        self.assertIn(
            'ats_check.py scan "<output>.pdf" jd_<target>.txt', self.skill)
        self.assertIn("--source-jd jd_<target>_source.txt", self.skill)

    def test_word_count_claim_matches_measured_behavior(self):
        self.assertIn(
            "compound-word semantics",
            self.skill)
        self.assertNotIn("same word boundaries used by a specific vendor", self.skill)


if __name__ == "__main__":
    unittest.main()
