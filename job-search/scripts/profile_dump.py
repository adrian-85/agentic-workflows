"""Resume profile dump: master .docx -> plain text for judgment prompts.

Stdlib-only (zipfile + ElementTree): extracts word/document.xml
paragraph text in order, whitespace-normalized. The real profile path
lives only in gitignored config.toml (spec: privacy model).
"""

import xml.etree.ElementTree as ET
import zipfile

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def dump_text(docx_path: str) -> str:
    """Ordered, whitespace-normalized paragraph text from a .docx."""
    with zipfile.ZipFile(docx_path) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        text = "".join(node.text or ""
                       for node in paragraph.iter(f"{WORD_NS}t"))
        normalized = " ".join(text.split())
        if normalized:
            paragraphs.append(normalized)
    return "\n".join(paragraphs)
