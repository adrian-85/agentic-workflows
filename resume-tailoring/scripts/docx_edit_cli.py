"""docx_edit.py command-line surface — inspect / find_p prefixes /
append-after / set-text.

Split from docx_edit.py so the editor core stays focused. Imports the
core one-way (`docx_edit` never imports this module at module level —
its __main__ guard delegates here, which pylint treats as cycle-free),
so `python3 scripts/docx_edit.py` keeps working unchanged.
"""
# pylint: disable=invalid-name
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.

# pylint: disable=invalid-name
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.


import ast
import contextlib
import io
import os
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
        note = "HEADLINE (positioning title, not the name): " \
            if i == headline_idx else ""
        out.append(f'{i:2}{"*" if ambiguous else " "}| find_p(ps, {chosen!r})  # {note}{txt}')
    return out


def _script_find_p_prefixes(script_path):
    """Every find_p search-string in a tailor script, via AST.

    Python's implicit string-literal concatenation collapses multi-line
    arguments into one Constant at parse time, so this handles both
    ``find_p(ps, "prefix")`` and multi-line set_labeled-style calls.
    Returns (prefix, lineno) pairs, in source order; None entries for
    calls whose search string is not a literal (dynamic prefix — can't
    be linted statically)."""
    with open(script_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), script_path)
    out = []
    for node in ast.walk(tree):
        func = getattr(node, "func", None) if isinstance(node, ast.Call) \
            else None
        # flat import (find_p(ps, ...)) -> ast.Name; module-qualified
        # (de.find_p(ps, ...)) -> ast.Attribute. Recognize both.
        is_find_p = (isinstance(func, ast.Attribute)
                     and func.attr == "find_p") or (
            isinstance(func, ast.Name) and func.id == "find_p")
        if not is_find_p:
            continue
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, str):
            out.append((node.args[1].value, node.lineno))
        else:
            out.append((None, node.lineno))
    return out


def lint_script(docx_path, script_path):
    """Validate a tailor script's find_p targets against a .docx BEFORE
    running it.

    A real session hand-typed two prefixes that missed the master
    ('Monitoring & Logging: Datadog' vs the master's '...Prometheus,
    Grafana, New Relic, Datadog'; 'Performed contract testing usi' vs
    'Performed contract testing to ') — each a run-crash-and-fix cycle
    that DOCX_EDIT_STRICT only catches AFTER execution. This lint runs
    the same resolution (find_p, smart punctuation included) against the
    master and reports every miss/ambiguity with line numbers, so the
    whole edit set is verified in one pre-run. Returns exit code 0 clean,
    1 findings, 2 usage error.

    A reported miss can also be a paragraph the script CREATES itself
    (clone_after then find_p) — those are expected; the lint output names
    the prefix so the author can judge.
    """
    if not os.path.exists(script_path):
        print(f"error: script not found: {script_path}", file=sys.stderr)
        return 2
    try:
        targets = _script_find_p_prefixes(script_path)
    except SyntaxError as e:
        print(f"error: {script_path} does not parse: {e}", file=sys.stderr)
        return 1
    if not targets:
        print(f"lint: no find_p calls found in {script_path} — nothing "
              "to verify")
        return 0
    _, body, _, _, _ = load(docx_path)
    ps = paras(body)
    bad = []
    with contextlib.redirect_stderr(io.StringIO()) as err_io:
        for prefix, lineno in targets:
            if prefix is None:
                bad.append((lineno, "<dynamic>",
                            "search string is not a literal — verify by "
                            "hand"))
                continue
            if find_p(ps, prefix) is None:
                warning = err_io.getvalue().strip().splitlines()
                reason = warning[-1] if warning else "not found"
                bad.append((lineno, prefix, reason))
                err_io.truncate(0)
                err_io.seek(0)
    for lineno, prefix, reason in bad:
        print(f"  MISS  line {lineno}: find_p({prefix!r}) — {reason}",
              file=sys.stderr)
    if bad:
        print(f"lint: {len(bad)} of {len(targets)} find_p target(s) "
              "do NOT resolve against this docx — fix the prefixes "
              "(see docx_edit.py <path> --prefixes) or confirm the "
              "target is script-created before running", file=sys.stderr)
        return 1
    print(f"lint: all {len(targets)} find_p target(s) resolve")
    return 0


def _cli_usage():
    """Print the docx_edit CLI usage message. Returns exit code 2."""
    print("usage: docx_edit.py <path.docx> [range] [--full] [--prefixes] [--style NAME]",
          file=sys.stderr)
    print("       docx_edit.py <path.docx> --append-after \"<ref prefix>\" --with \"<text>\"",
          file=sys.stderr)
    print("       docx_edit.py <path.docx> --lint-script <tailor_script.py>", file=sys.stderr)
    print("  Inspect paragraphs (default = full map: index | style | numId | text),",
          file=sys.stderr)
    print("  print find_p prefixes, clone a bullet, or rewrite a paragraph.",
          file=sys.stderr)
    print("  range: N-M (paragraphs N..M inclusive), N (just paragraph N),",
          file=sys.stderr)
    print("         or a comma-separated list, e.g. 3,7,10-12", file=sys.stderr)
    print("  --full:     show full text instead of truncating at 90 chars",
          file=sys.stderr)
    print("  --prefixes: print uniqueness-checked find_p(ps, \"…\") prefixes",
          file=sys.stderr)
    print("  --style N:  map filtered to one paragraph style (e.g. CompanyBlock)",
          file=sys.stderr)
    print("  --lint-script S: verify every find_p target in tailor script S",
          file=sys.stderr)
    print("              resolves against this docx BEFORE running it (exit 1 on miss)",
          file=sys.stderr)
    return 2


def _parse_edit_pair(args, flag):
    """Parse ``--<flag> <prefix> --with <text>`` from args. Returns
    (prefix, text) or None on a usage error (prints the usage message)."""
    try:
        i = args.index(flag)
        prefix = args[i + 1]
        if args[i + 2] != "--with":
            raise IndexError
        text = args[i + 3]
    except IndexError:
        print(f"usage: docx_edit.py <path.docx> {flag} \"<ref>\" "
              "--with \"<text>\"", file=sys.stderr)
        return None
    return prefix, text


def _cli_append_after(path, args):
    """Clone a bullet after the paragraph whose text starts with ref prefix."""
    pair = _parse_edit_pair(args, "--append-after")
    if pair is None:
        return 2
    ref_prefix, text = pair
    root, body, names, data, _ = load(path)
    ref_p = find_p(paras(body), ref_prefix)
    if ref_p is None:
        print(f"target paragraph {ref_prefix[:40]!r} not found; "
              f"no changes written", file=sys.stderr)
        return 2
    clone_after(body, ref_p, text)
    save(path, root, names, data)
    return 0


def _cli_set_text(path, args):
    """Rewrite a paragraph's text in place (first run's formatting kept)."""
    pair = _parse_edit_pair(args, "--set-text")
    if pair is None:
        return 2
    prefix, text = pair
    root, body, names, data, _ = load(path)
    p = find_p(paras(body), prefix)
    if p is None:
        print(f"target paragraph {prefix[:40]!r} not found; "
              f"no changes written", file=sys.stderr)
        return 2
    set_text(p, text)
    save(path, root, names, data)
    return 0


def _parse_range(args):
    """Parse range/list args from the inspect-mode args. Returns
    (rng, idxs, remaining_args) where rng is (lo, hi) or None and idxs
    is a set or None."""
    rng = None
    idxs = None
    remaining = []
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
            idxs = set()
            for part in a.split(","):
                if "-" in part:
                    lo, hi = part.split("-", 1)
                    idxs.update(range(int(lo), int(hi) + 1))
                else:
                    idxs.add(int(part))
        elif a.isdigit():
            rng = (int(a), int(a))
        else:
            remaining.append(a)
    return rng, idxs, remaining


def _style_lines(body, style_filter, width):
    """Build paragraph-map lines filtered to one style."""
    lines = []
    for i, p in enumerate(paras(body)):
        st, numid = style_and_numid(p)
        if st == style_filter:
            txt = text_of(p) if width is None else text_of(p)[:width]
            lines.append(f"{i:2} [{st}] num={numid} | {txt}")
    return lines


def _cli_inspect(path, args):
    """Inspect paragraphs: full map, prefixes, or style-filtered, with
    optional range/index filtering. Returns exit code 0."""
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
    rng, idxs, _ = _parse_range(args)
    _, body, _, _, _ = load(path)
    if want_prefixes:
        lines = prefixes(body)
    elif style_filter is not None:
        lines = _style_lines(body, style_filter, width)
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
      docx_edit.py <path.docx> --lint-script <tailor_script.py>
          verify every find_p target in a tailor script resolves against
          this docx BEFORE running the script (exit 1 on a miss) — the
          pre-run gate scripts/run_tailor.sh drives automatically.
    """
    if len(argv) < 2 or argv[1] in ("--help", "-h"):
        return _cli_usage()
    path = argv[1]
    args = argv[2:]
    if "--append-after" in args:
        return _cli_append_after(path, args)
    if "--set-text" in args:
        return _cli_set_text(path, args)
    if "--lint-script" in args:
        i = args.index("--lint-script")
        if i + 1 >= len(args):
            return _cli_usage()
        return lint_script(path, args[i + 1])
    return _cli_inspect(path, args)


if __name__ == "__main__":
    sys.exit(cli(sys.argv))
