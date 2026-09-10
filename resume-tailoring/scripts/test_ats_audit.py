"""Unit tests for ats_audit.py — the literal-phrase ATS backstop.

Run from the scripts directory:

    cd ~/.pi/agent/skills/resume-tailoring/scripts && python3 -m unittest test_ats_audit
"""

# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name,import-outside-toplevel,wrong-import-position
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.
# import-outside-toplevel/wrong-import-position: live tests guard heavy imports at runtime;
#   flat-namespace tests need the sys.path bootstrap before sibling imports.

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

    def test_parenthetical_in_resume_text(self):
        # Parentheticals inside the JD's own phrasing: "test automation
        # frameworks (Java)" renders as "frameworks (Java" in the PDF;
        # the mined "frameworks java" n-gram must still host (a real
        # deliverable failed on this parser artifact).
        self.assertTrue(aa._hosted(
            "oversaw migration of test automation frameworks (java selenium",
            "frameworks java"))
        self.assertTrue(aa._hosted(
            "expertise with test automation frameworks (java)",
            "automation frameworks java"))

    def test_slash_normalized_fallback(self):
        # Standard spellings split with a slash: the JD says "CI/CD
        # pipelines" (mined as "ci cd"), the resume renders "CI/CD".
        # The multi-token fallback must normalize the slash on BOTH sides
        # or every legitimate CI/CD resume FAILs as a false no-host (a
        # real deliverable failed 4x on this artifact).
        self.assertTrue(aa._hosted("built ci/cd pipelines", "ci cd"))
        self.assertTrue(aa._hosted("built ci/cd pipelines",
                                   "ci cd pipelines"))
        self.assertTrue(aa._hosted("agile/scrum environments",
                                   "agile scrum environments"))
        # Single words never get the fallback — "api" must not host
        # inside "rest/api" of a different token boundary sense.
        self.assertFalse(aa._hosted("rest/api endpoints", "rapid"))


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
        _count, errs = aa._audit_word_count("word " * 5000, 0)
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
        _ok_n, missing = aa._audit_jd(resume.lower(), self.JD)
        # The JD names Playwright/pytest; the resume hosts neither.
        self.assertIn("playwright", missing, missing)
        self.assertGreater(_ok_n, 0)

    def test_audit_clean_when_all_hosted(self):
        resume = ("Experience in software quality assurance with Python, "
                  "Playwright, Selenium, and pytest for test automation. "
                  "Scripting language work included regression testing.")
        _ok_n, missing = aa._audit_jd(resume.lower(), self.JD)
        self.assertEqual(missing, [])

    def test_prose_fragments_not_mined(self):
        # A responsibilities-style qual line is prose, not a skill list —
        # its fragments must not become literal terms.
        jd = ("Requirements\n\nAssess whether code changes make sense for "
              "the product and collaborate effectively with "
              "customer-facing teams.\n")
        self.assertEqual(aa._jd_literal_terms(jd), [])

    def test_trailing_punctuation_stripped(self):
        # Sentence-final punctuation rides along in the token regexes:
        # "...REST APIs." mined "apis.", "...C#." mined "c#." — no resume
        # can literally host a token with a trailing period, so those
        # terms only padded the FAIL list (a real audit listed apis.,
        # c#., locust. as FAILs). Stripped at extraction.
        jd = ("Requirements\n\nExperience with REST APIs.\n"
              "Strong C#. Familiarity with Locust.\n")
        terms = aa._jd_literal_terms(jd)
        self.assertNotIn("apis.", terms, terms)
        self.assertNotIn("c#.", terms, terms)
        self.assertNotIn("locust.", terms, terms)

    def test_period_form_and_gram_form_collapse(self):
        # "...Jenkins or GitLab CI." mined BOTH 'gitlab ci.' (seq token,
        # sentence-final period) and 'gitlab ci' (cue-tail n-gram) — the
        # FAIL list printed the term twice (a real audit did). The
        # punctuation strip happens BEFORE the set is built.
        jd = "Requirements\n\nCI experience with Jenkins or GitLab CI.\n"
        terms = aa._jd_literal_terms(jd)
        self.assertEqual(
            [t for t in terms if t.startswith("gitlab")], ["gitlab ci"])

    def test_structure_word_as_never_in_a_gram(self):
        # 'as' is a structure word: a cue tail '...such as Jenkins, ...'
        # mined 'as jenkins' — no resume hosts that, and it only padded
        # the FAIL list (a real audit listed 'as jenkins').
        jd = "Requirements\n\nCI experience with a comparable system " \
             "such as Jenkins or GitLab CI.\n"
        terms = aa._jd_literal_terms(jd)
        self.assertNotIn("as jenkins", terms, terms)

    def test_word_prefix_term_subsumed_by_longer(self):
        # Overlapping cue windows mined 'selenium driving' beside
        # 'selenium driving parallelized' — both padded the FAIL list.
        # A term that is a word-prefix of a longer term is subsumed: the
        # longest literal phrase is what to host.
        jd = ("Requirements\n\nProficiency in Python with Playwright or "
              "Selenium driving parallelized suites in CI.\n")
        terms = aa._jd_literal_terms(jd)
        self.assertNotIn("selenium driving", terms, terms)
        self.assertIn("selenium driving parallelized", terms, terms)


class MatchRateTargetTests(unittest.TestCase):
    """The ≥75 match-rate TARGET (SKILL Step 11): a stop signal for the
    literal-hosting loop, never a hard gate."""

    def _result(self):
        return aa._AuditResult()

    def test_score_below_target_warns(self):
        r = self._result()
        aa._audit_match_rate(69, 75, r)
        self.assertEqual(len(r.warns), 1)
        self.assertIn("below the 75 target", r.warns[0])
        self.assertEqual(r.ok_lines, [])

    def test_score_at_target_ok_and_stops_hosting(self):
        r = self._result()
        aa._audit_match_rate(88, 75, r)
        self.assertEqual(r.warns, [])
        self.assertEqual(len(r.ok_lines), 1)
        self.assertIn("MET", r.ok_lines[0])

    def test_zero_target_disables(self):
        r = self._result()
        aa._audit_match_rate(40, 0, r)
        self.assertEqual(r.warns, [])
        self.assertEqual(r.ok_lines, [])

    def test_missing_score_is_silent(self):
        r = self._result()
        aa._audit_match_rate(None, 75, r)
        self.assertEqual(r.warns, [])
        self.assertEqual(r.ok_lines, [])

    def test_report_match_rate_extracted(self):
        self.assertEqual(aa._report_match_rate({"matchRate":
                                                {"score": 88}}), 88)
        self.assertIsNone(aa._report_match_rate({}))
        self.assertIsNone(aa._report_match_rate({"matchRate":
                                                 {"score": "69"}}))



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

    def test_special_characters_ignored_by_rule(self):
        # The user's typographic formatting (Wingdings bullets, en-dash
        # date ranges, curly quotes) is deliberate: the finding is noise
        # in every report and must never trigger a reformat.
        data = {"findings": [
            {"key": "specialCharacters", "name": "Special Characters",
             "status": "fail"},
        ]}
        lines = aa._report_findings(data)
        self.assertTrue(any("IGNORED specialCharacters" in l for l in lines),
                        lines)
        self.assertNotIn("FAIL:", "\n".join(lines))

    def test_education_findings_ignored_when_section_dropped(self):
        # A PDF with no Education section got past the render gate, so
        # the drop was sanctioned (Step 3.4 predicate) — the scan's
        # generic advice does not re-open it.
        data = {"findings": [
            {"key": "headingEducation", "name": "Education Heading",
             "status": "fail"},
            {"key": "educationMatch", "name": "Education Match",
             "status": "warn"},
        ]}
        lines = aa._report_findings(data, "Summary\nWork Experience\n")
        joined = "\n".join(lines)
        self.assertEqual(joined.count("IGNORED"), 2, joined)
        self.assertNotIn("FAIL:", joined)
        self.assertNotIn("WARN:", joined)

    def test_education_findings_reported_when_section_present(self):
        # With Education in the resume, the findings are real signal and
        # report normally (the conservative direction on a detection
        # miss).
        data = {"findings": [
            {"key": "headingEducation", "name": "Education Heading",
             "status": "fail"},
        ]}
        lines = aa._report_findings(data, "Experience\nEducation\nB.S.\n")
        self.assertEqual(lines, ["  FAIL: Education Heading"])


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
            # Reclassified actionable (SKILL Steps 2/11): the warning must
            # tell the agent to HOST the phrase, not skip it as deliberate.
            self.assertIn("ACTIONABLE", out)
            self.assertIn("safe to infer", out)
            self.assertNotIn("advisory", out)
            self.assertIn("IGNORED contactEmail", out)
            # The report's wordCount is a cross-check line.
            self.assertIn("words (report cross-check): 949", out)
        finally:
            os.unlink(resume)
            os.unlink(report)

    def test_usage_error(self):
        rc, _ = self._run()
        self.assertEqual(rc, 2)

    def test_vacuous_mining_warns_not_clean(self):
        # A JD whose qual lines use no cue syntax mines ZERO phrases — the
        # audit must flag the check as vacuous, never report it clean (a
        # real session saw '0/0 hosted' read as ok and hand-rolled a
        # phrases file to get real results).
        resume = _tmp("Quality assurance with Python and Playwright.")
        jd = _tmp("Requirements\n\nOwn quality for the product team.\n")
        try:
            rc, out = self._run(resume, "--jd", jd)
            self.assertEqual(rc, 0)  # warning, not a failure
            self.assertIn("the literal check is vacuous", out)
            self.assertNotIn("JD literal terms:", out)  # no ok line
        finally:
            os.unlink(resume)
            os.unlink(jd)


if __name__ == "__main__":
    unittest.main()
