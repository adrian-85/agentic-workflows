"""profile_dump tests: synthetic docx -> text (no personal files)."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from profile_dump import dump_text

_DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/
2006/main">
  <w:body>
    <w:p><w:r><w:t>Staff   Engineer in   Test</w:t></w:r></w:p>
    <w:p><w:r><w:t>Tools: </w:t></w:r><w:r><w:t>Python, CI/CD</w:t></w:r></w:p>
    <w:p><w:r><w:t></w:t></w:r></w:p>
    <w:p><w:r><w:t>Release quality owner</w:t></w:r></w:p>
  </w:body>
</w:document>
""".replace("wordprocessingml/\n2006/main", "wordprocessingml/2006/main")


class DumpTextTest(unittest.TestCase):
    """dump_text extracts ordered, whitespace-normalized paragraph text."""

    def test_dump_text_extracts_paragraphs(self):
        """Paragraph text extracts in document order, runs concatenated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docx = Path(tmpdir) / "synthetic-resume.docx"
            with zipfile.ZipFile(docx, "w") as archive:
                archive.writestr("word/document.xml", _DOCUMENT_XML)
            text = dump_text(str(docx))
        lines = text.splitlines()
        self.assertEqual(lines[0], "Staff Engineer in Test")
        self.assertEqual(lines[1], "Tools: Python, CI/CD")
        self.assertEqual(lines[2], "Release quality owner")

    def test_dump_text_normalizes_whitespace(self):
        """Runs join without spacers; empty paragraphs vanish."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docx = Path(tmpdir) / "synthetic-resume.docx"
            with zipfile.ZipFile(docx, "w") as archive:
                archive.writestr("word/document.xml", _DOCUMENT_XML)
            text = dump_text(str(docx))
        self.assertNotIn("  ", text)
        self.assertNotIn("\n\n", text)


if __name__ == "__main__":
    unittest.main()
