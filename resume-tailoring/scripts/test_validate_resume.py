"""Unit tests for validate_resume.py's structural and claim checks.

Run from the scripts directory:

    cd ~/.pi/agent/skills/resume-tailoring/scripts && python3 -m unittest test_validate_resume
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402
import validate_resume as vr  # noqa: E402

W = de.W


def mk(text, style=None, numId=None):
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


def body(*ps):
    b = ET.Element(W + "body")
    for p in ps:
        b.append(p)
    return b


class StructuralTests(unittest.TestCase):
    def test_clean_region_no_errors(self):
        region = [
            mk("Acme Corp, Springfield, MA (Remote)03/2022 – 02/2023",
               style=mr.COMPANY_STYLE),
            mk("Staff Engineer", style=vr.TITLE_STYLE),
            mk("Bullet one", numId=4),
            mk("Tools & Technologies: Go"),
        ]
        self.assertEqual(vr._structural_errors(region), [])

    def test_dangling_title_is_error(self):
        # A company header was removed but its title survived, sitting right
        # after the previous role's Tools line (the orphan-title failure).
        region = [
            mk("Globex, TX08/2014 – 03/2015", style=mr.COMPANY_STYLE),
            mk("Senior QA Engineer", style=vr.TITLE_STYLE),
            mk("bullet", numId=4),
            mk("Tools & Technologies: Java"),
            mk("Senior QA Engineer", style=vr.TITLE_STYLE),  # dangling
        ]
        errs = vr._structural_errors(region)
        self.assertTrue(
            any("without a preceding company" in e for e in errs),
            f"expected orphan-title error, got: {errs}",
        )

    def test_company_without_title_is_error(self):
        region = [
            mk("Co A, City11/2017", style=mr.COMPANY_STYLE),
            mk("bullet without a title", numId=4),
        ]
        errs = vr._structural_errors(region)
        self.assertTrue(any("no job title" in e for e in errs))

    def test_orphaned_bullets_after_tools_flagged(self):
        region = [
            mk("Co A, City11/2017", style=mr.COMPANY_STYLE),
            mk("Title A", style=vr.TITLE_STYLE),
            mk("bullet A", numId=4),
            mk("Tools & Technologies: Go"),
            mk("leftover bullet with no company", numId=4),
        ]
        errs = vr._structural_errors(region)
        self.assertTrue(any("orphaned" in e for e in errs))

    def test_region_stops_at_next_section_heading(self):
        b = body(
            mk("Career Experience", style="SectionHeading"),
            mk("Co A, City11/2017", style=mr.COMPANY_STYLE),
            mk("bullet", numId=4),
            mk("Open Source", style="SectionHeading"),
            mk("an unrelated project bullet", numId=4),
        )
        region = vr._region(b)
        self.assertEqual(len(region), 2)
        self.assertTrue(all("Open Source" not in de.text_of(p) for p in region))


class DuplicateTests(unittest.TestCase):
    def test_near_duplicate_detected(self):
        # A merge that left the source's old text beside the rewritten
        # target — a merge-into case from real tailoring sessions.
        region = [
            mk("Developed an internal workflow integrating Azure CLI, "
               "GitHub CLI, and SonarQube API tooling", numId=4),
            mk("The internal workflow integrated Azure CLI, GitHub CLI, "
               "and SonarQube API tooling", numId=4),
        ]
        dups = list(vr._near_duplicates(region))
        self.assertEqual(len(dups), 1)

    def test_distinct_bullets_not_flagged(self):
        region = [
            mk("Refactored the Go integration test framework into modules", numId=4),
            mk("Built weekly release pipeline cutting lead time by 90%", numId=4),
        ]
        self.assertEqual(list(vr._near_duplicates(region)), [])


class ClaimTests(unittest.TestCase):
    def test_claim_years_parses(self):
        self.assertEqual(vr._claim_years("7+ years of testing experience"), 7)
        self.assertEqual(vr._claim_years("15 years"), 15)
        self.assertIsNone(vr._claim_years("nothing here"))

    def test_visible_span_from_company_dates(self):
        headers = [
            "Acme, MA (Remote)05/2021 – 02/2023",
            "Globex, TX03/2017 – 04/2018",
        ]
        first, last = mr._visible_span(headers)
        self.assertAlmostEqual(first, 2017 + 2 / 12, places=2)
        self.assertAlmostEqual(last, 2023 + 1 / 12, places=2)

    def test_undated_region_span_none(self):
        self.assertEqual(mr._visible_span(["plain paragraph"]), (None, None))

    def test_num_claim_regex_extracts_quantified_tokens(self):
        toks = [m.group(0) for m in
                vr.NUM_CLAIM.finditer("raised stability 50% and saved 40 hours")]
        self.assertEqual(toks, ["50%", "40 hours"])


def _write_docx(path, company_dates, education=True):
    """Write a minimal resume docx whose roles carry the given dates."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="'
            + de.XMLNS + '"><w:body/></w:document>',
        )
        z.writestr("[Content_Types].xml", "<Types/>")
    root, body, names, data, _ = de.load(path)
    ps = [mk("Career Experience", style="SectionHeading")]
    for date in company_dates:
        ps.append(mk("Company, City" + date, style=mr.COMPANY_STYLE))
        ps.append(mk("Title", style=vr.TITLE_STYLE))
        ps.append(mk("bullet", numId=4))
    if education:
        ps.append(mk("Education", style="SectionHeading"))
    for p in ps:
        body.append(p)
    with contextlib.redirect_stdout(io.StringIO()):
        de.save(path, root, names, data)  # silent: no edits applied


class PunctuationTests(unittest.TestCase):
    """Step 9 punctuation rule: periods and commas only in the Summary and
    job-history prose. Banned: em dashes, double hyphens (--), semicolons,
    and non-date en dashes. Exempt: single hyphens in compound words, en
    dashes inside date ranges, and structural lines (company headers, job
    titles) plus out-of-region sections (proficiencies, certifications)."""

    @staticmethod
    def _docx(path, summary_text=None, bullet_text="A clean bullet.",
              title_text="Staff Engineer", cert_text=None):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w="'
                + de.XMLNS + '"><w:body/></w:document>',
            )
            z.writestr("[Content_Types].xml", "<Types/>")
        root, body, names, data, _ = de.load(path)
        ps = []
        if summary_text is not None:
            ps.append(mk("Summary", style="SectionHeading"))
            ps.append(mk(summary_text, style=vr.SUMMARY_STYLE))
        ps.append(mk("Career Experience", style="SectionHeading"))
        ps.append(mk("Acme, MA (Remote)06/2021 – 05/2026",
                     style=mr.COMPANY_STYLE))
        ps.append(mk(title_text, style=vr.TITLE_STYLE))
        ps.append(mk(bullet_text, numId=4))
        ps.append(mk("Education", style="SectionHeading"))
        if cert_text is not None:
            ps.append(mk("Certifications", style="SectionHeading"))
            ps.append(mk(cert_text))
        for p in ps:
            body.append(p)
        with contextlib.redirect_stdout(io.StringIO()):
            de.save(path, root, names, data)

    @classmethod
    def _run(cls, path):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = vr.main([path])
        return rc, out.getvalue()

    # --- function-level: _punctuation_errors(region, summary) ---

    def test_clean_prose_passes(self):
        region = [
            mk("Acme, MA (Remote)06/2021 – 05/2026", style=mr.COMPANY_STYLE),
            mk("Staff Engineer – Test Automation & Quality Engineering",
               style=vr.TITLE_STYLE),
            mk("Sole quality resource for the core platform team.", numId=4),
            mk("Tools & Technologies: Go, Python, Jenkins"),
        ]
        self.assertEqual(vr._punctuation_errors(region, None), [])

    def test_compound_and_date_exemptions(self):
        region = [
            mk("Re-architected test-automation and end-to-end CI/CD pipelines.",
               numId=4),
            mk("Co-presented with a fellow Staff Engineer.", numId=4),
            mk("Covered releases 03/2024 – 06/2024 while on call.", numId=4),
        ]
        self.assertEqual(vr._punctuation_errors(region, None), [])

    def test_em_dash_flagged(self):
        region = [mk("Cut release lead time — by over 90%.", numId=4)]
        errs = vr._punctuation_errors(region, None)
        self.assertTrue(any("em dash" in e for e in errs), errs)

    def test_double_hyphen_flagged(self):
        region = [mk("Built the pipeline -- twice as fast.", numId=4)]
        errs = vr._punctuation_errors(region, None)
        self.assertTrue(any("double hyphen" in e for e in errs), errs)

    def test_semicolon_flagged(self):
        region = [mk("Ran workshops; documented best practices.", numId=4)]
        errs = vr._punctuation_errors(region, None)
        self.assertTrue(any("semicolon" in e for e in errs), errs)

    def test_non_date_en_dash_flagged(self):
        region = [mk("Owned quality – then speed of releases.", numId=4)]
        errs = vr._punctuation_errors(region, None)
        self.assertTrue(any("en dash" in e for e in errs), errs)

    def test_summary_scanned(self):
        s = mk("Leads quality end-to-end — no compromise.",
               style=vr.SUMMARY_STYLE)
        errs = vr._punctuation_errors([], s)
        self.assertTrue(any("em dash" in e for e in errs), errs)

    def test_structural_lines_not_scanned(self):
        # Job titles and company date lines are structural separators, not
        # prose — the title en dash and the date range must NOT flag.
        region = [
            mk("Acme, MA (Remote)06/2021 – 05/2026", style=mr.COMPANY_STYLE),
            mk("Staff Engineer – Test Automation & Quality Engineering",
               style=vr.TITLE_STYLE),
            mk("A clean bullet.", numId=4),
        ]
        self.assertEqual(vr._punctuation_errors(region, None), [])

    # --- blocking behavior through vr.main ---

    def test_em_dash_in_bullet_blocks_render(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path, bullet_text="Cut release lead time — by over 90%.")
            rc, out = self._run(path)
        finally:
            os.unlink(path)
        self.assertEqual(rc, 2)
        self.assertIn("PUNCTUATION", out)
        self.assertIn("em dash", out)

    def test_semicolon_in_summary_blocks_render(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path, summary_text="Leads quality; owns testing.")
            rc, out = self._run(path)
        finally:
            os.unlink(path)
        self.assertEqual(rc, 2)
        self.assertIn("semicolon", out)

    def test_out_of_scope_dashes_do_not_block(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path, cert_text="Test Academy – Issued 11/2025")
            rc, out = self._run(path)
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("ok (periods and commas", out)


class JdYearsTests(unittest.TestCase):
    """--jd-years N compares the visible span against the JD's years ask:
    under -> warn (underqualified), far over -> advisory note."""

    def _docx(self, path, company_dates):
        _write_docx(path, company_dates)

    def _run(self, path, jd_years):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = vr.main([path, "--jd-years", str(jd_years)])
        return rc, out.getvalue()

    def test_jd_years_underqualified_warns(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path, ["01/2022 – 12/2024"])
            rc, out = self._run(path, 5)
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("below the JD's 5", out)

    def test_jd_years_overshoot_notes(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path, ["02/2015 – 10/2026"])
            rc, out = self._run(path, 5)
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("well above the ask", out)

    def test_jd_years_aligned_ok(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path, ["09/2019 – 08/2026"])
            rc, out = self._run(path, 5)
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("aligned", out)

    def test_jd_years_without_jd_years_in_text_warns_invented(self):
        # Regression (real session): with no years line in the JD, an
        # agent invented --jd-years 10 'as a test value' and got a false
        # underqualified verdict plus a load-bearing education warning.
        # The validator now flags the invented ask.
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        fd2, jd = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd2, "w") as f:
            f.write("Strong web test automation experience required.")
        try:
            self._docx(path, ["09/2019 – 08/2026"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = vr.main([path, "--jd", jd, "--jd-years", "10"])
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 0)
        self.assertIn("--jd-years 10 passed", out.getvalue())
        self.assertIn("states no 'N+ years' ask", out.getvalue())


class TitleAlignmentValidateTests(unittest.TestCase):
    """--jd surfaces the SKILL Step 4 title signal at render time: a
    resume whose headline is MORE SENIOR than the JD's title warns
    (advisory — never blocks, exit 0); an already-aligned headline is ok.
    The check is shared with measure_resume (mr.title_alignment_notes)."""

    def _docx(self, path, headline="Staff Engineer"):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w="'
                + de.XMLNS + '"><w:body/></w:document>',
            )
            z.writestr("[Content_Types].xml", "<Types/>")
        root, body, names, data, _ = de.load(path)
        ps = [
            mk("Adrian Alan", style=mr.HEADLINE_STYLE),
            mk(headline, style=mr.HEADLINE_STYLE),
            mk("Summary", style="SectionHeading"),
            mk("Results-driven engineer.", style=vr.SUMMARY_STYLE),
            mk("Career Experience", style="SectionHeading"),
            mk("Company, City01/2020 – 12/2024", style=mr.COMPANY_STYLE),
            mk("Staff Engineer", style=vr.TITLE_STYLE),
            mk("bullet", numId=4),
        ]
        for p in ps:
            body.append(p)
        with contextlib.redirect_stdout(io.StringIO()):
            de.save(path, root, names, data)

    def _run(self, path, jd_text):
        fd, jd = tempfile.mkstemp(suffix=".txt")
        os.write(fd, jd_text.encode())
        os.close(fd)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = vr.main([path, "--jd", jd])
        finally:
            os.unlink(jd)
        return rc, out.getvalue()

    def test_staff_headline_vs_mid_jd_warns_without_blocking(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path)
            rc, out = self._run(path, "Software Test Engineer\n5+ years")
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)  # advisory, not a gate
        self.assertIn("MORE SENIOR", out)
        self.assertIn("Software Test Engineer", out)

    def test_aligned_headline_ok(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path, headline="Software Test Engineer")
            rc, out = self._run(path, "Software Test Engineer\n5+ years")
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertNotIn("MORE SENIOR", out)
        self.assertIn("matches the JD title", out)


class RoleIntegrityTests(unittest.TestCase):
    """Whole-role removals must be WHOLE (validated against the master):
    kept roles keep title+bullets; removed roles leave no surviving bullets
    (the orphaned-content failure)."""

    @staticmethod
    def _write(path, roles):
        """roles: list of (header, title_or_None, [bullet_texts])."""
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                "word/document.xml",
                '<?xml version="1.0"?><w:document xmlns:w="'
                + de.XMLNS + '"><w:body/></w:document>',
            )
            z.writestr("[Content_Types].xml", "<Types/>")
        root, body, names, data, _ = de.load(path)
        ps = [mk("Career Experience", style="SectionHeading")]
        for header, title, bullets in roles:
            ps.append(mk(header, style=mr.COMPANY_STYLE))
            if title:
                ps.append(mk(title, style=vr.TITLE_STYLE))
            for b in bullets:
                ps.append(mk(b, numId=4))
        ps.append(mk("Education", style="SectionHeading"))
        for p in ps:
            body.append(p)
        with contextlib.redirect_stdout(io.StringIO()):
            de.save(path, root, names, data)

    def _run(self, master_roles, target_roles):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        master = os.path.join(td.name, "Test Master Resume.docx")
        target = os.path.join(td.name, "Test Resume - Target.docx")
        self._write(master, master_roles)
        self._write(target, target_roles)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = vr.main([target, "--master", master, "--seniority-approved"])
        return rc, out.getvalue()

    def test_clean_tailoring_passes(self):
        roles = [
            ("Co A, City01/2020 – 06/2021", "Title A", ["bullet A1", "b A2"]),
            ("Co B, City11/2017 – 06/2018", "Title B", ["bullet B1"]),
        ]
        target = [roles[0]]  # B removed whole, A kept whole
        rc, out = self._run(roles, target)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("role integrity", out.lower())

    def test_role_kept_but_bullets_all_removed_is_error(self):
        roles = [
            ("Co A, City01/2020 – 06/2021", "Title A", ["bullet A1"]),
            ("Co B, City11/2017 – 06/2018", "Title B", ["bullet B1"]),
        ]
        target = [
            ("Co A, City01/2020 – 06/2021", "Title A", []),  # emptied
            ("Co B, City11/2017 – 06/2018", "Title B", ["bullet B1"]),
        ]
        rc, out = self._run(roles, target)
        self.assertEqual(rc, 2)
        self.assertIn("ALL its bullets", out)

    def test_role_removed_but_bullet_survives_is_error(self):
        roles = [
            ("Co A, City01/2020 – 06/2021", "Title A", ["bullet A1"]),
            ("Co B, City11/2017 – 06/2018", "Title B", ["orphan B1"]),
        ]
        # B removed but its bullet text survives under role A (the
        # orphaned-content failure: bullets kept, header/title dropped).
        target = [
            ("Co A, City01/2020 – 06/2021", "Title A",
             ["bullet A1", "orphan B1"]),
        ]
        rc, out = self._run(roles, target)
        self.assertEqual(rc, 2)
        self.assertIn("survives", out)

    def test_role_kept_but_title_removed_is_error(self):
        roles = [
            ("Co A, City01/2020 – 06/2021", "Title A", ["bullet A1"]),
        ]
        target = [
            ("Co A, City01/2020 – 06/2021", None, ["bullet A1"]),
        ]
        rc, out = self._run(roles, target)
        self.assertEqual(rc, 2)
        self.assertIn("job title was removed", out)


class SeniorityGateTests(unittest.TestCase):
    """The Step 3 seniority gate: whole-role elimination (visible span >= 2y
    shorter than the master) is a blocking error unless --seniority-approved
    records the user's approval."""

    @staticmethod
    def _pair(td, master_dates, target_dates):
        master = os.path.join(td, "Test Master Resume.docx")
        target = os.path.join(td, "Test Resume - Target.docx")
        _write_docx(master, master_dates)
        _write_docx(target, target_dates)
        return master, target

    @staticmethod
    def _run(target, master, *extra):
        out = io.StringIO()
        args = [target, "--jd-years", "5", "--master", master, *extra]
        with contextlib.redirect_stdout(out):
            rc = vr.main(args)
        return rc, out.getvalue()

    def test_elimination_without_approval_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            master, target = self._pair(
                td,
                ["02/2013 – 01/2015", "03/2016 – 04/2017", "05/2020 – 12/2026"],  # ~13.8y
                ["05/2020 – 12/2026"],  # ~6.6y  -> shrink ~7.2y
            )
            rc, out = self._run(target, master)
        self.assertEqual(rc, 2)
        self.assertIn("whole-role elimination detected", out)
        self.assertIn("--seniority-approved", out)

    def test_elimination_with_approval_passes(self):
        with tempfile.TemporaryDirectory() as td:
            master, target = self._pair(
                td,
                ["02/2013 – 01/2015", "03/2016 – 04/2017", "05/2020 – 12/2026"],
                ["05/2020 – 12/2026"],
            )
            rc, out = self._run(target, master, "--seniority-approved")
        self.assertEqual(rc, 0)
        self.assertIn("seniority alignment approved", out)

    def test_no_elimination_no_gate(self):
        with tempfile.TemporaryDirectory() as td:
            master, target = self._pair(td, ["03/2021 – 12/2026"], ["03/2021 – 12/2026"])
            rc, out = self._run(target, master)
            self.assertEqual(rc, 0)
            self.assertNotIn("whole-role elimination", out)

    def test_small_shrink_below_threshold_passes(self):
        # Shrink < SENIORITY_GATE_YEARS (1y) -> no gate, no flag needed.
        with tempfile.TemporaryDirectory() as td:
            master, target = self._pair(
                td,
                ["09/2015 – 12/2026"],
                ["09/2016 – 12/2026"],
            )
            rc, out = self._run(target, master)
        self.assertEqual(rc, 0)
        self.assertNotIn("whole-role elimination", out)


class EducationGateTests(unittest.TestCase):
    """--jd <file> encodes Step 3.4's education predicates mechanically:
    a JD that REQUIRES a degree blocks the render when Education was
    dropped (--education-approved records an override); under an
    'or equivalent' clause the clause is load-bearing only when the
    visible span exceeds the ask."""

    JD_DEGREE = ("Bachelor's degree in Computer Science or a related "
                 "field required. 5+ years of test automation experience.")
    JD_EQUIV = ("Bachelor's degree in Computer Science, or equivalent "
                "professional experience. 5+ years of test automation.")
    JD_NO_DEGREE = "5+ years of test automation experience required."

    def _jd(self, text):
        fd, jd = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        return jd

    def _run(self, path, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = vr.main([path, *args])
        return rc, out.getvalue()

    def test_degree_required_education_dropped_blocks(self):
        jd = self._jd(self.JD_DEGREE)
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _write_docx(path, ["04/2021 – 09/2026"], education=False)
            rc, out = self._run(path, "--jd", jd, "--jd-years", "5")
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 2)
        self.assertIn("Education", out)
        self.assertIn("no 'or equivalent' substitution clause", out)

    def test_degree_required_education_dropped_approved_passes(self):
        jd = self._jd(self.JD_DEGREE)
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _write_docx(path, ["04/2021 – 09/2026"], education=False)
            rc, out = self._run(path, "--jd", jd, "--education-approved")
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 0)
        self.assertIn("--education-approved", out)

    def test_degree_required_education_kept_ok(self):
        jd = self._jd(self.JD_DEGREE)
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _write_docx(path, ["04/2021 – 09/2026"])
            rc, out = self._run(path, "--jd", jd)
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 0)
        self.assertNotIn("restore the section", out)

    def test_equivalent_clause_span_above_ask_ok(self):
        # The clause is satisfied by experience when the visible span
        # exceeds the ask, so the Education drop is safe.
        jd = self._jd(self.JD_EQUIV)
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _write_docx(path, ["04/2021 – 09/2026"], education=False)
            rc, out = self._run(path, "--jd", jd, "--jd-years", "5")
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 0)
        self.assertIn("satisfied", out)

    def test_equivalent_clause_span_at_ask_warns(self):
        # At/below the ask the clause is load-bearing: dropping Education
        # leaves nothing substituting for the degree.
        jd = self._jd(self.JD_EQUIV)
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _write_docx(path, ["01/2022 – 12/2024"], education=False)
            rc, out = self._run(path, "--jd", jd, "--jd-years", "5")
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 0)
        self.assertIn("load-bearing", out)

    def test_no_degree_requirement_no_gate(self):
        jd = self._jd(self.JD_NO_DEGREE)
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _write_docx(path, ["04/2021 – 09/2026"], education=False)
            rc, out = self._run(path, "--jd", jd)
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 0)
        self.assertNotIn("Education", out)

    def test_prose_degree_word_is_not_a_degree_requirement(self):
        # Regression (real session): the JD's 'a high degree of autonomy'
        # matched the old bare \bdegree\b, so a JD with NO degree
        # requirement entered the education gate and warned about the
        # dropped Education section.
        jd = self._jd(
            "Able to operate with a high degree of autonomy and identify "
            "where your input will create the most value. 5+ years of "
            "test automation experience required."
        )
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _write_docx(path, ["04/2021 – 09/2026"], education=False)
            rc, out = self._run(path, "--jd", jd)
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 0)
        self.assertNotIn("Education", out)

    def test_language_equivalence_is_not_an_education_clause(self):
        # Regression (real session): 'CEFR C2 or equivalent' matched the
        # old bare `or equivalent` branch, fabricating a load-bearing
        # education clause on a JD with no degree ask.
        jd = self._jd(
            "Exceptional written and verbal communication skills in "
            "English (CEFR C2 or equivalent), as most collaboration "
            "happens asynchronously. 5+ years of test automation "
            "experience required."
        )
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _write_docx(path, ["04/2021 – 09/2026"], education=False)
            rc, out = self._run(path, "--jd", jd)
        finally:
            os.unlink(path)
            os.unlink(jd)
        self.assertEqual(rc, 0)
        self.assertNotIn("load-bearing", out)

    def test_degree_and_equivalence_still_detected(self):
        # The tightened regexes must keep matching real credential
        # language: 'Bachelor's degree ... required' and 'or equivalent
        # professional experience' still enter the gate.
        self.assertTrue(vr.DEGREE_RE.search(self.JD_DEGREE))
        self.assertTrue(vr.DEGREE_RE.search(
            "Associate degree in a related field preferred."))
        self.assertTrue(vr.DEGREE_RE.search(
            "A bachelor's degree is required for this role."))
        self.assertTrue(vr.EQUIV_CLAUSE_RE.search(self.JD_EQUIV))
        self.assertTrue(vr.EQUIV_CLAUSE_RE.search(
            "Five years of experience, or an equivalent combination of "
            "education and experience."))

    def test_curly_apostrophe_degree_still_detected(self):
        # Regression (real session): a JD pasted from a PDF carried the
        # curly apostrophe — "Master’s degree" — which the ASCII-only
        # (?:'s)? group missed, so a degree-REQUIRING JD skipped the
        # education gate entirely and a dropped Education survived
        # validation until --jd-years forced a second look.
        self.assertTrue(vr.DEGREE_RE.search(
            "Employer will accept a Master\u2019s degree in Computer "
            "Science, Engineering, or related Technical field."))
        self.assertTrue(vr.DEGREE_RE.search(
            "Bachelor\u2019s degree in a related field."))


if __name__ == "__main__":
    unittest.main()