"""Tests for jd_asks's fixed-header requirement_lines and the per-run
evidence-family extension (EXTRA_EVIDENCE_FAMILIES)."""

# pylint: disable=missing-function-docstring

import unittest

import jd_asks
import ats_audit


class RequirementLinesTests(unittest.TestCase):
    """Qualification-line collection over the canonical ask sections."""

    def test_collects_ask_section_lines(self):
        """required/Required/Additional/Education lines all collect."""
        jd = ("required:\n"
              "5+ years of test automation\n" "additional:\n"
              "Docker experience a plus\n")
        lines = jd_asks.requirement_lines(jd)
        self.assertIn("5+ years of test automation", lines)
        self.assertIn("Docker experience a plus", lines)

    def test_ignores_non_ask_sections(self):
        """Context sections (title/overview/responsibilities) never
        contribute qualification lines."""
        jd = ("title:\nQA Engineer\n"
              "company:\nWe build things.\n" "responsibilities:\nWrite automated tests daily.\n"
              "required:\n5+ years QA\n")
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
        jd = "required:\nWe offer great benefits.\n5+ years QA\n"
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




class SlashPathAndStopwordTests(unittest.TestCase):
    """Regression: JD audit false-failures on a slash-path and
    stopword-heavy JD (SKILL Step 11)."""

    JD = """title:
Software Development Engineer in Test

company:
We build things.

role:
Core contributor on the quality engineering team.

responsibilities:
Test things.

required:
Strong proficiency in Python for test automation
Experience with Locust is a plus
Familiarity with Unix/Linux/Mac OS development environments and shell scripting (Bash required).
PowerShell knowledge is a strong plus (for Windows automation workflows).
BS/BE/BTech in Computer Science, or equivalent experience.

additional:
GCP/Azure nice to have

education:

expectations:
"""

    def test_header_words_are_not_asks(self):
        """'expectations:' and 'required:' name no ask."""
        terms = jd_asks.hard_phrases(self.JD)
        self.assertNotIn("day", terms)
        self.assertNotIn("expectations", terms)
        self.assertNotIn("stack", terms)

    def test_degree_acronyms_are_not_asks(self):
        """'BS/BE/BTech' are education credentials, not skill asks."""
        terms = jd_asks.hard_phrases(self.JD)
        for t in ("bs", "be", "btech"):
            self.assertNotIn(t, terms)

    def test_slash_path_enumeration_hosts_by_segments(self):
        """'UI/API/component/unit tests' hosts when every level is named."""
        text = "built unit tests, component suites, api checks, and ui coverage"
        self.assertTrue(jd_asks.hosted(text, "ui/api/component/unit"))
        self.assertFalse(jd_asks.hosted("unit tests and api checks only",
                                        "ui/api/component/unit"))

    def test_bash_hosts_via_wsl_and_unix_via_linux(self):
        """WSL is Bash on Linux; Linux is the Unix-family environment."""
        ev = jd_asks._phrase_evidence
        self.assertTrue(ev("automation in wsl", "bash", "hard"))
        self.assertTrue(ev("linux servers", "unix", "hard"))

    def test_degree_phrase_hosts_via_bachelor(self):
        """'Computer Science' is hosted by the held degree line."""
        self.assertTrue(jd_asks._phrase_evidence(
            "bachelor's degree", "computer science", "hard"))

    def test_audits_qualification_scope_not_whole_posting(self):
        """ats_audit's term source keeps posting context but stays scoped."""
        terms = ats_audit._jd_literal_terms(self.JD)
        self.assertNotIn("day", terms)
        self.assertNotIn("expectations", terms)
        self.assertIn("locust", terms)  # a plus-item ask stays actionable


class GenericEvidenceDemotionTests(unittest.TestCase):
    """The ruthless-prune rule (2026-09-26): generic practice vocabulary
    alone is NOT evidence. Session evidence: ETL and model-based-testing
    bullets survived three prunes solely on test/testing/data/api/code/
    json matches, hosted no external-report skill, and were manually
    removed after every session."""

    def test_generic_only_text_reports_no_evidence(self):
        text = ("planned test coverage for a file upload process that "
                "utilized etl, mapping scenarios that validated data "
                "movement through the pipeline")
        self.assertEqual(jd_asks.evidence_set(text, {"test", "data", "api"}), set())

    def test_generic_cooccurring_with_specific_counts(self):
        text = "led karate adoption for api test automation"
        self.assertEqual(jd_asks.evidence_set(text, {"karate", "api", "test"}),
                         {"karate", "api", "test"})

    def test_specific_evidence_set_drops_generics(self):
        text = "led karate adoption for api test automation"
        self.assertEqual(jd_asks.specific_evidence_set(
            text, {"karate", "api", "test"}), {"karate"})

    def test_generic_only_evidence_names_the_generics(self):
        text = "wrote api tests that validated data movement"
        self.assertEqual(jd_asks.generic_only_evidence(
            text, {"api", "test", "data", "karate"}), {"api", "test", "data"})

    def test_specific_text_reports_no_generic_only(self):
        text = "led karate adoption for api test automation"
        self.assertEqual(jd_asks.generic_only_evidence(
            text, {"karate", "api", "test"}), set())


if __name__ == "__main__":
    unittest.main()
