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

# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name
# wrong-import-position: sibling imports follow the sys.path bootstrap
#   (flat namespace; spec 2026-09-07-pylint-clean-refactor).
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.
#
import contextlib
import io
import os
import re
import sys
import tempfile
import types
import unittest
import zipfile

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import docx_edit as de  # noqa: E402
import test_helpers
import measure_resume as mr  # noqa: E402
import measure_resume_jd  # noqa: E402
import measure_resume_format as mrf  # noqa: E402  (constants live here post-split)

# Format-assumption constants are READ through the owning module's globals
# (mr.* aliases the same objects), so white-box patches target mrf.
MR_PATCH = mrf

W = de.W


_para = test_helpers._para
_body = test_helpers._body
_write_docx = test_helpers._write_docx


def _sample_date():
    """A date token the CURRENT DATE_RE matches (MM/YYYY or ISO), so fixtures
    work under either format and the structural tests stay green after a
    legit constants re-config."""
    for cand in ("07/2014", "2014-07"):
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
            mr._company_key("Company ABC, Phoenix, AZ06/2013 – 08/2016"),
            "Company ABC, Phoenix, AZ",
        )

    def test_custom_date_pattern(self):
        saved = mr.DATE_RE
        try:
            mrf.DATE_RE = re.compile(r"\d{4}-\d{2}")
            self.assertEqual(
                mr._company_key("Widgets Inc2024-03 – 2025-01"),
                "Widgets Inc",
            )
        finally:
            mrf.DATE_RE = saved


class RolesTests(unittest.TestCase):
    """_roles finds roles between the career/education sections."""

    def _default_body(self):
        """The reference resume's structure, built from the CURRENT constants
        (so the suite stays green after a legitimate constants re-config)."""
        return _body([
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, Phoenix, AZ" + _sample_date() + " — 08/2016",
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
            _para("Company ABC, Phoenix, AZ07/2014 – 08/2016",
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
            mrf.BULLET_STYLES = ("MyBullet",)
            body = _body([
                _para(mr.SECTION_CAREER, style="SectionHeading"),
                _para("Company ABC, Phoenix, AZ07/2014 – 08/2016",
                      style=mr.COMPANY_STYLE),
                _para("Bullet one", style="MyBullet"),
                _para(mr.SECTION_EDUCATION, style="SectionHeading"),
            ])
            roles = mr._roles(body)
        finally:
            mrf.BULLET_STYLES = saved
        self.assertEqual(roles[0]["bullets"], 1)

    def test_parses_alternative_resume_via_constants(self):
        # A DIFFERENT resume: different section names, role-header style,
        # and ISO dates. Only the constants change — the logic must adapt.
        saved = (mr.SECTION_CAREER, mr.SECTION_EDUCATION,
                 mr.COMPANY_STYLE, mr.DATE_RE)
        try:
            mrf.SECTION_CAREER = "Work History"
            mrf.SECTION_EDUCATION = "Training"
            mrf.COMPANY_STYLE = "RoleHeader"
            mrf.DATE_RE = re.compile(r"\d{4}-\d{2}")
            body = _body([
                _para("Work History", style="SectionHeading"),
                _para("Widgets Inc2024-03 – 2025-01", style="RoleHeader"),
                _para("Shipped the thing", numId=1),
                _para("Training", style="SectionHeading"),
            ])
            roles = mr._roles(body)
        finally:
            (mrf.SECTION_CAREER, mrf.SECTION_EDUCATION,
             mrf.COMPANY_STYLE, mrf.DATE_RE) = saved
        self.assertEqual(len(roles), 1)
        r = roles[0]
        self.assertEqual(r["key"], "Widgets Inc")
        self.assertEqual(r["bullets"], 1)
        self.assertFalse(r["has_tools"])


class WrappedToolsBudgetTests(unittest.TestCase):
    """_wrapped_tools reports the MEASURED trim budget (value chars vs the
    first-rendered-line capacity), not a fixed "~N tools" guess. Session
    failure: two trim passes were needed because the wrap width was guessed
    (~45-48 chars) from a proportional-font render where no fixed count is
    right — the wrap point itself is the only honest budget."""

    KEY = "Company ABC, Phoenix, AZ"
    VALUE = "Go, Python, JavaScript, TypeScript, Azure Service Bus"

    def _flat(self, first_value, continuation):
        first = "   Tools & Technologies: " + first_value
        lines = [
            (1, "Career Experience", "    Career Experience"),
            (1, self.KEY, self.KEY + "06/2025 - 07/2026"),
            (1, "Bullet one", "   Bullet one"),
            (1, mr._norm(first), first),
        ]
        lines += [(1, mr._norm(c), "       " + c) for c in continuation]
        lines += [(2, mr.SECTION_EDUCATION,
                   "    " + mr.SECTION_EDUCATION)]
        return lines

    def _matched(self):
        return [({"key": self.KEY, "has_tools": True}, 1, 2, 5)]

    def test_reports_value_chars_capacity_and_overflow(self):
        # The PDF broke the line after 'TypeScript,' (35 value chars on the
        # first rendered line); the full value is 53 chars → cut ~18.
        flat = self._flat("Go, Python, JavaScript, TypeScript,",
                          ["Azure Service Bus"])
        got = mr._wrapped_tools(flat, self._matched())
        self.assertEqual(len(got), 1)
        key, value_chars, capacity, preview = got[0]
        self.assertEqual(key, self.KEY)
        self.assertEqual(value_chars, len(self.VALUE))
        self.assertEqual(capacity, len("Go, Python, JavaScript, TypeScript,"))
        self.assertEqual(value_chars - capacity, 18)
        self.assertTrue(preview.startswith("Tools & Technologies:"))

    def test_single_line_tools_not_reported(self):
        # No continuation before the boundary → no wrap, no entry.
        flat = self._flat(self.VALUE, [])
        self.assertEqual(mr._wrapped_tools(flat, self._matched()), [])

    def test_multi_line_continuation_joined(self):
        flat = self._flat(
            "Go, Python, JavaScript,",
            ["TypeScript, Azure", "Service Bus"])
        _key, value_chars, capacity, _preview = mr._wrapped_tools(
            flat, self._matched())[0]
        self.assertEqual(value_chars, len(self.VALUE))
        self.assertEqual(capacity, len("Go, Python, JavaScript,"))


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
            {"key": "Recent", "bullets": 8, "has_tools": True},
            {"key": "Oldest", "bullets": 1, "has_tools": True},
        ]
        # Match the (r, sp, ep, rendered) tuple shape used by main().
        wrapped = [(d, 1, 1, 26 if d["key"] == "Recent" else 6) for d in matched]
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
    emitted as copy-pasteable find_p(ps, "...") lines. The original
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
            "Tested partner integrations against their sandbox",
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


class TopRoleBatchTests(unittest.TestCase):
    """_top_role_batch: the most-recent role's trim batch, emitted when the
    deterministic plan cannot close the gap.

    THE motivating failure (a Principal-level tailoring session): the master's
    most-recent role held 23 bullets / 63 rendered lines, every older-role
    budget was a dead end, and the tool's BATCH RECLAIM PLAN still could
    not reach the 3-page target. Nothing in the output covered the top
    role, so the author had to invent levers — headless replays
    showed agents filling the vacuum with hand-shortening (rewriting kept
    bullets from two rendered lines to one), the lowest-leverage edit in
    the skill. Enforcement moved into the tool: when TOP-BLOCK + Tools
    de-wraps + feasible oldest cuts fall short, measure emits the top
    role's weakest UNPROTECTED bullets in the same copy-pasteable find_p
    format, so the authoring plan is a sum of tool-named removals.
    """

    def setUp(self):
        # Document order: most-recent role FIRST. Recent is the bloated top
        # role; the two oldest roles are dead ends (all bullets protected).
        self.matched = [
            ({"key": "Recent", "bullets": 5, "has_tools": True,
              "bullet_texts": [
                  "Wrote scripts for storing build artifacts in the registry",
                  "Demoed release process improvements at team meetings",
                  "Updated the team wiki page weekly",
                  "Landed Playwright as the company UI testing tool",
                  "Configured Playwright pipelines for cross-repo runs"]},
             1, 2, 30),
            ({"key": "Middle", "bullets": 2, "has_tools": True,
              "bullet_texts": [
                  "Landed Playwright as the company UI testing tool",
                  "Configured Playwright pipelines for cross-repo runs"]},
             2, 2, 10),
            ({"key": "Old", "bullets": 2, "has_tools": True,
              "bullet_texts": [
                  "Landed Playwright as the company UI testing tool",
                  "Configured Playwright pipelines for cross-repo runs"]},
             3, 3, 10),
        ]
        self.jd = ("playwright",)

    def test_emits_batch_sized_to_residual_gap(self):
        # required=20. Old and Middle are TRUE dead ends (both bullets
        # JD-protected -> feasible 0). Tools de-wraps (2) + top-block (2)
        # = 4 feasible. Residual 16 -> ceil(16/2.5)=7 bullets wanted,
        # capped at Recent's 3 unprotected.
        plan = [
            ("Old", "drop 2 bullet(s) (saves ~5 lines)", 5.0),
            ("Middle", "drop 2 bullet(s) (saves ~5 lines)", 5.0),
        ]
        budget = mr.Budget(per=2.5, required=20, tools_savings=2,
                           top_block_count=2)
        batch, adjusted, feasible = mr._top_role_batch(
            self.matched, plan, budget, jd_terms=self.jd)
        self.assertIsNotNone(batch)
        self.assertEqual(batch[0], "Recent")
        self.assertIn("drop 3 bullet(s)", batch[1])  # capped at 5-2=3 unprotected
        self.assertAlmostEqual(batch[2], 3 * 2.5)
        # Dead-end entries for the OTHER roles survive (they print the
        # honest infeasibility note); no Recent entry to double-count.
        self.assertEqual([p[0] for p in adjusted], ["Old", "Middle"])
        self.assertAlmostEqual(feasible, 4.0)

    def test_no_batch_when_feasible_cuts_close_the_gap(self):
        plan = [("Old", "drop 2 bullet(s) (saves ~5 lines)", 5.0)]
        budget = mr.Budget(per=2.5, required=4, tools_savings=4,
                           top_block_count=1)
        batch, _adjusted, feasible = mr._top_role_batch(
            self.matched, plan, budget, jd_terms=set())
        self.assertIsNone(batch)
        # feasible = 2 unprotected * 2.5 + 4 tools + 1 top-block = 10
        self.assertAlmostEqual(feasible, 10.0)

    def test_no_batch_when_top_role_fully_protected(self):
        matched = [({"key": "Recent", "bullets": 2, "has_tools": True,
                     "bullet_texts": ["Landed Playwright as the company UI "
                                       "testing tool"]}, 1, 1, 8)]
        plan = []
        budget = mr.Budget(per=2.5, required=10, tools_savings=0,
                           top_block_count=0)
        batch, _adjusted, _feasible = mr._top_role_batch(
            matched, plan, budget, jd_terms=("playwright",))
        self.assertIsNone(batch)

    def test_protected_section_lists_top_role_bullets_with_terms(self):
        # The fallback for a fully-protected top role: every matched bullet
        # with ITS OWN matched terms, so a generic-match false positive
        # ('new', 'build') is visibly weak and the human rule can override
        # protection deliberately. This is the evidence the session that
        # motivated it lacked — the tool said 'no unprotected bullet to
        # give' and the author hand-picked cuts with no data.
        section = mr._protected_top_role_section(self.matched, self.jd)
        self.assertIsNotNone(section)
        self.assertIn("TOP-ROLE PROTECTED BULLETS", section)
        self.assertIn("Landed Playwright as the company UI testing tool",
                      section)
        self.assertIn("[playwright]", section)
        # Off-JD bullets of the top role are NOT listed (they were already
        # available as cuttable; the listing covers only protected ones).
        self.assertNotIn("Wrote scripts for storing build artifacts",
                         section)

    def test_protected_section_none_without_jd(self):
        self.assertIsNone(mr._protected_top_role_section(self.matched, set()))

    def test_protected_section_none_when_no_matches(self):
        matched = [({"key": "Recent", "bullets": 1, "has_tools": True,
                     "bullet_texts": ["Updated the team wiki page weekly"]},
                    1, 1, 5)]
        self.assertIsNone(mr._protected_top_role_section(
            matched, ("playwright",)))

    def test_superseded_top_role_entry_removed_from_plan(self):
        # If the oldest-first loop reached the top role with a dead-end
        # budget, the batch replaces it (one authoritative sizing).
        plan = [("Recent", "drop 8 bullet(s) (saves ~20 lines)", 20.0)]
        budget = mr.Budget(per=2.5, required=40, tools_savings=0,
                           top_block_count=0)
        batch, adjusted, _feasible = mr._top_role_batch(
            self.matched, plan, budget, jd_terms=set())
        self.assertIsNotNone(batch)
        self.assertEqual(adjusted, [])

    def test_batch_section_renders_with_custom_header(self):
        batch = ("Recent", "drop 2 bullet(s) (saves ~5 lines)", 5.0)
        role = self.matched[0][0]
        header = "TOP-ROLE TRIM BATCH (Recent; closes the residual gap "
        bullets = role.get("bullet_texts") or []
        lines = mr._drop_plan_lines(bullets, 2, protect=(), jd_terms=self.jd)
        jd_listing = mr._jd_listing_lines(bullets, self.jd)
        section = mr._batch_section(batch, role, header, lines, jd_listing)
        self.assertIn("TOP-ROLE TRIM BATCH (Recent", section)
        self.assertIn("find_p(ps,", section)
        # Protected (Playwright) bullets are not suggested.
        self.assertNotIn("Championed internal tooling", section)


class JDAwareTests(unittest.TestCase):
    """--jd makes the DROP PLAN JD-aware: bullets whose text matches a
    candidate-tech term the JD asks for (Cypress, Gatling, Jenkins, ...) or
    a named JD practice (mentorship, shift-left) must NOT be suggested for
    cutting while any non-matching bullet remains. The motivating failure:
    the JD-blind scorer ranked 'Championed the adoption of Cypress' and
    'Created performance tests using Gatling' (both directly named JD quals)
    as weak, and silently cut a 'Mentored junior team member' bullet that
    the JD's 'Mentor junior QA engineers' requires."""

    def _prof_body(self):
        """Resume with a Technical Proficiencies block, a Tools line, and a
        job-title paragraph (the vocabulary sources for --jd terms)."""
        return _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Programming Languages: Java, C#, JavaScript, Python"),
            _para("API & Web Services: REST, SOAP, SQL"),
            _para("Automation Testing Frameworks: Karate, Cypress, Playwright, "
                    "Gatling, Selenium"),
            _para("CI/CD: Jenkins, CircleCI, GitHub Actions, Azure DevOps"),
            _para("Certifications", style="SectionHeading"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Senior SDET", style="JobTitleBlock"),
            _para("Championed the adoption of Cypress, co-architecting the "
                    "initial framework", numId=2),
            _para("Created performance tests using Gatling", numId=2),
            _para("Established weekly cross-team meetings", numId=2),
            _para("Tools & Technologies: Cypress, JavaScript, Gatling, Jenkins"),
            _para(mr.SECTION_EDUCATION, style="SectionHeading"),
        ])

    def test_jd_terms_intersect_proficiencies_with_jd(self):
        jd = "Hands-on Selenium, Cypress, or Playwright. CI/CD with Jenkins " \
             "or GitHub Actions. Performance testing with Gatling."
        terms = mr._jd_terms(jd, self._prof_body())
        for want in ("cypress", "playwright", "jenkins", "gatling",
                     "github actions"):
            self.assertIn(want, terms, f"{want!r} must be a JD-matched term")

    def test_jd_terms_protect_named_tech_when_not_generic(self):
        # Tech words are NOT stopwords: a JD that names Java/Python/REST
        # makes them JD terms (whole-word, capitalized), so bullets using
        # them stop falling to the cut list. They only stay excluded when
        # the generic-hit-rate guard fires (term hits >50% of bullets).
        jd = "Java, Python, C# programming. SQL and REST APIs."
        terms = mr._jd_terms(jd, self._prof_body())
        for want in ("java", "python", "c#", "sql", "rest"):
            self.assertIn(want, terms, f"{want!r} must be a JD-matched term")

    def test_jd_terms_generic_hit_rate_guard(self):
        # A term that hits more than half the bullets is prose, not
        # technology: it must be dropped even though the JD names it,
        # otherwise the DROP PLAN floods and stalls. (Own fixture: label
        # vocabulary now makes 'automation' a real term, so the bullets
        # must genuinely repeat it for the guard to fire.)
        body = _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Automation Tooling: Selenium, Postman"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Senior SDET", style="JobTitleBlock"),
            _para("Championed the adoption of Cypress automation", numId=2),
            _para("Created automation using Gatling", numId=2),
            _para("Established weekly automation meetings", numId=2),
            _para(mr.SECTION_EDUCATION, style="SectionHeading"),
        ])
        for extra in ("Ran automation suites nightly",
                      "Reviewed automation coverage reports",
                      "Trained peers on automation tooling",
                      "Logged automation defects in Jira"):
            body.append(_para(extra, numId=2))
        jd = "Testing, automation, and framework ownership required. " \
             "Cypress experience a plus."
        terms = mr._jd_terms(jd, body)
        # 'cypress' hits 1 of 7 bullets — survives.
        self.assertIn("cypress", terms)
        # 'automation' hits 7 of 7 bullets — guard-dropped.
        self.assertNotIn("automation", terms,
                         "hits most bullets — must be guard-dropped")

    def test_jd_terms_include_title_vocab(self):
        # 'sdet' comes from the job title line, not the proficiency block.
        jd = "Five or more years as an SDET."
        terms = mr._jd_terms(jd, self._prof_body())
        self.assertIn("sdet", terms)

    def test_jd_terms_include_bullet_only_tool(self):
        # A tool the candidate uses ONLY in a bullet (e.g. Snyk folded into
        # the master, absent from the proficiency list) must still be a JD
        # term when the JD names it — otherwise the Snyk bullet falls to the
        # cut list, the very JD-blind bug --jd exists to fix.
        body = _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Programming Languages: Java, C#, JavaScript, Python"),
            _para("Certifications", style="SectionHeading"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Senior SDET", style="JobTitleBlock"),
            _para("Adhered high-priority compliance and configured Snyk "
                  "for team repositories", numId=2),
            _para("Tools & Technologies: Java, SQL"),
            _para(mr.SECTION_EDUCATION, style="SectionHeading"),
        ])
        jd = "Exposure to security testing tools (OWASP ZAP, Burp Suite, " \
             "Snyk)."
        terms = mr._jd_terms(jd, body)
        self.assertIn("snyk", terms)

    def test_jd_terms_exclude_common_prose_words(self):
        # Prose words that appear in both the JD and a bullet (coverage,
        # stakeholders) must NOT become JD terms — that over-protects
        # everything and defeats the ranking.
        body = self._prof_body()
        body.append(_para("Increased test coverage and engaged stakeholders"))
        jd = "Drive continuous improvement of test coverage. Engage " \
             "stakeholders across the SDLC."
        terms = mr._jd_terms(jd, body)
        for banned in ("coverage", "stakeholders"):
            self.assertNotIn(banned, terms)

    def test_jd_terms_skip_short_or_numeric_tokens(self):
        self.assertNotIn("c", mr._jd_terms("C programming", self._prof_body()))

    def test_jd_matched_bullets_never_suggested_while_weak_remain(self):
        # The motivating failure: Cypress (JD Required qual) ranked weak and
        # landed on the cut list. With --jd it must be excluded.
        bullets = [
            "Championed the adoption of Cypress, co-architecting the initial "
            "framework",
            "Established weekly cross-team meetings",
        ]
        drops = mr._suggest_drops(bullets, 1, jd_terms={"cypress"})
        self.assertEqual(drops, [bullets[1]])

    def test_jd_matched_gatling_performance_bullet_kept(self):
        bullets = [
            "Created performance tests using Gatling, pinpointing a major "
            "issue in containerized services",
            "Established bi-monthly interdepartmental QA meetings",
        ]
        drops = mr._suggest_drops(bullets, 1, jd_terms={"gatling"})
        self.assertEqual(drops, [bullets[1]])

    def test_suggest_drops_without_jd_terms_is_unchanged(self):
        # Backward compat: no --jd means the old JD-blind ranking, where a
        # Cypress bullet (JD-relevant but unquantified) IS a cut candidate.
        bullets = [
            "Championed the adoption of Cypress",
            "Established weekly cross-team meetings",
        ]
        drops = mr._suggest_drops(bullets, 2)
        # Both are cut candidates without --jd; the generic one ranks weaker.
        self.assertIn(bullets[0], drops,
                      "without --jd the old JD-blind ranking must be unchanged")
        self.assertEqual(drops, [bullets[1], bullets[0]])

    def test_concept_mentorship_bullet_kept(self):
        # The motivating miss: a 'Mentored junior team member' bullet
        # was cut, but the JD requires mentoring. A JD practice phrase in
        # JD_CONCEPTS must keep it out of the cut list.
        bullets = [
            "Mentored junior team member resulting in their successful "
            "transition to an automation role",
            "Established weekly cross-team meetings",
        ]
        drops = mr._suggest_drops(bullets, 1)
        self.assertEqual(drops, [bullets[1]])

    def test_concept_hits_lists_matches(self):
        self.assertEqual(
            mr._concept_hits("Mentored a junior QA engineer one-on-one"),
            ["mentor"],
        )

    def test_drop_sections_notes_jd_kept_bullets(self):
        plan = [("Company ABC, City", "drop 1 bullet(s) (saves ~2 lines)", 2.0)]
        roles = [{"key": "Company ABC, City", "bullet_texts": [
            "Championed the adoption of Cypress frameworks across the team",
            "Established weekly cross-team meetings",
        ]}]
        sections = mr._drop_sections(
            plan, roles, jd_terms={"cypress"},
        )
        self.assertEqual(len(sections), 1)
        self.assertIn("JD-matched (kept)", sections[0])
        self.assertIn("Cypress frameworks", sections[0])
        dropped = [l for l in sections[0].splitlines() if "find_p(ps," in l]
        self.assertEqual(len(dropped), 1)
        self.assertIn("Established weekly", dropped[0])

    def test_drop_plan_lines_respect_jd_terms(self):
        bullets = ["Championed Cypress adoption", "Some generic bullet"]
        lines = mr._drop_plan_lines(bullets, 1, jd_terms={"cypress"})
        self.assertEqual(len(lines), 1)
        self.assertIn("Some generic bullet", lines[0])

    def test_weak_match_does_not_protect(self):
        # A term matching MORE than half a role's own bullets is weak
        # evidence (it cannot arbitrate between the role's bullets), so
        # bullets matched only by it stay cuttable. Motivating failure
        # (session 01a06fab): a testing JD's 'test' protected every bullet
        # of a tester role, the DROP PLAN dead-ended, and a 1-year top role
        # kept 16+ bullets while JD-relevant older-role bullets died.
        bullets = [
            "Primary test engineer for the NextGen platform.",
            "Coordinated test release images with internal IT.",
            "Proposed a continuous test plan to the department.",
            "Served as one of the first test engineers on the FDA product.",
        ]
        # 4 of 4 bullets contain the whole word 'test' -> weak -> unprotected.
        self.assertEqual(mr._protected_count(bullets, jd_terms={"test"}), 0)
        drops = mr._suggest_drops(bullets, 2, jd_terms={"test"})
        self.assertEqual(len(drops), 2)
        self.assertTrue(all(d in bullets for d in drops))

    def test_core_tech_noun_stays_strong_when_it_hits_all_bullets(self):
        # The weak rule must never weaken a specific technology noun:
        # a whole-role drop must not remove genuine 'playwright' evidence
        # just because the role is small (SKILL Step 3: JD evidence is the
        # rule, age the tiebreaker).
        bullets = [
            "Landed Playwright as the company UI testing tool",
            "Configured Playwright pipelines for cross-repo runs",
        ]
        self.assertEqual(mr._protected_count(bullets, jd_terms={"playwright"}), 2)
        drops = mr._suggest_drops(bullets, 1, jd_terms={"playwright"})
        self.assertEqual(drops, [])

    def test_drop_sections_lists_weak_matches_as_cuttable(self):
        plan = [("Company ABC, City", "drop 2 bullet(s) (saves ~4 lines)", 4.0)]
        bullets = [
            "Primary test engineer for the NextGen platform.",
            "Proposed a continuous test plan to the department.",
        ]
        sections = mr._drop_sections(
            plan, [{"key": "Company ABC, City", "bullet_texts": bullets}],
            jd_terms={"test"},
        )
        self.assertIn("weak-match (cuttable", sections[0])
        self.assertIn("[weak: test]", sections[0])
        dropped = [l for l in sections[0].splitlines() if "find_p(ps," in l]
        self.assertEqual(len(dropped), 2)  # both weak-match bullets cuttable

    def test_drop_sections_strong_match_still_listed_as_kept(self):
        plan = [("Company ABC, City", "drop 1 bullet(s) (saves ~2 lines)", 2.0)]
        bullets = [
            "Landed Playwright as the company UI testing tool",
            "Primary test engineer for the NextGen platform.",
            "Proposed a continuous test plan to the department.",
            "Coordinated test release images with internal IT.",
        ]
        sections = mr._drop_sections(
            plan, [{"key": "Company ABC, City", "bullet_texts": bullets}],
            jd_terms={"playwright", "test"},
        )
        self.assertIn("JD-matched (kept)", sections[0])
        self.assertIn("Landed Playwright", sections[0])
        self.assertIn("[weak: test]", sections[0])
        dropped = [l for l in sections[0].splitlines() if "find_p(ps," in l]
        self.assertEqual(len(dropped), 1)  # only the strong bullet protected


class JdHitsTests(unittest.TestCase):
    """_jd_hits: whole-word matching with plural tolerance."""

    def test_substring_no_longer_matches(self):
        # 'lead' must not match 'leader/leadership/leading'; 'flow' must
        # not match 'workflow' (the substring flood).
        self.assertEqual(mr._jd_hits("Mentored and led the leadership team "
                                     "through workflow redesign", {"lead",
                                     "flow"}), [])

    def test_whole_word_matches(self):
        self.assertEqual(mr._jd_hits("Cut lead time by 90%", {"lead"}),
                         ["lead"])

    def test_plural_term_matches_singular(self):
        # The JD asks for "API integrations", the bullet says "integration
        # test" — same evidence, plural stem must match.
        self.assertEqual(
            mr._jd_hits("Built an integration test suite", {"integrations"}),
            ["integrations"])

    def test_plural_stem_no_bogus_stem_match(self):
        # Stemming strips only a trailing 's': 'apis' legitimately matches
        # 'api', and a word whose stem is absent does not match.
        self.assertEqual(mr._jd_hits("the api layer", {"apis"}), ["apis"])
        self.assertEqual(mr._jd_hits("the api layer", {"tokens"}), [])

    def test_singular_term_matches_plural(self):
        # Bidirectional: the JD asks for 'integration' work, the bullet says
        # 'partner integrations' — same evidence (a past session: the
        # partner-integrations bullet was ranked for cutting while the
        # JD asked for 'API, service, integration, and backend validation').
        self.assertEqual(
            mr._jd_hits("Tested partner integrations", {"integration"}),
            ["integration"])

    def test_short_tech_term_matches_plural(self):
        # 'api' (len 3) must still match the plural 'APIs'.
        self.assertEqual(mr._jd_hits("Validated the REST APIs", {"api"}),
                         ["api"])

    def test_sentence_final_period_still_matches(self):
        # A term at sentence END was unmatchable: '.' sat in the token
        # class, so a bullet ending '...with Playwright.' read as off-JD.
        # A sentence-final period is a boundary, not a token char.
        self.assertEqual(mr._jd_hits("Built suites with Selenium.",
                                     {"selenium"}), ["selenium"])
        self.assertEqual(mr._jd_hits("rest api for c#. use it", {"c#"}),
                         ["c#"])

    def test_versioned_dot_stays_one_token(self):
        # The fix must not split versioned forms: 'node.js' stays one
        # token, so neither 'node' nor the trailing 'js' matches inside it.
        self.assertEqual(mr._jd_hits("the node.js runtime", {"node"}), [])
        self.assertEqual(mr._jd_hits("the node.js runtime", {"js"}), [])
        self.assertEqual(mr._jd_hits("built with Playwright.js", {"playwright"}),
                         [])


class JdCapitalizedTests(unittest.TestCase):
    """Bullet-only terms must be named as proper nouns in the JD."""

    def test_capitalized_mid_sentence_qualifies(self):
        self.assertTrue(mr._jd_capitalized(
            "Configure Snyk for dependency scanning. Snyk is a plus.", "snyk"))

    def test_lowercase_prose_rejected(self):
        self.assertFalse(mr._jd_capitalized(
            "you will be coordinating closely with partners", "closely"))

    def test_sentence_start_capital_rejected(self):
        # Every sentence starts capitalized — that is not evidence.
        self.assertFalse(mr._jd_capitalized(
            "Mentor junior engineers. Closely with clients.", "closely"))


class CoreTechNounTests(unittest.TestCase):
    """Core tech nouns are exempt from the bullet-only capitalization gate.

    A past session regressed here (a Playwright JD): the JD's
    'Perform API, service, integration, and backend validation' names
    'integration' lowercase mid-sentence, so the bullet-only term was
    rejected and the DROP PLAN suggested cutting the
    partner-integrations bullet — strong integration-testing evidence.
    The capitalization gate exists to block PROSE flood; these nouns can
    never be prose. The generic-hit-rate guard still applies.
    """

    def _body(self):
        return _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Programming Languages: Java, JavaScript"),
            _para("Certifications", style="SectionHeading"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Acme Corp, Austin, TX" + _sample_date() + " – 12/2023",
                  style=mr.COMPANY_STYLE),
            _para("Senior Quality Assurance Engineer", style="JobTitleBlock"),
            _para("Tested partner integrations against "
                  "their sandbox, coordinating with vendor engineers on "
                  "unexpected response codes", numId=2),
            _para("Established bi-monthly interdepartmental QA meetings",
                  numId=2),
            _para("Tools & Technologies: Java, Karate"),
            _para(mr.SECTION_EDUCATION, style="SectionHeading"),
        ])

    _JD = ("Perform API, service, integration, and backend validation. "
           "Validate end-to-end business workflows and system integrations.")

    def test_lowercase_integration_in_jd_is_a_term(self):
        terms = mr._jd_terms(self._JD, self._body())
        self.assertIn("integrations", terms)

    def test_partner_integration_bullet_is_jd_evidence(self):
        terms = mr._jd_terms(self._JD, self._body())
        partner_bullet = ("Tested partner integrations against "
                "their sandbox, coordinating with vendor engineers on "
                "unexpected response codes")
        self.assertTrue(mr._jd_kept(partner_bullet, terms),
                        "integration bullet must be JD-protected")

    def test_generic_hit_rate_guard_still_applies(self):
        # The exemption cannot flood: a core noun hitting most bullets is
        # still guard-dropped.
        body = _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Databases: SQL Server"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company A" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("SDET", style="JobTitleBlock"),
            _para("Validated database one", numId=2),
            _para("Validated database two", numId=2),
            _para("Validated database three", numId=2),
            _para("Unrelated meeting notes here", numId=2),
            _para(mr.SECTION_EDUCATION, style="SectionHeading"),
        ])
        for extra in ("Validated database four", "Validated database five",
                      "Validated database six"):
            body.append(_para(extra, numId=2))
        terms = mr._jd_terms("SQL and database validation required.", body)
        # 'sql' hits 0 of 7 bullets — survives; 'database' hits 6 of 7 —
        # the CORE_TECH_NOUNS exemption does not bypass the guard.
        self.assertIn("sql", terms)
        self.assertNotIn("database", terms, "hits >50% of bullets — guard")

    def test_prose_words_still_gated(self):
        # 'closely' is not a core tech noun: lowercase in the JD stays
        # rejected for bullet-only terms.
        jd = "you will be coordinating closely with partner teams"
        body = _body([
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company A" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("SDET", style="JobTitleBlock"),
            _para("Coordinating closely with partners", numId=2),
        ])
        self.assertNotIn("closely", mr._jd_terms(jd, body))


class LabelVocabEndToEndTests(unittest.TestCase):
    """Label words flow through _jd_terms: an 'API & Web Services'
    proficiencies line carries JD evidence when the JD asks for API work,
    so it must NOT be a TOP-BLOCK cut candidate."""

    def _body(self):
        return _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Programming Languages: Java, JavaScript"),
            _para("API & Web Services: REST, GraphQL, gRPC, SOAP"),
            _para("Certifications", style="SectionHeading"),
            _para("Performance Boot Camp: Vendor Academy"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Senior SDET", style="JobTitleBlock"),
            _para("Bullet one", numId=2),
        ])

    def test_api_label_line_is_jd_evidence_not_candidate(self):
        jd = "Deep hands-on expertise in API testing and backend validation."
        terms = mr._jd_terms(jd, self._body())
        self.assertIn("api", terms, "label vocabulary must reach _jd_terms")
        cands = mr._top_block_candidates(self._body(), terms)
        texts = [t for _p, t in cands]
        self.assertFalse(
            any("API & Web Services" in t for t in texts),
            f"API line must not be a cut candidate; candidates={texts}")

    def test_off_jd_label_lines_still_candidates(self):
        jd = "Deep hands-on expertise in API testing."
        terms = mr._jd_terms(jd, self._body())
        cands = mr._top_block_candidates(self._body(), terms)
        texts = [t for _p, t in cands]
        self.assertTrue(any("Performance Boot Camp" in t for t in texts))


class DeadEndTests(unittest.TestCase):
    """_dead_end_roles: a role whose DROP PLAN budget exceeds its
    unprotected bullets cannot meet the budget without cutting JD-matched
    content — surface that at the top so the fix is TOP-BLOCK cuts, a
    Tools-line trim, or a whole-role drop, not slicing kept bullets."""

    def test_all_protected_role_is_dead_end(self):
        plan = [("Company A", "drop 3 bullet(s) (saves ~6 lines)", 6)]
        roles = [{"key": "Company A",
                  "bullet_texts": ["Championed the adoption of Cypress",
                                   "Mentored junior QA engineers",
                                   "Owned the Karate framework"]}]
        dead = mr._dead_end_roles(plan, roles,
                                  protect=("Cypress", "Mentored", "Karate"))
        self.assertEqual(dead, ["Company A"])

    def test_partially_protected_role_is_not_dead_end(self):
        plan = [("Company A", "drop 1 bullet(s) (saves ~2 lines)", 2)]
        roles = [{"key": "Company A",
                  "bullet_texts": ["Championed the adoption of Cypress",
                                   "Established weekly meetings"]}]
        dead = mr._dead_end_roles(plan, roles, protect=("Cypress",))
        self.assertEqual(dead, [])

    def test_non_drop_plan_entries_ignored(self):
        plan = [("Company B",
                 "consider dropping the whole role (saves ~9 lines)", 9)]
        roles = [{"key": "Company B", "bullet_texts": ["Only bullet"]}]
        self.assertEqual(mr._dead_end_roles(plan, roles), [])

    def test_jd_terms_count_as_protection(self):
        plan = [("Company A", "drop 2 bullet(s) (saves ~4 lines)", 4)]
        roles = [{"key": "Company A",
                  "bullet_texts": ["Built the Playwright framework",
                                   "Wrote TypeScript page objects"]}]
        dead = mr._dead_end_roles(
            plan, roles,
            jd_terms={"playwright", "typescript"})
        self.assertEqual(dead, ["Company A"])


class LineTermsTests(unittest.TestCase):
    """_line_terms: the LABEL of a labeled line is part of the resume's
    claimed vocabulary too. A past session regressed here: the
    JD asked for API testing, but 'API' only appeared in the LABEL
    ('API & Web Services: REST, ...') which the old value-only splitter
    discarded — so the line carried 'no JD evidence' and landed on the
    TOP-BLOCK cut list."""

    def test_label_words_become_vocabulary(self):
        terms = mr._line_terms("API & Web Services: REST, GraphQL, gRPC")
        for want in ("api", "web", "services", "rest"):
            self.assertIn(want, terms, f"{want!r} must come from the label")

    def test_multiword_label_words(self):
        terms = mr._line_terms("Automation Testing Frameworks: Karate")
        for want in ("automation", "testing", "frameworks"):
            self.assertIn(want, terms)

    def test_short_label_words_included_len3(self):
        # 'api'/'sql' are length 3 and unambiguous tech terms.
        terms = mr._line_terms("Databases: SQL Server, PostgreSQL")
        self.assertIn("sql", terms)
        self.assertIn("databases", terms)

    def test_line_without_colon_whole_line_chunk(self):
        terms = mr._line_terms("Senior SDET")
        self.assertIn("senior sdet", terms)
        self.assertIn("sdet", terms)


class AcronymVocabTests(unittest.TestCase):
    """_line_terms/_acronym_terms: ALL-CAPS tokens of a labeled line are
    claimed vocabulary regardless of length. A 'CI/CD: Jenkins, ...' line
    must yield 'ci'/'cd', or a JD asking for 'CI' never intersects and
    tool-less CI bullets ('Re-architected CI from a degraded state...')
    mine as OFF-JD with nothing to protect them (a real Endpoint session
    cut CI evidence from every role this way)."""

    def test_label_acronyms_len2(self):
        terms = mr._line_terms("CI/CD: Jenkins, CircleCI, GitHub Actions")
        self.assertIn("ci", terms)
        self.assertIn("cd", terms)

    def test_chunk_acronyms_in_multword_lines(self):
        terms = mr._line_terms("Cloud & Containers: AWS, GCP, Azure, Docker")
        self.assertIn("aws", terms)
        self.assertIn("gcp", terms)

    def test_trailing_period_stripped_from_acronym(self):
        terms = mr._line_terms("Platform: KVM.")
        self.assertIn("kvm", terms)


class JdLineTermPeriodTests(unittest.TestCase):
    """_jd_line_terms: sentence-final periods must not survive inside a
    mined term. 'GitLab CI.' mined as 'gitlab ci.' — a form no resume can
    host — so the audit's no-host list carried it forever and the REAL
    ask ('CI') never matched (a real Endpoint session's no-host list
    showed 'ci.', 'vmware.', 'gcp.', 'parallels.')."""

    def test_trailing_period_stripped_from_seq(self):
        terms = mr._jd_line_terms(
            "CI experience with GitHub Actions, or a comparable system "
            "such as Jenkins or GitLab CI.")
        self.assertIn("gitlab ci", terms)
        self.assertNotIn("gitlab ci.", terms)

    def test_trailing_period_stripped_from_word(self):
        terms = mr._jd_line_terms(
            "Hands-on with a virtualization and provisioning stack — "
            "Packer image builds with QEMU/KVM, VMware, or Parallels.")
        self.assertIn("vmware", terms)
        self.assertNotIn("vmware.", terms)


class JunkQualTokenTests(unittest.TestCase):
    """Sentence-initial soft nouns of qual lines ('Sound judgment...",
    'Proficiency in Python...', 'Hands-on with...', 'Treat test...')
    must never mine as no-host 'gaps' — a real Endpoint session's list
    was half junk tokens, burying the real asks."""

    JD_LINES = [
        "Required Qualifications:",
        "Sound judgment on the test pyramid — where end-to-end coverage "
        "pays for itself.",
        "Proficiency in Python and/or TypeScript, with Playwright.",
        "Hands-on with a virtualization and provisioning stack — Packer "
        "image builds with QEMU/KVM.",
        "Treat test infrastructure as production software.",
        "Background in secure software development.",
        "Comfort incorporating AI-assisted tooling.",
    ]

    def test_junk_words_never_mine(self):
        terms = set()
        for line in self.JD_LINES:
            terms |= mr._jd_line_terms(line)
        for junk in ("sound", "proficiency", "hands", "treat",
                     "background", "comfort"):
            self.assertNotIn(junk, terms, f"{junk!r} is prose, not a skill")

    def test_real_tokens_on_same_lines_survive(self):
        terms = set()
        for line in self.JD_LINES:
            terms |= mr._jd_line_terms(line)
        self.assertIn("python", terms)
        self.assertIn("playwright", terms)
        self.assertIn("packer", terms)


class SoftSkillDetectionTests(unittest.TestCase):
    """JD_SOFT_SKILL_RE routes soft-skill asks to the action-verb rule;
    'reliability' (and friends) were missing, so a 'reliability' ask
    mined as a hard-skill term and reported a bare gap."""

    def test_reliability_detected_as_soft_skill(self):
        line = "Own the integration, performance, and reliability testing."
        self.assertTrue(mr.JD_SOFT_SKILL_RE.search(line))


class SessionGapFamilyTests(unittest.TestCase):
    """INFERENCE_FAMILIES additions: a real Endpoint JD's asks
    (performance/stress testing, OS platforms, endpoint security, VM
    tooling, GUI automation, secure SDLC) had real master evidence but
    no family, so the map reported bare gaps instead of candidates."""

    def _body(self):
        return _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Created performance and load testing suites using "
                  "Gatling.", numId=2),
            _para("Maintained Linux WSL and PowerShell tooling on the "
                  "team's desktop fleet.", numId=2),
        ])

    def test_performance_family(self):
        out = mr._inference_map(["stress testing"], self._body())
        self.assertIn("stress testing: CANDIDATE", "\n".join(out))

    def test_os_platform_family(self):
        out = mr._inference_map(["macos"], self._body())
        self.assertIn("macos: CANDIDATE", "\n".join(out))

    def test_gap_message_asks_the_user(self):
        out = mr._inference_map(["ontology"], self._body())
        joined = "\n".join(out)
        self.assertIn("ASK the user", joined)


class TopBlockCandidatesTests(unittest.TestCase):
    """_top_block_candidates: off-JD proficiencies/cert lines are
    first-class cut candidates."""

    def _body(self):
        ps = [
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Programming Languages: Java, Python"),
            _para("Monitoring & Logging: Datadog, Grafana"),
            _para("Certifications", style="SectionHeading"),
            _para("Performance Boot Camp: Vendor Academy"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Senior SDET", style="JobTitleBlock"),
            _para("Bullet one", numId=2),
        ]
        return _body(ps)

    def test_off_jd_lines_are_candidates(self):
        cands = mr._top_block_candidates(self._body(), jd_terms={"java"})
        texts = [t for _p, t in cands]
        self.assertTrue(any("Monitoring" in t for t in texts))
        self.assertTrue(any("Performance Boot Camp" in t for t in texts))

    def test_jd_matched_line_not_candidate(self):
        cands = mr._top_block_candidates(self._body(), jd_terms={"java"})
        texts = [t for _p, t in cands]
        self.assertFalse(any("Programming Languages" in t for t in texts))

    def test_prefixes_unique_and_pasteable(self):
        cands = mr._top_block_candidates(self._body(), jd_terms=set())
        for prefix, _t in cands:
            self.assertGreaterEqual(len(prefix), 6)

    def test_stops_at_career_region(self):
        cands = mr._top_block_candidates(self._body(), jd_terms=set())
        texts = [t for _p, t in cands]
        self.assertFalse(any(t.startswith("Company") for t in texts))
        self.assertFalse(any(t == "Bullet one" for t in texts))


def _docx_with_roles():
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)

    def p(text, style=None, numid=None):
        pPr = ""
        if style or numid:
            inner = ""
            if style:
                inner += f'<w:pStyle w:val="{style}"/>'
            if numid:
                inner += (f'<w:numPr><w:numId w:val="{numid}"/></w:numPr>')
            pPr = f'<w:pPr>{inner}</w:pPr>'
        return (f'<w:p>{pPr}<w:r><w:t xml:space="preserve">'
                f'{text}</w:t></w:r></w:p>')

    paras = [
        p(mr.SECTION_CAREER, style="SectionHeading"),
        p("Acme Corp, Springfield03/2022 – 02/2023", style=mr.COMPANY_STYLE),
        p("Staff Engineer", style="JobTitleBlock"),
        p("Led QA", style="BodyText", numid=4),
        p("Tools &amp; Technologies: Go", style="BodyText"),
        p("", style="BodyText"),
        p("Initech, Metropolis01/2017 – 06/2018", style=mr.COMPANY_STYLE),
        p("Software Test Engineer I", style="JobTitleBlock"),
        p("Tested data pipelines", style="BodyText", numid=8),
        p("Tools &amp; Technologies: MS Test", style="BodyText"),
        p("", style="BodyText"),
        p(mr.SECTION_EDUCATION, style="SectionHeading"),
        p("Some College", style=mr.COMPANY_STYLE),
        p("Bachelor's Degree", style="JobTitleBlock"),
    ]
    doc = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="' + de.XMLNS + '"><w:body>'
        + "".join(paras) + '</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("[Content_Types].xml", "<Types/>")
    return path


class ApplySimulateTests(unittest.TestCase):
    """_apply_simulate: seniority-alignment what-if — drop whole roles in a
    TEMP COPY and measure that, so the resulting visible timeline span is
    computed by the tool instead of by hand in chat. The original file must
    never be modified."""

    def test_drops_role_in_copy_original_untouched(self):
        src = _docx_with_roles()
        try:
            with open(src, "rb") as f:
                before = f.read()
            out = tempfile.mktemp(suffix=".docx")
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), \
                        contextlib.redirect_stderr(buf):
                    out_path, dropped = mr._apply_simulate(
                        src, ["Initech, Metropolis"], out)
                self.assertEqual(out_path, out)
                self.assertEqual(len(dropped), 1)
                self.assertIn("Initech", dropped[0])
                with open(src, "rb") as f:
                    self.assertEqual(f.read(), before,
                                     "original must never be modified")
                _, body, _, _, _ = de.load(out)
                texts = [de.text_of(p) for p in de.paras(body)]
                self.assertFalse(any("Initech" in t for t in texts))
                self.assertIn("Acme Corp, Springfield03/2022 – 02/2023", texts)
                self.assertIn(mr.SECTION_EDUCATION, texts)
            finally:
                for suffix in ("", ".drift.json"):
                    if os.path.exists(out + suffix):
                        os.unlink(out + suffix)
        finally:
            os.unlink(src)

    def test_missing_prefix_reported_not_dropped(self):
        src = _docx_with_roles()
        try:
            out = tempfile.mktemp(suffix=".docx")
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), \
                        contextlib.redirect_stderr(buf):
                    _out_path, dropped = mr._apply_simulate(
                        src, ["No Such Company"], out)
                self.assertEqual(dropped, [])
            finally:
                for suffix in ("", ".drift.json"):
                    if os.path.exists(out + suffix):
                        os.unlink(out + suffix)
        finally:
            os.unlink(src)


class RoleJdEvidenceTests(unittest.TestCase):
    """_role_jd_evidence_lines: --simulate must surface the JD evidence a
    whole-role drop would lose, so the trade-off is visible before approval
    (a real session dropped the strongest-evidence role for a JD that named
    that evidence). Generic data throughout: these tests verify the
    function's behavior, not any particular person's resume."""

    ROLES = [
        {"raw": "OldCorp, Springfield01/2010 – 12/2011",
         "bullet_texts": [
             "Tested one of the company's first FDA cleared products.",
             "Built traceability matrices for regulated projects.",
             "Maintained internal lab dashboards.",
         ]},
        {"raw": "RecentCo, Austin, TX (Remote)05/2020 – 02/2021",
         "bullet_texts": ["Built CI pipelines.", "Cut release time."]},
    ]

    def test_jd_evidence_loss_warned(self):
        lines = mr._role_jd_evidence_lines(
            self.ROLES, "OldCorp, Springfield01/2010 – 12/2011",
            {"fda", "traceability"})
        self.assertTrue(
            any("JD EVIDENCE LOST" in l and "2 JD-matched" in l
                for l in lines),
            f"expected evidence-loss warning, got: {lines}")
        self.assertTrue(any("FDA cleared" in l for l in lines))

    def test_clean_drop_candidate_noted(self):
        lines = mr._role_jd_evidence_lines(
            self.ROLES, "RecentCo, Austin, TX (Remote)05/2020 – 02/2021",
            {"fda"})
        self.assertEqual(len(lines), 1)
        self.assertIn("clean drop candidate", lines[0])

    def test_unknown_header_and_empty_terms_return_nothing(self):
        self.assertEqual(
            mr._role_jd_evidence_lines(self.ROLES, "No Such", {"fda"}), [])
        self.assertEqual(
            mr._role_jd_evidence_lines(
                self.ROLES,
                "RecentCo, Austin, TX (Remote)05/2020 – 02/2021", set()), [])


class ResolvedJdTermsTests(unittest.TestCase):
    """_resolved_jd_terms: --jd must stay JD-aware WITHOUT --simulate.

    Regression: main computed jd_terms only inside the --simulate block,
    so a plain `measure --jd` silently fell back to the JD-blind DROP
    PLAN (the "falling back to the JD-blind ranking" message looked like
    a file problem, not a tool bug). A real session misdiagnosed it as an
    extractor limitation and burned several tool calls debugging the
    wrong layer; the next session re-hit it."""

    def _body(self):
        path = _docx_with_roles()
        try:
            _root, body, _names, _data, _ = de.load(path)
            return body
        finally:
            os.unlink(path)

    def test_without_simulate_terms_computed_from_body(self):
        # "Software Test Engineer I" is JobTitleBlock vocab; a JD naming
        # it must yield that term even with no --simulate passed.
        terms = mr._resolved_jd_terms(
            "Senior software role; testing required.", self._body(),
            False, None)
        self.assertIn("software", terms)

    def test_with_simulate_uses_pre_drop_terms(self):
        # The simulate block pre-computes terms from the PRE-DROP body;
        # the helper passes them through untouched.
        self.assertEqual(
            mr._resolved_jd_terms(None, None, True, {"python"}), {"python"})

    def test_with_simulate_and_no_jd_yields_empty(self):
        self.assertEqual(mr._resolved_jd_terms(None, None, True, None), set())

    def test_no_jd_text_yields_empty_without_simulate(self):
        self.assertEqual(
            mr._resolved_jd_terms(None, self._body(), False, None), set())


class GapIfDroppedTests(unittest.TestCase):
    """_gap_if_dropped: interior whole-role drops open employment gaps."""

    def _roles(self):
        return [
            {"key": "acme", "raw": "Acme01/2024 – 06/2025"},
            {"key": "globex", "raw": "Globex09/2023 – 12/2023"},
            {"key": "initech", "raw": "Initech01/2022 – 08/2023"},
            {"key": "hooli", "raw": "Hooli03/2016 – 04/2017"},
        ]

    def test_interior_drop_opens_gap(self):
        # Dropping Globex leaves Initech (ends 08/2023) next to Acme
        # (starts 01/2024): a 5-month gap.
        self.assertEqual(mr._gap_if_dropped(self._roles(), "globex"), 5)

    def test_oldest_drop_no_gap(self):
        self.assertEqual(mr._gap_if_dropped(self._roles(), "hooli"), 0)

    def test_newest_drop_no_gap(self):
        self.assertEqual(mr._gap_if_dropped(self._roles(), "acme"), 0)

    def test_gapless_interior_drop_no_gap(self):
        roles = [
            {"key": "b", "raw": "B06/2017 – 11/2018"},
            {"key": "a", "raw": "A01/2016 – 05/2017"},
        ]
        self.assertEqual(mr._gap_if_dropped(roles, "a"), 0)

    def test_unknown_key_no_gap(self):
        self.assertEqual(mr._gap_if_dropped(self._roles(), "nope"), 0)


class VisibleSpanTests(unittest.TestCase):
    """_visible_span parses company-header date ranges into a span."""

    def test_mm_yyyy_dates(self):
        first, last = mr._visible_span([
            "Acme, MA (Remote)05/2021 – 02/2023",
            "Globex, TX03/2017 – 04/2018",
        ])
        self.assertAlmostEqual(first, 2017 + 2 / 12, places=2)
        self.assertAlmostEqual(last, 2023 + 1 / 12, places=2)

    def test_iso_dates(self):
        saved = mr.DATE_RE
        try:
            mrf.DATE_RE = re.compile(r"\d{4}-\d{2}")
            first, last = mr._visible_span([
                "Widgets Inc2024-03 – 2025-01",
            ])
        finally:
            mrf.DATE_RE = saved
        self.assertAlmostEqual(first, 2024 + 2 / 12, places=2)
        self.assertAlmostEqual(last, 2025, places=2)

    def test_no_dates_none(self):
        self.assertEqual(mr._visible_span(["no date here"]), (None, None))

    def test_empty_headers_none(self):
        self.assertEqual(mr._visible_span([]), (None, None))


class TitleAlignmentTests(unittest.TestCase):
    """SKILL Step 4: the headline under the name must not read MORE SENIOR
    than the JD's named title ('Staff Engineer' vs a mid-level posting is
    the recurring misalignment). Extraction (_jd_title) and the seniority
    ladder (_title_rank) are best-effort heuristics, so these helpers only
    ever advise — they never block a render."""

    def _head_body(self, headline="Staff Engineer"):
        return _body([
            _para("Jane Doe", style=mr.HEADLINE_STYLE),
            _para(headline, style=mr.HEADLINE_STYLE),
            _para("Results-driven engineer with 15 years of experience",
                  style="Summary"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Staff Engineer – Quality Automation", style="JobTitleBlock"),
            _para("Led test automation", numId=2),
        ])

    # -- _jd_title extraction -------------------------------------------
    def test_jd_title_from_first_line(self):
        self.assertEqual(
            mr._jd_title("Software Test Engineer\n\nOwn quality end-to-end."),
            "Software Test Engineer")

    def test_jd_title_skips_posting_url_line(self):
        # SKILL Step 1 persists the job posting URL as the JD file's FIRST
        # line — that metadata line must never become the title (a session
        # saw the placeholder parsed as the JD title).
        self.assertEqual(
            mr._jd_title("Posting URL: https://ats.example/apply/123\n"
                         "Forward Deployed AI Engineer\n\nOwn quality."),
            "Forward Deployed AI Engineer")
        self.assertIsNone(
            mr._jd_title("Posting URL: <not provided yet — ask user>"))

    def test_jd_title_from_label_line(self):
        self.assertEqual(
            mr._jd_title("Acme Careers\nJob Title: Software Test Engineer\n"
                         "Own quality end-to-end."),
            "Software Test Engineer")

    def test_jd_title_strips_bullet_prefix(self):
        self.assertEqual(
            mr._jd_title("  * Senior QA Engineer\nblah blah"),
            "Senior QA Engineer")

    def test_jd_title_none_for_long_first_line(self):
        # A first line that is a prose sentence (> TITLE_MAX_WORDS) is not
        # a title — skip the check rather than guess.
        self.assertIsNone(mr._jd_title(
            "We are hiring a Software Test Engineer to own quality across "
            "our SaaS platform. Come join us."))

    def test_jd_title_none_for_empty(self):
        self.assertIsNone(mr._jd_title(""))

    # -- seniority ladder ------------------------------------------------
    def test_title_rank_ladder(self):
        self.assertEqual(mr._title_rank("Staff Engineer"), 3.0)
        self.assertEqual(mr._title_rank("Principal Engineer"), 4.0)
        self.assertEqual(mr._title_rank("Senior QA Engineer"), 2.0)
        self.assertEqual(mr._title_rank("Software Test Engineer"), 1.0)
        self.assertEqual(mr._title_rank("Engineering Manager"), 3.0)
        self.assertEqual(mr._title_rank("Team Lead"), 2.5)

    # -- headline-vs-JD signal ------------------------------------------
    def _notes(self, body, jd):
        lvl, msg = mr.title_alignment_notes(body, jd)
        return {lvl: msg}

    def test_headline_more_senior_warns(self):
        notes = self._notes(self._head_body(),
                            "Software Test Engineer\n5+ years QE")
        self.assertIn("warn", notes)
        self.assertIn("MORE SENIOR", notes["warn"])
        self.assertIn("Staff Engineer", notes["warn"])
        self.assertIn("Software Test Engineer", notes["warn"])

    def test_headline_equals_jd_title_ok(self):
        notes = self._notes(self._head_body("Software Test Engineer"),
                            "Software Test Engineer\n5+ years QE")
        self.assertNotIn("warn", notes)
        self.assertIn("matches the JD title", notes["ok"])

    def test_same_level_different_name_no_warn(self):
        notes = self._notes(self._head_body(), "Staff SDET\nStaff-level")
        self.assertNotIn("warn", notes)
        self.assertIn("SAME level", notes["ok"])

    def test_jd_more_senior_keeps_headline(self):
        notes = self._notes(self._head_body(),
                            "Principal Software Engineer\nStaff+ level")
        self.assertNotIn("warn", notes)
        self.assertIn("keep the headline", notes["ok"])

    def test_no_headline_skips(self):
        body = _body([_para("Jane Doe", style=mr.HEADLINE_STYLE)])
        notes = self._notes(body, "Software Test Engineer\n5+ years QE")
        self.assertNotIn("warn", notes)
        self.assertIn("no headline title found", notes["note"])

    def test_unextractable_jd_title_notes(self):
        notes = self._notes(
            self._head_body(),
            "Acme is hiring a Software Test Engineer in our Payments group "
            "to own quality end to end across the platform. Apply today.")
        self.assertNotIn("warn", notes)
        self.assertIn("not extractable", notes["note"])


class JdReportTests(unittest.TestCase):
    """_jd_report describes the --jd ranking. Its fidelity job: print the
    FULL extracted term list (the old 'e.g.' line truncated at 8) so a term
    missing from a paraphrased/summarized JD file is visible, plus the JD's
    word count and a note when the file is too short to be a full posting.
    """

    def test_full_term_list_printed_when_many(self):
        terms = {f"tool{i}" for i in range(12)}
        lines = mr._jd_report("jd.txt", "word " * 400, terms)
        joined = "\n".join(lines)
        for i in range(12):
            self.assertIn(f"tool{i}", joined)
        self.assertNotIn("e.g.", joined)

    def test_tmp_jd_path_gets_persistence_note(self):
        # R1 regression: the /tmp note once crashed with NameError
        # (appended before `lines` existed) — no test exercised a /tmp
        # path. Both the ranked path and the no-terms early return must
        # carry the note.
        lines = mr._jd_report("/tmp/somejd.txt", "word " * 400,
                              {"playwright"})
        self.assertTrue(
            any("/tmp/somejd.txt" in l and "jd_<target>.txt" in l
                for l in lines), lines)

    def test_tmp_jd_note_on_no_terms_path(self):
        lines = mr._jd_report("/tmp/somejd.txt", "garbage text", set())
        self.assertTrue(any("jd_<target>.txt" in l for l in lines), lines)

    def test_persistent_jd_path_has_no_note(self):
        lines = mr._jd_report("jd_acme.txt", "word " * 400, {"playwright"})
        self.assertFalse(any("/tmp" in l for l in lines), lines)

    def test_word_count_reported(self):
        lines = mr._jd_report("jd.txt", "word " * 400, {"python"})
        self.assertIn("(400 words)", "\n".join(lines))

    def test_short_file_fidelity_note(self):
        # A full JD posting is rarely <100 words; if the file is, flag that
        # it may be a summary rather than the verbatim posting.
        lines = mr._jd_report("jd.txt", "short jd text " * 5, {"python"})
        self.assertIn("verbatim", "\n".join(lines))

    def test_normal_full_jd_no_fidelity_note(self):
        lines = mr._jd_report("jd.txt", "word " * 400, {"python"})
        self.assertNotIn("verbatim", "\n".join(lines))

    def test_no_terms_fallback_message(self):
        lines = mr._jd_report("jd.txt", "word " * 400, set())
        self.assertTrue(any("no candidate-tech terms" in ln for ln in lines))


class InferenceMapTests(unittest.TestCase):
    """The INFERENCE MAP for no-host JD terms: deterministic evidence
    search over the master (and an optional LinkedIn dump) via term
    variants and skill-family roots. 'No literal host' is a flag to
    infer from, not a verdict — a real session left six demonstrated
    skills (debugging, data management, aws services, UI, LLMs, Solving
    Problems) at zero because absence was read as absence of evidence."""

    def _body(self):
        return _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Wrote SQL queries against complex test data and shipped "
                  "new indexes to production.", numId=2),
            _para("Configured AWS cloud infrastructure for the team.",
                  numId=2),
        ])

    def test_family_root_candidate_found(self):
        # 'aws services' has no literal host, but its family root (aws,
        # cloud) hits a master paragraph — a CANDIDATE with the evidence.
        out = mr._inference_map(["aws services"], self._body())
        joined = "\n".join(out)
        self.assertIn("aws services: CANDIDATE", joined)
        self.assertIn("AWS cloud infrastructure", joined)

    def test_variant_hit_singular_and_hyphen(self):
        # Morphological variants host too: 'llms' matches an 'LLM'
        # paragraph, 'customer facing' matches a hyphenated one.
        body = _body([
            _para("Evaluated LLM evaluation harnesses and prompt tests.",
                  numId=2),
            _para("Advised on customer-facing production incidents.",
                  numId=2),
        ])
        joined = "\n".join(mr._inference_map(["llms"], body))
        self.assertIn("llms: CANDIDATE", joined)
        self.assertIn("LLM evaluation", joined)
        joined = "\n".join(mr._inference_map(["customer facing"], body))
        self.assertIn("customer facing: CANDIDATE", joined)
        self.assertIn("customer-facing production", joined)

    def test_no_evidence_term_is_a_gap_not_a_candidate(self):
        out = mr._inference_map(["ontology"], self._body())
        joined = "\n".join(out)
        self.assertIn("ontology: NO deterministic evidence", joined)
        self.assertNotIn("ontology: CANDIDATE", joined)

    def test_linkedin_dump_searched_as_second_source(self):
        # The LinkedIn export is the richer evidence source (a real
        # session justified the Elasticsearch fold from Skills.csv).
        dump = "===== Skills.csv =====\nElasticsearch\nAWS\n"
        out = mr._inference_map(["aws services"], self._body(), dump)
        joined = "\n".join(out)
        self.assertIn("linkedin: \"AWS\"", joined)

    def test_empty_when_nothing_missing(self):
        self.assertEqual(mr._inference_map([], self._body()), [])

    def test_evidence_capped_per_source(self):
        body = _body([
            _para(f"AWS duty number {n}: migrated a service to AWS.",
                  numId=2)
            for n in range(5)
        ])
        out = mr._inference_map(["aws services"], body)
        self.assertEqual(
            sum(1 for ln in out if ln.strip().startswith("master:")),
            mr._INFERENCE_MATCH_CAP)

    def test_report_wiring_prints_map_after_no_host_list(self):
        # _jd_report emits the map when the body misses JD terms.
        jd = ("Required Qualifications:\n"
              "5+ years of experience with AWS Services and Ontology\n")
        lines = mr._jd_report("jd.txt", jd, {"sql"}, self._body())
        joined = "\n".join(lines)
        self.assertIn("JD terms with NO host", joined)
        self.assertIn("INFERENCE MAP", joined)


class TargetNoteTests(unittest.TestCase):
    """The reclaim gap must be measured against the target actually agreed
    on (Step 3): measuring a 3-page senior resume against the 2-page
    default over-reports the gap ("OVER by 2 pages / drop ~117 lines") and
    invites over-cutting. The tool cannot know the agreed target, so it
    flags the one thing it CAN detect: the default is in play while the
    document is over it."""

    def test_note_when_default_target_and_over(self):
        note = mr._default_target_note(4, 2, True)
        self.assertIsNotNone(note)
        self.assertIn("2-page default", note)

    def test_no_note_when_target_explicit(self):
        self.assertIsNone(mr._default_target_note(4, 2, False))

    def test_no_note_when_fits_default(self):
        self.assertIsNone(mr._default_target_note(2, 2, True))

    def test_env_target_is_not_default(self):
        self.assertEqual(mr._target_from_args(["doc.docx"]), (2, True))
        saved = os.environ.get("TARGET_PAGES")
        os.environ["TARGET_PAGES"] = "3"
        try:
            self.assertEqual(mr._target_from_args(["doc.docx"]), (3, False))
        finally:
            if saved is None:
                del os.environ["TARGET_PAGES"]
            else:
                os.environ["TARGET_PAGES"] = saved
        self.assertEqual(mr._target_from_args(["doc.docx", "3"]), (3, False))


class SparseLastPageTests(unittest.TestCase):
    """TARGET NOTE when the last page fills <50% of capacity: a settle-it
    signal for the 2-vs-3 page target. Session failure: a senior resume
    hit "ON target" at 3 pages with a 43% last page, and ~8 measure/render
    cycles went into re-deciding the target mid-flight (43% → 20% → 13% →
    2 pages). SOFT guidance (2026-09-11 user rule): re-targeting lower is
    a judgment call gated on costing no JD-matched evidence — never a
    mandate, and never a reason to cut JD-matched bullets."""

    CAP = 44

    def test_note_when_at_target_and_last_page_sparse(self):
        fills = [41, 43, 19]  # 19/44 = 43%
        note = mr._sparse_last_page_note(3, 3, fills, self.CAP, 0)
        self.assertIsNotNone(note)
        self.assertIn("43% full (19 of ~44 lines)", note)
        self.assertIn("Consider re-targeting one page lower (2)", note)
        self.assertIn("judgment call", note)
        self.assertIn("never cut JD-matched bullets", note)

    def test_note_when_over_target_and_last_page_sparse(self):
        # 3 pages vs target 2 with a 3-line tail: the reclaim gap IS the
        # sparse tail — name both facts, frame the tradeoff as judgment.
        fills = [41, 43, 3]
        note = mr._sparse_last_page_note(3, 2, fills, self.CAP, 3)
        self.assertIsNotNone(note)
        self.assertIn("6% full (3 of ~44 lines)", note)
        self.assertIn("~3-line gap to 2 page(s)", note)
        self.assertIn("judgment call", note)
        self.assertIn("never a mandate", note)

    def test_no_note_when_last_page_full(self):
        self.assertIsNone(
            mr._sparse_last_page_note(2, 2, [41, 43], self.CAP, 0))

    def test_no_note_at_exactly_half(self):
        # 50% is the boundary — a half-full final page is normal, not a
        # signal; only strictly-under-50% fires.
        fills = [41, 22]
        self.assertIsNone(
            mr._sparse_last_page_note(2, 2, fills, self.CAP, 0))

    def test_no_note_on_single_page(self):
        self.assertIsNone(mr._sparse_last_page_note(1, 2, [30], self.CAP, 0))

    def test_no_lower_target_suggestion_for_one_page_target(self):
        # target 1 with 2 pages is "over target" — the over branch fires;
        # the at-target branch must not suggest "target 0".
        fills = [44, 10]
        note = mr._sparse_last_page_note(2, 1, fills, self.CAP, 10)
        self.assertIsNotNone(note)
        self.assertNotIn("page lower (0)", note)


class WidowHintTests(unittest.TestCase):
    """The WIDOW note must name the fix: which block to reclaim from and
    how much — the role whose content immediately precedes the stranded
    header — instead of the vague "trim earlier content"."""

    ACME = "Acme, Springfield, MA (Remote)03/2022 – 02/2023"
    GLOBEX = "Globex, Columbus, OH (Remote)05/2019 – 09/2019"

    def _pages(self, page2_tail):
        # Page 2 is full (10 lines) with its LAST line a role header whose
        # body starts page 3 — the widow.
        return [
            self.ACME + "\nbullet one\nbullet two\nbullet three",
            "filler\n" * 9 + page2_tail,
            "Senior QA Engineer\nbullet",
        ]

    def test_widow_note_names_preceding_role(self):
        matched = [
            ({"key": "Acme, Springfield", "bullets": 3,
              "has_tools": True}, 1, 1, 10),
            ({"key": "Globex, Columbus", "bullets": 2,
              "has_tools": True}, 2, 3, 6),
        ]
        out = mr._layout_hints(matched, self._pages(self.GLOBEX), 10)
        widow = [ln for ln in out if "WIDOW" in ln]
        self.assertEqual(len(widow), 1)
        self.assertIn("reclaim ~2 line(s) from the Acme, Springfield block",
                      widow[0])

    def test_widow_without_preceding_role_keeps_generic_hint(self):
        # No role header precedes the widow on the page (its page is all
        # filler + the header) — fall back to the generic hint.
        matched = [
            ({"key": "Globex, Columbus", "bullets": 2,
              "has_tools": True}, 2, 3, 6),
        ]
        out = mr._layout_hints(matched, self._pages(self.GLOBEX), 10)
        widow = [ln for ln in out if "WIDOW" in ln]
        self.assertEqual(len(widow), 1)
        self.assertIn("trim earlier content or merge bullets", widow[0])
        self.assertNotIn("preceding", widow[0])


class JdMissingTermsTests(unittest.TestCase):
    """JD-side skill terms the resume does not host anywhere.

    jd_terms is the INTERSECTION (JD ask ∩ resume vocabulary), so a
    required skill the resume cannot host never appears in any JD-aware
    section — the omission surfaced only if the agent re-read the JD
    (REST Assured was caught by reading; the Agile preferred qual was
    caught by chance at final review). This makes the 'never fabricate'
    flags mechanical."""

    JD = ("Senior QA Automation Engineer, E&I Commercial UW\n"
          "At AcmeCo, we build things.\n"
          "Primary Responsibilities:\n"
          "Take ownership of the automated test approach.\n"
          "Required Qualifications:\n"
          "5+ years of experience using Selenium Web Driver, Java, "
          "TestNG, Cucumber, REST Assured, or similar IDE\n"
          "Experience with SoapUI or REST API testing tools\n"
          "Agile development process experience\n")

    def _body(self):
        return _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built REST API test suites with Selenium WebDriver, "
                  "Java, TestNG and Cucumber.", numId=2),
            _para("Wrote SQL queries for data validation.", numId=2),
        ])

    def test_reports_jd_skills_with_no_host(self):
        missing = {t.lower() for t in
                   mr._jd_missing_terms(self.JD, self._body(), set())}
        self.assertIn("rest assured", missing)
        self.assertIn("soapui", missing)
        self.assertIn("agile", missing)

    def test_hosted_skills_not_reported(self):
        missing = {t.lower() for t in
                   mr._jd_missing_terms(self.JD, self._body(), set())}
        for hosted in ("java", "cucumber", "testng", "sql", "selenium web"):
            self.assertNotIn(hosted, missing)

    def test_company_voice_and_headings_not_mined(self):
        # 'we build things' is mission prose and 'Required
        # Qualifications:' is a heading — neither may surface as a
        # missing skill; the title line is skipped wholesale.
        missing = mr._jd_missing_terms(self.JD, self._body(), set())
        self.assertNotIn("acmeco", [t.lower() for t in missing])
        self.assertNotIn("qualifications",
                         [t.lower() for t in missing])

    def test_no_qualification_section_is_silent(self):
        # Without a qualifications/requirements heading (a recruiter's
        # message), mining would be unbounded prose — stay silent.
        self.assertEqual(
            mr._jd_missing_terms(
                "Hi there, I'm recruiting for a Senior QA Engineer role. "
                "REST Assured and SoapUI experience would be great.",
                self._body(), set()),
            [])

    def test_line_terms(self):
        terms = mr._jd_line_terms(
            "5+ years of experience using Selenium Web Driver, Java, "
            "TestNG, REST Assured, or similar IDE")
        self.assertIn("rest assured", terms)
        self.assertIn("java", terms)
        self.assertIn("testng", terms)
        self.assertIn("selenium web driver", terms)
        self.assertNotIn("ide", terms)

    def test_camelcase_tokens_mine(self):
        # 'macOS' starts lowercase, so the Capitalized-token regex never
        # saw it — a real Endpoint session's no-host list missed the
        # JD's macOS ask entirely. Mixed-case qual tokens are tech names.
        terms = mr._jd_line_terms(
            "Depth in operating-system behavior on at least two of "
            "Windows, macOS, and Linux.")
        self.assertIn("macos", terms)
        self.assertIn("windows", terms)
        self.assertIn("linux", terms)

    def test_line_terms_filters_self_assessment_adjectives(self):
        # A soft-skill qual line's only capitalized token is the
        # self-assessment adjective — never skill evidence (a session
        # chased "excellent" as a keyword across three user replies).
        terms = mr._jd_line_terms(
            "Excellent communication, stakeholder management, and "
            "technical leadership skills")
        self.assertEqual(terms, set())


class KeepTrimCandidatesTests(unittest.TestCase):
    """Word-level trim candidates: kept bullets that still carry non-JD
    content. Compression was bullet-granular — a kept bullet dragged its
    non-JD tools and dead sentences to the deliverable untouched. The
    section names them deterministically: non-JD tech nouns (strip from
    the clause) and sentences with no JD evidence (cut whole)."""

    def _body_with_bullet(self, bullet_text):
        return _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para(bullet_text, numId=2),
            _para("Tools & Technologies: Selenium, Java, TestNG, "
                  "Playwright, Kafka"),
        ])

    def test_flags_nonjd_tool_and_dead_sentence(self):
        # The JD asks Selenium/Java only: TestNG/Playwright ride along in
        # the kept bullet, the second sentence carries no JD evidence,
        # and the Tools line's non-JD chunks flag at list level.
        jd = "Required Qualifications:\nExperience with Selenium and Java\n"
        body = self._body_with_bullet(
            "Built Selenium suites with Java, TestNG and Playwright. "
            "Ran weekly standups and sprint retrospectives.")
        section = mr._keep_trim_section(mr._roles(body),
                                        mr._jd_terms(jd, body), body)
        self.assertIn("WORD-LEVEL TRIM CANDIDATES", section)
        self.assertIn("JD does not name: playwright, testng", section)
        self.assertIn("sentence with no JD evidence", section)
        self.assertIn("Ran weekly standups", section)
        self.assertIn("find_p(ps, ", section)
        self.assertIn("list lines (Technical Proficiencies / "
                      "Tools & Technologies):", section)
        self.assertIn("- JD does not name: testng, playwright, kafka",
                      section)

    def test_proficiencies_line_chunks_trimmed(self):
        # Technical Proficiencies is where non-JD tools pile up: a kept
        # line's non-JD chunks are trim candidates, its JD-named tools
        # stay, and the label survives either way.
        jd = "Required Qualifications:\nExperience with Selenium\n"
        body = _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Automated QA: TestNG, Selenium, Playwright"),
        ])
        section = mr._keep_trim_section(mr._roles(body),
                                        mr._jd_terms(jd, body), body)
        self.assertIn("find_p(ps, ", section)
        self.assertIn("- JD does not name: testng, playwright", section)
        self.assertNotIn("no JD term on this line", section)

    def test_fully_nonjd_list_line_points_to_whole_line_cut(self):
        # A list line with NO JD term is a whole-line cut (TOP-BLOCK
        # rule) — token-trimming it would leave an orphaned label.
        jd = "Required Qualifications:\nExperience with Selenium\n"
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built Selenium suites with Java.", numId=2),
            _para("Tools & Technologies: TestNG, JUnit"),
        ])
        section = mr._keep_trim_section(mr._roles(body),
                                        mr._jd_terms(jd, body), body)
        self.assertIn("no JD term on this line — whole-line "
                      "cut (TOP-BLOCK rule), not token trimming", section)

    def test_concept_carrying_list_line_skipped(self):
        # A list line carrying a JD practice phrase is skipped entirely —
        # its chunks may host the concept.
        jd = "Required Qualifications:\nExperience with Selenium\n"
        body = _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Code Review Standards: Gerrit, GitHub"),
        ])
        section = mr._keep_trim_section(mr._roles(body),
                                        mr._jd_terms(jd, body), body)
        self.assertNotIn("Gerrit", section or "")

    def test_spares_concept_sentence_tokens_and_dead_flag(self):
        # A sentence carrying a JD practice phrase is skipped entirely —
        # its tokens may be the concept's only host (Kafka hosting
        # "root-cause" analysis tooling), so neither the token nor the
        # sentence flags while a sibling dead sentence still does.
        jd = "Required Qualifications:\nExperience with Selenium\n"
        body = self._body_with_bullet(
            "Built Selenium suites for regression coverage. "
            "Ran root-cause triage on flaky builds with Kafka. "
            "Attended optional office socials.")
        section = mr._keep_trim_section(mr._roles(body),
                                        mr._jd_terms(jd, body), body)
        self.assertNotIn("sentence with no JD evidence: \"Ran root-cause",
                         section)
        self.assertIn("Attended optional office socials", section)

    def test_offjd_bullet_not_a_trim_candidate(self):
        # OFF-JD/weak bullets are whole-cut candidates (JD-FIT AUDIT) —
        # trimming them word-by-word would be the wrong granularity. A
        # bullet with zero JD evidence never enters the trim scan (the
        # list-line group may still report; that is a separate finding).
        jd = "Required Qualifications:\nExperience with Selenium\n"
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Organized team meetings and maintained trackers.",
                  numId=2),
        ])
        section = mr._keep_trim_section(mr._roles(body),
                                        mr._jd_terms(jd, body), body)
        self.assertNotIn("Organized team meetings", section or "")

    def test_silent_without_jd(self):
        body = self._body_with_bullet("Built Selenium suites with Java.")
        self.assertIsNone(
            mr._keep_trim_section(mr._roles(body), set(), body))


class JdRequirementCoverageTests(unittest.TestCase):
    """The requirement → evidence map: cutting off-JD content keeps the
    resume honest; coverage keeps it QUALIFIED. Every JD qualification
    line must be demonstrated by a kept bullet, or flagged [weak] (only
    a proficiencies/Tools line hosts it — SKILL Step 5: weave it in) or
    [UNCOVERED] (no host — restore from the master or raise to the
    user; never fabricate)."""

    def _jd_and_body(self):
        jd = ("Required Qualifications:\n"
              "5+ years of experience using Selenium Web Driver, Java, "
              "TestNG, Cucumber, REST Assured, or similar IDE\n"
              "Experience with Kubernetes and Helm\n"
              "Experience with Terraform and Ansible\n")
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built REST API test suites with Selenium WebDriver, "
                  "Java, TestNG and Cucumber.", numId=2),
            _para("Tools & Technologies: Kubernetes, Helm"),
        ])
        return jd, body

    def test_covered_line_lists_host_bullet(self):
        jd, body = self._jd_and_body()
        result = mr._jd_requirement_coverage(mr._roles(body), body, jd)
        self.assertTrue(any(s == "covered" and "Selenium" in label
                            for label, s, _ in result), result)
        self.assertTrue(any("Acme" in detail
                            for _, s, detail in result if s == "covered"),
                        result)

    def test_uncovered_line_flagged(self):
        jd, body = self._jd_and_body()
        result = mr._jd_requirement_coverage(mr._roles(body), body, jd)
        self.assertTrue(any(s == "uncovered" and "Terraform" in label
                            for label, s, _ in result), result)
        self.assertTrue(any("never fabricate" in detail
                            for _, s, detail in result
                            if s == "uncovered"), result)

    def test_non_bullet_host_is_weak(self):
        # Kubernetes/Helm live only on the Tools line: [weak] with the
        # Step-5 weave instruction, not [covered].
        jd, body = self._jd_and_body()
        result = mr._jd_requirement_coverage(mr._roles(body), body, jd)
        self.assertTrue(any(s == "weak" and "Kubernetes" in label
                            for label, s, _ in result), result)
        self.assertTrue(any("weave" in detail
                            for _, s, detail in result if s == "weak"),
                        result)

    def test_no_qualification_section_is_silent(self):
        _jd, body = self._jd_and_body()
        self.assertEqual(
            mr._jd_requirement_coverage(mr._roles(body), body,
                                        "Hi there, let's talk."),
            [])

    def test_soft_skill_line_is_by_hand_with_action_verb_detail(self):
        # "Excellent communication..." extracts no terms (the adjective
        # is filtered) — it must read as a judged soft-skill ask with
        # the action-verb evidence rule, not [UNCOVERED] on "excellent".
        jd, body = self._jd_and_body()
        jd += ("Excellent communication, stakeholder management, and "
               "technical leadership skills\n")
        result = mr._jd_requirement_coverage(mr._roles(body), body, jd)
        self.assertTrue(any(s == "by_hand" and "soft-skill" in detail
                            for _, s, detail in result), result)

    def test_bare_colon_headings_still_collect(self):
        # A short-form JD labels its qualification sections with a bare
        # "Required:" / "Preferred:" heading line (no noun after the
        # qualifier). Such a line ends in ':', which the collector reads
        # as a section TERMINATOR — the heading regex must recognize it
        # as a heading first, or the requirement-coverage map (and its
        # never-fabricate guard) silently fires for the whole posting.
        jd = ("Requirements\n"
              "Required:\n"
              "5+ years of experience using Selenium Web Driver, Java, "
              "TestNG\n"
              "Preferred:\n"
              "Familiarity with Kubernetes and Helm\n")
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built REST API test suites with Selenium WebDriver, "
                  "Java, TestNG and Cucumber.", numId=2),
            _para("Tools & Technologies: Kubernetes, Helm"),
        ])
        result = mr._jd_requirement_coverage(mr._roles(body), body, jd)
        self.assertTrue(result, "bare Required:/Preferred: headings must "
                        "collect qualification lines")
        self.assertTrue(any(s == "covered" and "Selenium" in label
                            for label, s, _ in result), result)
        # Kubernetes/Helm live only on the Tools line: [weak], per the
        # same rule test_non_bullet_host_is_weak asserts above.
        self.assertTrue(any(s == "weak" and "Kubernetes" in label
                            for label, s, _ in result), result)


class SpacerBoundaryTests(unittest.TestCase):
    """The readability pause, reported instead of remembered: inter-role
    boundaries without a blank spacer paragraph (SKILL Step 8 spacing)."""

    def _body(self, with_spacer):
        ps = [_para("Career Experience", style="SectionHeading"),
              _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                    style=mr.COMPANY_STYLE),
              _para("Built the first framework.", numId=2)]
        if with_spacer:
            ps.append(_para(""))
        ps += [_para("Globex, Town" + _sample_date() + " \u2013 08/2018",
                     style=mr.COMPANY_STYLE),
               _para("Built the second framework.", numId=2)]
        return _body(ps)

    def test_boundary_without_spacer_reported(self):
        gaps = mr._boundaries_without_spacer(self._body(False))
        self.assertEqual(len(gaps), 1)
        header, anchor = gaps[0]
        self.assertIn("Globex", header)
        self.assertIn("first framework", anchor)

    def test_boundary_with_spacer_silent(self):
        self.assertEqual(mr._boundaries_without_spacer(self._body(True)),
                         [])

    def test_you_bring_heading_collects_qualifications(self):
        # Modern JDs often label their qualification section "You Bring"
        # (or "What You'll Bring") instead of "Required Qualifications"
        # — e.g. OnePay's QE Platform Engineer posting. The collector
        # must recognize it as a heading, or the requirement-coverage
        # map (and its never-fabricate guard) silently stays silent for
        # the whole posting. Bullets under it collect; the company-voice
        # "Tools We Use" prose after it must not surface as qual lines.
        jd = ("QE Platform Engineer\n"
              "About OnePay\n"
              "We're an all-in-one financial services platform.\n"
              "The Role\n"
              "Design and own shared test automation frameworks.\n"
              "You Bring\n"
              "Deep experience building test automation frameworks "
              "such as Playwright, Selenium, Appium, or similar\n"
              "Proficiency in TypeScript/Node.js\n"
              "Experience with cloud-native infrastructure such as "
              "Kubernetes and AWS\n"
              "Tools We Use\n"
              "We use Node and TypeScript on the server.\n")
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built test automation frameworks with Playwright and "
                  "Selenium.", numId=2),
            _para("Designed TypeScript test suites.", numId=2),
            _para("Tools & Technologies: Kubernetes, Docker, AWS"),
        ])
        result = mr._jd_requirement_coverage(mr._roles(body), body, jd)
        self.assertTrue(result, "You Bring heading must collect "
                        "qualification lines")
        self.assertTrue(any(s == "covered" and label.startswith("Deep experience")
                            for label, s, _ in result), result)
        self.assertTrue(any("Acme, City" in detail and "Playwright" in detail
                            for _, s, detail in result if s == "covered"), result)
        # Kubernetes/AWS live only on the Tools line: [weak], same rule.
        self.assertTrue(any(s == "weak" and "Kubernetes" in label
                            for label, s, _ in result), result)
        # The company-voice Tools We Use prose must not be mined.
        self.assertFalse(any("Tools We Use" in label
                             for label, _, _ in result), result)


class JdFitAuditTests(unittest.TestCase):
    """The JD-FIT AUDIT: per-role bullet classification printed for EVERY
    role with --jd, independent of the page math. The DROP PLAN fires only
    when cuts are needed to hit the target — which is how an under-cap
    role once kept every bullet (two of them matching nothing the JD
    names) after other roles closed the gap. JD alignment is the FIRST
    priority: weak and OFF-JD bullets must surface even when on target."""

    def _roles(self, *bullet_groups):
        return [{"key": f"Role{i}",
                 "raw": f"Role{i}, City 01/2020 \u2013 02/2021",
                 "bullets": len(bs), "bullet_texts": list(bs),
                 "has_tools": False}
                for i, bs in enumerate(bullet_groups)]

    def test_off_jd_bullets_listed_when_on_target(self):
        # 2 strong + 1 zero-hit bullet: the audit names the OFF-JD bullet
        # even though the role is under any cap and the page math needs
        # nothing.
        roles = self._roles([
            "Advised engineer working on the Playwright test framework on "
            "best practices.",
            "Developed a semi-autonomous agentic workflow using sub-agents "
            "to improve test coverage.",
            "Coordinated across teams to establish meeting cadences and "
            "enhance documentation practices.",
        ])
        sections = mr._jd_fit_audit(roles, {"playwright", "agentic"})
        self.assertEqual(len(sections), 1)
        self.assertIn("JD-FIT AUDIT (Role0): 2 of 3 bullet(s) carry JD "
                      "evidence", sections[0])
        self.assertIn("OFF-JD", sections[0])
        self.assertIn("Coordinated across teams", sections[0])
        self.assertIn("even when on target", sections[0])

    def test_weak_only_match_is_cuttable_not_kept(self):
        # A term hitting half the role's own bullets is weak: the bullet
        # shows as weak-match, and the role's kept count excludes it.
        roles = self._roles([
            "Configured CI pipelines to trigger tests based on cross "
            "dependency changes.",
            "Advised engineer working on the Playwright test framework on "
            "best practices.",
        ])
        sections = mr._jd_fit_audit(roles, {"test", "playwright"})
        self.assertEqual(len(sections), 1)
        self.assertIn("1 of 2 bullet(s) carry JD evidence", sections[0])
        self.assertIn("weak-match", sections[0])
        self.assertIn("Configured CI pipelines", sections[0])

    def test_mostly_irrelevant_role_is_stub_candidate(self):
        # 2 of 3 bullets carry no JD evidence: stub guidance fires — cut
        # to the strongest bullet; keep a 1-bullet stub only to prevent
        # an employment gap.
        roles = self._roles([
            "Coordinated across teams to establish meeting cadences and "
            "enhance documentation practices.",
            "Organized team events and maintained the shared calendar.",
            "Developed a semi-autonomous agentic workflow using sub-agents "
            "to improve test coverage.",
        ])
        sections = mr._jd_fit_audit(roles, {"agentic"})
        self.assertEqual(len(sections), 1)
        self.assertIn("STUB CANDIDATE", sections[0])
        self.assertIn("1-bullet stub", sections[0])

    def test_all_jd_evidence_role_is_silent(self):
        # Each term hits exactly one of two bullets (not >half the role),
        # so both classify strong and the audit stays silent.
        roles = self._roles([
            "Advised engineer working on the Playwright test framework on "
            "best practices.",
            "Developed a semi-autonomous agentic workflow using sub-agents "
            "to improve test coverage.",
        ])
        self.assertEqual(mr._jd_fit_audit(roles, {"playwright", "agentic"}),
                         [])

    def test_no_jd_terms_is_silent(self):
        self.assertEqual(mr._jd_fit_audit(self._roles(["any bullet"]), set()),
                         [])

    def test_protected_bullet_counts_as_evidence(self):
        # --protect marks candidate-specific facts the user confirmed (a
        # sandbox duty, a named partner): the JD text cannot name them, so
        # zero term hits must NOT read as OFF-JD.
        roles = self._roles([
            "Tested American Express partner integrations against their "
            "sandbox.",
        ])
        self.assertEqual(
            mr._jd_fit_audit(roles, {"playwright"},
                             protect=("partner integrations",)), [])


class MeasureHelpFlagTests(unittest.TestCase):
    """Bare --help must print usage and exit 0 — the hand-rolled argv
    loop used to consume it as the positional .docx path and die with a
    FileNotFoundError."""

    def test_help_exits_zero(self):
        argv = sys.argv
        sys.argv = ["measure_resume.py", "--help"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as ctx:
                    mr._parse_measure_args()
        finally:
            sys.argv = argv
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("measure_resume.py", buf.getvalue())


class CoverageTermsVisibilityTests(unittest.TestCase):
    """Regression: an UNCOVERED line whose qual the resume demonstrably
    hosts used to cost a matcher-debugging session ('Solid SQL skills'
    mines the single artifact term 'solid sql' — a capitalized-sequence
    artifact invisible in the report). The coverage printer now shows the
    extracted terms on weak/uncovered lines."""

    SQL_LINE = "Solid SQL skills and experience with database validation."

    def test_line_terms_map_aligned_and_artifact_visible(self):
        jd = "Required Qualifications:\n" + self.SQL_LINE + "\n"
        terms = dict(mr._jd_line_terms_map(jd))
        line = [k for k in terms if "Solid SQL" in k][0]
        self.assertIn("solid sql", terms[line], terms)

    def test_uncovered_line_prints_extracted_terms(self):
        jd = ("Required Qualifications:\n"
              "Experience with Kubernetes and Helm\n" + self.SQL_LINE + "\n")
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built REST API test suites with Selenium WebDriver.",
                  numId=2),
            _para("Tools & Technologies: Kubernetes, Helm"),
        ])

        _Ctx = types.SimpleNamespace()  # duck-typed _ReportCtx subset

        _Ctx.jd_terms = {"sql", "kubernetes"}
        _Ctx.jd_text = jd
        _Ctx.roles = mr._roles(body)
        _Ctx.body = body

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mr._print_jd_coverage(_Ctx.roles, _Ctx.body, _Ctx.jd_text,
                                  _Ctx.jd_terms)
        out = buf.getvalue()
        self.assertIn("UNCOVERED", out)
        self.assertIn("extracted terms:", out)
        self.assertIn("solid sql", out)

    def test_covered_line_has_no_term_noise(self):
        jd = ("Required Qualifications:\n"
              "Experience with Kubernetes and Helm\n")
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Deployed services on Kubernetes clusters with Helm "
                  "charts.", numId=2),
            _para("Tools & Technologies: Kubernetes, Helm"),
        ])

        _Ctx = types.SimpleNamespace()

        _Ctx.jd_terms = {"kubernetes"}
        _Ctx.jd_text = jd
        _Ctx.roles = mr._roles(body)
        _Ctx.body = body

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mr._print_jd_coverage(_Ctx.roles, _Ctx.body, _Ctx.jd_text,
                                  _Ctx.jd_terms)
        self.assertNotIn("extracted terms:", buf.getvalue())


class InferenceFamilyTests(unittest.TestCase):
    """Families added after a real session: 'software engineering' and
    'programming skills' carried strong master evidence (languages,
    production test code) but no family mapped them, so the INFERENCE MAP
    reported them as genuine gaps."""

    def test_programming_family(self):
        roots = mr._family_roots("programming skills")
        self.assertIn("java", roots)
        self.assertIn("python", roots)

    def test_software_engineering_family(self):
        roots = mr._family_roots("software engineering")
        self.assertIn("software", roots)
        self.assertIn("sdlc", roots)

    def test_unrelated_term_has_no_family(self):
        self.assertEqual(mr._family_roots("ontologies"), ())


class WordBudgetTests(unittest.TestCase):
    """The 1000-word cap is a blocking gate; the WORD BUDGET section
    surfaces the arithmetic BEFORE the gate blocks, so cuts are planned
    in one pass instead of hand-estimated across blocked re-runs (a real
    session burned six gate-blocked cycles chasing the cap)."""

    def _body_with_words(self, n):
        filler = " ".join(f"word{i}" for i in range(n))
        return _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para(filler, numId=2),
        ])

    def test_budget_printed_near_cap(self):
        body = self._body_with_words(900)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mr._print_word_budget(body)
        out = buf.getvalue()
        self.assertIn("WORD BUDGET", out)
        self.assertIn(f"cap {mr.MAX_WORDS}", out)
        self.assertIn("Acme", out)

    def test_budget_silent_far_below_cap(self):
        body = self._body_with_words(40)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mr._print_word_budget(body)
        self.assertEqual(buf.getvalue(), "")

    def test_budget_names_wordiest_bullets(self):
        filler = " ".join(f"f{i}" for i in range(880))
        long_bullet = " ".join(f"w{i}" for i in range(50))
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para(filler, numId=2),
            _para(long_bullet, numId=2),
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mr._print_word_budget(body)
        self.assertIn("Wordiest bullets", buf.getvalue())



    def test_jd_requirement_lines_conversational_headings(self):
        """'Who you are' / 'What you'll do' headings are qual sections."""
        jd = (
            "Software Test Architect\n\n"
            "What you'll do:\n\n"
            "Define test automation architecture across products.\n"
            "Lead proofs of concept for UI and API testing.\n\n"
            "Who you are:\n\n"
            "5+ years of experience in test automation engineering.\n"
            "Proficiency in TypeScript, C#, Java, or Python.\n\n"
            "Benefits:\n\n"
            "Great pay and a 401k.\n"
        )
        lines = measure_resume_jd._jd_requirement_lines(jd)
        self.assertEqual(len(lines), 4)
        self.assertIn("5+ years", lines[2])
        # benefits prose stays excluded
        self.assertFalse(any("401k" in ln for ln in lines))



if __name__ == "__main__":
    unittest.main()


class RequirementsSummaryTests(unittest.TestCase):
    """REQUIREMENTS SUMMARY: a compact one-line signal after the per-qual
    coverage list. Gives the agent a machine-readable hook for the
    three-state rule (SKILL Step 2) — when unconfirmed_hard > 0 the
    checklist MUST be presented before claiming the honest ceiling."""

    def _ctx_with(self, jd, body):
        roles = mr._roles(body)
        jd_terms = mr._jd_terms(jd, body)
        return mr._ReportCtx(
            target=2, default_target=True, jd_text=jd, jd_terms=jd_terms,
            protect=[], body=body, roles=roles,
            matched=[], pages_text=[], total_pages=2, over=0,
            overflow_lines=0, capacity=44, fixed_top=20,
            role_lines=30, edu=3, wrapped=[])

    def test_summary_line_printed(self):
        jd = ("Required Qualifications:\n"
              "Selenium and Java experience\n"
              "Terraform and Ansible\n")
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built test suites with Selenium WebDriver and Java.",
                  numId=2),
        ])
        roles = mr._roles(body)
        jd_terms = mr._jd_terms(jd, body)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mr._print_jd_coverage(roles, body, jd, jd_terms)
        buf = out.getvalue()
        self.assertIn("REQUIREMENTS SUMMARY", buf)
        self.assertIn("unconfirmed hard skill", buf)

    def test_no_unconfirmed_no_call_to_action(self):
        # A fully-covered run must NOT tell the agent to present a
        # checklist that is empty — the call-to-action is conditional.
        jd = ("Required Qualifications:\n"
              "Selenium and Java experience\n")
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built test suites with Selenium WebDriver and Java.",
                  numId=2),
        ])
        roles = mr._roles(body)
        jd_terms = mr._jd_terms(jd, body)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mr._print_jd_coverage(roles, body, jd, jd_terms)
        buf = out.getvalue()
        self.assertIn("REQUIREMENTS SUMMARY", buf)
        self.assertNotIn("unconfirmed hard skill", buf)
        self.assertIn("1/1 quals covered", buf)

    def test_by_hand_soft_lines_get_hosting_directive(self):
        # A soft-skill qual line extracts no terms ([by hand]). Without a
        # directive the summary counted it and moved on — hosting waited
        # for the Step-11 scan to flag the absence. The directive names
        # THIS pass (authoring time), not the scan (2026-09-11).
        jd = ("Required Qualifications:\n"
              "Selenium and Java experience\n"
              "Excellent communication, stakeholder management, and "
              "technical leadership skills\n")
        body = _body([
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " \u2013 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Built test suites with Selenium WebDriver and Java.",
                  numId=2),
        ])
        roles = mr._roles(body)
        jd_terms = mr._jd_terms(jd, body)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mr._print_jd_coverage(roles, body, jd, jd_terms)
        buf = out.getvalue()
        self.assertIn("1 soft-skill line(s) [by hand]", buf)
        self.assertIn("host the literal phrases in THIS pass", buf)
        self.assertIn("safe to infer", buf)



class PrunePlanModeTests(unittest.TestCase):
    """The master is measured ONLY in prune-plan mode (SKILL Step 3):
    relevance assessment first, page/word math never. The Gravie session
    planned its cuts from full-master page math and still shipped four
    non-JD sentences the user hand-cut afterward — because master page
    math answers 'what fits', not 'what matters'. The master without
    --jd, or with --simulate, is refused; with --jd the output is the
    JD assessment alone (audit + trim + top-block candidates), with
    copy-pasteable anchors, and no PAGES/RECLAIM/WORD BUDGET sections.
    """

    JD = ("Required Qualifications:\n"
          "Playwright experience\n")

    def _master_paras(self):
        return [
            _para("Adrian Sample"),
            _para("Staff Engineer", style="Title"),
            _para("Staff engineer with deep test automation experience.",
                  style="Summary"),
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Testing: Selenium, Kubernetes"),
            _para("Career Experience", style="SectionHeading"),
            _para("Acme, City" + _sample_date() + " – 08/2016",
                  style=mr.COMPANY_STYLE),
            _para("Senior QA Engineer", style="JobTitleBlock"),
            _para("Advised engineer working on the Playwright test "
                  "framework on best practices.", numId=2),
            _para("Coordinated across teams to establish meeting "
                  "cadences.", numId=2),
            _para("Tools & Technologies: Kubernetes, Helm"),
        ]

    def _write_master(self, td):
        docx = os.path.join(td, "Adrian Sample Master Resume.docx")
        _write_docx(docx, self._master_paras())
        return docx

    def _jd_file(self, td, text=JD):
        path = os.path.join(td, "jd.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _args(self, docx, jd_file=None, simulate=(), target=None):
        jd_text = None
        if jd_file:
            with open(jd_file, encoding="utf-8") as fh:
                jd_text = fh.read()
        return mr._Args(
            docx=docx, target=target or 2,
            default_target=target is None, jd_text=jd_text,
            jd_file=jd_file, evidence_text=None, protect=[],
            simulate=list(simulate))

    def test_is_master_input(self):
        self.assertTrue(mr._is_master_input("/x/A Master Resume.docx"))
        self.assertFalse(mr._is_master_input("/x/A Resume - Target.docx"))
        self.assertFalse(mr._is_master_input("/x/master-resume.docx"))

    def test_master_without_jd_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            docx = self._write_master(td)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    mr._main_prune_plan(self._args(docx))
            self.assertEqual(ctx.exception.code, 2)
            self.assertIn("ONLY with --jd", err.getvalue())

    def test_master_simulate_is_refused(self):
        # Whole-role what-ifs are a Step-4 seniority question, answered on
        # the PRUNED copy — never on the master.
        with tempfile.TemporaryDirectory() as td:
            docx = self._write_master(td)
            jd_file = self._jd_file(td)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    mr._main_prune_plan(
                        self._args(docx, jd_file=jd_file,
                                   simulate=("Acme",)))
            self.assertEqual(ctx.exception.code, 2)
            self.assertIn("seniority", err.getvalue())

    def test_master_with_jd_prints_prune_plan_only(self):
        with tempfile.TemporaryDirectory() as td:
            docx = self._write_master(td)
            args = self._args(docx, jd_file=self._jd_file(td))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mr._main_prune_plan(args)
            out = buf.getvalue()
            # the prune plan's sections are present, with anchors
            self.assertIn("PRUNE PLAN", out)
            self.assertIn("JD-FIT AUDIT (Acme", out)
            self.assertIn("OFF-JD", out)
            self.assertIn("WORD-LEVEL TRIM CANDIDATES", out)
            self.assertIn("TOP-BLOCK PRUNE CANDIDATES", out)
            self.assertIn('find_p(ps, "Coordi"', out)
            self.assertIn("REQUIREMENTS SUMMARY", out)
            # page/word math is suppressed — never measured on the master
            self.assertNotIn("PAGES:", out)
            self.assertNotIn("RECLAIM PLAN", out)
            self.assertNotIn("WORD BUDGET", out)
            self.assertNotIn("TIMELINE:", out)
            self.assertNotIn("Per-role rendered cost", out)

    def test_prune_plan_ignores_explicit_target_with_note(self):
        with tempfile.TemporaryDirectory() as td:
            docx = self._write_master(td)
            args = self._args(docx, jd_file=self._jd_file(td), target=3)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mr._main_prune_plan(args)
            self.assertIn("page target 3 ignored", buf.getvalue())


class AuditAnchorTests(unittest.TestCase):
    """JD-FIT AUDIT cut candidates carry copy-pasteable find_p anchors
    when all_texts is supplied — the prune script is authorable from the
    audit alone (was: previews only, and the agent re-derived prefixes by
    hand)."""

    def _roles(self):
        return [{"key": "Acme, City",
                 "raw": "Acme, City 01/2020 – 02/2021",
                 "bullets": 2,
                 "bullet_texts": [
                     "Advised engineer working on the Playwright test "
                     "framework on best practices.",
                     "Coordinated across teams to establish meeting "
                     "cadences."],
                 "has_tools": False}]

    def test_off_jd_line_carries_find_p_anchor(self):
        texts = ["Advised engineer working on the Playwright test "
                 "framework on best practices.",
                 "Coordinated across teams to establish meeting "
                 "cadences."]
        sections = mr._jd_fit_audit(self._roles(), {"playwright"},
                                    all_texts=texts)
        self.assertIn('find_p(ps, "Coordi"', sections[0])

    def test_fallback_without_all_texts(self):
        sections = mr._jd_fit_audit(self._roles(), {"playwright"})
        self.assertIn("Coordinated across teams", sections[0])
        self.assertNotIn("find_p(", sections[0])
