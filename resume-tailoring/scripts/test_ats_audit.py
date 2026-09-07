"""Unit tests for ats_audit.py — the literal-phrase ATS backstop.

Run from the scripts directory:

    cd ~/.pi/agent/skills/resume-tailoring/scripts && python3 -m unittest test_ats_audit
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import ats_audit as aa  # noqa: E402


def _tmp(text, suffix=".txt"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


class HostedTests(unittest.TestCase):
    def test_word_boundary_literal_match(self):
        self.assertTrue(aa._hosted("ran regression testing weekly",
                                   "regression testing"))
        self.assertFalse(aa._hosted("ran regression frameworks weekly",
                                    "regression testing"))

    def test_no_substring_inside_words(self):
        # "api" must not match inside "rapid" — the strip fallback never
        # applies to single words.
        self.assertFalse(aa._hosted("rapid delivery of quality", "api"))

    def test_plural_suffix_stems(self):
        # External scorers match stemmed: "triage" hosts "triages".
        self.assertTrue(aa._hosted("triages and documents defects",
                                   "triage"))
        self.assertTrue(aa._hosted("created test cases", "test case"))

    def test_line_wrap_and_hyphen_fallback(self):
        # A phrase wrapped across a pdftotext line break still hosts, and
        # a spaced phrase hosts inside its hyphenated compound.
        self.assertTrue(aa._hosted("ran regression\ntesting weekly",
                                   "regression testing"))
        self.assertTrue(aa._hosted("end-to-end pipelines", "end to end"))


class WordCountTests(unittest.TestCase):
    def test_under_cap_ok(self):
        count, errs = aa._audit_word_count("word " * 500, 1000)
        self.assertEqual((count, errs), (500, []))

    def test_over_cap_is_error(self):
        count, errs = aa._audit_word_count("word " * 1054, 1000)
        self.assertEqual(count, 1054)
        self.assertEqual(len(errs), 1)
        self.assertIn("exceeds the 1000-word cap by 54", errs[0])

    def test_zero_disables_cap(self):
        count, errs = aa._audit_word_count("word " * 5000, 0)
        self.assertEqual(errs, [])

    def test_parser_artifacts_stripped(self):
        # Page footers and bullet glyphs are not words: the count mirrors
        # the external scorers (calibration: a real deliverable counted
        # 1054 raw pdftotext tokens, 949 by the external report, 989 with
        # this logic).
        text = "word " * 600 + "Page 1|3 Page 2|3 \uf075 \uf0b7"
        count, errs = aa._audit_word_count(text, 1000)
        self.assertEqual((count, errs), (600, []))

    def test_spelled_out_page_word_stripped(self):
        text = "P a g e 1 | 3 word " * 100
        self.assertEqual(aa._count_words(text), 100)

    def test_tokens_without_alphanumerics_not_counted(self):
        self.assertEqual(aa._count_words("| | – —"), 0)

    def test_report_wordcount_finding_extracted(self):
        data = {"findings": [
            {"key": "wordCount", "name": "Word Count", "status": "pass",
             "variables": {"wordCount": 949}},
            {"key": "atsTip", "status": "pass"},
        ]}
        self.assertEqual(aa._report_word_count(data), 949)
        self.assertIsNone(aa._report_word_count({"findings": []}))
        self.assertIsNone(aa._report_word_count({}))


class JdLiteralTermsTests(unittest.TestCase):
    JD = (
        "About Us\n\nWe combine healthcare expertise and artificial "
        "intelligence.\n\nRequirements\n\n"
        "Minimum of 5 years of experience in software quality assurance\n"
        "Proficiency in Python or another scripting language used for test "
        "automation\n"
        "Experience with Playwright, Selenium, and pytest\n"
    )

    def test_qualification_phrases_extracted(self):
        terms = aa._jd_literal_terms(self.JD)
        for expected in ("software quality assurance", "test automation",
                         "scripting language"):
            self.assertIn(expected, terms, terms)
        # Generic qualification nouns never become terms.
        self.assertNotIn("minimum", terms)
        self.assertNotIn("proficiency", terms)
        # Core tech nouns survive as single tokens.
        for expected in ("python", "playwright", "selenium"):
            self.assertIn(expected, terms, terms)

    def test_audit_reports_zero_host_phrases(self):
        resume = ("Software quality assurance engineer. Scripting language "
                  "automation with Selenium and continuous integration.")
        ok_n, missing = aa._audit_jd(resume.lower(), self.JD)
        # The JD names Playwright/pytest; the resume hosts neither.
        self.assertIn("playwright", missing, missing)
        self.assertGreater(ok_n, 0)

    def test_audit_clean_when_all_hosted(self):
        resume = ("Experience in software quality assurance with Python, "
                  "Playwright, Selenium, and pytest for test automation. "
                  "Scripting language work included regression testing.")
        ok_n, missing = aa._audit_jd(resume.lower(), self.JD)
        self.assertEqual(missing, [])

    def test_prose_fragments_not_mined(self):
        # A responsibilities-style qual line is prose, not a skill list —
        # its fragments must not become literal terms.
        jd = ("Requirements\n\nAssess whether code changes make sense for "
              "the product and collaborate effectively with "
              "customer-facing teams.\n")
        self.assertEqual(aa._jd_literal_terms(jd), [])


class PhraseAuditTests(unittest.TestCase):
    def test_zero_hit_phrases_listed(self):
        text = "built data quality dashboards and automated regression"
        missing = aa._audit_phrases(
            text, ["data quality", "regression testing", "pytest"])
        self.assertEqual(missing, ["regression testing", "pytest"])


class ReportSkillsTests(unittest.TestCase):
    def test_keyword_extraction_tolerant(self):
        data = {"keywords": {"hard": ["pytest", {"keyword": "data quality"}],
                             "soft": ["communication skills"]}}
        hard, soft = aa._report_skills(data)
        self.assertEqual(hard, [("pytest", None), ("data quality", None)])
        self.assertEqual(soft, [("communication skills", None)])

    def test_hardsoft_keys_variant_with_resume_count(self):
        # External scan reports key skills as dicts with a name and the
        # authoritative resumeCount.
        data = {"hardSkills": [
            {"name": "selenium", "resumeCount": 4},
            {"name": "data quality", "resumeCount": 0},
        ], "softSkills": [{"name": "ownership"}]}
        hard, soft = aa._report_skills(data)
        self.assertEqual(hard, [("selenium", 4), ("data quality", 0)])
        self.assertEqual(soft, [("ownership", None)])


class FindingsReportTests(unittest.TestCase):
    def test_contact_email_ignored_by_rule(self):
        data = {"findings": [
            {"key": "contactEmail", "name": "Contact Email",
             "status": "fail"},
            {"key": "atsTip", "name": "ATS Tip", "status": "pass"},
            {"key": "measurableResults", "name": "Measurable Results",
             "status": "warn"},
        ]}
        lines = aa._report_findings(data)
        self.assertTrue(any("IGNORED contactEmail" in l for l in lines),
                        lines)
        # The pass finding is silent; other non-pass findings are reported.
        self.assertTrue(any("WARN: Measurable Results" in l for l in lines))
        self.assertEqual(sum(1 for l in lines if "ATS Tip" in l), 0)


class MainTests(unittest.TestCase):
    def _run(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = aa.main(list(args))
        return rc, out.getvalue()

    def test_over_word_cap_exits_1(self):
        path = _tmp("word " * 1100)
        try:
            rc, out = self._run(path)
            self.assertEqual(rc, 1)
            self.assertIn("exceeds the 1000-word cap", out)
        finally:
            os.unlink(path)

    def test_clean_resume_exits_0(self):
        path = _tmp("Quality assurance with Python and pytest. " * 10)
        try:
            rc, out = self._run(path, "--max-words", "1000")
            self.assertEqual(rc, 0, out)
        finally:
            os.unlink(path)

    def test_jd_mode_reports_missing_terms(self):
        resume = _tmp("Scripting language automation experience.")
        jd = _tmp(JdLiteralTermsTests.JD)
        try:
            rc, out = self._run(resume, "--jd", jd)
            self.assertEqual(rc, 1)
            self.assertIn("NO host in the rendered text", out)
        finally:
            os.unlink(resume)
            os.unlink(jd)

    def test_report_json_hard_miss_fails_soft_miss_warns(self):
        resume = _tmp("built data quality dashboards with selenium "
                      "triages defects " + "word " * 300)
        report = _tmp(json.dumps({
            "keywords": {"hard": [
                "data quality",
                {"name": "pytest", "resumeCount": 0},
                {"name": "selenium", "resumeCount": 4},
            ],
                "soft": ["communication skills"]},
            "findings": [{"key": "contactEmail", "status": "fail"},
                         {"key": "wordCount", "status": "pass",
                          "variables": {"wordCount": 949}}],
        }), suffix=".json")
        try:
            rc, out = self._run(resume, "--report-json", report)
            self.assertEqual(rc, 1)
            # resumeCount-authoritative: "data quality" and "pytest" have
            # zero report hits AND no literal host; selenium is hosted by
            # the report's own count; "triage" hosts via plural stemming.
            self.assertIn("NO literal host: pytest", out)
            self.assertNotIn("selenium", out)
            self.assertIn("soft skills with NO literal host", out)
            self.assertIn("IGNORED contactEmail", out)
            # The report's wordCount is a cross-check line.
            self.assertIn("words (report cross-check): 949", out)
        finally:
            os.unlink(resume)
            os.unlink(report)

    def test_usage_error(self):
        rc, _ = self._run()
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
