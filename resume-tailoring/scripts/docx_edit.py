"""Reusable .docx in-place editor for resume tailoring.

Design constraints captured here:
- Edit the Word XML in place so ALL existing styling is preserved (fonts, sizes,
  paragraph styles, numbering/list definitions, hyperlinks, headers/footers).
  Rebuilding a docx from scratch loses this; python-docx alone also drops a lot.
- Operate on the OOXML paragraph list; locate target paragraphs by their text.
- Provide primitives: set_text (preserve first run's rPr), clone_after
  (preserve pPr incl numbering so cloned bullets keep their bullet style),
  remove, find_p, text_of.

Usage as a library::

    from docx_edit import (
        load, save, paras, text_of, find_p, set_text, set_labeled,
        replace_text, clone_after, remove, remove_empty,
    )

    root, body, names, data, W = load("in.docx")
    ps = paras(body)
    # All mutation helpers (set_text, set_labeled, replace_text, clone_after,
    # remove) are defensive: if find_p returns None (the master changed and the
    # prefix no longer exists), they skip the edit with a stderr warning
    # instead of crashing — so the script still runs and renders. find_p
    # resolves prefixes against each paragraph's ORIGINAL text (captured at
    # load time), so a script's own earlier edits cannot rewrite one
    # paragraph's text to start with another target's prefix and collide
    # mid-run (e.g. trimming two roles' "Tools & Technologies" lines).
    # save() prints an applied-vs-skipped summary; set DOCX_EDIT_STRICT=1
    # to exit non-zero when any edit was skipped instead of just reporting it.
    intro = find_p(ps, "<unique text prefix of the intro paragraph>")
    set_text(intro, "New intro text...")
    # Proficiency lines keep a bold-label / non-bold-value split:
    set_labeled(find_p(ps, "Programming Languages:"),
               "Programming Languages: ", "Java, Python, Go")
    # Surgical substring edits (grammar, casing, a word swap) preserve run
    # formatting; use instead of set_text when you don't want to rewrite the
    # whole paragraph or collapse a multi-run proficiency line:
    replace_text(find_p(ps, "<prefix of a kept bullet>"), "Github", "GitHub")
    # clone_after adds a NEW bullet to the MASTER (real experience belongs in
    # the master, not in per-target scripts); preserve bullet styling:
    # clone_after(body, ref_bullet, "A new bullet in the master.")
    remove_empty(body, startswith="<text prefix at/after which to drop spacers>")
    save("out.docx", root, names, data)

CLI (inspect structure before editing)::

    python3 scripts/docx_edit.py path/to/resume.docx
        # prints: index | style | numId | text[:90]  for every paragraph
    python3 scripts/docx_edit.py path/to/resume.docx 26-38 --full
        # prints paragraphs 26-38 with FULL text (no truncation)
"""

import copy
import os
import sys
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XMLNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SPACE = "{http://www.w3.org/XML/1998/namespace}space"


# Original-text snapshot for order-independent prefix resolution.
# id(p) -> (paragraph, text as of load()/clone time). load() clears it
# first, so it never spans documents and paragraphs stay alive via `body`
# for the run — stale entries cannot clash.
_ORIG = {}

# Applied/skipped edit accounting for save()'s end-of-run report.
_APPLIED = 0
_SKIPS = []  # prefix/label of each skipped edit (recorded by mutators only)


def _orig_text(p):
    """The paragraph's text when load() ran (its ORIGINAL master text).

    ``None`` for paragraphs created after load (unless registered by
    ``clone_after``)."""
    entry = _ORIG.get(id(p))
    return entry[1] if entry else None


def _warn_missing(prefix_or_label, record=True):
    """Warn that a target paragraph was not found; mutation helpers skip
    the edit with this warning instead of raising, so a script still runs
    and renders when the master changed and a prefix no longer matches.

    Records the skipped edit (reported by save(); ``DOCX_EDIT_STRICT=1``
    fails the run) unless ``record=False`` — find_p is a read-only helper
    and passes False so the receiving mutation helper records each skipped
    edit exactly once.
    """
    if record:
        _SKIPS.append(prefix_or_label)
    print(
        f"warning: target paragraph not found (prefix/label: "
        f"{prefix_or_label!r}); master may have changed — skipping edit",
        file=sys.stderr,
    )


def _warn_ambiguous(prefix, samples):
    """Warn that ``prefix`` matches more than one paragraph, naming the
    candidates so the author can lengthen the prefix. Callers skip the edit
    (the mutation helper receiving ``None`` records the skip) rather than
    mutating the wrong paragraph.
    """
    lines = "\n".join(f"    [{i}] {s!r}" for i, s in samples)
    print(
        f"warning: find_p({prefix!r}) matches multiple paragraphs "
        f"({len(samples)}); prefix not unique — returning None (edit skipped):\n"
        f"{lines}\n"
        f"Use a longer prefix (see `docx_edit.py <docx> --prefixes`) or "
        f"capture targets before any rewrite.",
        file=sys.stderr,
    )


def load(path):
    """Open a .docx and return (root, body, names, data, W).

    Mutate `root`/`body` in place, then pass (root, names, data) to save().
    """
    ET.register_namespace("w", XMLNS)
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        data = {n: z.read(n) for n in names}
    root = ET.fromstring(data["word/document.xml"])
    body = root.find(W + "body")
    # Snapshot each paragraph's ORIGINAL text so find_p can resolve prefixes
    # order-independently: a script's own later edits can't make one
    # paragraph's current text start with another target's prefix and collide.
    _ORIG.clear()
    for p in paras(body):
        _ORIG[id(p)] = (p, text_of(p))
    return root, body, names, data, W


def save(path, root, names, data):
    """Serialize mutated root back into the .docx zip at `path`.

    After writing, prints an applied-vs-skipped summary so a silently
    skipped edit (a find_p prefix that drifted or is ambiguous) cannot go
    unnoticed. With ``DOCX_EDIT_STRICT=1``, exits with status 2 if any edit
    was skipped instead of merely reporting it.
    """
    global _APPLIED
    data["word/document.xml"] = ET.tostring(
        root, xml_declaration=True, encoding="UTF-8"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, data[n])
    applied = _APPLIED
    skipped = list(_SKIPS)
    _APPLIED = 0
    _SKIPS.clear()
    if skipped:
        print(
            f"NOTICE: {applied} edits applied, {len(skipped)} skipped "
            f"(see stderr warnings above); DOCX_EDIT_STRICT=1 fails on "
            f"skipped edits",
            file=sys.stderr,
        )
    else:
        print(f"applied {applied} edits, 0 skipped")
    if os.environ.get("DOCX_EDIT_STRICT", "").strip().lower() == "1" and skipped:
        raise SystemExit(2)


def paras(body):
    """Current list of <w:p> elements in document order."""
    return list(body.iter(W + "p"))


def text_of(p):
    """Concatenated text of a paragraph (runs joined)."""
    return "".join(t.text or "" for t in p.iter(W + "t"))


def find_p(paragraphs, startswith):
    """The unique paragraph whose text starts with `startswith`, else None.

    Match on .startswith() so it is robust to minor trailing differences
    (trailing punctuation, whitespace).

    Resolution is order-independent: the prefix is matched against each
    paragraph's ORIGINAL master text (captured at load() time) first, so a
    script's own earlier edits cannot rewrite one paragraph's text to start
    with another target's prefix and collide with it mid-run. Falls back to
    matching current text when no original matches (e.g. targeting a
    paragraph the script itself just created or rewrote).

    Returns None (stderr warning naming the candidates) if the prefix is
    missing or matches more than one paragraph — an ambiguous prefix could
    match the wrong paragraph, so callers skip rather than mutate. Use a
    unique prefix (see `prefixes()`).
    """
    orig = [
        (i, p)
        for i, p in enumerate(paragraphs)
        if (_orig_text(p) or "").startswith(startswith)
    ]
    if len(orig) == 1:
        return orig[0][1]
    if len(orig) > 1:
        _warn_ambiguous(
            startswith, [(i, (_orig_text(p) or "")[:80]) for i, p in orig]
        )
        return None
    # No original match — fall back to current text.
    cur = [
        (i, p) for i, p in enumerate(paragraphs)
        if text_of(p).startswith(startswith)
    ]
    if not cur:
        _warn_missing(startswith, record=False)
        return None
    if len(cur) > 1:
        _warn_ambiguous(startswith, [(i, text_of(p)[:80]) for i, p in cur])
        return None
    return cur[0][1]


def _runs(p):
    return p.findall(W + "r")


def set_text(p, text):
    """Replace a paragraph's text, preserving the first run's formatting (rPr).

    Keeps the first run (with its rPr: font, size, bold) and discards the rest,
    so the paragraph keeps its visual style. Used for rewriting bullets/intros.

    No-op with a stderr warning if ``p`` is ``None`` (target paragraph not
    found in the master) so a script still runs when the master changed.
    """
    if p is None:
        _warn_missing(text[:40])
        return
    rs = _runs(p)
    if not rs:
        r = ET.SubElement(p, W + "r")
        t = ET.SubElement(r, W + "t")
        t.text = text
        t.set(SPACE, "preserve")
        return
    first = rs[0]
    rPr = first.find(W + "rPr")
    for t in first.findall(W + "t"):
        first.remove(t)
    for r in rs[1:]:
        p.remove(r)
    t = ET.SubElement(first, W + "t")
    t.text = text
    t.set(SPACE, "preserve")
    if rPr is not None:
        first.remove(rPr)
        first.insert(0, rPr)
    global _APPLIED
    _APPLIED += 1


def set_labeled(p, label, value):
    """Rewrite a 'Label: values' proficiency paragraph, preserving the
    master's two-run structure: a BOLD label run and a NON-BOLD values run.

    Use this instead of `set_text` for proficiency/skills lines of the form
    ``"Programming Languages: Java, Python, ..."``. The master renders these
    as two runs — a bold label and a non-bold value — but `set_text` collapses
    all text into the first (bold) run, making the whole line bold.

    If the paragraph has no non-bold run to borrow from (a new line built via
    `clone_after`, which collapses to a single bold run), the value run's
    formatting is derived from the label run — same font/size/color, with the
    bold/style dropped — so the value never falls back to document defaults
    (wrong font/color).

    No-op with a stderr warning if ``p`` is ``None`` (target paragraph not
    found in the master) so a script still runs when the master changed.
    """
    if p is None:
        _warn_missing(label)
        return
    rs = _runs(p)
    bold_rPr = None
    val_rPr = None
    if rs:
        first_rPr = rs[0].find(W + "rPr")
        if first_rPr is not None:
            bold_rPr = copy.deepcopy(first_rPr)
    for r in rs[1:]:
        rPr = r.find(W + "rPr")
        if rPr is None:
            continue
        b = rPr.find(W + "b")
        if b is not None and b.get(W + "val") in ("0", "false"):
            val_rPr = copy.deepcopy(rPr)
            break
    if val_rPr is None and bold_rPr is not None:
        # No visible non-bold value run (clone_after collapses a "Label:
        # values" line to one bold run). Derive the value formatting from
        # the label run — drop the label style and the bold flag, keep
        # font/size/color — instead of leaving the value run with no rPr,
        # which falls back to document defaults (the "OS & Scripting" bug).
        val_rPr = copy.deepcopy(bold_rPr)
        for tag in (W + "rStyle", W + "b", W + "bCs"):
            el = val_rPr.find(tag)
            if el is not None:
                val_rPr.remove(el)
    for r in rs:
        p.remove(r)
    rlab = ET.SubElement(p, W + "r")
    if bold_rPr is not None:
        rlab.insert(0, copy.deepcopy(bold_rPr))
    tlab = ET.SubElement(rlab, W + "t")
    tlab.text = label
    tlab.set(SPACE, "preserve")
    rval = ET.SubElement(p, W + "r")
    if val_rPr is not None:
        rval.insert(0, copy.deepcopy(val_rPr))
    tval = ET.SubElement(rval, W + "t")
    tval.text = value
    tval.set(SPACE, "preserve")
    global _APPLIED
    _APPLIED += 1


def replace_text(p, old, new):
    """Replace all occurrences of substring ``old`` with ``new`` in a paragraph,
    per run, preserving each run's formatting (rPr).

    Use this for surgical edits (grammar, casing, a single word/phrase swap)
    where rewriting the whole paragraph via :func:`set_text` would be broader
    than needed or would collapse a multi-run proficiency line.

    Replaces within each run independently (``run.text.replace(old, new)``),
    preserving each run's formatting. Occurrences spanning run boundaries
    (a word split across two runs) are not replaced.

    For whole-paragraph rewrites use :func:`set_text`; for ``"Label: values"``
    proficiency lines use :func:`set_labeled`.

    No-op with a stderr warning if ``p`` is ``None`` or ``old`` is not found,
    so a script still runs when the master changed.
    """
    if p is None:
        _warn_missing(old)
        return
    if old not in text_of(p):
        _warn_missing(old)
        return
    for r in _runs(p):
        for t in r.findall(W + "t"):
            if t.text and old in t.text:
                t.text = t.text.replace(old, new)
    global _APPLIED
    _APPLIED += 1


def remove_empty(body, startswith=None):
    """Remove empty (blank-text) paragraphs from the body.

    If `startswith` is given, only remove empty paragraphs at or after the
    first paragraph whose text starts with that prefix — used to drop the
    inter-role spacer paragraphs in the lower half of the resume to reclaim
    vertical space without touching the top.

    Returns the count removed.
    """
    ps = paras(body)
    if startswith is not None:
        start = None
        for i, p in enumerate(ps):
            if text_of(p).startswith(startswith):
                start = i
                break
        if start is None:
            return 0
        targets = ps[start:]
    else:
        targets = ps
    n = 0
    for p in targets:
        if text_of(p).strip() == "":
            body.remove(p)
            n += 1
    return n


def clone_after(body, ref_p, text):
    """Clone `ref_p` (keeping its pPr, incl. numbering -> bullet style) and
    insert immediately after it with new text. Borrow formatting from ref's
    first run. Use this to add NEW bullets that inherit the bullet style of
    an existing one.

    No-op with a stderr warning if ``ref_p`` is ``None`` (target paragraph
    not found in the master) so a script still runs when the master changed.
    """
    if ref_p is None:
        _warn_missing(text[:40])
        return None
    new = copy.deepcopy(ref_p)
    for r in new.findall(W + "r"):
        new.remove(r)
    ref_runs = ref_p.findall(W + "r")
    r = ET.SubElement(new, W + "r")
    if ref_runs:
        ref_rPr = ref_runs[0].find(W + "rPr")
        if ref_rPr is not None:
            r.insert(0, copy.deepcopy(ref_rPr))
    t = ET.SubElement(r, W + "t")
    t.text = text
    t.set(SPACE, "preserve")
    idx = list(body).index(ref_p)
    body.insert(idx + 1, new)
    _ORIG[id(new)] = (new, text)  # register so find_p can resolve it
    global _APPLIED
    _APPLIED += 1
    return new


def remove(body, p):
    """Remove a paragraph from the body.

    No-op with a stderr warning if ``p`` is ``None`` (target paragraph not
    found in the master) so a script still runs when the master changed.
    """
    if p is None:
        _warn_missing("(remove)")
        return
    body.remove(p)
    global _APPLIED
    _APPLIED += 1


def style_and_numid(p):
    """Return ``(style, numId)`` extracted from a paragraph's pPr;
    both are ``None`` when absent.
    """
    pPr = p.find(W + "pPr")
    if pPr is None:
        return None, None
    style = None
    st = pPr.find(W + "pStyle")
    if st is not None:
        style = st.get(W + "val")
    numId = None
    np = pPr.find(W + "numPr")
    if np is not None:
        ni = np.find(W + "numId")
        if ni is not None:
            numId = ni.get(W + "val")
    return style, numId


def paragraph_map(body, width=90):
    """Return list of "idx | style | numId | text" strings for inspection.

    `width` truncates each paragraph's text to that many characters; pass
    ``None`` for full text (no truncation).
    """
    out = []
    for i, p in enumerate(paras(body)):
        style, numId = style_and_numid(p)
        txt = text_of(p) if width is None else text_of(p)[:width]
        out.append(f"{i:2} [{style}] num={numId} | {txt}")
    return out


def prefixes(body, min_len=30, max_len=70):
    """Return copy-pasteable ``find_p(ps, "…")`` prefixes for every paragraph.

    For each paragraph, pick the shortest prefix (between ``min_len`` and
    ``max_len`` characters) that no other paragraph starts with, so the
    prefix is a safe, unique argument to :func:`find_p`. If no unique prefix
    exists up to ``max_len``, use ``max_len`` and mark the line with ``*``
    (ambiguous — lengthen manually or pick a different anchor).

    Returns a list of strings of the form::

        idx | find_p(ps, "<prefix>")  # <full text>

    Print with::

        python3 scripts/docx_edit.py <path.docx> --prefixes
    """
    ps = paras(body)
    texts = [text_of(p) for p in ps]
    out = []
    for i, txt in enumerate(texts):
        if not txt:
            out.append(f"{i:2} | (empty)")
            continue
        chosen = None
        ambiguous = False
        for n in range(min_len, min(max_len, len(txt)) + 1):
            cand = txt[:n]
            if sum(1 for t in texts if t.startswith(cand)) == 1:
                chosen = cand
                break
        if chosen is None:
            chosen = txt[:max_len] if len(txt) >= max_len else txt
            ambiguous = len(txt) > max_len and sum(
                1 for t in texts if t.startswith(chosen)
            ) > 1
        flag = "*" if ambiguous else " "
        out.append(f'{i:2}{flag}| find_p(ps, {chosen!r})  # {txt}')
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: docx_edit.py <path.docx> [range] [--full] [--prefixes]", file=sys.stderr)
        print("  range: N-M (paragraphs N..M inclusive) or N (just paragraph N)",
              file=sys.stderr)
        print("  --full: show full text instead of truncating at 90 chars",
              file=sys.stderr)
        print("  --prefixes: print copy-pasteable, uniqueness-checked "
              "find_p(ps, \"\u2026\") prefixes", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    args = sys.argv[2:]
    full = "--full" in args
    want_prefixes = "--prefixes" in args
    args = [a for a in args if a not in ("--full", "--prefixes")]
    width = None if full else 90
    rng = None
    for a in args:
        if "-" in a and a.split("-", 1)[0].isdigit() and a.split("-", 1)[1].isdigit():
            lo, hi = a.split("-", 1)
            rng = (int(lo), int(hi))
        elif a.isdigit():
            rng = (int(a), int(a))
    root, body, names, data, _ = load(path)
    if want_prefixes:
        lines = prefixes(body)
    else:
        lines = paragraph_map(body, width=width)
    if rng:
        lo, hi = rng
        lo = max(0, lo)
        hi = min(hi, len(lines) - 1)
        lines = lines[lo:hi + 1]
    for line in lines:
        print(line)
