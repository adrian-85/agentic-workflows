"""docx_edit.py command-line surface — inspect / find_p prefixes /
append-after / set-text.

Split from docx_edit.py so the editor core stays focused. Imports the
core one-way (`docx_edit` never imports this module at module level —
its __main__ guard delegates here, which pylint treats as cycle-free),
so `python3 scripts/docx_edit.py` keeps working unchanged.
"""
# pylint: disable=invalid-name
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.

# pylint: disable=invalid-name
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.


import ast
import builtins
import contextlib
import io
import json
import os
import re
import sys

from docx_edit import (ROLE_STYLE, SECTION_STYLE, TITLE_STYLE, _BLOCK_BOUNDARY_STYLES, _block,
                       clone_after, find_p, load, paras, prune_sidecar_path, save,
                       set_text, style_and_numid, text_of)
from validate_resume_checks import MAX_BULLETS_PER_ROLE, SUMMARY_STYLE
from measure_resume_format import BULLET_STYLES


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
    reading (the name line and the headline share the Title style, so the
    index alone is ambiguous). Returns None
    when the document does not open with a Title run."""
    if not styles or styles[0] != TITLE_STYLE:
        return None
    i = 0
    while i + 1 < len(styles) and styles[i + 1] == TITLE_STYLE:
        i += 1
    return i


def _role_bullet_counts(ps):
    """{role-header index: kept-bullet count} — the hard-cap visibility
    behind the --prefixes dump's `[N/8 bullets]` annotation. A role runs
    from its CompanyBlock header to the next role/section heading; bullets
    are numbered paragraphs (numId set) or ListBullet-styled ones."""
    texts = [text_of(p) for p in ps]
    pairs = [style_and_numid(p) for p in ps]
    counts = {}
    role_idx = None
    for i, txt in enumerate(texts):
        style, numid = pairs[i]
        if style == ROLE_STYLE and txt:
            role_idx = i
            counts[i] = 0
        elif style in ("SectionHeading", "Heading1", "Heading2"):
            role_idx = None  # a section heading ends the role region
        elif role_idx is not None and txt:
            if (numid is not None and numid != "0") or style in BULLET_STYLES:
                counts[role_idx] += 1
    return counts


def _unique_prefix(texts, txt, min_len, max_len):
    """(chosen, ambiguous) — the shortest unique prefix of ``txt`` among
    ``texts``, or the ``max_len`` head marked ambiguous."""
    for n in range(min_len, min(max_len, len(txt)) + 1):
        cand = txt[:n]
        if sum(1 for t in texts if t.startswith(cand)) == 1:
            return cand, False
    chosen = txt[:max_len] if len(txt) >= max_len else txt
    ambiguous = len(txt) > max_len and sum(
        1 for t in texts if t.startswith(chosen)
    ) > 1
    return chosen, ambiguous


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
    # Per-role kept-bullet counts vs the hard cap, annotated on each role
    # header line so the cap is visible at AUTHORING time instead of only
    # when run_tailor/validate rejects an over-cap role.
    bullet_counts = _role_bullet_counts(ps)
    out = []
    for i, txt in enumerate(texts):
        if not txt:
            out.append(f"{i:2} | (empty)")
            continue
        chosen, ambiguous = _unique_prefix(texts, txt, min_len, max_len)
        note = "HEADLINE (positioning title, not the name): " \
            if i == headline_idx else ""
        if i in bullet_counts:
            n = bullet_counts[i]
            note = f"[{n}/{MAX_BULLETS_PER_ROLE} bullets" \
                   f"{' — OVER CAP' if n > MAX_BULLETS_PER_ROLE else ''}] " + note
        out.append(f'{i:2}{"*" if ambiguous else " "}| find_p(ps, {chosen!r})  # {note}{txt}')
    return out


def _script_find_p_prefixes(tree):
    """Every find_p search-string in a parsed tailor script, via AST.

    Python's implicit string-literal concatenation collapses multi-line
    arguments into one Constant at parse time, so this handles both
    ``find_p(ps, "prefix")`` and multi-line set_labeled-style calls.
    Returns (prefix, lineno) pairs, in source order; None entries for
    calls whose search string is not a literal (dynamic prefix — can't
    be linted statically). Takes the already-parsed tree so lint_script
    parses the script once.
    """
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
        nth = None
        for kw in node.keywords:
            if kw.arg == "nth" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, int):
                nth = kw.value.value
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, str):
            out.append((node.args[1].value, node.lineno, nth))
        else:
            out.append((None, node.lineno, None))
    return out


def _script_summary_edit_targets(tree, ps):
    """Find literal set_text/set_labeled edits aimed at the Summary."""
    out = []
    edit_names = {"set_text", "set_labeled", "replace_text"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(
            func, "id", None)
        if name not in edit_names:
            continue
        target = node.args[0]
        if not isinstance(target, ast.Call) or len(target.args) < 2:
            continue
        target_func = target.func
        target_name = target_func.attr if isinstance(target_func, ast.Attribute) \
            else getattr(target_func, "id", None)
        prefix = target.args[1]
        if target_name != "find_p" or not isinstance(prefix, ast.Constant) \
                or not isinstance(prefix.value, str):
            continue
        nth = next((kw.value.value for kw in target.keywords
                    if kw.arg == "nth"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, int)), None)
        paragraph = find_p(ps, prefix.value, nth=nth)
        if paragraph is not None \
                and style_and_numid(paragraph)[0] == SUMMARY_STYLE:
            out.append((node.lineno, prefix.value))
    return out


def _resolve_find_p_targets(targets, ps):
    """(prefix, lineno, reason) for every find_p target that does not
    resolve against ``ps`` — the shared scan behind lint_script."""
    bad = []
    with contextlib.redirect_stderr(io.StringIO()) as err_io:
        for prefix, lineno, nth in targets:
            if prefix is None:
                bad.append((lineno, "<dynamic>",
                            "search string is not a literal (loop/variable) — the lint "
                            "and DOCX_EDIT_STRICT cannot verify it; unroll the loop into "
                            "literal find_p(ps, ...) calls (one per anchor, e.g. one "
                            "clone_after per spacer boundary) so every target is checked"))
                continue
            if nth is not None:
                resolved = find_p(ps, prefix, nth=nth)
            else:
                resolved = find_p(ps, prefix)
            if resolved is None:
                warning = err_io.getvalue().strip().splitlines()
                reason = warning[-1] if warning else "not found"
                bad.append((lineno, prefix, reason))
                err_io.truncate(0)
                err_io.seek(0)
    return bad


def _script_drop_blocks(tree, body):
    """[(lineno, api, prefix, paragraph_ids)] for every literal
    drop_role()/drop_section() call — the blocks the script removes."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in ("drop_role", "drop_section") \
                or not isinstance(node.args[1], ast.Constant) \
                or not isinstance(node.args[1].value, str):
            continue
        prefix = node.args[1].value
        anchor_style = ROLE_STYLE if name == "drop_role" else SECTION_STYLE
        with contextlib.redirect_stderr(io.StringIO()):
            block = _block(body, prefix, anchor_style, _BLOCK_BOUNDARY_STYLES)
        if block:
            out.append((node.lineno, name, prefix, {id(p) for p in block}))
    return out


def _drop_block_skips(targets, drop_blocks, ps):
    """(lineno, prefix, drop_line, drop_api, drop_prefix) for every find_p
    target that resolves INSIDE a block a LATER drop_role()/drop_section()
    removes — those edits WILL SKIP under DOCX_EDIT_STRICT (the paragraph
    is gone by then). Edits placed BEFORE the drop are fine: they run, then
    the drop removes the edited paragraph."""
    skips = []
    with contextlib.redirect_stderr(io.StringIO()):
        for prefix, lineno, nth in targets:
            if prefix is None:
                continue
            resolved = find_p(ps, prefix, nth=nth) if nth is not None else find_p(ps, prefix)
            if resolved is None:
                continue
            for drop_line, drop_api, drop_prefix, ids in drop_blocks:
                if id(resolved) in ids and lineno > drop_line:
                    skips.append((lineno, prefix, drop_line, drop_api, drop_prefix))
    return skips


def _report_lint_findings(bad, will_skip, total):
    """Print MISS/WILL-SKIP findings and summaries; True when any fired."""
    for lineno, prefix, reason in bad:
        print(f"  MISS  line {lineno}: find_p({prefix!r}) — {reason}", file=sys.stderr)
    for lineno, prefix, drop_line, drop_api, drop_prefix in will_skip:
        print(
            f"  WILL-SKIP  line {lineno}: find_p({prefix!r}) — the paragraph is removed by "
            f"{drop_api}({drop_prefix!r}) at line {drop_line}, and this edit runs AFTER the "
            f"drop, so DOCX_EDIT_STRICT will fail the run. Delete this edit (and its "
            f"'# kept:' comment) — an enclosing drop_role()/drop_section() is the whole-role "
            f"disposition (SKILL Step 5)", file=sys.stderr)
    if bad:
        print(f"lint: {len(bad)} of {total} find_p target(s) "
              "do NOT resolve against this docx — fix the prefixes "
              "(see docx_edit.py <path> --prefixes) or confirm the "
              "target is script-created before running", file=sys.stderr)
    if will_skip:
        print(f"lint: {len(will_skip)} find_p target(s) sit inside a later "
              "drop_role()/drop_section() block — remove those edits before running",
              file=sys.stderr)
    return bool(bad or will_skip)


def _script_undefined_names(tree):
    """(name, lineno) for every name the script LOADS with no binding anywhere.

    A tailor script that calls set_labeled/clone_after/drop_role without
    extending auto_prune's emitted import list crashes mid-run with
    NameError — after the master copy, before any edit applies. ast.parse
    cannot see that; this pass can. Scope-naive by design: the binding set
    is the union of EVERY binding in the module (imports, assignments,
    defs, parameters, loop/comprehension targets, exception names), so a
    name bound in any scope suppresses a report — false negatives are
    safe, false positives are not.
    """
    bound = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.Import):
            bound.update(alias.asname or alias.name.split(".")[0]
                         for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            bound.update(alias.asname or alias.name for alias in node.names)
    return [(node.id, node.lineno) for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            and node.id not in bound]


def lint_script(docx_path, script_path):
    """Validate a tailor script's find_p targets against a .docx BEFORE
    running it.

    A hand-typed prefix that does not resolve as intended ('Monitoring &
    Logging: Datadog' vs the master's '...Prometheus, Grafana, New Relic,
    Datadog') is otherwise caught only AFTER execution by DOCX_EDIT_STRICT,
    as a run-crash-and-fix cycle. This lint runs
    the same resolution (find_p, smart punctuation included) against the
    master and reports every miss/ambiguity with line numbers, so the
    whole edit set is verified in one pre-run. It also reports every name
    the script loads without a binding (a helper used but not imported
    crashes the run mid-edit). Returns exit code 0 clean,
    1 findings, 2 usage error.

    A reported miss can also be a paragraph the script CREATES itself
    (clone_after then find_p) — those are expected; the lint output names
    the prefix so the author can judge.
    """
    if not os.path.exists(script_path):
        print(f"error: script not found: {script_path}", file=sys.stderr)
        return 2
    try:
        with open(script_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), script_path)
        targets = _script_find_p_prefixes(tree)
    except SyntaxError as e:
        print(f"error: {script_path} does not parse: {e}", file=sys.stderr)
        return 1
    undefined = _script_undefined_names(tree)
    for name, lineno in undefined:
        print(f"  MISS  line {lineno}: undefined name {name!r} — not "
              "imported or assigned anywhere in the script (extend the "
              "docx_edit import list)", file=sys.stderr)
    if undefined:
        print(f"lint: {len(undefined)} undefined name(s) — the script "
              "crashes at run time (NameError) before edits apply; fix "
              "before running", file=sys.stderr)
        return 1
    if not targets:
        print(f"lint: no find_p calls found in {script_path} — nothing "
              "to verify")
        return 0
    _, body, _, _, _ = load(docx_path)
    ps = paras(body)
    summary_edits = _script_summary_edit_targets(tree, ps)
    for lineno, prefix in summary_edits:
        print(f"  immutable Summary  line {lineno}: "
              f"find_p({prefix!r}) — Summary/intro edits are forbidden",
              file=sys.stderr)
    if summary_edits:
        return 1
    bad = _resolve_find_p_targets(targets, ps)
    drop_blocks = _script_drop_blocks(tree, body)
    will_skip = _drop_block_skips(targets, drop_blocks, ps)
    if _report_lint_findings(bad, will_skip, len(targets)):
        return 1
    print(f"lint: all {len(targets)} find_p target(s) resolve")
    return 0


PRUNE_SIDECAR_SUFFIX = ".prune.json"


def _script_jd_name(script_path):
    """The JD filename recorded in the tailor script's docstring.

    auto_prune emits ``JD: jd_<target>.txt.`` as the docstring's first
    body line; the prune-plan sidecar is keyed by that JD (see
    docx_edit.prune_sidecar_path), so the coverage lint can find the
    plan for THIS run instead of a shared file another parallel session
    may have overwritten. Returns None when the docstring records no JD
    (hand-written scripts) — the caller falls back to the legacy path.
    """
    try:
        with open(script_path, encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return None
    m = re.search(r"^JD:\s+(\S+)", src, re.M)
    if not m:
        return None
    return m.group(1).rstrip(".")


def _norm_prune(text):
    """Normalization for coverage matching: whitespace-collapsed, lower,
    curly quotes unified — the same paragraph text appears in the prune
    sidecar, the tailor script, and ``# kept:`` comments with varying
    quoting, and matching must not hinge on a typographic apostrophe."""
    for cur, straight in (("\u2019", "'"), ("\u2018", "'"),
                          ("\u201c", '"'), ("\u201d", '"')):
        text = text.replace(cur, straight)
    return " ".join(text.lower().split())


def _script_cover_strings(script_path):
    """(literals, keep_lines, dropped_roles) from a tailor script.

    Literals are edit anchors and keep_lines are recorded keep reasons.
    ``dropped_roles`` contains literal arguments to ``drop_role`` so a
    candidate inside an explicitly removed role is covered by that stronger
    disposition instead of being misreported as an uncovered trim.
    """
    with open(script_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, script_path)
    literals = set()
    dropped_roles = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(_norm_prune(node.value))
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(
            func, "id", None)
        if name == "drop_role" and len(node.args) >= 2 \
                and isinstance(node.args[1], ast.Constant) \
                and isinstance(node.args[1].value, str):
            dropped_roles.add(_norm_prune(node.args[1].value))
    keeps = []
    for line in source.splitlines():
        low = _norm_prune(line)
        if "# kept:" in low or "# keep:" in low:
            keeps.append(low)
    return literals, keeps, dropped_roles


def _prune_covered(candidate, literals, keeps, dropped_roles):
    """Whether one sidecar candidate is addressed by the script.

    Matching is one-directional: the plan's prefix is the shortest unique
    one and the script pastes its extensions verbatim, so a script literal
    starting with the prefix covers it; the reverse would be ambiguous.
    Returns ``EDIT`` for an edit anchor, ``DROP`` for a candidate inside a
    role explicitly passed to ``drop_role``, ``KEEP`` for a keep comment, or
    ``None`` when the plan item is unaddressed.
    """
    role = _norm_prune(candidate.get("role") or "")
    if role and role in dropped_roles:
        return "DROP"
    head = _norm_prune(candidate["prefix"] or candidate["text"][:24])
    for lit in literals:
        # An exact match of the candidate's own (normalized) prefix cannot
        # be a spurious substring match, so it is covered even when the
        # normalization-stripped literal is under the 6-char guard (a real
        # case: prefix "Moved " normalizes to "moved", len 5).
        if lit == head or (len(lit) >= 6 and lit.startswith(head)):
            return "EDIT"
    text_head = _norm_prune(candidate["text"][:24])
    for keep in keeps:
        if head in keep or text_head in keep:
            return "KEEP"
    return None


def _prune_sidecar_candidates(sidecar):
    """(candidates, error) from the prune sidecar — a non-None error
    means exit 2 (sidecar missing)."""
    if not os.path.exists(sidecar):
        return None, (
            f"prune-coverage: no sidecar: {sidecar} — run the PRUNE PLAN "
            "first (measure_resume.py <master> --jd <JD.txt>); it emits "
            "the candidate list this gate enforces (SKILL Step 3)")
    with open(sidecar, encoding="utf-8") as f:
        return json.load(f).get("candidates", []), None


def _prune_stale_prefixes(candidates, ps):
    """Sidecar candidate anchors that no longer resolve against the docx
    — the master changed since the plan (stale sidecar)."""
    stale = []
    with contextlib.redirect_stderr(io.StringIO()):
        for c in candidates:
            if c["prefix"] is not None and find_p(ps, c["prefix"]) is None:
                stale.append(c["prefix"])
    return stale


def _prune_coverage_counts(candidates, literals, keeps, dropped_roles):
    """Coverage counts over sidecar candidates."""
    uncovered, edits, drops, keeps_n = [], 0, 0, 0
    for c in candidates:
        state = _prune_covered(c, literals, keeps, dropped_roles)
        if state == "EDIT":
            edits += 1
        elif state == "DROP":
            drops += 1
        elif state == "KEEP":
            keeps_n += 1
        else:
            uncovered.append(c)
    return uncovered, edits, drops, keeps_n


def _report_uncovered(uncovered, total):
    """Print the UNCOVERED candidate listing + summary (the exit-1 path)."""
    print(
        f"prune-coverage: {len(uncovered)} of {total} "
        "PRUNE-PLAN candidate(s) UNCOVERED — no edit targets them and "
        'no "# kept: <JD reason>" comment records them. Address each '
        "(CUT: drop(); TRIM: set_text/replace_text on the flagged "
        "sentence/clause/chunk) or record the keep — the plan is final "
        "on WHICH; a skipped trim is caught by this gate, not by the "
        "user:", file=sys.stderr)
    for c in uncovered:
        prefix = c["prefix"]
        anchor = f'find_p(ps, "{prefix}")' if prefix \
            else "(no unique prefix)"
        print(f"  UNCOVERED  {c['kind']:<10s} {anchor}", file=sys.stderr)
        print(f"      # {c['text'][:76]}", file=sys.stderr)
        if c["detail"]:
            print(f"      ({c['detail'][:76]})", file=sys.stderr)
    print(f"prune-coverage: {len(uncovered)} uncovered / {total} "
          "candidate(s) — fix the tailor script before running",
          file=sys.stderr)


def _prune_sidecar_for_script(docx_path, script_path):
    """Choose the JD-specific sidecar recorded by a tailor script."""
    jd_name = _script_jd_name(script_path)
    sidecar = prune_sidecar_path(docx_path, jd_name)
    if jd_name and not os.path.exists(sidecar):
        legacy = docx_path + PRUNE_SIDECAR_SUFFIX
        if os.path.exists(legacy):
            return legacy
    return sidecar


def lint_prune_coverage(docx_path, script_path):
    """Every PRUNE-PLAN candidate must be addressed by the tailor script.

    Companion to :func:`lint_script` (run_tailor.sh runs both before the
    strict exec). measure_resume.py --jd writes every cut candidate it
    printed to the ``<docx>.prune.json`` sidecar; this lint reads it and
    requires each candidate to be COVERED by the script — an edit anchor
    (find_p/drop/set_text literal on the same paragraph: a CUT or TRIM),
    an enclosing ``drop_role()`` (a whole-role DROP), or a recorded
    ``# kept: <JD reason>`` comment (a KEEP). A candidate with none is
    UNCOVERED and fails the run: every planned trim must be actually
    addressed, so 'the trims are in' is a checked claim, not an
    assertion.

    The sidecar must exist (run the prune plan first — SKILL Step 3) and
    every candidate anchor must still resolve against this docx: a master
    edit between the plan and this lint makes the sidecar stale (exit 2 —
    re-run the prune plan; the fold/user-edit flow re-runs it anyway).
    Returns 0 clean, 1 uncovered candidates, 2 usage/sidecar errors.
    """
    try:
        literals, keeps, dropped_roles = _script_cover_strings(script_path)
    except (OSError, SyntaxError) as e:
        print(f"error: {script_path}: {e}", file=sys.stderr)
        return 2
    sidecar = _prune_sidecar_for_script(docx_path, script_path)
    candidates, err = _prune_sidecar_candidates(sidecar)
    if err:
        print(err, file=sys.stderr)
        return 2
    if not candidates:
        print("prune-coverage: sidecar has no candidates — nothing to "
              "cover (the plan flagged nothing against this JD)")
        return 0
    _, body, _, _, _ = load(docx_path)
    stale = _prune_stale_prefixes(candidates, paras(body))
    if stale:
        print(f"prune-coverage: {len(stale)} sidecar candidate(s) no longer "
              "resolve against this docx — the sidecar is STALE (master "
              "edited since the plan). Re-run the prune plan: "
              "measure_resume.py <master> --jd <JD.txt>", file=sys.stderr)
        return 2
    uncovered, edits, drops, keeps_n = _prune_coverage_counts(
        candidates, literals, keeps, dropped_roles)
    if uncovered:
        _report_uncovered(uncovered, len(candidates))
        return 1
    print(f"prune-coverage: all {len(candidates)} PRUNE-PLAN candidate(s) "
          f"covered ({edits} edit(s), {drops} role-drop(s), " f"{keeps_n} recorded keep(s))")
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
    print("  --lint-prune S:  every <docx>.prune.json candidate (emitted by the PRUNE",
          file=sys.stderr)
    print("              PLAN) is addressed by S — an edit or a # kept: reason",
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
    if _wants_usage(argv):
        return _cli_usage()
    path = argv[1]
    args = argv[2:]
    if "--append-after" in args:
        return _cli_append_after(path, args)
    if "--set-text" in args:
        return _cli_set_text(path, args)
    if "--lint-script" in args:
        return lint_script(path, args[args.index("--lint-script") + 1])
    if "--lint-prune" in args:
        return lint_prune_coverage(path,
                                   args[args.index("--lint-prune") + 1])
    return _cli_inspect(path, args)


def _wants_usage(argv):
    """Whether argv cannot dispatch: no path, a help flag, or a lint flag
    missing its argument (these two index their argument directly; the
    append/set-text modes report their own usage errors)."""
    if len(argv) < 2 or argv[1] in ("--help", "-h"):
        return True
    args = argv[2:]
    return any(flag in args and args.index(flag) + 1 >= len(args)
               for flag in ("--lint-script", "--lint-prune"))


if __name__ == "__main__":
    sys.exit(cli(sys.argv))
