"""Shared fixtures for the resume-tailoring script tests.

Owns the sys.path bootstrap so sibling-import tests and docx scaffolding
live in one place (was copy-pasted ~40x across the giant test files).
"""

import contextlib
import io
import os
import sys
import tempfile
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import docx_edit as de  # noqa: E402

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


def _write_docx(path, paragraphs):
    """Zip a minimal .docx (document.xml + [Content_Types]) to ``path`` and
    return (root, body, names, data) via de.load() for edits."""
    fd, real = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    os.replace(real, path)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="' + de.XMLNS
                   + '"><w:body/></w:document>')
        z.writestr("[Content_Types].xml", "<Types/>")
    root, body, names, data, _ = de.load(path)
    for p in paragraphs:
        body.append(p)
    with contextlib.redirect_stdout(io.StringIO()):
        de.save(path, root, names, data)
    return root, body, names, data