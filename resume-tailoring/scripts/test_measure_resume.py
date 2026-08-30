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

    def test_roles_capture_bullet_texts_in_order(self):
        # The DROP PLAN needs the actual bullet texts (not just a count) to
        # rank weakest-first and emit copy-pasteable find_p prefixes.
        roles = mr._roles(self._default_body())
        self.assertEqual(roles[0]["bullet_texts"], ["Bullet one", "Bullet two"])

    def test_bullet_texts_excludes_tools_line(self):
        # A Tools line is not a cuttable bullet and must not be ranked.
        roles = mr._roles(self._default_body())
        self.assertNotIn("Tools & Technologies: Java, SQL",
                         roles[0]["bullet_texts"])

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


class LayoutAndReclaimTests(unittest.TestCase):
    """New page-fill / measured-cost / batch-plan helpers."""

    def test_measured_lines_per_bullet(self):
        # A: 8 rendered lines, 2 bullets, no tools -> (8-2)/2 = 3 each
        # B: 5 rendered lines, 1 bullet, tools -> (5-2-1)/1 = 2
        # avg = (6+2)/3 = 8/3
        matched = [
            ({"key": "A", "bullets": 2, "has_tools": False}, 1, 1, 8),
            ({"key": "B", "bullets": 1, "has_tools": True}, 1, 2, 5),
        ]
        per = mr._measured_lines_per_bullet(matched)
        self.assertAlmostEqual(per, 8 / 3, places=6)

    def test_reclaim_batch_oldest_first_whole_role(self):
        # gap=5: oldest role has 1 bullet -> recommend dropping the whole
        # role (header+tools+bullet ~6 lines) before touching newer roles.
        matched = [
            {"key": "GEICO", "bullets": 8, "has_tools": True},
            {"key": "Oldest", "bullets": 1, "has_tools": True},
        ]
        # Match the (r, sp, ep, rendered) tuple shape used by main().
        wrapped = [(d, 1, 1, 26 if d["key"] == "GEICO" else 6) for d in matched]
        plan, remaining = mr._reclaim_batch(wrapped, 2.5, 5)
        self.assertEqual(plan[0][0], "Oldest")
        self.assertIn("whole role", plan[0][1])
        self.assertLessEqual(remaining, 0)

    def test_reclaim_batch_single_bullet_cuts_in_order(self):
        matched = [
            {"key": "Newer", "bullets": 3, "has_tools": True},
            {"key": "Middle", "bullets": 2, "has_tools": True},
            {"key": "Old", "bullets": 1, "has_tools": True},
        ]
        wrapped = [
            (d, i, i, 5) for i, d in enumerate(matched, start=1)
        ]
        plan, _ = mr._reclaim_batch(wrapped, 2.5, 6)
        # Oldest first: Old (whole role, 5), then Middle (1 bullet, 2.5).
        self.assertEqual([p[0] for p in plan], ["Old", "Middle"])
        self.assertIn("drop 1 bullet", plan[1][1])

    def test_layout_hints_detects_widow_header(self):
        # Role header is the LAST line of page 1; its body starts page 2.
        pages = ["Header line\nRole B, City\n", "bullet one\nbullet two\n"]
        matched = [({"key": "Role B, City", "bullets": 2, "has_tools": False}, 2, 2, 2)]
        hints = mr._layout_hints(matched, pages, capacity=2)
        self.assertTrue(any("WIDOW" in h for h in hints))

    def test_layout_hints_flags_underfilled_page(self):
        # page 1 holds 1 line (very underfilled); page 2 starts a role.
        pages = ["only line\n", "Role C, City\nbullet\n"]
        matched = [({"key": "Role C, City", "bullets": 1, "has_tools": False}, 2, 2, 2)]
        hints = mr._layout_hints(matched, pages, capacity=5)
        self.assertTrue(any("underfilled" in h for h in hints))


class DropPlanTests(unittest.TestCase):
    """The DROP PLAN turns each "drop N bullet(s)" reclaim line into the
    ACTUAL bullets to cut — ranked weakest-first by a deterministic scorer,
    emitted as copy-pasteable find_p(ps, "...") lines. The session's
    cut-render-cut loop existed because the batch plan said how many to
    drop but never which."""

    def test_weakest_are_generic_phrases_without_numbers(self):
        # Quantified bullets are the strongest (hard numbers); generic
        # process phrasing without numbers is the weakest.
        bullets = [
            "Established weekly cross-team meetings",
            "Drove a 50% reduction in pipeline errors",
            "Coordinated across engineering teams",
            "Reduced open backlog by over 90%",
        ]
        drops = mr._suggest_drops(bullets, 2)
        self.assertEqual(drops, ["Established weekly cross-team meetings",
                                 "Coordinated across engineering teams"])

    def test_tie_breaks_toward_longer_text(self):
        # Within the same weakness bucket, dropping the longer bullet saves
        # more rendered lines per cut.
        bullets = [
            "Enhanced documentation quality",
            "Enhanced documentation quality and clarified the review process "
            "across all three teams",
        ]
        drops = mr._suggest_drops(bullets, 1)
        self.assertEqual(drops, [bullets[1]])

    def test_quantified_bullets_never_suggested_while_weak_remain(self):
        bullets = [
            "Implemented a native Go integration test measurement tool that "
            "ran during CI to measure exercised code",
            "Decreased run times by 50% across the department",
            "Created automated weekly report reducing lead time by over 90%",
        ]
        # Budget 1: only the non-quantified bullet exists to suggest — the
        # quantified ones rank stronger and stay out of the cut list.
        drops = mr._suggest_drops(bullets, 1)
        self.assertEqual(drops, [bullets[0]])

    def test_drop_plan_lines_resolve_to_the_weakest_bullet(self):
        # The emitted line is copy-pasteable: its find_p prefix, run against
        # the role's paragraphs, resolves to the suggested bullet.
        weak = "Established weekly cross-team meetings"
        strong = "Drove a 50% reduction in pipeline errors"
        lines = mr._drop_plan_lines([weak, strong], 1)
        self.assertEqual(len(lines), 1)
        prefix = lines[0].split('"')[1]
        body = _body([
            _para(weak, numId=1),
            _para(strong, numId=1),
        ])
        found = de.find_p(de.paras(body), prefix)
        self.assertEqual(de.text_of(found), weak)

    def test_empty_suggestion_returns_no_lines(self):
        self.assertEqual(mr._drop_plan_lines([], 2), [])
        self.assertEqual(mr._suggest_drops([], 3), [])

    def test_protected_phrases_never_suggested(self):
        # The scorer cannot know the JD — a --protect phrase (e.g. "partner
        # integrations") keeps JD-critical bullets out of the cut list no
        # matter how generic they score. Without it, the weakest-first rank
        # would suggest the user's best JD evidence.
        bullets = [
            "Tested American Express partner integrations against their sandbox",
            "Established bi-monthly interdepartmental QA meetings",
        ]
        drops = mr._suggest_drops(bullets, 1, protect=("partner integrations",))
        self.assertEqual(drops, [bullets[1]])

    def test_protect_matches_without_protection(self):
        bullets = ["Established weekly meetings"]
        self.assertEqual(mr._suggest_drops(bullets, 1), bullets)

    def test_weakness_ranking_covers_generic_phrases(self):
        """GENERIC_PHRASES is the live code path; assert it classifies all
        entries as weak (lower score than quantified text of equal length).
        A single test that every phrase triggers the generic branch is
        cheaper than 14 separate tests and catches typos in the list."""
        quantified = "Drove 49% reduction in pipeline errors"
        q_key = mr._weakness_key(quantified)
        for phrase in mr.GENERIC_PHRASES:
            with self.subTest(phrase=phrase):
                weak_text = f"{phrase.capitalize()} weekly cross-team status"
                self.assertLess(
                    mr._weakness_key(weak_text), q_key,
                    f"'{phrase}' should rank weaker than a quantified bullet",
                )

    def test_drop_plan_lines_respect_protect(self):
        bullets = ["Explored partner integrations in sandbox", "Some generic bullet"]
        lines = mr._drop_plan_lines(bullets, 1, protect=("partner integrations",))
        self.assertEqual(len(lines), 1)
        self.assertIn("Some generic bullet", lines[0])

    def test_drop_sections_map_plan_to_role_bullets(self):
        # Each "drop N bullet(s)" plan entry becomes a DROP PLAN section
        # naming the exact bullets; "consider dropping the whole role"
        # entries yield no per-bullet lines.
        plan = [
            ("Company B, City", "drop 1 bullet(s) (saves ~2 lines)", 2.0),
            ("Company C, City", "consider dropping the whole role (saves ~9 lines)", 9.0),
        ]
        roles = [
            {"key": "Company B, City", "bullet_texts": [
                "Established weekly cross-team meetings",
                "Drove a 50% reduction in pipeline errors"]},
            {"key": "Company C, City", "bullet_texts": ["Only bullet"]},
        ]
        sections = mr._drop_sections(plan, roles)
        self.assertEqual(len(sections), 1)
        self.assertIn("Company B, City", sections[0])
        self.assertIn("find_p(ps,", sections[0])
        self.assertNotIn("Company C, City", sections[0])

    def test_drop_sections_respect_whole_role_entries(self):
        # A plan entry that removes the whole role does NOT suggest bullets
        # (the header/tools save more than any single bullet).
        plan = [("Company A", "consider dropping the whole role (saves ~10 lines)", 10.0)]
        roles = [{"key": "Company A", "bullet_texts": ["Some bullet"]}]
        self.assertEqual(mr._drop_sections(plan, roles), [])


class VisibleSpanTests(unittest.TestCase):
    """_visible_span parses company-header date ranges into a span."""

    def test_mm_yyyy_dates(self):
        first, last = mr._visible_span([
            "GEICO, MD (Remote)06/2025 – 07/2026",
            "Republic, AZ02/2019 – 04/2020",
        ])
        self.assertAlmostEqual(first, 2019 + 1 / 12, places=2)
        self.assertAlmostEqual(last, 2026 + 6 / 12, places=2)

    def test_iso_dates(self):
        saved = mr.DATE_RE
        try:
            mr.DATE_RE = re.compile(r"\d{4}-\d{2}")
            first, last = mr._visible_span([
                "Widgets Inc2024-03 – 2025-01",
            ])
        finally:
            mr.DATE_RE = saved
        self.assertAlmostEqual(first, 2024 + 2 / 12, places=2)
        self.assertAlmostEqual(last, 2025, places=2)

    def test_no_dates_none(self):
        self.assertEqual(mr._visible_span(["no date here"]), (None, None))

    def test_empty_headers_none(self):
        self.assertEqual(mr._visible_span([]), (None, None))


if __name__ == "__main__":
    unittest.main()