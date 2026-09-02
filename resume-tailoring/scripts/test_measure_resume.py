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

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
import zipfile
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


class TopRoleBatchTests(unittest.TestCase):
    """_top_role_batch: the most-recent role's trim batch, emitted when the
    deterministic plan cannot close the gap.

    THE session failure (CarMax Principal Quality tailoring): the master's
    most-recent role held 23 bullets / 63 rendered lines, every older-role
    budget was a dead end, and the tool's BATCH RECLAIM PLAN still could
    not reach the 3-page target. Nothing in the output covered the top
    role, so the author had to invent levers — headless-session replays
    showed agents filling the vacuum with hand-shortening (rewriting kept
    bullets from two rendered lines to one), the lowest-leverage edit in
    the skill. Enforcement moved into the tool: when TOP-BLOCK + Tools
    de-wraps + feasible oldest cuts fall short, measure emits the top
    role's weakest UNPROTECTED bullets in the same copy-pasteable find_p
    format, so the authoring plan is a sum of tool-named removals.
    """

    def setUp(self):
        # Document order: most-recent role FIRST. GEICO is the bloated top
        # role; the two oldest roles are dead ends (all bullets protected).
        self.matched = [
            ({"key": "GEICO", "bullets": 5, "has_tools": True,
              "bullet_texts": [
                  "Wrote scripts for storing images in JFrog Artifactory",
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
        # capped at GEICO's 3 unprotected.
        plan = [
            ("Old", "drop 2 bullet(s) (saves ~5 lines)", 5.0),
            ("Middle", "drop 2 bullet(s) (saves ~5 lines)", 5.0),
        ]
        batch, adjusted, feasible = mr._top_role_batch(
            self.matched, plan, 2.5, 20, tools_savings=2,
            top_block_count=2, jd_terms=self.jd)
        self.assertIsNotNone(batch)
        self.assertEqual(batch[0], "GEICO")
        self.assertIn("drop 3 bullet(s)", batch[1])  # capped at 5-2=3 unprotected
        self.assertAlmostEqual(batch[2], 3 * 2.5)
        # Dead-end entries for the OTHER roles survive (they print the
        # honest infeasibility note); no GEICO entry to double-count.
        self.assertEqual([p[0] for p in adjusted], ["Old", "Middle"])
        self.assertAlmostEqual(feasible, 4.0)

    def test_no_batch_when_feasible_cuts_close_the_gap(self):
        plan = [("Old", "drop 2 bullet(s) (saves ~5 lines)", 5.0)]
        batch, adjusted, feasible = mr._top_role_batch(
            self.matched, plan, 2.5, 4, tools_savings=4,
            top_block_count=1, jd_terms=set())
        self.assertIsNone(batch)
        # feasible = 2 unprotected * 2.5 + 4 tools + 1 top-block = 10
        self.assertAlmostEqual(feasible, 10.0)

    def test_no_batch_when_top_role_fully_protected(self):
        matched = [({"key": "GEICO", "bullets": 2, "has_tools": True,
                     "bullet_texts": ["Landed Playwright as the company UI "
                                       "testing tool"]}, 1, 1, 8)]
        plan = []
        batch, _adjusted, _feasible = mr._top_role_batch(
            matched, plan, 2.5, 10, tools_savings=0, top_block_count=0,
            jd_terms=("playwright",))
        self.assertIsNone(batch)

    def test_superseded_top_role_entry_removed_from_plan(self):
        # If the oldest-first loop reached the top role with a dead-end
        # budget, the batch replaces it (one authoritative sizing).
        plan = [("GEICO", "drop 8 bullet(s) (saves ~20 lines)", 20.0)]
        batch, adjusted, _feasible = mr._top_role_batch(
            self.matched, plan, 2.5, 40, tools_savings=0,
            top_block_count=0, jd_terms=set())
        self.assertIsNotNone(batch)
        self.assertEqual(adjusted, [])

    def test_batch_section_renders_with_custom_header(self):
        batch = ("GEICO", "drop 2 bullet(s) (saves ~5 lines)", 5.0)
        role = self.matched[0][0]
        header = "TOP-ROLE TRIM BATCH (GEICO; closes the residual gap "
        section = mr._batch_section(
            batch, role, header,
            protect=(), jd_terms=self.jd)
        self.assertIn("TOP-ROLE TRIM BATCH (GEICO", section)
        self.assertIn("find_p(ps,", section)
        # Protected (Playwright) bullets are not suggested.
        self.assertNotIn("Championed agentic workflows", section)


class JDAwareTests(unittest.TestCase):
    """--jd makes the DROP PLAN JD-aware: bullets whose text matches a
    candidate-tech term the JD asks for (Cypress, Gatling, Jenkins, ...) or
    a named JD practice (mentorship, shift-left) must NOT be suggested for
    cutting while any non-matching bullet remains. This session's failure:
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
            _para("Company ABC, City" + _sample_date() + " – 04/2020",
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
            _para("Company ABC, City" + _sample_date() + " – 04/2020",
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
            _para("Company ABC, City" + _sample_date() + " – 04/2020",
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
        # The session's failure: Cypress (JD Required qual) ranked weak and
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
        # The session's worst miss: a 'Mentored junior team member' bullet
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
        # 'partner integrations' — same evidence (QualityAI session: the
        # Amex partner-integrations bullet was ranked for cutting while the
        # JD asked for 'API, service, integration, and backend validation').
        self.assertEqual(
            mr._jd_hits("Tested partner integrations", {"integration"}),
            ["integration"])

    def test_short_tech_term_matches_plural(self):
        # 'api' (len 3) must still match the plural 'APIs'.
        self.assertEqual(mr._jd_hits("Validated the REST APIs", {"api"}),
                         ["api"])


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

    Session failure regressed here (QualityAI Playwright JD): the JD's
    'Perform API, service, integration, and backend validation' names
    'integration' lowercase mid-sentence, so the bullet-only term was
    rejected and the DROP PLAN suggested cutting the Amex
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
            _para("Rakuten, San Diego, CA" + _sample_date() + " – 01/2019",
                  style=mr.COMPANY_STYLE),
            _para("Senior Quality Assurance Engineer", style="JobTitleBlock"),
            _para("Tested American Express partner integrations against "
                  "their sandbox, coordinating with Amex engineers on "
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

    def test_amex_integration_bullet_is_jd_evidence(self):
        terms = mr._jd_terms(self._JD, self._body())
        amex = ("Tested American Express partner integrations against "
                "their sandbox, coordinating with Amex engineers on "
                "unexpected response codes")
        self.assertTrue(mr._jd_kept(amex, terms),
                        "integration bullet must be JD-protected")

    def test_generic_hit_rate_guard_still_applies(self):
        # The exemption cannot flood: a core noun hitting most bullets is
        # still guard-dropped.
        body = _body([
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Databases: SQL Server"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company A" + _sample_date() + " – 04/2020",
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
            _para("Company A" + _sample_date() + " – 04/2020",
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
            _para("Payments Boot Camp: Glenbrook Partners"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, City" + _sample_date() + " – 04/2020",
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
        self.assertTrue(any("Payments Boot Camp" in t for t in texts))


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
    claimed vocabulary too. Session failure regressed here: the QualityAI
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


class TopBlockCandidatesTests(unittest.TestCase):
    """_top_block_candidates: off-JD proficiencies/cert lines are
    first-class cut candidates."""

    def _body(self, jd_term_line=True):
        ps = [
            _para("Technical Proficiencies", style="SectionHeading"),
            _para("Programming Languages: Java, Python"),
            _para("Monitoring & Logging: Datadog, Grafana"),
            _para("Certifications", style="SectionHeading"),
            _para("Payments Boot Camp: Glenbrook Partners"),
            _para(mr.SECTION_CAREER, style="SectionHeading"),
            _para("Company ABC, City" + _sample_date() + " – 04/2020",
                  style=mr.COMPANY_STYLE),
            _para("Senior SDET", style="JobTitleBlock"),
            _para("Bullet one", numId=2),
        ]
        return _body(ps)

    def test_off_jd_lines_are_candidates(self):
        cands = mr._top_block_candidates(self._body(), jd_terms={"java"})
        texts = [t for _p, t in cands]
        self.assertTrue(any("Monitoring" in t for t in texts))
        self.assertTrue(any("Payments Boot Camp" in t for t in texts))

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


class ApplySimulateTests(unittest.TestCase):
    """_apply_simulate: seniority-alignment what-if — drop whole roles in a
    TEMP COPY and measure that, so the resulting visible timeline span is
    computed by the tool instead of by hand in chat. The original file must
    never be modified."""

    def _docx_with_roles(self):
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
            p("GEICO, Chevy Chase06/2025 – 07/2026", style=mr.COMPANY_STYLE),
            p("Staff Engineer", style="JobTitleBlock"),
            p("Led QA", style="BodyText", numid=4),
            p("Tools &amp; Technologies: Go", style="BodyText"),
            p("", style="BodyText"),
            p("Illumina, San Diego02/2012 – 10/2014", style=mr.COMPANY_STYLE),
            p("Software Test Engineer I", style="JobTitleBlock"),
            p("Tested DNA pipelines", style="BodyText", numid=8),
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

    def test_drops_role_in_copy_original_untouched(self):
        src = self._docx_with_roles()
        try:
            with open(src, "rb") as f:
                before = f.read()
            out = tempfile.mktemp(suffix=".docx")
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), \
                        contextlib.redirect_stderr(buf):
                    out_path, dropped = mr._apply_simulate(
                        src, ["Illumina, San Diego"], out)
                self.assertEqual(out_path, out)
                self.assertEqual(len(dropped), 1)
                self.assertIn("Illumina", dropped[0])
                with open(src, "rb") as f:
                    self.assertEqual(f.read(), before,
                                     "original must never be modified")
                root, body, _, _, _ = de.load(out)
                texts = [de.text_of(p) for p in de.paras(body)]
                self.assertFalse(any("Illumina" in t for t in texts))
                self.assertIn("GEICO, Chevy Chase06/2025 – 07/2026", texts)
                self.assertIn(mr.SECTION_EDUCATION, texts)
            finally:
                for suffix in ("", ".drift.json"):
                    if os.path.exists(out + suffix):
                        os.unlink(out + suffix)
        finally:
            os.unlink(src)

    def test_missing_prefix_reported_not_dropped(self):
        src = self._docx_with_roles()
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


class GapIfDroppedTests(unittest.TestCase):
    """_gap_if_dropped: interior whole-role drops open employment gaps."""

    def _roles(self):
        return [
            {"key": "geico", "raw": "GEICO06/2025 – 07/2026"},
            {"key": "symbols", "raw": "Symbols02/2025 – 06/2025"},
            {"key": "caremetx", "raw": "CareMetx04/2023 – 01/2025"},
            {"key": "rakuten", "raw": "Rakuten01/2016 – 01/2019"},
        ]

    def test_interior_drop_opens_gap(self):
        # Dropping Symbols leaves CareMetx (ends 01/2025) next to GEICO
        # (starts 06/2025): a 5-month gap.
        self.assertEqual(mr._gap_if_dropped(self._roles(), "symbols"), 5)

    def test_oldest_drop_no_gap(self):
        self.assertEqual(mr._gap_if_dropped(self._roles(), "rakuten"), 0)

    def test_newest_drop_no_gap(self):
        self.assertEqual(mr._gap_if_dropped(self._roles(), "geico"), 0)

    def test_gapless_interior_drop_no_gap(self):
        roles = [
            {"key": "b", "raw": "B01/2020 – 06/2020"},
            {"key": "a", "raw": "A01/2019 – 01/2020"},
        ]
        self.assertEqual(mr._gap_if_dropped(roles, "a"), 0)

    def test_unknown_key_no_gap(self):
        self.assertEqual(mr._gap_if_dropped(self._roles(), "nope"), 0)


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