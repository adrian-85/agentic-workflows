"""Tests for jd_sections — the fixed JD header contract (SKILL Step 1)."""

import unittest

import jd_sections as js


def _full_jd(**overrides):
    """A complete, validly-sectioned JD with every canonical header."""
    body = {
        "title": "Senior QA Engineer",
        "company": "We build things.",
        "role": "Own the quality of the platform.",
        "responsibilities": "Write and maintain automated tests.",
        "required": "5+ years of test automation.",
        "additional": "",
        "education": "",
        "expectations": "",
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
    """Exact-match header recognition (case-insensitive, colon REQUIRED)."""

    def test_matches_exact_header_case_insensitive(self):
        """A canonical header matches in any case, colon required."""
        self.assertEqual(js.header_at("required:"), "required")
        self.assertEqual(js.header_at("REQUIRED:"), "required")
        self.assertEqual(js.header_at("  Title : "), "title")

    def test_colon_is_mandatory(self):
        """The one-word headers must not match a bare body word — the
        trailing colon is what separates a header from prose."""
        self.assertIsNone(js.header_at("required"))
        self.assertIsNone(js.header_at("title"))
        self.assertIsNone(js.header_at("Title"))

    def test_header_word_with_content_is_not_a_header(self):
        """An inline label ('Title: Senior Engineer') is body prose,
        not a section header — only the bare header line opens one."""
        self.assertIsNone(js.header_at("Title: Senior Engineer"))

    def test_no_match_for_synonym_heading(self):
        """No fuzzy fallback: a differently-phrased heading never matches."""
        self.assertIsNone(js.header_at("What You Will Need:"))
        self.assertIsNone(js.header_at("Qualifications:"))
        self.assertIsNone(js.header_at("Tech Stack:"))
        self.assertIsNone(js.header_at("Position Title:"))

    def test_is_ask_header(self):
        """Only the three ask-bearing headers qualify as ask sections."""
        self.assertTrue(js.is_ask_header("required:"))
        self.assertTrue(js.is_ask_header("additional:"))
        self.assertTrue(js.is_ask_header("education:"))
        self.assertFalse(js.is_ask_header("company:"))
        self.assertFalse(js.is_ask_header("role:"))
        self.assertFalse(js.is_ask_header("some random line"))


class ParseSectionsTests(unittest.TestCase):
    """The strict whole-file split into the 8 canonical sections."""

    def test_freeform_jd_returns_none(self):
        """Unsectioned text is a different input class: None, not a parse."""
        self.assertIsNone(js.parse_sections(
            "Top 3 skills: Python, SQL, and Selenium."))

    def test_complete_jd_parses_every_section(self):
        """A complete JD yields all eight bodies under their headers."""
        jd = _full_jd(**{"required": "5+ years QA"})
        sections = js.parse_sections(jd)
        self.assertEqual(sections["title"], "Senior QA Engineer")
        self.assertEqual(sections["required"], "5+ years QA")
        self.assertEqual(sections["additional"], "")
        self.assertEqual(set(sections), set(js.SECTION_HEADERS))

    def test_section_order_in_file_does_not_matter(self):
        """Content is collected by header NAME into a dict — the headers
        may appear in any order in the file; each body simply runs until
        the next header line."""
        jd = ("required:\n5+ years QA\n"
              "title:\nSenior QA Engineer\n"
              "company:\nWe build things.\n"
              "role:\nOwn quality.\n"
              "responsibilities:\nWrite tests.\n"
              "additional:\nDocker\n"
              "education:\nBS\n"
              "expectations:\nShip fast\n")
        sections = js.parse_sections(jd)
        self.assertEqual(sections["title"], "Senior QA Engineer")
        self.assertEqual(sections["required"], "5+ years QA")
        self.assertEqual(sections["company"], "We build things.")
        self.assertEqual(sections["expectations"], "Ship fast")

    def test_missing_header_raises_with_name(self):
        """A sectioned JD missing headers raises naming each one."""
        jd = "title:\nQA Engineer\n"
        with self.assertRaises(ValueError) as ctx:
            js.parse_sections(jd)
        msg = str(ctx.exception)
        self.assertIn("company", msg)
        self.assertIn("required", msg)

    def test_header_without_colon_counts_as_missing(self):
        """A one-word header line missing its colon reads as prose —
        parse_sections reports it (and every section after it) missing."""
        jd = _full_jd().replace("required:\n", "required\n", 1)
        with self.assertRaises(ValueError) as ctx:
            js.parse_sections(jd)
        self.assertIn("required", str(ctx.exception))

    def test_header_present_but_blank_body_is_empty_string(self):
        """The blank-when-absent contract: header present, body empty."""
        jd = _full_jd(**{"additional": ""})
        sections = js.parse_sections(jd)
        self.assertEqual(sections["additional"], "")


class FindSectionTests(unittest.TestCase):
    """The lenient single-section lookup used by jd_asks."""

    def test_returns_body_between_headers(self):
        """A section's body runs to the next canonical header."""
        jd = ("required:\n5+ years QA\nStrong SQL\n"
              "additional:\nDocker\n")
        self.assertEqual(js.find_section(jd, "required"),
                         "5+ years QA\nStrong SQL")
        self.assertEqual(js.find_section(jd, "additional"),
                         "Docker")

    def test_repeated_header_blocks_accumulate(self):
        """A migrated JD may carry former tech-stack lines in a second
        required: block — repeats re-open collection and merge, matching
        parse_sections (a break-at-first-block would silently drop the
        second block's asks from requirement_lines)."""
        jd = ("required:\nPython, Selenium\n"
              "responsibilities:\nWrite tests.\n"
              "required:\n5+ years QA\n")
        self.assertEqual(js.find_section(jd, "required"),
                         "Python, Selenium\n5+ years QA")

    def test_header_at_eof_returns_empty_string(self):
        """A header as the last line yields an empty body string."""
        jd = "required:\n5+ years QA\nadditional:\n"
        self.assertEqual(js.find_section(jd, "additional"), "")

    def test_missing_header_returns_none(self):
        """A header that never appears yields None (not an empty body)."""
        jd = "required:\n5+ years QA\n"
        self.assertIsNone(js.find_section(jd, "education"))

    def test_works_on_partial_ad_hoc_snippet(self):
        """Unit tests elsewhere use minimal snippets, not the full 8-header
        file — find_section (unlike parse_sections) tolerates that."""
        jd = "required:\nKubernetes and Helm\n"
        self.assertEqual(js.find_section(jd, "required"),
                         "Kubernetes and Helm")


if __name__ == "__main__":
    unittest.main()
