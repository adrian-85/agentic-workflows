"""Unit tests for measure_resume.py's resume-format assumptions.

The suite is config-agnostic by design: structural fixtures derive from the
current constants (via `_sample_date`), so re-configuring the constants for
a different resume keeps the suite green. Three tests exercise the override
paths: `test_default_date_pattern` (reference MM/YYYY stripping, verbatim —
update it when you change DATE_RE), `test_custom_date_pattern` and
`test_parses_alternative_resume_via_constants` (different date format /
section names / role-header style measured via constants only).

Run from the scripts directory (so `docx_edit`/`measure_resume` import):

    python3 -m unittest test_measure_resume
"""

import re
import sys
import unittest
from xml.etree import ElementTree as ET

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402

W = de.W


def _para(text, style=None, numId=None):
    """Build a <w:p> with optional pStyle/numId (mirrors the master)."""
    p = ET.Element(W + "p")
    if style is not None or numId is not None:
        pPr = ET.SubElement(p, W + "pPr")
        if style is not None:
            st = ET.SubElement(pPr, W + "pStyle")
            st.set(W + "val", style)
        if numId is not None:
            np = ET.SubElement(pPr, W + "numPr")
            ni = ET.SubElement(np, W + "numId")
            ni.set(W + "val", str(numId))
    r = ET.SubElement(p, W + "r")
    t = ET.SubElement(r, W + "t")
    t.text = text
    return p


def _body(ps):
    body = ET.Element(W + "body")
    for p in ps:
        body.append(p)
    return body


def _sample_date():
    """A date token the CURRENT DATE_RE matches (MM/YYYY or ISO), so fixtures
    work under either format and the structural tests stay green after a
    legit constants re-config."""
    for cand in ("02/2019", "2019-02"):
        if mr.DATE_RE.search(cand):
            return cand
    raise AssertionError(
        f"fixture cannot build: DATE_RE {mr.DATE_RE.pattern!r} matches neither "
        "MM/YYYY nor YYYY-MM"
    )


class CompanyKeyTests(unittest.TestCase):
    """_company_key strips a trailing date to yield a PDF-match prefix."""

    def test_default_date_pattern(self):
        # Verbatim reference pin: strips the MM/YYYY date and
        # whitespace-normalizes the company portion. Update when DATE_RE
        # is re-configured for a different date format.
        self.assertEqual(
            mr._company_key("Company ABC, Phoenix, AZ02/2019 – 04/2020"),
            "Company ABC, Phoenix, AZ",
        )

    def test_custom_date_pattern(self):
        saved = mr.DATE_RE
        try:
            mr.DATE_RE = re.compile(r"\d{4}-\d{2}")
            self.assertEqual(
                mr._company_key("Widgets Inc2024-03 – 2025-01"),
                "Widgets Inc",
            )
        finally:
            mr.DATE_RE = saved


class RolesTests(unittest.TestCase):
    """_roles finds roles between the career/education sections."""

    def _default_body(self):
        """The reference resume's structure, built from the CURRENT constants
        (so the suite stays green after a legitimate constants re-config)."""
        return _body([
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, Phoenix, AZ" + _sample_date() + " — 04/2020",
                  style=mr.COMPANY_STYLE),
            _para("Bullet one", numId=2),
            _para("Bullet two", numId=2),
            _para("Tools & Technologies: Java, SQL"),
            _para(mr.SECTION_EDUCATION, style="SectionHeading"),
        ])

    def test_parses_default_structure(self):
        roles = mr._roles(self._default_body())
        self.assertEqual(len(roles), 1)
        r = roles[0]
        self.assertEqual(r["key"], "Company ABC, Phoenix, AZ")
        self.assertEqual(r["bullets"], 2)
        self.assertTrue(r["has_tools"])

    def test_counts_bullets_with_style_level_numbering(self):
        # A resume whose bullets are numbered by the PARAGRAPH STYLE (e.g.
        # Word built-in "List Bullet": <w:numPr> lives in styles.xml, not on
        # the paragraph) has no paragraph numId. _roles must count those via
        # BULLET_STYLES, or a style-numbered resume reports bullets=0 and the
        # reclaim plan is empty.
        body = _body([
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, Phoenix, AZ02/2019 – 04/2020",
                  style=mr.COMPANY_STYLE),
            _para("Bullet one", style="ListBullet"),
            _para("Bullet two", style="ListBullet"),
            _para(mr.SECTION_EDUCATION, style="SectionHeading"),
        ])
        roles = mr._roles(body)
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]["bullets"], 2,
                         "style-numbered bullets must count via BULLET_STYLES")

    def test_bullet_styles_is_configurable(self):
        # User-defined bullet style (not in the default tuple): counting
        # follows BULLET_STYLES, so a custom list style is honored.
        saved = mr.BULLET_STYLES
        try:
            mr.BULLET_STYLES = ("MyBullet",)
            body = _body([
                _para(mr.SECTION_CAREER, style="SectionHeading"),
                _para("Company ABC, Phoenix, AZ02/2019 – 04/2020",
                      style=mr.COMPANY_STYLE),
                _para("Bullet one", style="MyBullet"),
                _para(mr.SECTION_EDUCATION, style="SectionHeading"),
            ])
            roles = mr._roles(body)
        finally:
            mr.BULLET_STYLES = saved
        self.assertEqual(roles[0]["bullets"], 1)

    def test_parses_alternative_resume_via_constants(self):
        # A DIFFERENT resume: different section names, role-header style,
        # and ISO dates. Only the constants change — the logic must adapt.
        saved = (mr.SECTION_CAREER, mr.SECTION_EDUCATION,
                 mr.COMPANY_STYLE, mr.DATE_RE)
        try:
            mr.SECTION_CAREER = "Work History"
            mr.SECTION_EDUCATION = "Training"
            mr.COMPANY_STYLE = "RoleHeader"
            mr.DATE_RE = re.compile(r"\d{4}-\d{2}")
            body = _body([
                _para("Work History", style="SectionHeading"),
                _para("Widgets Inc2024-03 – 2025-01", style="RoleHeader"),
                _para("Shipped the thing", numId=1),
                _para("Training", style="SectionHeading"),
            ])
            roles = mr._roles(body)
        finally:
            (mr.SECTION_CAREER, mr.SECTION_EDUCATION,
             mr.COMPANY_STYLE, mr.DATE_RE) = saved
        self.assertEqual(len(roles), 1)
        r = roles[0]
        self.assertEqual(r["key"], "Widgets Inc")
        self.assertEqual(r["bullets"], 1)
        self.assertFalse(r["has_tools"])


if __name__ == "__main__":
    unittest.main()