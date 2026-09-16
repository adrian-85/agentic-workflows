"""Tests for jd_asks's fixed-header requirement_lines and the per-run
evidence-family extension (EXTRA_EVIDENCE_FAMILIES)."""

import unittest

import jd_asks


class RequirementLinesTests(unittest.TestCase):
    """Qualification-line collection over the canonical ask sections."""

    def test_collects_ask_section_lines(self):
        """Tech Stack/Required/Additional/Education lines all collect."""
        jd = ("Required Experience:\n"
              "5+ years of test automation\n"
              "Additional Experience:\n"
              "Docker experience a plus\n")
        lines = jd_asks.requirement_lines(jd)
        self.assertIn("5+ years of test automation", lines)
        self.assertIn("Docker experience a plus", lines)

    def test_ignores_non_ask_sections(self):
        """Context sections (title/overview/responsibilities) never
        contribute qualification lines."""
        jd = ("Position Title:\nQA Engineer\n"
              "Company Overview:\nWe build things.\n"
              "Responsibilities:\nWrite automated tests daily.\n"
              "Required Experience:\n5+ years QA\n")
        lines = jd_asks.requirement_lines(jd)
        self.assertEqual(lines, ["5+ years QA"])

    def test_unsectioned_jd_returns_empty(self):
        """No canonical header at all: a different, documented input class
        (recruiter message) — parse_asks mines the whole text instead."""
        self.assertEqual(
            jd_asks.requirement_lines("Top skills: Python, SQL, Selenium."),
            [])

    def test_synonym_heading_is_not_recognized(self):
        """No fallback: 'What You Will Need:' is not a canonical header,
        so its lines are not collected as qualification lines."""
        jd = "What You Will Need:\n5+ years of QA experience\n"
        self.assertEqual(jd_asks.requirement_lines(jd), [])

    def test_company_voice_sentence_filtered_from_ask_section(self):
        """A stray 'We offer...' sentence inside an ask section is
        filtered like it always was."""
        jd = "Required Experience:\nWe offer great benefits.\n5+ years QA\n"
        lines = jd_asks.requirement_lines(jd)
        self.assertEqual(lines, ["5+ years QA"])


class ExtraEvidenceFamiliesTests(unittest.TestCase):
    """The per-run --equivalence extension of the one ask/evidence
    matcher (auto_prune populates EXTRA_EVIDENCE_FAMILIES)."""

    def tearDown(self):
        """Equivalences are scoped to one run — never leak between
        tests."""
        jd_asks.EXTRA_EVIDENCE_FAMILIES.clear()

    def test_per_run_equivalence_hosts_the_jd_term(self):
        """A JD-specific term ('iv&v') whose truthful equivalent is worded
        differently in the resume ('testing') hosts via the extension."""
        jd_asks.EXTRA_EVIDENCE_FAMILIES["iv&v"] = ("iv&v", "testing")
        self.assertTrue(jd_asks._phrase_evidence(
            "performed independent testing", "iv&v", "hard"))

    def test_default_families_unaffected_by_empty_extra(self):
        """Empty extension dict: the general families answer unchanged."""
        self.assertEqual(jd_asks._evidence_candidates("python scripting"),
                         jd_asks._EVIDENCE_FAMILIES["python scripting"])

    def test_extra_family_overrides_for_this_run_only(self):
        """A populated extension wins for the run and clears afterward."""
        jd_asks.EXTRA_EVIDENCE_FAMILIES["scripting"] = ("scripting", "coding")
        self.assertEqual(jd_asks._evidence_candidates("scripting"),
                         ("scripting", "coding"))
        jd_asks.EXTRA_EVIDENCE_FAMILIES.clear()
        self.assertEqual(jd_asks._evidence_candidates("scripting"),
                         jd_asks._EVIDENCE_FAMILIES["scripting"])


if __name__ == "__main__":
    unittest.main()
