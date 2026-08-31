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
            mk("GEICO, Chevy Chase, MD (Remote)06/2025 – 07/2026",
               style=mr.COMPANY_STYLE),
            mk("Staff Engineer", style=vr.TITLE_STYLE),
            mk("Bullet one", numId=4),
            mk("Tools & Technologies: Go"),
        ]
        self.assertEqual(vr._structural_errors(region), [])

    def test_dangling_title_is_error(self):
        # A company header was removed but its title survived, sitting right
        # after the previous role's Tools line (the Epic/Rakuten failure).
        region = [
            mk("Republic, AZ02/2019 – 04/2020", style=mr.COMPANY_STYLE),
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
            mk("Co A, City01/2019", style=mr.COMPANY_STYLE),
            mk("bullet without a title", numId=4),
        ]
        errs = vr._structural_errors(region)
        self.assertTrue(any("no job title" in e for e in errs))

    def test_orphaned_bullets_after_tools_flagged(self):
        region = [
            mk("Co A, City01/2019", style=mr.COMPANY_STYLE),
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
            mk("Co A, City01/2019", style=mr.COMPANY_STYLE),
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
        # target — the ASDLC case from real tailoring sessions.
        region = [
            mk("Developed an ASDLC integrating Azure CLI, GitHub CLI, "
               "SonarQube API, and Grafana tooling", numId=4),
            mk("ASDLC integrations included Azure CLI, GitHub CLI, "
               "SonarQube API, and Grafana tooling; set up MCP", numId=4),
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
            "GEICO, MD (Remote)06/2025 – 07/2026",
            "Republic, AZ02/2019 – 04/2020",
        ]
        first, last = mr._visible_span(headers)
        self.assertAlmostEqual(first, 2019 + 1 / 12, places=2)
        self.assertAlmostEqual(last, 2026 + 6 / 12, places=2)

    def test_undated_region_span_none(self):
        self.assertEqual(mr._visible_span(["plain paragraph"]), (None, None))

    def test_num_claim_regex_extracts_quantified_tokens(self):
        toks = [m.group(0) for m in
                vr.NUM_CLAIM.finditer("raised stability 50% and saved 40 hours")]
        self.assertEqual(toks, ["50%", "40 hours"])


def _write_docx(path, company_dates):
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
        ps.append(mk("GEICO, MD (Remote)01/2020 – 12/2026",
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
            mk("GEICO, MD (Remote)01/2020 – 12/2026", style=mr.COMPANY_STYLE),
            mk("Staff Engineer – Quality Automation & Engineering Enablement",
               style=vr.TITLE_STYLE),
            mk("Sole quality resource for the Payments department.", numId=4),
            mk("Tools & Technologies: Go, Python, Jenkins"),
        ]
        self.assertEqual(vr._punctuation_errors(region, None), [])

    def test_compound_and_date_exemptions(self):
        region = [
            mk("Re-architected test-automation and end-to-end CI/CD pipelines.",
               numId=4),
            mk("Co-presented with a fellow Staff Engineer.", numId=4),
            mk("Covered releases 06/2025 – 07/2026 while on call.", numId=4),
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
            mk("GEICO, MD (Remote)01/2020 – 12/2026", style=mr.COMPANY_STYLE),
            mk("Staff Engineer – Quality Automation & Engineering Enablement",
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
            self._docx(path, cert_text="Glenbrook Partners – Issued 03/2026")
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
            self._docx(path, ["01/2016 – 12/2026"])
            rc, out = self._run(path, 5)
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("well above the ask", out)

    def test_jd_years_aligned_ok(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._docx(path, ["01/2020 – 12/2026"])
            rc, out = self._run(path, 5)
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0)
        self.assertIn("aligned", out)


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
                ["01/2012 – 12/2014", "01/2015 – 12/2016", "01/2019 – 12/2026"],  # ~14.5y
                ["01/2019 – 12/2026"],  # ~7.9y  -> shrink ~6.6y
            )
            rc, out = self._run(target, master)
        self.assertEqual(rc, 2)
        self.assertIn("whole-role elimination detected", out)
        self.assertIn("--seniority-approved", out)

    def test_elimination_with_approval_passes(self):
        with tempfile.TemporaryDirectory() as td:
            master, target = self._pair(
                td,
                ["01/2012 – 12/2014", "01/2015 – 12/2016", "01/2019 – 12/2026"],
                ["01/2019 – 12/2026"],
            )
            rc, out = self._run(target, master, "--seniority-approved")
        self.assertEqual(rc, 0)
        self.assertIn("seniority alignment approved", out)

    def test_no_elimination_no_gate(self):
        with tempfile.TemporaryDirectory() as td:
            master, target = self._pair(td, ["01/2019 – 12/2026"], ["01/2019 – 12/2026"])
            rc, out = self._run(target, master)
            self.assertEqual(rc, 0)
            self.assertNotIn("whole-role elimination", out)

    def test_small_shrink_below_threshold_passes(self):
        # Shrink < SENIORITY_GATE_YEARS (1y) -> no gate, no flag needed.
        with tempfile.TemporaryDirectory() as td:
            master, target = self._pair(
                td,
                ["01/2014 – 12/2026"],
                ["01/2015 – 12/2026"],
            )
            rc, out = self._run(target, master)
        self.assertEqual(rc, 0)
        self.assertNotIn("whole-role elimination", out)


if __name__ == "__main__":
    unittest.main()