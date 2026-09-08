"""docx_edit.py command-line surface — inspect / find_p prefixes /
append-after / set-text.

Split from docx_edit.py so the editor core stays focused. Imports the
core one-way (`docx_edit` never imports this module at module level —
its __main__ guard delegates here, which pylint treats as cycle-free),
so `python3 scripts/docx_edit.py` keeps working unchanged.
"""

import sys

from docx_edit import (TITLE_STYLE, clone_after, find_p, load, paras, save,
                       set_text, style_and_numid, text_of)


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


def _headline_index(styles):
    """Index of the positioning headline among the paragraphs, or ``None``.

    The headline is the LAST paragraph of the document's leading run of
    ``TITLE_STYLE`` paragraphs — the name line shares the style, so the
    first Title is the NAME, not the headline. Marking it in the
    ``--prefixes`` dump moves the name-vs-headline distinction out of the
    skill text and into the tool output the script author is actually
    reading (a session authored the anchor against the wrong Title and
    spent two calls inspecting find_p's source to recover). Returns None
    when the document does not open with a Title run."""
    if not styles or styles[0] != TITLE_STYLE:
        return None
    i = 0
    while i + 1 < len(styles) and styles[i + 1] == TITLE_STYLE:
        i += 1
    return i


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
    styles = [style_and_numid(p)[0] for p in ps]
    headline_idx = _headline_index(styles)
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
        note = "HEADLINE (positioning title, not the name): " \
            if i == headline_idx else ""
        out.append(f'{i:2}{flag}| find_p(ps, {chosen!r})  # {note}{txt}')
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
        print("  range: N-M (paragraphs N..M inclusive), N (just paragraph N),",
              file=sys.stderr)
        print("         or a comma-separated list, e.g. 3,7,10-12", file=sys.stderr)
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
    idxs = None
    for a in args:
        if "-" in a and a.split("-", 1)[0].isdigit() and a.split("-", 1)[1].isdigit():
            lo, hi = a.split("-", 1)
            rng = (int(lo), int(hi))
        elif "," in a and all(
            p.isdigit()
            or ("-" in p and p.split("-", 1)[0].isdigit()
                and p.split("-", 1)[1].isdigit())
            for p in a.split(",")
        ):
            # Comma list — sparse, non-contiguous indexes (61,63,65,70-72).
            # The per-index subprocess loop this replaces issues one
            # python-per-paragraph; a session read 9 scattered bullets that
            # way because the range form could not express gaps.
            idxs = set()
            for part in a.split(","):
                if "-" in part:
                    lo, hi = part.split("-", 1)
                    idxs.update(range(int(lo), int(hi) + 1))
                else:
                    idxs.add(int(part))
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
    if idxs:
        hi = len(lines) - 1
        lines = [line for i, line in enumerate(lines)
                 if i in idxs and i <= hi]
    elif rng:
        lo, hi = rng
        lo = max(0, lo)
        hi = min(hi, len(lines) - 1)
        lines = lines[lo:hi + 1]
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv))