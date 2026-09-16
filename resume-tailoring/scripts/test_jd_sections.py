"""Tests for jd_sections — the fixed JD header contract (SKILL Step 1)."""

import unittest

import jd_sections as js


def _full_jd(**overrides):
    """A complete, validly-sectioned JD with every canonical header."""
    body = {
        "Position Title": "Senior QA Engineer",
        "Company Overview": "We build things.",
        "Tech Stack": "Python, Selenium, Postgres",
        "Responsibilities": "Write and maintain automated tests.",
        "Required Experience": "5+ years of test automation.",
        "Additional Experience": "",
        "Required Education": "",
        "30/60/90 Day Expectations": "",
    }
    body.update(overrides)
    lines = []
    for h in js.SECTION_HEADERS:
        lines.append(f"{h}:")
        if body[h]:
            lines.append(body[h])
        lines.append("")
    return "\n".join(lines)


class HeaderAtTests(unittest.TestCase):

    def test_matches_exact_header_case_insensitive(self):
        self.assertEqual(js.header_at("required experience"),
                         "Required Experience")
        self.assertEqual(js.header_at("REQUIRED EXPERIENCE:"),
                         "Required Experience")

    def test_no_match_for_synonym_heading(self):
        # The whole point: no fuzzy fallback for a differently-phrased
        # heading, however common in real postings.
        self.assertIsNone(js.header_at("What You Will Need:"))
        self.assertIsNone(js.header_at("Qualifications:"))
        self.assertIsNone(js.header_at("You Have:"))

    def test_is_ask_header(self):
        self.assertTrue(js.is_ask_header("Required Experience:"))
        self.assertTrue(js.is_ask_header("Tech Stack"))
        self.assertFalse(js.is_ask_header("Company Overview:"))
        self.assertFalse(js.is_ask_header("some random line"))


class IsSectionedTests(unittest.TestCase):

    def test_freeform_jd_is_unsectioned(self):
        self.assertFalse(js.is_sectioned(
            "Top 3 skills: Python, SQL, and Selenium."))

    def test_one_canonical_header_marks_sectioned(self):
        self.assertTrue(js.is_sectioned("Required Experience:\nSQL\n"))


class ParseSectionsTests(unittest.TestCase):

    def test_freeform_jd_returns_none(self):
        self.assertIsNone(js.parse_sections(
            "Top 3 skills: Python, SQL, and Selenium."))

    def test_complete_jd_parses_every_section(self):
        jd = _full_jd(**{"Required Experience": "5+ years QA"})
        sections = js.parse_sections(jd)
        self.assertEqual(sections["Position Title"], "Senior QA Engineer")
        self.assertEqual(sections["Required Experience"], "5+ years QA")
        self.assertEqual(sections["Additional Experience"], "")
        self.assertEqual(set(sections), set(js.SECTION_HEADERS))

    def test_missing_header_raises_with_name(self):
        jd = "Position Title:\nQA Engineer\n"
        with self.assertRaises(ValueError) as ctx:
            js.parse_sections(jd)
        msg = str(ctx.exception)
        self.assertIn("Company Overview", msg)
        self.assertIn("Required Experience", msg)

    def test_header_present_but_blank_body_is_empty_string(self):
        jd = _full_jd(**{"Additional Experience": ""})
        sections = js.parse_sections(jd)
        self.assertEqual(sections["Additional Experience"], "")


class FindSectionTests(unittest.TestCase):

    def test_returns_body_between_headers(self):
        jd = ("Required Experience:\n5+ years QA\nStrong SQL\n"
              "Additional Experience:\nDocker\n")
        self.assertEqual(js.find_section(jd, "Required Experience"),
                         "5+ years QA\nStrong SQL")
        self.assertEqual(js.find_section(jd, "Additional Experience"),
                         "Docker")

    def test_header_at_eof_returns_empty_string(self):
        jd = "Required Experience:\n5+ years QA\nAdditional Experience:\n"
        self.assertEqual(js.find_section(jd, "Additional Experience"), "")

    def test_missing_header_returns_none(self):
        jd = "Required Experience:\n5+ years QA\n"
        self.assertIsNone(js.find_section(jd, "Tech Stack"))

    def test_works_on_partial_ad_hoc_snippet(self):
        # Unit tests elsewhere use minimal snippets, not the full 8-header
        # file — find_section (unlike parse_sections) tolerates that.
        jd = "Required Experience:\nKubernetes and Helm\n"
        self.assertEqual(js.find_section(jd, "Required Experience"),
                         "Kubernetes and Helm")


if __name__ == "__main__":
    unittest.main()
