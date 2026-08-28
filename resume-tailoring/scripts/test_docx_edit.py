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


class ReplaceTextTests(unittest.TestCase):
    """replace_text: per-run substring replacement preserving formatting."""

    def test_per_run_replaces_in_single_run(self):
        p = mkp(("hello world foo", False), ("bar", True))
        de.replace_text(p, "world", "WORLD")
        self.assertEqual(de.text_of(p), "hello WORLD foobar")

    def test_per_run_preserves_other_runs_formatting(self):
        p = mkp(("hello world foo", False), ("bar", True))
        de.replace_text(p, "world", "WORLD")
        self.assertEqual(fmt(p), [("hello WORLD foo", False), ("bar", True)])

    def test_multiple_occurrences_within_single_run(self):
        p = mkp(("foo and foo", False))
        de.replace_text(p, "foo", "FOO")
        self.assertEqual(de.text_of(p), "FOO and FOO")

    def test_occurrences_across_runs_replaced_per_run(self):
        # "foo" sits fully within each run that contains it; the run that
        # only holds "fo" (no trailing "o") is untouched.
        p = mkp(("foo and foo", False), (" plus fo", True), ("o again", False))
        de.replace_text(p, "foo", "FOO")
        self.assertEqual(de.text_of(p), "FOO and FOO plus foo again")

    def test_spanning_occurrence_left_in_place(self):
        # "world" is split as "wo" + "rld" across two runs. Per-run-only
        # replacement does not touch it (documented YAGNI behavior).
        p = mkp(("hello wo", False), ("rld end", True))
        de.replace_text(p, "world", "WORLD")
        self.assertEqual(de.text_of(p), "hello world end")

    def test_old_in_new_is_safe(self):
        # str.replace per run handles "AI" -> "AIx" without looping.
        p = mkp(("AI AI", False))
        de.replace_text(p, "AI", "AIx")
        self.assertEqual(de.text_of(p), "AIx AIx")

    def test_not_found_warns_and_no_crash(self):
        p = mkp(("nothing here", False))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.replace_text(p, "MISSING", "X")
        self.assertIn("target paragraph not found", err.getvalue())
        self.assertEqual(de.text_of(p), "nothing here")

    def test_none_paragraph_warns_and_no_crash(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            de.replace_text(None, "x", "y")
        self.assertIn("target paragraph not found", err.getvalue())


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

    @staticmethod
    def _empty_docx(path):
        doc = (
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="' + de.XMLNS + '"><w:body/></w:document>'
        )
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", doc)
            z.writestr("[Content_Types].xml", "<Types/>")

    def _reset_stats(self):
        de._APPLIED = 0
        de._SKIPS.clear()

    def test_reports_clean_run(self):
        self._reset_stats()
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            self._empty_docx(path)
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
            self._empty_docx(path)
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


if __name__ == "__main__":
    unittest.main()
