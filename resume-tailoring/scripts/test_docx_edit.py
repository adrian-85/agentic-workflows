"""Unit tests for the docx_edit helper library.

Run from the scripts directory (so `docx_edit` is importable):

    cd ~/.pi/agent/skills/resume-tailoring/scripts && python3 -m unittest test_docx_edit

Or directly:

    python3 scripts/test_docx_edit.py

These tests build tiny in-memory OOXML paragraphs (no .docx files on disk)
and exercise the mutation primitives: replace_text (per-run replacement;
spanning occurrences left in place), set_text, set_labeled, find_p, remove,
remove_empty, clone_after.
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

W = de.W
SPACE = de.SPACE


# Shared fixtures used by multiple test classes.
def _empty_docx(path):
    """Minimal valid .docx with an empty body — fast, no real content."""
    doc = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="' + de.XMLNS + '"><w:body/></w:document>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("[Content_Types].xml", "<Types/>")


def mkp(*runs):
    """Build a <w:p> from (text, bold) run tuples.

    bold is one of:
      True  -> <w:b/>                       (explicit bold)
      False -> <w:b w:val="false"/>         (explicit non-bold, as the master
                                            marks proficiency value runs)
      None  -> no <w:b> element at all       (formatating inherited)
    """
    p = ET.Element(W + "p")
    for text, bold in runs:
        r = ET.SubElement(p, W + "r")
        rPr = ET.SubElement(r, W + "rPr")
        if bold is True:
            ET.SubElement(rPr, W + "b")
        elif bold is False:
            b = ET.SubElement(rPr, W + "b")
            b.set(W + "val", "false")
        t = ET.SubElement(r, W + "t")
        t.text = text
        t.set(SPACE, "preserve")
    return p


def fmt(p):
    """Return [(run_text, is_bold), ...] for a paragraph.

    A run is bold only if <w:b/> is present without a false val. <w:b
    w:val="false"/> (how the master marks non-bold value runs) is NOT bold.
    """
    out = []
    for rr in p.findall(W + "r"):
        txt = "".join(tt.text or "" for tt in rr.findall(W + "t"))
        bold = False
        rPr = rr.find(W + "rPr")
        if rPr is not None:
            b = rPr.find(W + "b")
            if b is not None and b.get(W + "val") not in ("0", "false"):
                bold = True
        out.append((txt, bold))
    return out


def mkstyled(text, style, numId=None):
    """Build a <w:p> with a pStyle (and optional numId), mirroring the
    master's CompanyBlock/JobTitleBlock/BodyText/SectionHeading styles."""
    p = ET.Element(W + "p")
    pPr = ET.SubElement(p, W + "pPr")
    st = ET.SubElement(pPr, W + "pStyle")
    st.set(W + "val", style)
    if numId is not None:
        np = ET.SubElement(pPr, W + "numPr")
        ni = ET.SubElement(np, W + "numId")
        ni.set(W + "val", str(numId))
    r = ET.SubElement(p, W + "r")
    t = ET.SubElement(r, W + "t")
    t.text = text
    t.set(SPACE, "preserve")
    return p


class ReplaceTextTests(unittest.TestCase):
    """replace_text: per-run substring replacement preserving formatting."""

    def setUp(self):
        de._APPLIED = 0
        de._SKIPS.clear()

    def tearDown(self):
        de._APPLIED = 0
        de._SKIPS.clear()

    def test_replaces_and_preserves_formatting(self):
        """The core behavior: replace per-run and check result text and
        each run's formatting (bold preserved where expected)."""
        cases = [
            # (name, runs, old, new, want_text, want_fmt)
            ("single run",
             [("hello world foo", False), ("bar", True)],
             "world", "WORLD",
             "hello WORLD foobar",
             [("hello WORLD foo", False), ("bar", True)]),
            ("multi occurrences",
             [("foo and foo", False)],
             "foo", "FOO",
             "FOO and FOO",
             [("FOO and FOO", False)]),
            ("across runs",
             [("foo and foo", False), (" plus fo", True), ("o again", False)],
             "foo", "FOO",
             "FOO and FOO plus foo again",
             [("FOO and FOO", False), (" plus fo", True), ("o again", False)]),
            ("spanning untouched",
             [("hello wo", False), ("rld end", True)],
             "world", "WORLD",
             "hello world end",
             [("hello wo", False), ("rld end", True)]),
            ("old-in-new safe",
             [("AI AI", False)],
             "AI", "AIx",
             "AIx AIx",
             [("AIx AIx", False)]),
        ]
        for name, runs, old, new, want_text, want_fmt in cases:
            with self.subTest(name=name):
                p = mkp(*runs)
                de.replace_text(p, old, new)
                self.assertEqual(de.text_of(p), want_text)
                self.assertEqual(fmt(p), want_fmt)

    def test_not_found_warns_and_no_crash(self):
        """A None paragraph warns 'target paragraph not found' and leaves
        state unchanged; a paragraph that WAS found but lacks the search text
        warns distinctly, naming the paragraph (not the literal) so an author
        who targeted the wrong paragraph sees that the PREFIX is the problem.
        """
        # None paragraph: find_p() couldn't resolve — the prefix is missing.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.replace_text(None, "x", "y")
        self.assertIn("target paragraph not found", err.getvalue())
        self.assertIn("x", de._SKIPS)

        # Paragraph found but the search text is absent from it: the fix is a
        # DIFFERENT find_p prefix, not a text problem. The warning must name
        # the paragraph, not the literal old string (session case: target-
        # wrong-bullet edit misreported as a 'paragraph not found').
        p = mkp(("nothing here", False))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.replace_text(p, "MISSING", "X")
        self.assertEqual(de.text_of(p), "nothing here")
        self.assertEqual(de._APPLIED, 0)
        out = err.getvalue()
        self.assertNotIn("target paragraph not found", out)
        self.assertIn("does not contain that text", out)
        self.assertIn("'nothing here'", out)  # names the real paragraph
        self.assertIn("MISSING", de._SKIPS)

    def test_spanning_occurrence_skips_without_partial_mutation(self):
        # `old` appears in the joined text but NO single run contains it
        # (split across a run boundary): per-run replacement cannot cross
        # runs. Must skip cleanly BEFORE mutating — no partial edit, no
        # applied count, skip recorded so strict mode surfaces it. (The
        # session case: a grammar fix silently no-op'd against text whose
        # runs split the phrase, and only a manual XML grep caught it.)
        p = mkp(("Conducted Chaos testing ", False), ("Using AWS FIS", False))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.replace_text(p, "Chaos testing Using", "chaos testing using")
        self.assertEqual(de.text_of(p), "Conducted Chaos testing Using AWS FIS")
        self.assertEqual(de._APPLIED, 0, "spanning edit must not count as applied")
        self.assertIn("spans run boundaries", err.getvalue())
        self.assertIn("Chaos testing Using", de._SKIPS)


class SetTextTests(unittest.TestCase):
    """set_text rewrites a paragraph's text preserving the first run's rPr."""

    def test_rewrites_text_keeping_first_run_formatting(self):
        p = mkp(("old text", True), ("more", False))
        de.set_text(p, "new text")
        self.assertEqual(de.text_of(p), "new text")
        # Only the first run survives, with its bold rPr.
        self.assertEqual(fmt(p), [("new text", True)])

    def test_none_warns_and_no_crash(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.set_text(None, "anything")
        self.assertIn("target paragraph not found", err.getvalue())


class SetLabeledTests(unittest.TestCase):
    """set_labeled keeps the bold-label / non-bold-value split."""

    def test_splits_label_and_value(self):
        # Mirror the master's real structure: bold label run, then a value
        # run marked explicitly non-bold via <w:b w:val="false"/>.
        p = mkp(("Programming Languages:", True), (" Java, Python", False))
        de.set_labeled(p, "Programming Languages: ", "Java, Python, Go")
        self.assertEqual(de.text_of(p), "Programming Languages: Java, Python, Go")
        runs = fmt(p)
        self.assertEqual(len(runs), 2)
        self.assertTrue(runs[0][1], "label run should be bold")
        self.assertFalse(runs[1][1], "value run should be non-bold")

    def test_clone_shaped_single_run_label_derives_value_formatting(self):
        # clone_after collapses a "Label: values" line to ONE run carrying
        # the label's rPr, so set_labeled has no non-bold value run to copy.
        # It must derive the value run's rPr from the label run (drop the
        # style + bold, keep font/color) rather than leave it with no rPr —
        # the "OS & Scripting" line rendered with default font/color.
        p = ET.Element(W + "p")
        r = ET.SubElement(p, W + "r")
        rPr = ET.SubElement(r, W + "rPr")
        ET.SubElement(rPr, W + "rStyle").set(W + "val", "Strong")
        ET.SubElement(rPr, W + "rFonts")
        ET.SubElement(rPr, W + "b")
        color = ET.SubElement(rPr, W + "color")
        color.set(W + "val", "3465A4")
        sz = ET.SubElement(rPr, W + "sz")
        sz.set(W + "val", "20")
        t = ET.SubElement(r, W + "t")
        t.text = "OS & Scripting: "
        t.set(SPACE, "preserve")

        de.set_labeled(p, "OS & Scripting: ", "Linux, Bash, WSL, Powershell")

        runs = p.findall(W + "r")
        self.assertEqual(len(runs), 2)
        self.assertIsNotNone(runs[0].find(W + "rPr/" + W + "b"),
                             "label run keeps bold")
        vrPr = runs[1].find(W + "rPr")
        self.assertIsNotNone(vrPr, "value run must not be left without rPr")
        self.assertIsNone(vrPr.find(W + "b"), "value run must not be bold")
        self.assertIsNone(vrPr.find(W + "rStyle"),
                          "value run must not carry the label style")
        self.assertEqual(vrPr.find(W + "color").get(W + "val"), "3465A4",
                         "value run keeps the label color")
        self.assertEqual(vrPr.find(W + "sz").get(W + "val"), "20",
                         "value run keeps the label size")

    def test_none_warns_and_no_crash(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.set_labeled(None, "Label: ", "values")
        self.assertIn("target paragraph not found", err.getvalue())


class FindPTests(unittest.TestCase):
    """find_p locates a paragraph by unique text prefix."""

    def test_finds_by_prefix(self):
        ps = [mkp(("alpha", False)), mkp(("beta gamma", True))]
        self.assertIs(de.find_p(ps, "beta"), ps[1])

    def test_returns_none_when_missing(self):
        ps = [mkp(("alpha", False))]
        self.assertIsNone(de.find_p(ps, "zzz"))

    def test_warns_when_prefix_matches_multiple_paragraphs(self):
        # Ambiguous prefix (e.g. after a rewrite adopts another's label):
        # return None so the caller skips instead of clobbering the wrong
        # paragraph.
        ps = [mkp(("AI Tooling: new, rewritten", True)),
              mkp(("AI Tooling: original", True))]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = de.find_p(ps, "AI Tooling:")
        self.assertIsNone(result, "ambiguous prefix must skip, not clobber")
        self.assertIn("matches multiple paragraphs", err.getvalue())
        self.assertIn("not unique", err.getvalue())

    def test_finds_curly_apostrophe_prefix_typed_ascii(self):
        # Master text uses U+2019 (curly apostrophe); the script prefix is
        # typed with an ASCII quote. find_p must normalize both sides.
        ps = [mkp(("The company\u2019s goal is quality", False)),
              mkp(("Other paragraph", False))]
        self.assertIs(de.find_p(ps, "The company's goal"), ps[0])

    def test_finds_en_dash_date_typed_ascii_hyphen(self):
        # Company headers use an en dash in the date range (03/2022 – 02/2023).
        ps = [mkp(("03/2022 \u2013 02/2023", False)),
              mkp(("08/2019 \u2013 06/2020", False))]
        self.assertIs(de.find_p(ps, "03/2022 - 02/2023"), ps[0])
        self.assertIs(de.find_p(ps, "08/2019 - 06/2020"), ps[1])

    def test_finds_em_dash_bullet_typed_ascii_hyphen(self):
        # Bullets use em dashes (—) as separators.
        ps = [mkp(("Designed the release process \u2014 authored docs", False)),
              mkp(("Other", False))]
        self.assertIs(de.find_p(ps, "Designed the release process - authored docs"), ps[0])

    def test_finds_curly_quotes_typed_ascii_quotes(self):
        ps = [mkp(("He said \u201cyes\u201d today", False))]
        self.assertIs(de.find_p(ps, 'He said "yes" today'), ps[0])

    def test_ascii_prefix_still_matches_ascii_master_text(self):
        # Regression: normalization must not break the all-ASCII case.
        ps = [mkp(("Results-driven quality engineer ", True))]
        self.assertIs(de.find_p(ps, "Results-driven quality engineer "), ps[0])

    def test_after_anchors_search_to_later_paragraphs(self):
        # Two roles share an identical job title paragraph. Plain find_p is
        # ambiguous; anchored after the SECOND company header it must resolve
        # to that role's title (the duplicate-job-title case: anchor on the
        # role's OWN header to find its title below it).
        a = mkp(("Company A", False))
        t1 = mkp(("Senior Quality Assurance Engineer", True))
        b = mkp(("Company B", False))
        t2 = mkp(("Senior Quality Assurance Engineer", True))
        ps = [a, t1, b, t2]
        self.assertIsNone(de.find_p(ps, "Senior Quality Assurance Engineer"))
        self.assertIs(de.find_p(ps, "Senior Quality Assurance Engineer",
                                 after=b), t2)
        # After a, BOTH titles are strictly later — still ambiguous.
        self.assertIsNone(de.find_p(ps, "Senior Quality Assurance Engineer",
                                    after=a))

    def test_after_keeps_window_ambiguity(self):
        # Both duplicates sit after the anchor: still ambiguous, still None.
        a = mkp(("Company A", False))
        t1 = mkp(("Title", True))
        t2 = mkp(("Title", True))
        ps = [a, t1, t2]
        self.assertIsNone(de.find_p(ps, "Title", after=a))

    def test_after_missing_anchor_ignored(self):
        # An unresolvable anchor falls back to a plain (unanchored) lookup.
        ps = [mkp(("alpha", False)), mkp(("beta", True))]
        self.assertIs(de.find_p(ps, "beta", after=None), ps[1])

    def test_nth_selects_positional_duplicate(self):
        ps = [mkp(("Title", True)), mkp(("Title", True)), mkp(("Title", True))]
        self.assertIs(de.find_p(ps, "Title", nth=2), ps[1])
        self.assertIs(de.find_p(ps, "Title", nth=3), ps[2])

    def test_nth_beyond_count_returns_none(self):
        ps = [mkp(("Title", True)), mkp(("Title", True))]
        self.assertIsNone(de.find_p(ps, "Title", nth=5))


class ShortestUniquePrefixTests(unittest.TestCase):
    """shortest_unique_prefix returns the shortest prefix that uniquely
    identifies a paragraph among all paragraphs — the copy-pasteable
    find_p(ps, "...") argument. Powers measure_resume's DROP PLAN so the
    agent applies the exact listed bullet drops instead of re-reading the
    --prefixes dump."""

    def test_shortest_unique_prefix(self):
        texts = ["alpha one thing", "alpha two another", "beta whatever"]
        # Shortest prefix unique against ALL texts (min_len=1 contract):
        self.assertEqual(de.shortest_unique_prefix(texts, 0), "alpha o")
        self.assertEqual(de.shortest_unique_prefix(texts, 1), "alpha t")
        self.assertEqual(de.shortest_unique_prefix(texts, 2), "b")

    def test_none_when_duplicated_text(self):
        texts = ["identical title", "identical title", "other"]
        self.assertIsNone(de.shortest_unique_prefix(texts, 0))
        self.assertIsNone(de.shortest_unique_prefix(texts, 1))
        self.assertEqual(de.shortest_unique_prefix(texts, 2), "o")

    def test_full_text_prefix_is_unique(self):
        # A paragraph whose own text is a prefix of another's cannot be
        # addressed by ANY prefix (find_p would always be ambiguous) — the
        # helper returns None rather than a colliding prefix. The longer
        # paragraph resolves past the shorter text.
        texts = ["Lead the team", "Lead the team and built the framework"]
        self.assertIsNone(de.shortest_unique_prefix(texts, 0))
        self.assertEqual(de.shortest_unique_prefix(texts, 1),
                         "Lead the team ")


class RemoveEmptyTests(unittest.TestCase):
    """remove_empty drops blank spacer paragraphs."""

    def test_removes_blank_paragraphs(self):
        body = ET.Element(W + "body")
        a = ET.SubElement(body, W + "p"); _ = ET.SubElement(a, W + "t"); _.text = "keep"
        blank = ET.SubElement(body, W + "p")
        self.assertEqual(de.text_of(blank), "")
        n = de.remove_empty(body)
        self.assertEqual(n, 1)
        self.assertEqual(len(list(body.iter(W + "p"))), 1)

    def test_startswith_only_removes_at_or_after(self):
        body = ET.Element(W + "body")
        # blank BEFORE the marker stays; blank AT/AFTER marker is removed.
        blank_before = ET.SubElement(body, W + "p")
        marker = ET.SubElement(body, W + "p"); _ = ET.SubElement(marker, W + "t"); _.text = "MARKER"
        blank_after = ET.SubElement(body, W + "p")
        n = de.remove_empty(body, startswith="MARKER")
        self.assertEqual(n, 1)
        # blank_before remains, blank_after removed
        remaining = list(body.iter(W + "p"))
        self.assertIn(blank_before, remaining)
        self.assertNotIn(blank_after, remaining)


class CloneAfterTests(unittest.TestCase):
    """clone_after adds a bullet inheriting the ref's pPr/numbering."""

    def test_clones_bullet_after_ref_keeping_numbering(self):
        body = ET.Element(W + "body")
        ref = ET.SubElement(body, W + "p")
        pPr = ET.SubElement(ref, W + "pPr")
        numPr = ET.SubElement(pPr, W + "numPr")
        ni = ET.SubElement(numPr, W + "numId")
        ni.set(W + "val", "4")  # Most recent experience bullet numbering id
        r = ET.SubElement(ref, W + "r"); t = ET.SubElement(r, W + "t"); t.text = "ref"
        new = de.clone_after(body, ref, "new bullet")
        self.assertIsNotNone(new)
        # Cloned pPr keeps the same numId -> bullet style preserved.
        new_numId = new.find(W + "pPr/" + W + "numPr/" + W + "numId")
        self.assertIsNotNone(new_numId)
        self.assertEqual(new_numId.get(W + "val"), "4")
        self.assertEqual(de.text_of(new), "new bullet")
        # Inserted immediately after ref.
        self.assertEqual(list(body).index(new), list(body).index(ref) + 1)

    def test_none_ref_warns_and_no_crash(self):
        body = ET.Element(W + "body")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.clone_after(body, None, "x")
        self.assertIn("target paragraph not found", err.getvalue())


class RemoveTests(unittest.TestCase):
    """remove drops a paragraph from the body."""

    def test_removes_paragraph(self):
        body = ET.Element(W + "body")
        a = ET.SubElement(body, W + "p"); _ = ET.SubElement(a, W + "t"); _.text = "keep"
        b = ET.SubElement(body, W + "p"); _ = ET.SubElement(b, W + "t"); _.text = "drop"
        de.remove(body, b)
        self.assertEqual(len(list(body.iter(W + "p"))), 1)
        self.assertEqual(de.text_of(list(body.iter(W + "p"))[0]), "keep")

    def test_none_warns_and_no_crash(self):
        body = ET.Element(W + "body")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.remove(body, None)
        self.assertIn("target paragraph not found", err.getvalue())


class DropTests(unittest.TestCase):
    """drop(): library removal by prefixes — always resolves against a
    fresh paras(body), names skipped prefixes, returns the refreshed list."""

    def setUp(self):
        body = ET.Element(W + "body")
        for text in ("Established a comprehensive test automation approach",
                     "Established bi-monthly interdepartmental QA meetings",
                     "Unrelated bullet"):
            p = ET.SubElement(body, W + "p")
            t = ET.SubElement(p, W + "t")
            t.text = text
            de._ORIG[id(p)] = (p, de.text_of(p))
        self.body = body
        de._APPLIED = 0
        de._SKIPS.clear()
        de._ELEMENT_FORM_DROPS = 0

    def tearDown(self):
        de._ORIG.clear()
        de._APPLIED = 0
        de._SKIPS.clear()
        de._ELEMENT_FORM_DROPS = 0

    def test_removes_all_and_returns_refreshed_list(self):
        ps = de.drop(self.body, ["Established a comprehensive",
                                 "Unrelated bullet"])
        self.assertEqual([de.text_of(p) for p in ps],
                         ["Established bi-monthly interdepartmental QA meetings"])
        self.assertEqual(de._APPLIED, 2)

    def test_regression_short_prefix_after_superstring_removed(self):
        # THE session failure (BILL SDET tailoring): drop the LONGER prefix
        # first, then a SHORT prefix that also matches the removed
        # paragraph's text. The old per-script _drop threaded one ps list
        # across calls without refreshing the caller's copy, so the later
        # find_p ran against a list still holding the detached paragraph —
        # false ambiguity, edit skipped, exit 2 under strict. drop()
        # resolves against a fresh paras(body) every iteration, so the
        # short prefix resolves uniquely.
        de.drop(self.body, ["Established bi-monthly interde"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ps = de.drop(self.body, ["Establ"])
        self.assertNotIn("matches multiple", err.getvalue())
        self.assertEqual([de.text_of(p) for p in ps], ["Unrelated bullet"])

    def test_element_argument_converts_to_its_own_text(self):
        # THE motivating failure (a real tailoring session): set_text/
        # set_labeled/merge_into take find_p(...) ELEMENTS while drop()
        # documented prefix STRINGS, so a mixed-API script crashed with a
        # TypeError on its first strict run and cost a fix-and-rerun cycle.
        # A paragraph element's own text IS the prefix, so it is converted
        # (with a stderr note) instead of raising.
        element = de.find_p(de.paras(self.body), "Unrelated bullet")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ps = de.drop(self.body, [element])
        # The per-call stderr note was replaced by a counter that save()
        # reports as one summary line (22 bullet drops printed 22 notes).
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(de._ELEMENT_FORM_DROPS, 1)
        self.assertEqual([de.text_of(p) for p in ps],
                         ["Established a comprehensive test automation approach",
                          "Established bi-monthly interdepartmental QA meetings"])
        self.assertEqual(de._APPLIED, 1)

    def test_stale_element_records_skip_under_its_text(self):
        # An element held from BEFORE an earlier drop() removed its
        # paragraph must not mutate anything: the derived prefix is
        # re-resolved against a fresh paras(body), finds nothing, and the
        # skip is named by the (stale) paragraph's own text.
        stale = de.find_p(de.paras(self.body), "Unrelated bullet")
        de.drop(self.body, ["Unrelated bullet"])
        de._APPLIED = 0  # only the stale-element call below is under test
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ps = de.drop(self.body, [stale])
        self.assertIn("Unrelated bullet", err.getvalue())
        self.assertEqual([de.text_of(p) for p in ps],
                         ["Established a comprehensive test automation approach",
                          "Established bi-monthly interdepartmental QA meetings"])
        self.assertEqual(de._APPLIED, 0)

    def test_junk_argument_still_fails_fast(self):
        # Element conversion covers the documented authoring slip; a junk
        # type is a different bug and keeps the fail-fast contract.
        with self.assertRaises(TypeError) as ctx:
            de.drop(self.body, [42])
        self.assertIn("prefix STRING", str(ctx.exception))
        self.assertEqual(de._APPLIED, 0)
        self.assertEqual(len(list(self.body.iter(W + "p"))), 3)

    def test_missing_prefix_skips_with_named_prefix(self):
        # Unlike remove(None)'s generic "(remove)" label, the skip record
        # and warning name the actual prefix so strict reports point at
        # the culprit line in the tailor script.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.drop(self.body, ["No Such Prefix"])
        self.assertIn("No Such Prefix", err.getvalue())
        self.assertEqual(de._SKIPS, ["No Such Prefix"])
        self.assertEqual(de._APPLIED, 0)
        self.assertEqual(len(list(self.body.iter(W + "p"))), 3)


class DropRoleTests(unittest.TestCase):
    """drop_role(): whole-role removal for seniority alignment (SKILL Step 3).

    Session failure regressed here: a hand-rolled role-drop helper appended
    each paragraph BEFORE checking the block boundary and only treated
    Heading1/Heading2 as boundaries, so the role drop swallowed the
    SectionHeading ("Education") that followed the role — the later
    drop(body, ["Education", ...]) then skipped with 'target paragraph not
    found'. drop_role owns the block grammar: boundary styles are known,
    and the boundary paragraph is excluded, never consumed.
    """

    def setUp(self):
        ps = [
            mkstyled("Career Experience", "SectionHeading"),
            mkstyled("Acme Corp, Springfield03/2022 - 02/2023", "CompanyBlock"),
            mkstyled("Staff Engineer", "JobTitleBlock"),
            mkstyled("Led QA at Acme Corp", "BodyText", numId=4),
            mkstyled("Tools & Technologies: Go, Python", "BodyText"),
            mkstyled("", "BodyText"),
            mkstyled("Globex, Riverside07/2019 - 08/2019", "CompanyBlock"),
            mkstyled("Software QA Engineer", "JobTitleBlock"),
            mkstyled("Led QA for the flagship platform", "BodyText", numId=8),
            mkstyled("Tools & Technologies: Bamboo", "BodyText"),
            mkstyled("", "BodyText"),
            mkstyled("Initech, Metropolis01/2017 - 06/2018", "CompanyBlock"),
            # Duplicate of Globex's title — the case plain drop() cannot do.
            mkstyled("Software QA Engineer", "JobTitleBlock"),
            mkstyled("Primary test engineer for the flagship project", "BodyText", numId=8),
            mkstyled("Tools & Technologies: MS Test", "BodyText"),
            mkstyled("", "BodyText"),
            mkstyled("Education", "SectionHeading"),
            mkstyled("Some College", "CompanyBlock"),
            mkstyled("Bachelor's Degree", "JobTitleBlock"),
        ]
        self.body = ET.Element(W + "body")
        for p in ps:
            self.body.append(p)
            de._ORIG[id(p)] = (p, de.text_of(p))
        de._APPLIED = 0
        de._SKIPS.clear()

    def tearDown(self):
        de._ORIG.clear()
        de._APPLIED = 0
        de._SKIPS.clear()

    def _texts(self):
        return [de.text_of(p) for p in de.paras(self.body)]

    def test_removes_whole_role_including_tools_and_spacer(self):
        de.drop_role(self.body, "Initech, Metropolis")
        texts = self._texts()
        for gone in ("Initech, Metropolis01/2017 - 06/2018",
                     "Primary test engineer for the flagship project",
                     "Tools & Technologies: MS Test"):
            self.assertNotIn(gone, texts)
        # the trailing blank spacer went with the role (3 fixtures spacers
        # minus Initech's = 2 remain)
        self.assertEqual(texts.count(""), 2)

    def test_boundary_section_heading_is_never_consumed(self):
        # THE bug: the paragraph AFTER the role (Education SectionHeading)
        # must survive.
        de.drop_role(self.body, "Initech, Metropolis")
        texts = self._texts()
        self.assertIn("Education", texts)
        self.assertIn("Some College", texts)
        self.assertIn("Bachelor's Degree", texts)

    def test_previous_role_and_duplicate_title_survive(self):
        de.drop_role(self.body, "Initech, Metropolis")
        texts = self._texts()
        self.assertIn("Globex, Riverside07/2019 - 08/2019", texts)
        self.assertIn("Led QA for the flagship platform", texts)
        # exactly one of the two duplicate titles remains (Epic's)
        self.assertEqual(texts.count("Software QA Engineer"), 1)

    def test_returns_refreshed_paragraph_list(self):
        ps = de.drop_role(self.body, "Initech, Metropolis")
        self.assertEqual(ps, de.paras(self.body))
        # 19 fixture paragraphs - 5 removed (header, title, bullet, tools,
        # spacer) = 14
        self.assertEqual(len(ps), 14)

    def test_counts_one_applied_edit_per_removed_paragraph(self):
        de.drop_role(self.body, "Initech, Metropolis")
        # header + title + bullet + tools + spacer = 5 paragraphs
        self.assertEqual(de._APPLIED, 5)

    def test_missing_prefix_warns_names_prefix_and_mutates_nothing(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ps = de.drop_role(self.body, "No Such Company")
        self.assertIn("No Such Company", err.getvalue())
        self.assertEqual(de._SKIPS, ["drop_role: No Such Company"])
        self.assertEqual(ps, de.paras(self.body))
        self.assertEqual(de._APPLIED, 0)

    def test_anchor_on_wrong_style_skips(self):
        # A prefix that resolves to a NON-company paragraph (e.g. a section
        # heading) must refuse to mass-delete from that point.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ps = de.drop_role(self.body, "Career Experience")
        self.assertIn("CompanyBlock", err.getvalue())
        self.assertEqual(de._APPLIED, 0)
        self.assertEqual(len(ps), 19)

    def test_role_at_end_of_document_removed_to_eof(self):
        body = ET.Element(W + "body")
        for p in (mkstyled("Company A07/2014 - 08/2016", "CompanyBlock"),
                  mkstyled("Senior QA Engineer", "JobTitleBlock"),
                  mkstyled("Did things", "BodyText", numId=8),
                  mkstyled("Tools & Technologies: Java", "BodyText"),
                  mkstyled("", "BodyText")):
            body.append(p)
            de._ORIG[id(p)] = (p, de.text_of(p))
        try:
            de.drop_role(body, "Company A")
            self.assertEqual([de.text_of(p) for p in de.paras(body)], [])
        finally:
            de._ORIG.clear()

    def test_custom_style_names_for_other_resume_formats(self):
        body = ET.Element(W + "body")
        for p in (mkstyled("Employer X07/2014", "Employer"),
                  mkstyled("Title", "JobTitle"),
                  mkstyled("Bullet", "Body", numId=3),
                  mkstyled("Summary", "Heading")):
            body.append(p)
            de._ORIG[id(p)] = (p, de.text_of(p))
        try:
            de.drop_role(body, "Employer X", company_style="Employer",
                         boundary_styles=("Employer", "Heading"))
            self.assertEqual(
                [de.text_of(p) for p in de.paras(body)], ["Summary"])
        finally:
            de._ORIG.clear()

    def test_element_argument_converts_to_its_own_text(self):
        # Same mixed-API slip as DropTests: drop_role accepts a find_p
        # element and derives the company-header prefix from its text. The
        # whole Initech role (header through trailing spacer) goes; the
        # Education heading that bounds the block survives.
        element = de.find_p(de.paras(self.body), "Initech, Metropolis")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.drop_role(self.body, element)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(de._ELEMENT_FORM_DROPS, 1)
        texts = [de.text_of(p) for p in de.paras(self.body)]
        self.assertNotIn("Initech, Metropolis01/2017 - 06/2018", texts)
        self.assertNotIn("Primary test engineer for the flagship project", texts)
        self.assertIn("Education", texts)
        self.assertEqual(de._APPLIED, 5)


class DropSectionTests(unittest.TestCase):
    """drop_section(): remove a SectionHeading's whole section (e.g.
    Education when the JD gives the degree no evidentiary weight)."""

    def setUp(self):
        ps = [
            mkstyled("Acme Corp06/2017 - 09/2019", "CompanyBlock"),
            mkstyled("Senior QA Engineer", "JobTitleBlock"),
            mkstyled("Tested partner integrations", "BodyText", numId=8),
            mkstyled("", "BodyText"),
            mkstyled("Education", "SectionHeading"),
            mkstyled("Some College", "CompanyBlock"),
            mkstyled("Bachelor's Degree", "JobTitleBlock"),
            mkstyled("Certifications", "SectionHeading"),
            mkstyled("Advanced Testing Practice: Test Academy", "BodyText"),
        ]
        self.body = ET.Element(W + "body")
        for p in ps:
            self.body.append(p)
            de._ORIG[id(p)] = (p, de.text_of(p))
        de._APPLIED = 0
        de._SKIPS.clear()

    def tearDown(self):
        de._ORIG.clear()
        de._APPLIED = 0
        de._SKIPS.clear()

    def _texts(self):
        return [de.text_of(p) for p in de.paras(self.body)]

    def test_removes_section_stopping_at_next_section_heading(self):
        de.drop_section(self.body, "Education")
        texts = self._texts()
        for gone in ("Education", "Some College",
                     "Bachelor's Degree"):
            self.assertNotIn(gone, texts)
        # the NEXT section and the role above are untouched
        self.assertIn("Certifications", texts)
        self.assertIn("Advanced Testing Practice: Test Academy", texts)
        self.assertIn("Acme Corp06/2017 - 09/2019", texts)

    def test_section_at_eof_removed_to_end(self):
        de.drop_section(self.body, "Certifications")
        texts = self._texts()
        self.assertNotIn("Advanced Testing Practice: Test Academy", texts)
        self.assertIn("Education", texts)

    def test_missing_prefix_skips_named(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.drop_section(self.body, "No Such Section")
        self.assertEqual(de._SKIPS, ["drop_section: No Such Section"])
        self.assertEqual(len(self._texts()), 9)


class OriginalTextResolutionTests(unittest.TestCase):
    """find_p resolves prefixes against each paragraph's ORIGINAL text
    (captured at load/clone time), so a script's own earlier edits cannot
    cause prefix collisions mid-run."""

    def _register(self, *ps):
        for p in ps:
            de._ORIG[id(p)] = (p, de.text_of(p))

    def test_earlier_rewrite_cannot_collide_with_anothers_prefix(self):
        # Exact collision from an earlier tailoring run: two tools lines with
        # DIFFERENT original texts, where an earlier edit trims one so its
        # CURRENT text starts with the other's prefix. find_p must resolve by
        # ORIGINAL text. Data-driven over both list orders (the only thing
        # that varies) to prove resolution is keyed to original text, not
        # position.
        tools_a = mkp(("Tools & Technologies: C#, .NET, Angular, REST, SQL, MSMQ", True))
        tools_b = mkp(("Tools & Technologies: MVC, C#, .NET, Angular, REST", True))
        self._register(tools_a, tools_b)
        # Earlier edit: trim tools_b so its CURRENT text starts like tools_a's.
        de.set_labeled(
            tools_b,
            "Tools & Technologies: ",
            "C#, .NET, Angular, REST, GraphQL, SQL, Oracle, Kafka, Kubernetes",
        )
        self.assertTrue(
            de.text_of(tools_b).startswith("Tools & Technologies: C#, .NET")
        )
        for i, ordered_ps in enumerate(([tools_a, tools_b], [tools_b, tools_a])):
            with self.subTest(order=i):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    found = de.find_p(ordered_ps, "Tools & Technologies: C#, .NET")
                self.assertIs(found, tools_a, "resolve by ORIGINAL text, not collide")
                self.assertNotIn("matches multiple", err.getvalue())
        de._ORIG.clear()

    def test_genuine_duplicate_original_prefix_still_ambiguous(self):
        # Two paragraphs whose ORIGINAL texts both start with the prefix:
        # a real author-time ambiguity — still None + warning naming both.
        a = mkp(("Tools & Technologies: C#, .NET, Angular", True))
        b = mkp(("Tools & Technologies: C#, .NET, Angular", True))
        self._register(a, b)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            found = de.find_p([a, b], "Tools & Technologies: C#, .NET")
        self.assertIsNone(found)
        self.assertIn("matches multiple paragraphs", err.getvalue())
        self.assertIn("[0]", err.getvalue())
        self.assertIn("[1]", err.getvalue())

    def test_unregistered_paragraph_falls_back_to_current_text(self):
        # Paragraphs built in-memory (never registered) match via current
        # text — the pre-existing fallback used by the other tests.
        p = mkp(("Freshly written bullet", False))
        self.assertIs(de.find_p([p], "Freshly"), p)


class SaveReportTests(unittest.TestCase):
    """save() reports skipped edits and can fail under strict mode."""

    def _reset_stats(self):
        de._APPLIED = 0
        de._SKIPS.clear()
        de._ELEMENT_FORM_DROPS = 0

    def test_element_form_drop_reports_one_summary_line(self):
        # save() summarizes element-form drop calls in ONE line instead of
        # the old per-call note (22 bullet drops printed 22 near-identical
        # note lines, burying the stderr warnings that matter).
        self._reset_stats()
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _empty_docx(path)
            root, body, names, data, _ = de.load(path)
            for text in ("Bullet one", "Bullet two"):
                p = ET.SubElement(body, de.W + "p")
                t = ET.SubElement(p, de.W + "t"); t.text = text
            elements = [de.find_p(de.paras(body), t) for t in ("Bullet one", "Bullet two")]
            de.drop(body, elements)
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                de.save(path, root, names, data)
            self.assertIn(
                "note: 2 drop-family call(s) used the element form",
                err.getvalue(),
            )
            self.assertNotIn("derived its prefix", err.getvalue())
        finally:
            os.unlink(path)

    def test_reports_clean_run(self):
        self._reset_stats()
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _empty_docx(path)
            root, body, names, data, _ = de.load(path)
            p = ET.SubElement(body, de.W + "p")
            t = ET.SubElement(p, de.W + "t"); t.text = "x"
            de.set_text(p, "hello")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                de.save(path, root, names, data)
            self.assertIn("0 skipped", out.getvalue())
        finally:
            os.unlink(path)

    def test_strict_env_var_fails_on_skipped_edit(self):
        # save() takes no strict param anymore — DOCX_EDIT_STRICT=1 is the
        # single way to make a skipped edit fail the run (exit 2).
        self._reset_stats()
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _empty_docx(path)
            root, body, names, data, _ = de.load(path)
            de.remove(body, None)  # skipped edit -> recorded
            old = os.environ.get("DOCX_EDIT_STRICT")
            os.environ["DOCX_EDIT_STRICT"] = "1"
            try:
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    with self.assertRaises(SystemExit) as cm:
                        de.save(path, root, names, data)
                self.assertEqual(cm.exception.code, 2)
                self.assertIn("skipped", err.getvalue())
            finally:
                if old is None:
                    del os.environ["DOCX_EDIT_STRICT"]
                else:
                    os.environ["DOCX_EDIT_STRICT"] = old
        finally:
            os.unlink(path)


class SaveDriftTests(unittest.TestCase):
    """save() drift sidecar records an applied-edit-count baseline."""

    def _one_edit(self, path):
        root, body, names, data, _ = de.load(path)
        p = ET.SubElement(body, de.W + "p")
        t = ET.SubElement(p, de.W + "t"); t.text = "x"
        de.set_text(p, "hello")
        return root, body, names, data

    def _two_edits(self, path):
        root, body, names, data, _ = de.load(path)
        p1 = ET.SubElement(body, de.W + "p")
        t1 = ET.SubElement(p1, de.W + "t"); t1.text = "x"
        p2 = ET.SubElement(body, de.W + "p")
        t2 = ET.SubElement(p2, de.W + "t"); t2.text = "y"
        de.set_text(p1, "hello")
        de.set_text(p2, "world")
        return root, body, names, data

    def _run(self, path, builder, strict=False, key="tailor_x.py",
             expect_exit=False):
        de._APPLIED = 0
        root, body, names, data = builder(path)
        out = io.StringIO()
        err = io.StringIO()
        old = os.environ.get("DOCX_EDIT_STRICT")
        if strict:
            os.environ["DOCX_EDIT_STRICT"] = "1"
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                cm = None
                if strict and expect_exit:
                    with self.assertRaises(SystemExit) as cm:
                        de.save(path, root, names, data, drift_key=key)
                else:
                    de.save(path, root, names, data, drift_key=key)
        finally:
            if old is None:
                os.environ.pop("DOCX_EDIT_STRICT", None)
            else:
                os.environ["DOCX_EDIT_STRICT"] = old
        return out.getvalue(), err.getvalue(), cm

    def test_first_run_records_baseline_without_warning(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _empty_docx(path)
            out, err, _ = self._run(path, self._one_edit)
            self.assertNotIn("drift", err)
            self.assertTrue(os.path.exists(path + ".drift.json"))
        finally:
            os.unlink(path)
            if os.path.exists(path + ".drift.json"):
                os.unlink(path + ".drift.json")

    def test_unchanged_rerun_is_clean(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _empty_docx(path)
            self._run(path, self._one_edit)
            out, err, _ = self._run(path, self._one_edit)
            self.assertNotIn("drift", err)
        finally:
            os.unlink(path)
            if os.path.exists(path + ".drift.json"):
                os.unlink(path + ".drift.json")

    def test_drift_detected_when_applied_count_changes(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _empty_docx(path)
            self._run(path, self._one_edit)
            out, err, _ = self._run(path, self._two_edits)
            self.assertIn("DRIFT", err)
            self.assertIn("expected 1", err)
            self.assertIn("applied 2", err)
        finally:
            os.unlink(path)
            if os.path.exists(path + ".drift.json"):
                os.unlink(path + ".drift.json")

    def test_drift_rebaselines_so_next_run_is_clean(self):
        # A count change is a REVIEW signal, not a permanent gate: after the
        # warning fires once, the new count becomes the baseline. An agent
        # that intentionally adds an edit gets one warning, not an infinite
        # exit-2 trap that would block every render of a revised script.
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _empty_docx(path)
            self._run(path, self._one_edit)
            out, err, _ = self._run(path, self._two_edits)  # DRIFT warning
            self.assertIn("DRIFT", err)
            out, err, _ = self._run(path, self._two_edits)  # now clean
            self.assertNotIn("DRIFT", err)
        finally:
            os.unlink(path)
            if os.path.exists(path + ".drift.json"):
                os.unlink(path + ".drift.json")

    def test_drift_is_warning_not_gate_even_under_strict(self):
        # The blocking gate for "edit stopped matching" is the skipped-edit
        # check (separate). A pure count change (intentional add/remove)
        # must not trap the run under strict.
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            _empty_docx(path)
            self._run(path, self._one_edit)
            out, err, cm = self._run(path, self._two_edits, strict=True)
            self.assertIsNone(cm, "drift alone must not exit under strict")
            self.assertIn("DRIFT", err)
        finally:
            os.unlink(path)
            if os.path.exists(path + ".drift.json"):
                os.unlink(path + ".drift.json")


class AppendCLITests(unittest.TestCase):
    """docx_edit.py --append-after — the reusable replacement for the
    bespoke fold_master_confirmed.py script: clone a NEW bullet after a
    reference paragraph located by prefix, in place. A one-shot CLI call
    must not silently no-op: a missing/ambiguous ref exits 2."""

    def _docx_with(self, *texts):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        doc = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="' + de.XMLNS + '"><w:body>'
        )
        for t in texts:
            doc += (
                f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
            )
        doc += '</w:body></w:document>'
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", doc)
            z.writestr("[Content_Types].xml", "<Types/>")
        return path

    def _texts(self, path):
        root, body, names, data, _ = de.load(path)
        return [de.text_of(p) for p in de.paras(body)]

    def test_appends_after_ref_by_prefix(self):
        path = self._docx_with("Ref paragraph", "Other paragraph")
        try:
            de._APPLIED = 0
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = de.cli(["docx_edit.py", path, "--append-after",
                             "Ref paragraph", "--with", "New bullet"])
            self.assertEqual(rc, 0)
            self.assertEqual(self._texts(path),
                             ["Ref paragraph", "New bullet", "Other paragraph"])
        finally:
            os.unlink(path)

    def test_missing_ref_exits_2(self):
        path = self._docx_with("Ref paragraph")
        err = io.StringIO()
        try:
            de._APPLIED = 0
            with contextlib.redirect_stderr(err):
                rc = de.cli(["docx_edit.py", path, "--append-after", "No such para", "--with",
                             "New bullet"])
            self.assertEqual(rc, 2)
            self.assertIn("not found", err.getvalue())
            self.assertEqual(self._texts(path), ["Ref paragraph"],
                             "missing ref must not mutate the doc")
        finally:
            os.unlink(path)

    def test_curly_apostrophe_ref_matches_ascii_prefix(self):
        path = self._docx_with("The company\u2019s goal", "Other")
        try:
            de._APPLIED = 0
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = de.cli(["docx_edit.py", path, "--append-after",
                             "The company's goal", "--with", "New bullet"])
            self.assertEqual(rc, 0)
            self.assertEqual(self._texts(path),
                             ["The company\u2019s goal", "New bullet", "Other"])
        finally:
            os.unlink(path)

    def test_invalid_usage_exits_2(self):
        path = self._docx_with("Ref")
        try:
            rc = de.cli(["docx_edit.py", path, "--append-after", "Ref"])  # missing --with
            self.assertEqual(rc, 2)
            self.assertEqual(self._texts(path), ["Ref"])
        finally:
            os.unlink(path)


class MasterChangeGateTests(unittest.TestCase):
    """save() MASTER CHANGED gate — deterministic enforcement of the
    fold-then-retailor ordering. When a tailored copy's script runs against
    a master that changed since its last run, skipped edits exit 2 EVEN
    WITHOUT DOCX_EDIT_STRICT: a mid-session master fold can no longer
    silently strand drifted prefixes (the session failure where MASTER
    CHANGED printed as a warning and relied on the agent re-running strict
    manually)."""

    def setUp(self):
        de._APPLIED = 0
        de._SKIPS.clear()
        fd, self.master = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        fd, self.dst = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        _empty_docx(self.master)
        _empty_docx(self.dst)

    def tearDown(self):
        for path in (self.master, self.dst):
            for suffix in ("", ".drift.json"):
                p = path + suffix
                if os.path.exists(p):
                    os.unlink(p)
        de._APPLIED = 0
        de._SKIPS.clear()

    def _rewrite_master(self, text):
        # Change the master's bytes so its sha256 differs from run 1's.
        with open(self.master, "wb") as f:
            f.write(b"changed-master-bytes-" + text.encode())

    def _run(self, skip=False, strict=False):
        de._APPLIED = 0
        root, body, names, data, _ = de.load(self.dst)
        p = ET.SubElement(body, de.W + "p")
        t = ET.SubElement(p, de.W + "t")
        t.text = "x"
        if skip:
            de.set_text(None, "a skipped edit")
        else:
            de.set_text(p, "hello")
        out, err = io.StringIO(), io.StringIO()
        old = os.environ.get("DOCX_EDIT_STRICT")
        if strict:
            os.environ["DOCX_EDIT_STRICT"] = "1"
        cm = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    de.save(self.dst, root, names, data,
                            drift_key="tailor_gate.py", src=self.master)
                except SystemExit as e:
                    cm = e
        finally:
            if old is None:
                os.environ.pop("DOCX_EDIT_STRICT", None)
            else:
                os.environ["DOCX_EDIT_STRICT"] = old
        return out.getvalue(), err.getvalue(), cm

    def test_first_run_establishes_baseline_no_gate(self):
        # No previous sha recorded: skipped edits alone do not exit without
        # strict (unchanged legacy behavior for a first run).
        out, err, cm = self._run(skip=True)
        self.assertIsNone(cm)
        self.assertNotIn("MASTER CHANGED", err)

    def test_unchanged_master_rerun_with_skips_gated_only_by_strict(self):
        self._run()
        out, err, cm = self._run(skip=True)
        self.assertIsNone(cm, "master unchanged: gate must not fire")
        self.assertNotIn("MASTER CHANGED", err)

    def test_changed_master_with_skips_exits_2_without_strict(self):
        self._run()
        self._rewrite_master("v2")
        out, err, cm = self._run(skip=True)
        self.assertIn("MASTER CHANGED", err)
        self.assertIsNotNone(cm, "changed master + skipped edit must gate")
        self.assertEqual(cm.code, 2)

    def test_changed_master_clean_rerun_passes(self):
        # The intended workflow: fold changed the master, the tailor script
        # is re-run, every prefix still resolves -> no gate, warning only.
        self._run()
        self._rewrite_master("v2")
        out, err, cm = self._run()
        self.assertIn("MASTER CHANGED", err)
        self.assertIsNone(cm, "changed master + zero skips must pass")

    def test_gate_applies_under_strict_too(self):
        self._run()
        self._rewrite_master("v2")
        out, err, cm = self._run(skip=True, strict=True)
        self.assertIsNotNone(cm)
        self.assertEqual(cm.code, 2)


class SetTextCLITests(unittest.TestCase):
    """docx_edit.py --set-text — one-shot bullet rewrite from the CLI, the
    replacement for bespoke fold scripts whose only edit is set_text."""

    def _docx_with(self, *texts):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        doc = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="' + de.XMLNS + '"><w:body>'
        )
        for t in texts:
            doc += (
                f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
            )
        doc += '</w:body></w:document>'
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", doc)
            z.writestr("[Content_Types].xml", "<Types/>")
        return path

    def _texts(self, path):
        root, body, names, data, _ = de.load(path)
        return [de.text_of(p) for p in de.paras(body)]

    def test_rewrites_paragraph_by_prefix(self):
        path = self._docx_with("Implemented Jest and Playwright for tests.",
                               "Unrelated bullet")
        try:
            de._APPLIED = 0
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = de.cli(["docx_edit.py", path, "--set-text",
                             "Implemented Jest and Playwright",
                             "--with", "Landed Playwright company-wide"])
            self.assertEqual(rc, 0)
            self.assertEqual(self._texts(path),
                             ["Landed Playwright company-wide",
                              "Unrelated bullet"])
        finally:
            os.unlink(path)
            if os.path.exists(path + ".drift.json"):
                os.unlink(path + ".drift.json")

    def test_missing_prefix_exits_2_without_mutation(self):
        path = self._docx_with("Some bullet")
        try:
            de._APPLIED = 0
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = de.cli(["docx_edit.py", path, "--set-text",
                             "No such prefix", "--with", "New text"])
            self.assertEqual(rc, 2)
            self.assertEqual(self._texts(path), ["Some bullet"])
        finally:
            os.unlink(path)

    def test_missing_with_arg_exits_2(self):
        path = self._docx_with("Some bullet")
        try:
            rc = de.cli(["docx_edit.py", path, "--set-text", "Some bullet"])
            self.assertEqual(rc, 2)
        finally:
            os.unlink(path)


class StyleFilterCLITests(unittest.TestCase):
    """docx_edit.py --style <name> — discover block-boundary styles (the
    CompanyBlock/SectionHeading map) without paging the full paragraph map."""

    def _docx_with_styles(self):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        ps = (
            ("Career Experience", "SectionHeading"),
            ("Acme Corp, Springfield03/2022", "CompanyBlock"),
            ("Staff Engineer", "JobTitleBlock"),
            ("Bullet one", "BodyText"),
            ("Education", "SectionHeading"),
        )
        doc = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="' + de.XMLNS + '"><w:body>'
        )
        for text, style in ps:
            doc += (
                f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
                f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
            )
        doc += '</w:body></w:document>'
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", doc)
            z.writestr("[Content_Types].xml", "<Types/>")
        return path

    def test_filters_paragraphs_by_style(self):
        path = self._docx_with_styles()
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = de.cli(["docx_edit.py", path, "--style", "SectionHeading"])
            self.assertEqual(rc, 0)
            text = out.getvalue()
            self.assertIn("Career Experience", text)
            self.assertIn("Education", text)
            self.assertNotIn("Staff Engineer", text)
            self.assertNotIn("Bullet one", text)
            # original index numbers preserved (0 and 4), not renumbered
            self.assertRegex(text, r"\b0\b")
            self.assertRegex(text, r"\b4\b")
        finally:
            os.unlink(path)

    def test_unknown_style_prints_nothing_exits_0(self):
        path = self._docx_with_styles()
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = de.cli(["docx_edit.py", path, "--style", "Nope"])
            self.assertEqual(rc, 0)
            self.assertEqual(out.getvalue().strip(), "")
        finally:
            os.unlink(path)


class MergeIntoTests(unittest.TestCase):
    """merge_into rewrites the target and removes the source in one op,
    so a merge can't leave the source's old text as near-dup residue."""

    def _mk_body(self):
        body = ET.Element(W + "body")
        t = ET.SubElement(body, W + "p")
        r = ET.SubElement(t, W + "r")
        x = ET.SubElement(r, W + "t"); x.text = "old target"
        s = ET.SubElement(body, W + "p")
        r = ET.SubElement(s, W + "r")
        x = ET.SubElement(r, W + "t"); x.text = "old source"
        de._ORIG[id(t)] = (t, "old target")
        de._ORIG[id(s)] = (s, "old source")
        return body, t, s

    def test_rewrites_target_and_removes_source(self):
        body, t, s = self._mk_body()
        de._APPLIED = 0
        de.merge_into(body, t, s, "combined text")
        self.assertEqual(de.text_of(t), "combined text")
        self.assertNotIn(s, list(body))
        self.assertEqual(de._APPLIED, 2, "counts as a rewrite + a removal")

    def test_target_none_warns_and_no_ops(self):
        body, t, s = self._mk_body()
        err = io.StringIO()
        de._APPLIED = 0
        with contextlib.redirect_stderr(err):
            de.merge_into(body, None, s, "x")
        self.assertIn("target paragraph not found", err.getvalue())
        self.assertEqual(de._APPLIED, 0)
        self.assertIn(t, list(body))
        self.assertIn(s, list(body))

    def test_source_none_still_rewrites_target(self):
        body, t, s = self._mk_body()
        err = io.StringIO()
        de._APPLIED = 0
        with contextlib.redirect_stderr(err):
            de.merge_into(body, t, None, "merged")
        self.assertEqual(de.text_of(t), "merged")
        self.assertEqual(de._APPLIED, 1, "rewrite lands, no removal")
        self.assertIn(s, list(body))

    def test_target_is_source_skipped(self):
        body = ET.Element(W + "body")
        p = ET.SubElement(body, W + "p")
        r = ET.SubElement(p, W + "r")
        x = ET.SubElement(r, W + "t"); x.text = "solo"
        err = io.StringIO()
        de._APPLIED = 0
        with contextlib.redirect_stderr(err):
            de.merge_into(body, p, p, "y")
        self.assertIn("same paragraph", err.getvalue())
        self.assertEqual(de._APPLIED, 0)
        self.assertIn(p, list(body))


class PrefixesHeadlineTests(unittest.TestCase):
    """--prefixes marks the positioning headline so the script author does
    not have to re-derive the name-vs-headline distinction from the skill
    text (a session anchored set_text on the wrong Title — the name line
    and the headline share the Title style — and spent two calls reading
    find_p's source to recover)."""

    def _lines(self, styled):
        # styled: (text, style) pairs; None style = no pPr
        body = ET.Element(W + "body")
        for text, style in styled:
            p = ET.SubElement(body, W + "p")
            if style is not None:
                pPr = ET.SubElement(p, W + "pPr")
                st = ET.SubElement(pPr, W + "pStyle")
                st.set(W + "val", style)
            r = ET.SubElement(p, W + "r")
            t = ET.SubElement(r, W + "t")
            t.text = text
        return de.prefixes(body)

    def test_marks_the_last_title_of_the_leading_run(self):
        lines = self._lines([
            ("Jane Doe", de.TITLE_STYLE),
            ("Staff Engineer", de.TITLE_STYLE),
            ("Results-driven software engineer with 10 years", None),
        ])
        self.assertIn("HEADLINE (positioning title, not the name): "
                      "Staff Engineer", lines[1])
        # The name line is Title-styled too — it must NOT be marked.
        self.assertNotIn("HEADLINE", lines[0])

    def test_later_title_styled_paragraphs_are_not_marked(self):
        lines = self._lines([
            ("Jane Doe", de.TITLE_STYLE),
            ("Staff Engineer", de.TITLE_STYLE),
            ("Acme Corp", de.ROLE_STYLE),
            ("Staff Engineer - Quality Automation", None),
        ])
        self.assertNotIn("HEADLINE", lines[3])

    def test_no_title_run_no_mark(self):
        lines = self._lines([
            ("Jane Doe", None),
            ("Staff Engineer", None),
        ])
        self.assertFalse(any("HEADLINE" in line for line in lines))


class CommaListRangeTests(unittest.TestCase):
    """cli() range argument accepts comma-separated indexes (61,63,65,70-72)
    — reading scattered bullets used to cost one subprocess per index."""

    def _docx_with(self, *texts):
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        doc = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="' + de.XMLNS + '"><w:body>'
        )
        for t in texts:
            doc += (
                f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
            )
        doc += '</w:body></w:document>'
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", doc)
            z.writestr("[Content_Types].xml", "<Types/>")
        return path

    def _map(self, path, rng):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = de.cli(["docx_edit.py", path, rng])
        self.assertEqual(rc, 0)
        return out.getvalue()

    def test_comma_list_prints_only_the_named_paragraphs(self):
        path = self._docx_with("zero", "one", "two", "three", "four")
        try:
            lines = self._map(path, "1,3").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("one", lines[0])
            self.assertIn("three", lines[1])
        finally:
            os.unlink(path)

    def test_comma_list_mixes_singles_and_ranges(self):
        path = self._docx_with("zero", "one", "two", "three", "four")
        try:
            lines = self._map(path, "0,2-3").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("zero", lines[0])
            self.assertIn("two", lines[1])
            self.assertIn("three", lines[2])
        finally:
            os.unlink(path)

    def test_comma_list_is_clamped_to_the_document(self):
        path = self._docx_with("zero", "one")
        try:
            lines = self._map(path, "1,9").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("one", lines[0])
        finally:
            os.unlink(path)


class DeliverableGateTests(unittest.TestCase):
    """save()'s DELIVERABLE GATE — a state validate_resume would refuse to
    render is never WRITTEN at all when a tailor script saves with src=SRC.
    The render gate alone is bypassable: by render time the .docx exists on
    disk and the user can convert it themselves. With this gate there is no
    .docx on disk in a gated state — nothing to hand-convert."""

    def setUp(self):
        import validate_resume as vr  # noqa: F401
        de._APPLIED = 0
        de._SKIPS.clear()
        workdir = tempfile.mkdtemp()
        self.workdir = workdir
        self.master = os.path.join(workdir, "Test Master Resume.docx")
        self.dst = os.path.join(workdir, "Test tailored.docx")
        _empty_docx(self.master)
        _empty_docx(self.dst)
        self._old_env = os.environ.pop("RESUME_VALIDATE_ARGS", None)

    def tearDown(self):
        for path in (self.master, self.dst):
            for suffix in ("", ".drift.json"):
                p = path + suffix
                if os.path.exists(p):
                    os.unlink(p)
        de._APPLIED = 0
        de._SKIPS.clear()
        if self._old_env is not None:
            os.environ["RESUME_VALIDATE_ARGS"] = self._old_env
        else:
            os.environ.pop("RESUME_VALIDATE_ARGS", None)

    @staticmethod
    def _career_paragraphs(bullet_count, company="Acme, MA (Remote)06/2021 – 05/2026"):
        import measure_resume as mr
        import validate_resume as vr
        ps = [
            mkstyled(mr.SECTION_CAREER, "SectionHeading"),
            mkstyled(company, mr.COMPANY_STYLE),
            mkstyled("Staff Engineer", vr.TITLE_STYLE),
        ]
        ps += [mkstyled(f"Quantified win {i} percent.", "BodyText", numId=4)
               for i in range(bullet_count)]
        ps.append(mkstyled("Tools & Technologies: Go, Python", "BodyText"))
        return ps

    def _populate(self, path, bullet_count):
        root, body, names, data, _ = de.load(path)
        for p in self._career_paragraphs(bullet_count):
            body.append(p)
        return root, body, names, data

    def _save(self, path, root, names, data, src):
        out, err = io.StringIO(), io.StringIO()
        cm = None
        try:
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err):
                de.save(path, root, names, data, src=src)
        except SystemExit as e:
            cm = e
        return cm, out.getvalue(), err.getvalue()

    def test_over_cap_save_refused_and_nothing_written(self):
        # Ungated first (no src): the same state writes fine.
        root, body, names, data = self._populate(self.dst, 9)
        with contextlib.redirect_stdout(io.StringIO()):
            de.save(self.dst, root, names, data)
        os.unlink(self.dst)
        _empty_docx(self.dst)
        # Gated (src passed): refused, nothing on disk.
        de._APPLIED = 0
        root, body, names, data = self._populate(self.dst, 9)
        cm, _out, err = self._save(self.dst, root, names, data, src=self.master)
        self.assertIsNotNone(cm, "over-cap save must exit 2")
        self.assertIn("DELIVERABLE GATE", err)
        self.assertIn("keeps 9 bullets", err)
        # The gate refuses BEFORE opening the zip for write, and removes
        # the stale (ungated) copy a tailor run's shutil.copy left at the
        # path — no deliverable, docx or pdf, can be produced by any path.
        self.assertFalse(os.path.exists(self.dst),
                         "gated state and its stale copy must be gone")

    def test_clean_save_with_src_passes(self):
        root, body, names, data = self._populate(self.dst, 8)
        cm, _out, err = self._save(self.dst, root, names, data, src=self.master)
        self.assertIsNone(cm, err)
        self.assertTrue(os.path.exists(self.dst))

    def test_no_src_save_ungated(self):
        # Tool-internal saves (measure --simulate, squeeze, tests) pass no
        # src and are never gated.
        root, body, names, data = self._populate(self.dst, 30)
        cm, _out, err = self._save(self.dst, root, names, data, src=None)
        self.assertIsNone(cm, err)
        self.assertTrue(os.path.exists(self.dst))

    def test_master_path_save_exempt(self):
        # Folding into the master itself is never gated — the master
        # intentionally keeps everything.
        root, body, names, data = self._populate(self.master, 12)
        cm, _out, err = self._save(self.master, root, names, data,
                                   src=self.master)
        self.assertIsNone(cm, err)
        self.assertTrue(os.path.exists(self.master))

    def test_seniority_block_without_token_then_passes_with_token(self):
        # A tailored copy whose visible span shrank >= SENIORITY_GATE_YEARS
        # vs the master must not be writable without the user's approval;
        # with the token in RESUME_VALIDATE_ARGS it writes.
        root, body, names, data = self._populate(self.master, 3)
        # Rewrite the master's role dates to 2010-2019 (span ~9.7y).
        for p in body.iter(de.W + "p"):
            if "Acme, MA" in (p.find(f"{de.W}r/{de.W}t").text or ""):
                p.find(f"{de.W}r/{de.W}t").text = \
                    "Old Co, City01/2010 – 12/2019"
        with contextlib.redirect_stdout(io.StringIO()):
            de.save(self.master, root, names, data)

        root, body, names, data = self._populate(self.dst, 3)
        for p in body.iter(de.W + "p"):
            tt = p.find(f"{de.W}r/{de.W}t")
            if tt is not None and "Acme, MA" in (tt.text or ""):
                tt.text = "New Co, City01/2024 – 12/2026"
        for p in body.iter(de.W + "p"):
            tt = p.find(f"{de.W}r/{de.W}t")
            if tt is not None and tt.text and "Quantified win" in tt.text:
                tt.text = tt.text.replace("Quantified win", "Newer win")
        os.unlink(self.dst)  # fixture empty docx must not count as output
        de._APPLIED = 0
        cm, _out, err = self._save(self.dst, root, names, data,
                                   src=self.master)
        self.assertIsNotNone(cm, "unapproved role elimination must exit 2")
        self.assertIn("whole-role elimination", err)

        self.assertFalse(os.path.exists(self.dst),
                         "gated seniority state must NOT be written to disk")

        os.environ["RESUME_VALIDATE_ARGS"] = "--seniority-approved"
        _empty_docx(self.dst)
        root, body, names, data = self._populate(self.dst, 3)
        for p in body.iter(de.W + "p"):
            tt = p.find(f"{de.W}r/{de.W}t")
            if tt is not None and tt.text and "Acme, MA" in tt.text:
                tt.text = "New Co, City01/2024 – 12/2026"
            elif tt is not None and tt.text and "Quantified win" in tt.text:
                tt.text = tt.text.replace("Quantified win", "Newer win")
        for p in body.iter(de.W + "p"):
            tt = p.find(f"{de.W}r/{de.W}t")
            if tt is not None and "Acme, MA" in (tt.text or ""):
                tt.text = "New Co, City01/2024 – 12/2026"
        de._APPLIED = 0
        cm, _out, err = self._save(self.dst, root, names, data,
                                   src=self.master)
        self.assertIsNone(cm, err)
        self.assertTrue(os.path.exists(self.dst))


if __name__ == "__main__":
    unittest.main()
