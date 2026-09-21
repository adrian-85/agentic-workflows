"""Tests for diff_resume's --cutset (the Theme Review A master-vs-build diff)."""

# Test method names are self-documenting.
# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring
import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import test_helpers  # noqa: E402
import diff_resume  # noqa: E402


def _base_paras():
    """Header, Summary, and role header shared by both cut-set fixtures."""
    return [test_helpers._para("Adrian Alan", style="Title"),
            test_helpers._para("Staff Engineer", style="Title"),
            test_helpers._para("Summary of a long career.", style="Normal"),
            test_helpers._para("GEICO, Chevy Chase, MD", style="CompanyBlock"),
            test_helpers._para("Staff Engineer", style="JobTitleBlock")]


def _master_fixture(path):
    """Summary, one role with two bullets, one section heading below."""
    paras = _base_paras() + [
        test_helpers._para("Owned testing, CI, and release for payments.",
                            style="ListParagraph", numId=3),
        test_helpers._para("Introduced mutation testing into CI.", style="ListParagraph", numId=3),
        test_helpers._para("Education", style="SectionHeading"),
        test_helpers._para("BA, Something University", style="Normal"),
    ]
    test_helpers._write_docx(path, paras)


def _build_fixture(path):
    """Same minus one bullet and the Education section; one rewritten bullet."""
    paras = _base_paras() + [
        # rewritten: appears as BOTH cut (old text) and added (new text)
        test_helpers._para("Owned testing, CI, and release for the payments platform.",
                            style="ListParagraph", numId=3),
        test_helpers._para("Education", style="SectionHeading"),
    ]
    test_helpers._write_docx(path, paras)


class CutsetTests(unittest.TestCase):
    """--cutset prints grouped, normalized cut/added paragraph lists."""

    def test_cutset_reports_cut_added_and_grouping(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = os.path.join(tmp, "master.docx")
            build = os.path.join(tmp, "build.docx")
            _master_fixture(master)
            _build_fixture(build)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                diff_resume.cutset(master, build)
            text = out.getvalue()
            self.assertIn("3 cut", text)   # old rewritten bullet, mutation bullet, Education BA
            self.assertIn("1 added", text)  # rewritten host text
            self.assertIn("[GEICO, Chevy Chase, MD] Introduced mutation testing", text)
            self.assertIn("[Education] BA, Something University", text)
            self.assertIn("payments platform.", text)

    def test_cutset_identical_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.docx")
            b = os.path.join(tmp, "b.docx")
            _master_fixture(a)
            _master_fixture(b)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                diff_resume.cutset(a, b)
            self.assertIn("identical", out.getvalue())

    def test_cutset_ignores_blank_spacers(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.docx")
            b = os.path.join(tmp, "b.docx")
            paras = [
                test_helpers._para("GEICO, Chevy Chase, MD", style="CompanyBlock"),
                test_helpers._para("Owned testing.", style="ListParagraph", numId=3),
                test_helpers._para("", style="Normal"),
            ]
            test_helpers._write_docx(a, paras)
            paras.append(test_helpers._para("", style="Normal"))
            test_helpers._write_docx(b, paras)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                diff_resume.cutset(a, b)
            self.assertIn("identical", out.getvalue())

    def test_cli_cutset_flag_dispatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = os.path.join(tmp, "master.docx")
            build = os.path.join(tmp, "build.docx")
            _master_fixture(master)
            _build_fixture(build)
            argv = sys.argv
            try:
                sys.argv = ["diff_resume.py", "--cutset", master, build]
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    diff_resume.main()
                self.assertIn("CUT", out.getvalue())
            finally:
                sys.argv = argv


if __name__ == "__main__":
    unittest.main()
