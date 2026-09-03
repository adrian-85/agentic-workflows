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
    # paragraphs are XML ELEMENTS — read their text with text_of(p), never
    # p.text / p.text_ (AttributeError).
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
    # Merging overlapping content into an existing bullet: merge_into
    # rewrites the target AND removes the source in one op, so a merge can
    # never leave the source's old text as near-duplicate residue:
    # merge_into(body, find_p(ps, "<keep>"), find_p(ps, "<absorb>"), "merged")
    remove_empty(body, startswith="<text prefix at/after which to drop spacers>")
    # save() records a per-script drift sidecar (no hand-counting needed;
    # the baseline is established on the first run).

CLI (inspect structure before editing)::

    python3 scripts/docx_edit.py path/to/resume.docx
        # prints: index | style | numId | text[:90]  for every paragraph
    python3 scripts/docx_edit.py path/to/resume.docx 26-38 --full
        # prints paragraphs 26-38 with FULL text (no truncation)
"""

import copy
import hashlib
import json
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


def save(path, root, names, data, drift_key=None, src=None):
    """Serialize mutated root back into the .docx zip at `path`.

    After writing, prints an applied-vs-skipped summary so a silently
    skipped edit (a find_p prefix that drifted or is ambiguous) cannot go
    unnoticed. With ``DOCX_EDIT_STRICT=1``, exits with status 2 if any edit
    was skipped instead of merely reporting it.

    It also auto-maintains a ``<path>.drift.json`` sidecar keyed by the
    calling script: the first run records the applied count as the baseline,
    and every later run warns when the count changed — i.e. an edit was
    added, removed, or stopped matching the master. Warn-once, rebaseline;
    the blocking gate for a stopped-matching edit is the skipped-edit check
    (exit 2 under strict).

    When ``src`` (the master the script copied from) is passed, the sidecar
    also records the master's sha256 and warns ``MASTER CHANGED`` when it
    differs from the previous run of the same script. This catches the
    silent hazard a skipped-edit warning cannot see: a master edited
    mid-session (or between runs) where a script prefix STILL matches but
    the text underneath changed — the rewrite would land on the new text
    with no skip fired. On this warning, re-dump
    ``docx_edit.py <master> --prefixes`` and run ``diff_resume.py --tailor``
    before rendering.

    The MASTER CHANGED detection is also a GATE, not just a warning: when
    the master changed since the script's last run, skipped edits exit 2
    even WITHOUT ``DOCX_EDIT_STRICT``. This deterministically enforces the
    SKILL fold-ordering rule (fold into the master, then re-run the tailor
    script) without relying on the agent remembering to re-run under
    strict: a mid-session master fold can no longer silently strand drifted
    prefixes — the next tailor run either resolves every prefix (clean
    pass) or fails loudly.
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
    strict = os.environ.get("DOCX_EDIT_STRICT", "").strip().lower() == "1"
    if skipped:
        print(
            f"NOTICE: {applied} edits applied, {len(skipped)} skipped "
            f"(see stderr warnings above); DOCX_EDIT_STRICT=1 fails on "
            f"skipped edits",
            file=sys.stderr,
        )
    else:
        print(f"applied {applied} edits, 0 skipped")
    if drift_key is None:
        drift_key = os.path.basename(sys.argv[0]).rsplit(".", 1)[0]
    drift_path = path + ".drift.json"
    baseline = {}
    if os.path.exists(drift_path):
        try:
            with open(drift_path) as f:
                baseline = json.load(f)
        except (ValueError, OSError):
            baseline = {}
    master_sha = None
    if src:
        with open(src, "rb") as f:
            master_sha = hashlib.sha256(f.read()).hexdigest()
    prev = baseline.get(drift_key)
    prev_edits = prev.get("edits") if isinstance(prev, dict) else prev
    prev_sha = prev.get("master_sha") if isinstance(prev, dict) else None
    if prev is not None and prev_edits != applied:
        print(
            f"DRIFT: {drift_key} expected {prev_edits} edits (last "
            f"recorded run) but applied {applied} — an edit was added, "
            f"removed, or stopped matching the master. Review before "
            f"rendering. If this change was intentional, no action is "
            f"needed: the baseline updates automatically (warn-once), and "
            f"the blocking gate for a stopped-matching edit is the "
            f"skipped-edit check.",
            file=sys.stderr,
        )
        # A count change is a review signal, not a gate: rebaseline so the
        # warning fires ONCE per change (an intentional add/remove must not
        # trap every later run). The blocking gate for "an edit stopped
        # matching" is the skipped-edit check below.
    master_changed = bool(prev_sha and master_sha and prev_sha != master_sha)
    if master_changed:
        print(
            f"MASTER CHANGED: {src} differs from the master of the last "
            f"run of {drift_key} — prefixes may have drifted or edits may "
            f"now land on rewritten text. Re-dump `docx_edit.py {src!r} "
            f"--prefixes` and run diff_resume.py --tailor before "
            f"rendering. Expected if you folded content into the master "
            f"this session; this run is auto-strict — any skipped edit "
            f"now exits 2.",
            file=sys.stderr,
        )
    baseline[drift_key] = {"edits": applied, "master_sha": master_sha}
    try:
        with open(drift_path, "w") as f:
            json.dump(baseline, f, indent=1)
    except OSError:
        pass  # sidecar is best-effort; never fails the save
    if strict and skipped:
        print(
            f"output written to {path}; strict check FAILED "
            f"({len(skipped)} skipped edit(s)) — review the warnings above",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if master_changed and skipped and not strict:
        # Deterministic enforcement (see docstring): a run against a changed
        # master must prove every prefix still resolves. Without this, a
        # mid-session master fold strands drifted prefixes silently unless
        # the agent remembers to re-run under DOCX_EDIT_STRICT.
        print(
            f"output written to {path}; MASTER-CHANGED gate FAILED "
            f"({len(skipped)} skipped edit(s) against a changed master) — "
            f"re-dump `docx_edit.py {src!r} --prefixes`, fix the skipped "
            f"prefixes, and re-run",
            file=sys.stderr,
        )
        raise SystemExit(2)


def paras(body):
    """Current list of <w:p> elements in document order."""
    return list(body.iter(W + "p"))


def text_of(p):
    """Concatenated text of a paragraph (runs joined)."""
    return "".join(t.text or "" for t in p.iter(W + "t"))


def _matchkey(s):
    """Normalize smart punctuation for prefix MATCHING only (never display).

    find_p matches against master text that may use curly apostrophes/quotes
    (\u2018\u2019\u201c\u201d) or en/em dashes (\u2013\u2014) while a hand-typed
    script prefix uses the ASCII equivalents. Normalize both sides so
    `find_p(ps, "company's goal")` finds "company\u2019s goal" without a round
    trip to inspect the XML.
    """
    return (s or "").translate(_SMART)


_SMART = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
})


def find_p(paragraphs, startswith, *, after=None, nth=None):
    """The unique paragraph whose text starts with `startswith`, else None.

    Match on .startswith() so it is robust to minor trailing differences
    (trailing punctuation, whitespace). Smart punctuation is collapsed
    before matching (\u2018\u2019->', \u201c\u201d->", \u2013\u2014->-), so a
    script prefix typed with ASCII quotes/dashes finds a curly-punctuated
    master.

    Resolution is order-independent: the prefix is matched against each
    paragraph's ORIGINAL master text (captured at load() time) first, so a
    script's own earlier edits cannot rewrite one paragraph's text to start
    with another target's prefix and collide with it mid-run. Falls back to
    matching current text when no original matches (e.g. targeting a
    paragraph the script itself just created or rewrote).

    `after=<paragraph>` restricts the search to paragraphs strictly AFTER
    that one in document order — the disambiguator for duplicate job
    titles. Two roles can textually share a title (e.g. two "Senior Quality
    Assurance Engineer" paragraphs); anchor on the role's company header
    and locate the title inside it:

        find_p(ps, "Senior Quality Assurance Engineer",
               after=find_p(ps, "Company B"))

    `nth=N` returns the N-th matching paragraph (1-based) instead of
    requiring uniqueness — for repeated text where position is the only
    disambiguator.

    Returns None (stderr warning naming the candidates) if the prefix is
    missing or matches more than one paragraph (without an `nth`) — an
    ambiguous prefix could match the wrong paragraph, so callers skip
    rather than mutate. Use a unique prefix (see `prefixes()`).
    """
    pref = _matchkey(startswith)
    after_idx = None
    if after is not None:
        for i, p in enumerate(paragraphs):
            if p is after:
                after_idx = i
                break

    orig = [
        p for i, p in enumerate(paragraphs)
        if (after_idx is None or i > after_idx)
        and _matchkey(_orig_text(p) or "").startswith(pref)
    ]
    cur = orig or [
        p for i, p in enumerate(paragraphs)
        if (after_idx is None or i > after_idx)
        and _matchkey(text_of(p)).startswith(pref)
    ]
    if nth is not None:
        if len(cur) < nth:
            _warn_missing(f"{startswith} (nth={nth})", record=False)
            return None
        return cur[nth - 1]
    if len(cur) == 1:
        return cur[0]
    if len(cur) > 1:
        _warn_ambiguous(
            startswith,
            [(i, (_orig_text(p) or text_of(p) or "")[:80])
             for i, p in enumerate(paragraphs) if p in cur],
        )
        return None
    _warn_missing(startswith, record=False)
    return None


def _runs(p):
    return p.findall(W + "r")


def set_text(p, text):
    """Replace a paragraph's text, preserving the first run's formatting (rPr).

    Keeps the first run (with its rPr: font, size, bold) and discards the rest,
    so the paragraph keeps its visual style. Used for rewriting bullets/intros.

    No-op with a stderr warning if ``p`` is ``None`` (target paragraph not
    found in the master) so a script still runs when the master changed.
    """
    global _APPLIED
    if p is None:
        _warn_missing(text[:40])
        return
    rs = _runs(p)
    if not rs:
        r = ET.SubElement(p, W + "r")
        t = ET.SubElement(r, W + "t")
        t.text = text
        t.set(SPACE, "preserve")
        _APPLIED += 1
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

    No-op with a stderr warning if ``p`` is ``None`` (target paragraph not
    found) or ``old`` is not in the paragraph (the search text is absent from
    a paragraph that WAS found). The two cases are warned differently — the
    latter names the paragraph, not the literal search string, so an author
    who pointed at the wrong paragraph (their real fix is a different
    `find_p` prefix, not a text change) can see the mismatch.
    """
    if p is None:
        _warn_missing(old)
        return
    ptext = text_of(p)
    if old not in ptext:
        # Paragraph was found, but the search string isn't in it. The most
        # likely author error is a mismatched `find_p(...)` prefix pointing at
        # the wrong paragraph — so name the paragraph, not `old`, and record
        # the skipped edit so strict mode / drift sidecar still surface it.
        _SKIPS.append(old)
        print(
            f"warning: replace_text({old!r}) targeted a paragraph that does "
            f"not contain that text; paragraph starts:"
            f" {ptext[:50]!r} — this usually means the find_p prefix "
            f"resolved to the wrong paragraph; check the prefix, not the "
            f"text — edit skipped",
            file=sys.stderr,
        )
        return
    if not any(
        old in (t.text or "")
        for r in _runs(p)
        for t in r.findall(W + "t")
    ):
        # The joined text contains `old` but no single run does: the phrase
        # spans run boundaries (e.g. a bold lead-in run + a plain run).
        # Per-run replacement cannot cross runs, so mutating now would edit
        # nothing while still counting the edit as applied. Skip cleanly
        # (all-or-nothing) and record so strict mode surfaces it.
        print(
            f"warning: replace_text({old!r}) appears in the paragraph's "
            f"joined text but spans run boundaries — per-run replacement "
            f"cannot cross runs; no change made, edit skipped",
            file=sys.stderr,
        )
        _SKIPS.append(old)
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


def drop(body, prefixes):
    """Remove paragraphs whose text starts with any of ``prefixes``.

    The library replacement for the per-script ``_drop`` helper, and the
    fix for its stale-list failure mode: a helper that threads one ``ps``
    list across edits keeps references to paragraphs removed by EARLIER
    calls (the caller's list is never refreshed), so a later ``find_p``
    against that stale list can "find" an already-detached paragraph —
    a false ambiguity on a short prefix, or a silent edit applied to a
    detached element. ``drop`` resolves every prefix against a FRESH
    :func:`paras` of the body, so detachment is impossible.

    A prefix that matches nothing (or is ambiguous) is skipped with the
    prefix named in the warning/skip record — unlike ``remove(None)``'s
    generic "(remove)" label — so strict-mode reports name the culprit.

    Returns the refreshed paragraph list; assign it back::

        ps = drop(body, ["prefix one", "prefix two"])
    """
    for prefix in prefixes:
        if not isinstance(prefix, str):
            raise TypeError(
                "drop() takes prefix STRINGS (copy-pasteable find_p(ps, '…') "
                "lines from the --prefixes dump / DROP PLAN), not paragraph "
                "elements. Got "
                f"{type(prefix).__name__}; pass the prefix text itself."
            )
        p = find_p(paras(body), prefix)
        if p is None:
            # find_p already warned (missing or ambiguous, record=False);
            # record the skip under the real prefix for save()'s report.
            _SKIPS.append(prefix)
            continue
        remove(body, p)
    return paras(body)


# Block grammar of the resume layout (see drop_role/drop_section). A role
# runs from its CompanyBlock header to just BEFORE the next CompanyBlock or
# section heading; a section runs from its SectionHeading to just BEFORE
# the next SectionHeading. Heading1/Heading2 are accepted as boundaries too
# so documents that use real heading styles instead of SectionHeading work.
ROLE_STYLE = "CompanyBlock"
SECTION_STYLE = "SectionHeading"
_BLOCK_BOUNDARY_STYLES = ("CompanyBlock", "SectionHeading",
                          "Heading1", "Heading2")


def _prefix_arg(prefix, api):
    """Guard the whole-role/section removers: they take a prefix STRING.

    A common authoring slip (seen in a real tailoring session) is passing the
    result of ``find_p(...)`` — an lxml/ElementTree element — where the prefix
    text belongs. Fail immediately with a message naming the fix instead of a
    raw ``AttributeError`` deep inside ``find_p``."""
    if not isinstance(prefix, str):
        raise TypeError(
            f"{api}() takes a prefix STRING (a copy-pasteable find_p line "
            f"from the --prefixes dump), not a paragraph element; got "
            f"{type(prefix).__name__}. Pass the prefix text itself."
        )
    return prefix


def _block(body, prefix, anchor_style, boundary_styles):
    """Paragraphs of the contiguous block anchored at ``prefix`` (resolved
    by find_p and REQUIRED to have ``anchor_style``), up to but EXCLUDING
    the first subsequent boundary-style paragraph. ``None`` (with a stderr
    warning) when the prefix is missing/ambiguous or anchors to a paragraph
    of a different style — a wrong-style anchor must refuse to mass-delete
    from that point rather than eat half the document."""
    ps = paras(body)
    anchor = find_p(ps, prefix)
    if anchor is None:
        return None
    style, _ = style_and_numid(anchor)
    if style != anchor_style:
        print(
            f"warning: block anchored at {prefix!r} resolved to a "
            f"{style!r} paragraph, expected {anchor_style!r} — skipping",
            file=sys.stderr,
        )
        return None
    out = []
    started = False
    for p in ps:
        if p is anchor:
            started = True
            out.append(p)
            continue
        if not started:
            continue
        st, _ = style_and_numid(p)
        if st in boundary_styles:
            break  # boundary EXCLUDED — checked before appending
        out.append(p)
    return out


def drop_role(body, company_prefix, company_style=ROLE_STYLE,
              boundary_styles=_BLOCK_BOUNDARY_STYLES):
    """Remove an ENTIRE role: the company header found by ``company_prefix``
    through its job title, bullets, Tools line, and trailing blank spacer —
    stopping BEFORE the next company header or section heading.

    Boundary is checked BEFORE appending, so the next section heading is
    never consumed. Duplicate job titles need no ``after=``/``nth=`` anchor
    (the block is contiguous from the role's OWN header).

    For a resume whose style names differ, pass ``company_style`` and
    ``boundary_styles`` explicitly. Returns the refreshed paragraph list;
    a missing/ambiguous/wrong-style prefix records a skip
    (``drop_role: <prefix>``) and mutates nothing."""
    block = _block(body, _prefix_arg(company_prefix, "drop_role"),
                   company_style, boundary_styles)
    if block is None:
        _warn_missing(f"drop_role: {company_prefix}")
        return paras(body)
    for p in block:
        remove(body, p)
    return paras(body)


def drop_section(body, heading_prefix, heading_style=SECTION_STYLE,
                 boundary_styles=("SectionHeading", "Heading1", "Heading2")):
    """Remove a whole SECTION: the SectionHeading found by
    ``heading_prefix`` through every paragraph up to (excluding) the next
    section heading — e.g. dropping Education when the JD gives the degree
    no evidentiary weight (SKILL Step 3.4). The boundary heading is excluded
    for the same reason as :func:`drop_role`'s. Returns the refreshed
    paragraph list; a missing/ambiguous/wrong-style prefix records a skip
    (named ``drop_section: <prefix>``) and mutates nothing."""
    block = _block(body, _prefix_arg(heading_prefix, "drop_section"),
                   heading_style, boundary_styles)
    if block is None:
        _warn_missing(f"drop_section: {heading_prefix}")
        return paras(body)
    for p in block:
        remove(body, p)
    return paras(body)


def merge_into(body, target, source, text):
    """Merge ``source`` into ``target`` in ONE op: rewrite ``target`` with
    ``text`` and remove ``source``.

    Use this for "merge, don't append" edits (Skill workflow Step 6) where
    new content overlaps an existing bullet: the source's old text is
    removed in the same op, so a merge can never leave the source's original
    text sitting next to the rewritten target as a near-duplicate residue
    (the failure mode of doing `set_text` + a separate `remove`).

    Resolve both paragraphs via :func:`find_p` at the call site:

        target = find_p(ps, "<prefix of the bullet to keep>")
        source = find_p(ps, "<prefix of the bullet to absorb>")
        merge_into(body, target, source, "<merged text>")

    Defensive when the master changed: if ``target`` is ``None`` the merge
    is a no-op with a warning; if ``source`` is ``None`` the target is
    still rewritten (the merged content lands) but nothing is removed; if
    ``target is source`` the merge is skipped so the only paragraph is not
    deleted. Counts as 2 applied edits (one rewrite + one removal) when
    both paragraphs resolve.
    """
    if target is None:
        _warn_missing(text[:40])
        return
    if target is source:
        print(
            f"WARNING: merge_into target is the same paragraph as source "
            f"({text[:40]!r}); skipping to avoid deleting the only "
            f"paragraph.",
            file=sys.stderr,
        )
        return
    set_text(target, text)
    if source is not None:
        remove(body, source)


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


def shortest_unique_prefix(texts, idx, min_len=1):
    """Shortest prefix of ``texts[idx]`` that no other text starts with.

    Returns None when the paragraph's text is duplicated (no prefix can
    uniquely identify it) or the index is out of range. This is the
    copy-pasteable argument for :func:`find_p` — powers measure_resume's
    DROP PLAN so suggested bullet cuts ship as working ``find_p(ps, ...)``
    lines, not as a re-reading chore.
    """
    if idx < 0 or idx >= len(texts):
        return None
    target = texts[idx]
    others_match = [
        i for i, t in enumerate(texts) if t.startswith(target)
    ]
    if len(others_match) > 1:
        return None  # another text starts with the WHOLE target
    for n in range(min_len, len(target) + 1):
        cand = target[:n]
        if sum(1 for t in texts if t.startswith(cand)) == 1:
            return cand
    return target if target else None


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


def cli(argv):
    """docx_edit.py command line. Returns a process exit code.

    Modes:
      docx_edit.py <path.docx> [range] [--full] [--prefixes] [--style NAME]
          inspect paragraphs / print copy-pasteable find_p prefixes. With
          no range or flag this prints the FULL PARAGRAPH MAP — index,
          style, numId, text — which is how you discover the block-boundary
          styles (CompanyBlock, SectionHeading) that drop_role/drop_section
          key on; --style NAME filters the map to one style.
      docx_edit.py <path.docx> --append-after "<ref prefix>" \
          --with "<new bullet text>"
          clone a new bullet AFTER the paragraph whose text starts with the
          ref prefix (inherits ref's numbering/bullet style), in place.
      docx_edit.py <path.docx> --set-text "<prefix>" --with "<new text>"
          rewrite the paragraph's text in place (first run's formatting
          kept). For one-off folds/fixes; NOT for "Label: values"
          proficiency lines (set_text collapses the bold split — use a
          script with set_labeled for those). Both edit modes resolve the
          prefix with find_p — smart punctuation is tolerated, and a
          missing/ambiguous prefix exits 2 so a one-shot edit cannot
          silently no-op.
    """
    if len(argv) < 2 or argv[1] in ("--help", "-h"):
        print("usage: docx_edit.py <path.docx> [range] [--full] [--prefixes] [--style NAME]",
              file=sys.stderr)
        print("       docx_edit.py <path.docx> --append-after \"<ref prefix>\" --with \"<text>\"",
              file=sys.stderr)
        print("  Inspect paragraphs (default = full map: index | style | numId | text),",
              file=sys.stderr)
        print("  print find_p prefixes, clone a bullet, or rewrite a paragraph.",
              file=sys.stderr)
        print("  range: N-M (paragraphs N..M inclusive) or N (just paragraph N)",
              file=sys.stderr)
        print("  --full:     show full text instead of truncating at 90 chars",
              file=sys.stderr)
        print("  --prefixes: print uniqueness-checked find_p(ps, \"\u2026\") prefixes",
              file=sys.stderr)
        print("  --style N:  map filtered to one paragraph style (e.g. CompanyBlock)",
              file=sys.stderr)
        return 2
    path = argv[1]
    args = argv[2:]
    if "--append-after" in args:
        try:
            i = args.index("--append-after")
            ref_prefix = args[i + 1]
            if args[i + 2] != "--with":
                raise IndexError
            text = args[i + 3]
        except IndexError:
            print("usage: docx_edit.py <path.docx> --append-after \"<ref>\" "
                  "--with \"<text>\"", file=sys.stderr)
            return 2
        root, body, names, data, _ = load(path)
        ps = paras(body)
        ref_p = find_p(ps, ref_prefix)
        if ref_p is None:
            print(f"target paragraph {ref_prefix[:40]!r} not found; "
                  f"no changes written", file=sys.stderr)
            return 2
        clone_after(body, ref_p, text)
        save(path, root, names, data)
        return 0
    if "--set-text" in args:
        try:
            i = args.index("--set-text")
            prefix = args[i + 1]
            if args[i + 2] != "--with":
                raise IndexError
            text = args[i + 3]
        except IndexError:
            print("usage: docx_edit.py <path.docx> --set-text \"<prefix>\" "
                  "--with \"<text>\"", file=sys.stderr)
            return 2
        root, body, names, data, _ = load(path)
        ps = paras(body)
        p = find_p(ps, prefix)
        if p is None:
            print(f"target paragraph {prefix[:40]!r} not found; "
                  f"no changes written", file=sys.stderr)
            return 2
        set_text(p, text)
        save(path, root, names, data)
        return 0
    full = "--full" in args
    want_prefixes = "--prefixes" in args
    style_filter = None
    if "--style" in args:
        i = args.index("--style")
        if i + 1 < len(args):
            style_filter = args[i + 1]
    args = [a for a in args if a not in ("--full", "--prefixes", "--style")
            and a != style_filter]
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
    elif style_filter is not None:
        lines = []
        for i, p in enumerate(paras(body)):
            st, numid = style_and_numid(p)
            if st == style_filter:
                txt = text_of(p) if width is None else text_of(p)[:width]
                lines.append(f"{i:2} [{st}] num={numid} | {txt}")
    else:
        lines = paragraph_map(body, width=width)
    if rng:
        lo, hi = rng
        lo = max(0, lo)
        hi = min(hi, len(lines) - 1)
        lines = lines[lo:hi + 1]
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv))
