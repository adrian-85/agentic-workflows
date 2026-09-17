"""auto_prune — the MACHINE Phase 1 of the resume-tailoring workflow.

One command replaces the agent-driven prune pass end to end: it reads the
master + JD, machine-dispositions EVERY prune candidate (no agent keeps,
no overrides, no cut report), EMITS the first tailor script, and runs it
through run_tailor.sh's full gate chain (ast + find_p lint + prune-coverage
+ strict exec). The agent's work starts on the resulting lean base build
(SKILL Phase 2) — it never negotiates a cut, never sees a disposition
checklist, and never page/word-measures the master.

Machine disposition rules (deterministic, no judgment). Every disposition
is row/sentence/whole-category granular — the machine never edits words or
phrases inside a surviving sentence or a surviving list line; that kind of
wording change is Phase 2 agent work (SKILL Step 8), done only when the
agent is already touching the line to host something:
  - bullet-cut (unevidenced by the unified ask engine): CUT every one.
  - word-trim (kept bullet with dead sentences): drop whole sentences that
    carry no JD evidence, capped at WORD_CAP words by dropping more whole
    sentences (fewest-JD-hits first) — never rewrites words within a
    surviving sentence.
  - list-trim (proficiencies/Tools line): a line hosting ANY JD-evidenced
    chunk is KEPT WHOLE, unmodified; a line hosting NONE is CUT WHOLE —
    never a partial value list.
  - top-block (no-JD-evidence proficiencies/cert line): CUT. A section
    whose every line is cut is removed whole (drop_section) — an entire
    technical-proficiency category may go.
  - STUB RULE: a role left with zero bullets keeps its strongest bullet
    (header + 1 bullet) — whole roles are NEVER dropped, so the timeline
    stays gapless and the seniority gate sees every role.
  - PER-ROLE CAP: a role keeping more than PER_ROLE_CAP bullets loses the
    weakest ones (the docx_edit-level cap stays enforced downstream too).

usage:
    python3 scripts/auto_prune.py "<userName> Master Resume.docx" \
        jd_<target>.txt [--target "<Target Name>"]

Output (deliberately minimal — no cut report):
    WROTE scripts/tailor_<target>.py
    BUILD: <userName> Resume - <Target>.docx  (Phase 2 tailors this copy)

The agent should not read this file's plan internals — the SKILL contract
is: run the command, then work from the base build.
"""

import json
import os
import re
import subprocess
import sys
from typing import NamedTuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_edit as de  # noqa: E402
from docx_edit import (SECTION_STYLE, paras, shortest_unique_prefix,  # noqa: E402
                       text_of, prune_sidecar_path)
from measure_resume_drops import _sentence_clauses, _weakness_key, \
    prune_candidates  # noqa: E402
from measure_resume_format import (BULLET_STYLES, COMPANY_STYLE,
                                   SECTION_PROFICIENCIES, _roles)
import jd_asks  # noqa: E402
import jd_sections  # noqa: E402
import workflow_gate  # noqa: E402
from script_args import (extract_flag, extract_flag_all, maybe_help,  # noqa: E402
                         read_jd_text)

WORD_CAP = 40      # a trimmed bullet carries at most this many words
PER_ROLE_CAP = 8   # hard per-role kept-bullet cap (SKILL Step 8)

USAGE = """usage: auto_prune.py "<userName> Master Resume.docx" \\
        jd_<target>.txt [--target "<Target Name>"] \\
        [--theme "<company-focus JD theme brief>"] \\
        [--equivalence "<term>=<alt1>[,<alt2>...]"]

Machine Phase 1: machine-prunes the master against the JD, emits
scripts/tailor_<target>.py, and runs it through run_tailor.sh's gates.
--target names the deliverable (default: derived from the JD filename).
--theme records the agent's characterization of the whole JD — company
focus, differentiator, role mission/outcomes, and the capability
connection — in the emitted script's docstring for provenance only. It is
NON-OPERATIVE: the machine prune ignores it; Theme Review A is the required
post-prune judgment gate (SKILL Step 3).
--equivalence (repeatable) adds a JD-specific terminology equivalence —
e.g. --equivalence "IV&V=testing,quality validation" — extending the
ONE ask/evidence matcher for this run only: a master bullet evidencing
an alternative phrase protects the JD's term. Never a second filter.
"""


# --------------------------------------------------------------------- #
# Anchors
# --------------------------------------------------------------------- #
def _anchor_for(all_texts, text):
    """(prefix, nth) anchor for one paragraph text.

    prefix is the shortest-unique find_p prefix (drop()-ready); when the
    text has no unique prefix (exact duplicates), the cut is emitted as
    ``find_p(ps, "<text[:40]>", nth=1)`` once per occurrence — each
    remove() takes the first remaining match, so sequential calls
    remove the duplicates in document order. Returns (prefix_or_None,
    nth).
    """
    try:
        prefix = shortest_unique_prefix(all_texts, all_texts.index(text),
                                        min_len=6)
    except ValueError:
        prefix = None
    if prefix is not None:
        return prefix, None
    return None, 1


# --------------------------------------------------------------------- #
# Machine dispositions
# --------------------------------------------------------------------- #
def _strength(text, jd_terms):
    """Stub-strength: the engine's ask-evidence count first, then the
    tool's weakness rank."""
    return (len(jd_asks.evidence_set(text.lower(), jd_terms)),
            _weakness_key(text))


def _trim_bullet_text(text, jd_terms):
    """The bullet rewritten without dead SENTENCES, capped at WORD_CAP.

    Row/sentence granular only — never rewrites words or phrases within a
    surviving sentence (that is Phase 2 agent work, SKILL Step 8). A
    sentence survives when it carries a JD term or a practice-phrase
    concept; survivors over the word cap are dropped whole (fewest-JD-hits
    first, ties: longest first — removes the most words). Never returns a
    kept bullet with zero sentences (a kept bullet always has one
    JD-evidence or concept sentence); returns None when nothing survives
    (caller cuts the bullet instead); returns the text UNCHANGED when no
    sentence needs dropping — a lone surviving sentence is kept however
    long, so an over-cap residual can reach validate_resume and Phase 2
    (the caller records that as a whole-bullet keep, not an edit).
    """
    keep = [s for s in _sentence_clauses(text)
            if jd_asks.evidence_set(s.lower(), jd_terms)]
    if not keep:
        return None

    def _words(sents):
        return len(" ".join(sents).split())

    while _words(keep) > WORD_CAP and len(keep) > 1:
        victim = min(range(len(keep)),
                     key=lambda i: (-len(jd_asks.evidence_set(
                         keep[i].lower(), jd_terms)), -len(keep[i])))
        keep.pop(victim)
    return " ".join(keep)


def _hosts_jd_chunk(text, jd_terms):
    """Whether any comma/semicolon chunk of a list line hosts a JD term
    or concept — the whole-line disposition signal: True keeps the line
    AS-IS (never a partial value list); False cuts the line whole."""
    if ":" not in text:
        return False
    value = text.split(":", 1)[1]
    return any(
        c and jd_asks.evidence_set(c.lower(), jd_terms)
        for c in (chunk.strip().rstrip(".,;:!?'\"")
                  for chunk in re.split(r"[,;]", value)))


def _top_sections(body):
    """(heading_text, [non-blank content texts]) per SectionHeading
    section from Technical Proficiencies to the career region — the
    whole-category cut scope (a section whose every line is cut goes
    entirely)."""
    out = []
    heading, contents = None, []
    started = False
    for p in paras(body):
        style, _ = de.style_and_numid(p)
        t = text_of(p)
        if style == SECTION_STYLE:
            if started and heading is not None:
                out.append((heading, contents))
            heading, contents = (t.strip(), []) if t.strip() else (None, [])
            started = started or t.strip() == SECTION_PROFICIENCIES
            continue
        if not started:
            continue
        if style == COMPANY_STYLE and t.strip():
            break  # career region begins
        if heading is not None and t.strip():
            contents.append(t.strip())
    if started and heading is not None:
        out.append((heading, contents))
    return out


def _role_cuts(candidates, roles, jd_terms):
    """Per-role machine dispositions.

    Returns a _RoleState: the bullet-cut text set per role (stub keeps
    removed), the stub texts, the per-role cap excess texts, and the
    cap excess (role key, text) pairs.
    """
    cut_texts_by_role = {}
    for c in candidates:
        if c["kind"] == "bullet-cut":
            cut_texts_by_role.setdefault(c["role"], set()).add(c["text"])

    # --- stub rule: a role losing EVERY bullet keeps its strongest ---- #
    stub_texts = {}  # role key -> stub bullet text
    for role in roles:
        bullets = role.get("bullet_texts") or []
        if not bullets:
            continue
        cuts = cut_texts_by_role.get(role["key"], set())
        if all(b in cuts for b in bullets):
            stub = max(bullets, key=lambda b: _strength(b, jd_terms))
            stub_texts[role["key"]] = stub
            cut_texts_by_role[role["key"]] -= {stub}

    # --- per-role cap on the SURVIVING kept bullets ------------------- #
    cap_drops = []  # (role key, text)
    for role in roles:
        cuts = cut_texts_by_role.get(role["key"], set())
        kept = [b for b in (role.get("bullet_texts") or []) if b not in cuts]
        if len(kept) > PER_ROLE_CAP:
            excess = sorted(kept, key=_weakness_key)[:len(kept) - PER_ROLE_CAP]
            cap_drops.extend((role["key"], t) for t in excess)
    cap_texts = {t for _r, t in cap_drops}
    return _RoleState(cut_texts_by_role, stub_texts, cap_texts, cap_drops)


class _RoleState(NamedTuple):
    """Per-role dispositions shared by the walk and the cap pass."""

    cut_texts: dict  # role key -> set of bullet texts to cut
    stubs: dict      # role key -> stub bullet text (kept for gaplessness)
    cap_texts: set   # texts dropped only by the per-role cap
    cap_drops: list  # (role key, text) excess pairs


def _disposition(c, anchors, role_state, jd_terms):
    """(action, payload) for one candidate.

    Actions: 'cut', 'keep' ((anchor_head, reason) — the stub rule, an
    already-in-cap fully-evidenced bullet, or a list line hosting JD
    evidence kept whole), and 'trim' (((prefix, text), new_text) — a
    whole dead SENTENCE removed, never a sub-sentence word/phrase
    edit)."""
    kind, role, text = c["kind"], c["role"], c["text"]
    prefix, _nth = anchors[text]
    if kind == "bullet-cut" and \
            text not in role_state.cut_texts.get(role, set()):
        return "keep", (prefix if prefix else text[:24],
                        "stub: role keeps its strongest bullet "
                        "(timeline gaplessness; auto-prune)")
    payload = None
    if kind == "word-trim":
        trimmed = None
        if text not in role_state.cut_texts.get(role, set()) and \
                text not in role_state.cap_texts:
            trimmed = _trim_bullet_text(text, jd_terms)
        if trimmed is not None and trimmed != text:
            payload = "trim", ((prefix, text), trimmed)
        elif trimmed == text:
            return "keep", (prefix if prefix else text[:24],
                            "bullet kept whole — every sentence carries "
                            "JD evidence (auto-prune; nothing to cut)")
    elif kind == "list-trim":
        if _hosts_jd_chunk(text, jd_terms):
            return "keep", (prefix if prefix else text[:24],
                            "list line kept whole — hosts at least one "
                            "JD-evidenced item (auto-prune; never a "
                            "partial value list)")
    if payload is None:
        # bullet-cut, a trim that cut whole, a list line with no JD chunk,
        # and top-block all collapse to CUT — the drop covers the candidate
        return "cut", None
    return payload


def _walk_candidates(candidates, anchors, role_state, jd_terms):
    """Disposition every candidate into emitted edits.

    Returns the plan's edit lists (drops, removes, keeps, trims, and
    empty section lists) as a dict.
    """
    edits = {"drops": [], "removes": [], "keeps": [], "trims": [],
             "section_drops": [], "section_keeps": []}
    drops, removes = edits["drops"], edits["removes"]
    drop_keys = set()

    def _add_cut(c):
        """Emit one cut: a drop()-list entry, or an nth=1 remove() when
        the text has no unique prefix (exact duplicates — sequential
        nth=1 removes take one occurrence each)."""
        prefix, _nth = anchors[c["text"]]
        if prefix is not None:
            key = (prefix, c["text"])
            if key not in drop_keys:
                drop_keys.add(key)
                drops.append((prefix, c["text"]))
        else:
            removes.append((c["text"], 1))

    for c in candidates:
        action, payload = _disposition(c, anchors, role_state, jd_terms)
        if action == "cut":
            _add_cut(c)
        elif action == "keep":
            edits["keeps"].append(payload)
        elif action == "trim":
            edits["trims"].append(payload)
    return edits


def _add_cap_drops(cap_drops, anchors, all_texts, edits):
    """Add the per-role cap excess (candidate and non-candidate bullets)
    to the plan's cut lists."""
    drop_keys = set(edits["drops"])
    for _role_key, text in cap_drops:
        prefix, nth = anchors.get(text) or _anchor_for(all_texts, text)
        if prefix is not None:
            if (prefix, text) not in drop_keys:
                drop_keys.add((prefix, text))
                edits["drops"].append((prefix, text))
        elif not any(t == text and n == nth for t, n in edits["removes"]):
            edits["removes"].append((text, nth))


def _apply_section_cuts(body, all_texts, edits):
    """Whole-category cuts: a top section whose EVERY line is cut goes
    whole (drop_section); its line cuts move into keep comments so the
    coverage gate still sees them addressed. Mutates ``edits``."""
    drops, removes = edits["drops"], edits["removes"]
    cut_line_texts = {t for _p, t in drops} | {t for t, _n in removes}
    for heading, contents in _top_sections(body):
        if not contents or not all(t in cut_line_texts for t in contents):
            continue
        hprefix, _hn = _anchor_for(all_texts, heading)
        if hprefix is None:
            continue  # duplicate heading text: leave the line cuts as-is
        edits["section_drops"].append((hprefix, heading))
        for t in contents:
            p2, _n2 = _anchor_for(all_texts, t)
            if p2:
                drops[:] = [d for d in drops if d[0] != p2]
            else:
                removes[:] = [r for r in removes if r[0] != t]
            edits["section_keeps"].append(
                (p2 if p2 else t[:24],
                 f"removed with the emptied '{heading}' section "
                 f"(drop_section; auto-prune)"))


def _anchor_map(candidates, all_texts):
    """candidate text -> (prefix, nth), computed once per distinct text."""
    anchors = {}
    for c in candidates:
        if c["text"] not in anchors:
            anchors[c["text"]] = _anchor_for(all_texts, c["text"])
    return anchors


def plan_phase_a(candidates, roles, jd_terms, body):
    """Machine-disposition every candidate; return the emitted-edit plan.

    Returns a dict:
      drops        [(prefix, text)]       — drop()-list entries
      removes      [(text, nth)]          — nth-disambiguated cuts
      keeps        [(anchor_head, why)]   — '# kept:' comment lines
      trims        [(anchor, new_text)]   — set_text rewrites (whole dead
                                             sentences dropped; never a
                                             sub-sentence word/phrase edit)
      section_drops [(heading_prefix, heading)] — drop_section calls
      stats        {cut, trim, stub, section}
    """
    all_texts = [text_of(p) for p in paras(body)]
    anchors = _anchor_map(candidates, all_texts)
    role_state = _role_cuts(candidates, roles, jd_terms)
    edits = _walk_candidates(candidates, anchors, role_state, jd_terms)
    _add_cap_drops(role_state.cap_drops, anchors, all_texts, edits)
    _apply_section_cuts(body, all_texts, edits)
    edits["stats"] = {
        "cut": len(edits["drops"]) + len(edits["removes"]),
        "trim": len(edits["trims"]),
        "stub": len(role_state.stubs),
        "section": len(edits["section_drops"])}
    return edits


# --------------------------------------------------------------------- #
# Script emission
# --------------------------------------------------------------------- #
# The emitted script imports exactly what the machine emits — no more.
# Phase 2 extensions add their own imports as they author edits
# (set_labeled, drop_role, merge_into, ...); the full authoring-time
# superset lives in the tailor_resume.py template.
_EMITTED_IMPORTS = (
    "import shutil\n"
    "\n"
    "from docx_edit import (\n"
    "    DriftMeta, drop, drop_section, find_p, load, paras, remove,\n"
    "    remove_empty, save, set_text,\n"
    ")\n"
)


def _py(s):
    """A double-quoted Python string literal for one emitted line."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_script(plan, src, dst, meta):
    # too-many-locals: the function is one linear list-literal build of the
    # emitted script (docstring, cuts, trims, sections); splitting it would
    # interleave the emission order across helpers for no gain.
    # pylint: disable=too-many-locals
    """The first tailor script: machine cuts/trims + gate comments.

    ``meta`` carries the docstring fields: target, jd_name, script_name.
    """
    stats = plan["stats"]
    lines = [
        f'"""Auto-pruned base build for {meta["target"]} — machine '
        f'Phase 1 (auto_prune.py).',
        "",
        f"JD: {meta['jd_name']}. Every PRUNE-PLAN candidate is addressed "
        f"here by the machine:",
        f"CUT {stats['cut']}, TRIM {stats['trim']}, stubs {stats['stub']}, "
        f"emptied sections {stats['section']}.",
    ]
    if meta.get("theme"):
        lines += [f"JD theme: {meta['theme']}"]
    lines += [
        "No agent judgment and no cut report — the agent's work starts at "
        "SKILL Phase 2",
        "on this build. Re-run:",
        "",
        f'    cd "$(dirname "$0")/.." && python3 '
        f'scripts/{meta["script_name"]}',
        "",
        f'Gates after Theme Review B: RESUME_WORKFLOW_STATE='
        f'"{meta.get("state_name", dst + ".workflow.json")}" '
        f'scripts/run_tailor.sh "{src}" scripts/{meta["script_name"]}',
        '"""',
        "",
        _EMITTED_IMPORTS,
        f"SRC = {_py(src)}",
        f"DST = {_py(dst)}",
        "",
        "",
        "def main():",
        '    """Apply the machine prune and save the base build."""',
        "    shutil.copy(SRC, DST)",
        "    root, body, names, data, _ = load(DST)",
        "    ps = paras(body)",
        "",
        "    # ---- Phase 1 cuts (machine dispositions) ---------------- #",
    ]
    if plan["drops"]:
        lines.append("    ps = drop(body, [")
        for prefix, _text in plan["drops"]:
            lines.append(f"        {_py(prefix)},")
        lines.append("    ])")
    for text, nth in plan["removes"]:
        lines.append(f"    remove(body, find_p(ps, {_py(text[:40])}, "
                     f"nth={nth}))")
    for head, why in plan["keeps"]:
        lines.append(f"    # kept: {head} — {why}")
    if plan["trims"]:
        lines.append("")
        lines.append("    # ---- sentence trims (dead sentences dropped "
                     f"whole, {WORD_CAP}-word cap) ----- #")
    for (prefix, _text), new in plan["trims"]:
        lines.append(f"    set_text(find_p(ps, {_py(prefix)}), {_py(new)})")
    if plan["section_drops"]:
        lines.append("")
        lines.append("    # ---- whole-category cuts (emptied sections) "
                     "--------------------- #")
        for hprefix, _heading in plan["section_drops"]:
            lines.append(f"    drop_section(body, {_py(hprefix)})")
        for head, why in plan["section_keeps"]:
            lines.append(f"    # kept: {head} — {why}")
    lines += [
        "",
        "    remove_empty(body)",
        "",
        "    save(DST, root, names, data, drift=DriftMeta(src=SRC))",
        '    print("WROTE", DST)',
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #
def _parse_args(argv):
    maybe_help(argv, USAGE)
    rest = list(argv)
    theme = extract_flag(rest, "--theme")
    equivalences = extract_flag_all(rest, "--equivalence")
    target = None
    if "--target" in rest:
        i = rest.index("--target")
        if i + 1 >= len(rest):
            print("error: --target needs a value", file=sys.stderr)
            sys.exit(2)
        target = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if len(rest) != 2:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    docx, jd_file = rest
    if not docx.endswith("Master Resume.docx"):
        print("error: auto_prune runs on the MASTER only "
              f"(got {docx!r}); the tailored copy is its OUTPUT",
              file=sys.stderr)
        sys.exit(2)
    if not os.path.exists(docx):
        print(f"error: master not found: {docx}", file=sys.stderr)
        sys.exit(2)
    if not os.path.exists(jd_file):
        print(f"error: JD file not found: {jd_file}", file=sys.stderr)
        sys.exit(2)
    if target is None:
        stem = re.sub(r"^jd_", "", os.path.splitext(
            os.path.basename(jd_file))[0])
        target = stem.replace("_", " ").strip().title()
    return docx, jd_file, target, theme, equivalences


def validate_jd_contract(jd_text):
    """Enforce the fixed JD section contract (SKILL Step 1, no fallback):
    every one of the eight canonical headers present — blank body when
    the posting omits that content. Returns the sections dict or exits 2
    naming exactly what is missing, so a mis-pasted JD fails at the
    pipeline's entry instead of silently mis-collecting asks."""
    try:
        sections = jd_sections.parse_sections(jd_text)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    if sections is None:
        print("error: the JD file carries none of the canonical section "
              "headers — re-save it in the 8-section template (SKILL "
              "Step 1): " + ", ".join(jd_sections.SECTION_HEADERS),
              file=sys.stderr)
        sys.exit(2)
    return sections


def apply_equivalences(equivalences):
    """Populate jd_asks.EXTRA_EVIDENCE_FAMILIES from --equivalence
    "term=alt1,alt2" strings — a per-run extension of the one ask/evidence
    matcher (see EXTRA_EVIDENCE_FAMILIES). Exits 2 on malformed input."""
    for item in equivalences:
        if "=" not in item:
            print(f"error: --equivalence {item!r} needs the form "
                  "\"<term>=<alt1>[,<alt2>...]\"", file=sys.stderr)
            sys.exit(2)
        term, alts = item.split("=", 1)
        term = term.strip().lower()
        forms = tuple(a.strip().lower() for a in alts.split(",") if a.strip())
        if not term or not forms:
            print(f"error: --equivalence {item!r} needs a term and at "
                  "least one alternative", file=sys.stderr)
            sys.exit(2)
        jd_asks.EXTRA_EVIDENCE_FAMILIES[term] = (term,) + forms


def _emit_and_run(plan, meta):
    """Write the prune sidecar, emit the tailor script, run the gates.

    ``meta`` carries docx, jd_file, dst, skill_root, and the emitted
    docstring fields. Exits with the gate's return code when
    run_tailor.sh fails.
    """
    docx, skill_root = meta["docx"], meta["skill_root"]
    script_name = meta["script_name"]
    sidecar = prune_sidecar_path(docx, meta["jd_file"])
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump({"jd": os.path.basename(meta["jd_file"]),
                   "candidates": plan["candidates"]}, f, indent=1)
    script_path = os.path.join(skill_root, "scripts", script_name)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(emit_script(plan, os.path.basename(docx), meta["dst"],
                            meta))
    runner = os.path.join(skill_root, "scripts", "run_tailor.sh")
    proc = subprocess.run(["bash", runner, os.path.basename(docx),
                           f"scripts/{script_name}"],
                          cwd=skill_root, check=False,
                          env={**os.environ, "RESUME_TAILOR_PHASE": "prune"})
    if proc.returncode != 0:
        print(f"error: run_tailor.sh gates failed (exit {proc.returncode})",
              file=sys.stderr)
        sys.exit(proc.returncode)
    state_path = os.path.join(skill_root, meta["state_name"])
    workflow_gate.create_state(
        state_path, meta["target"], os.path.basename(meta["jd_file"]),
        meta.get("theme", ""))
    print(f"WORKFLOW STATE: {meta['state_name']} (phase: pruned)")


def _build_meta(docx, jd_file, target, skill_root):
    """(dst, meta): the deliverable name and the emit/run bundle."""
    user = re.sub(r"\s*Master Resume\.docx$", "",
                  os.path.basename(docx))
    dst = f"{user} Resume - {target}.docx"
    meta = {"target": target, "jd_name": os.path.basename(jd_file),
            "jd_file": jd_file, "docx": docx, "dst": dst,
            "skill_root": skill_root, "state_name": dst + ".workflow.json"}
    meta["script_name"] = "tailor_" + re.sub(
        r"[^a-z0-9]+", "_", target.lower()).strip("_") + ".py"
    return dst, meta


def _intro_candidates(body, _roles, _jd_terms, all_texts):
    """Word-trim candidates for over-cap role-INTRO prose paragraphs.

    A paragraph under a company header that is neither a numbered bullet
    nor a Tools line is role intro text — an editable prose paragraph the
    40-word cap governs (validate_resume blocks the build otherwise), so
    the machine dispositions it exactly like a kept bullet: trim to JD-
    evidenced sentences, capped at WORD_CAP. Under-cap intros are never
    candidates. ``_roles``/``_jd_terms`` are unused here — role ownership
    is tracked from the body's own company headers as we walk it, and
    every over-cap intro is a candidate regardless of JD terms (the
    JD-evidenced trim itself happens downstream in ``_trim_bullet_text``)
    — kept for signature symmetry with the other candidate-scanning
    functions.
    """
    out = []
    cur = None
    for p in de.paras(body):
        style, num_id = de.style_and_numid(p)
        txt = de.text_of(p).strip()
        if style == COMPANY_STYLE and txt:
            cur = txt
            continue
        if cur is None or not txt:
            continue
        is_bullet = (num_id is not None and num_id != "0") or \
            style in BULLET_STYLES
        if is_bullet or (txt.lower().startswith("tool") and
                         "technolog" in txt.lower()):
            continue
        if len(txt.split()) <= WORD_CAP:
            continue
        try:
            prefix = de.shortest_unique_prefix(all_texts,
                                               all_texts.index(de.text_of(p)),
                                               min_len=6)
        except ValueError:
            prefix = None
        out.append({"kind": "word-trim", "role": cur, "prefix": prefix,
                    "text": de.text_of(p),
                    "detail": "over-cap intro prose (>40 words)"})
    return out


def _load_candidates(docx, jd_text):
    """(body, roles, jd_terms, candidates) for a master + JD; exits 2
    when the JD has no intersection with the resume's vocabulary or
    yields no prune candidates (nothing to machine-prune)."""
    _, body, _, _, _ = de.load(docx)
    roles = _roles(body)
    jd_terms = {a.phrase for a in jd_asks.parse_asks(jd_text)}
    if not jd_terms:
        print("error: no JD asks were extracted — check the JD file is the "
              "raw posting text", file=sys.stderr)
        sys.exit(2)
    candidates = prune_candidates(roles, jd_terms, body, protect=())
    texts = [de.text_of(p) for p in de.paras(body)]
    candidates.extend(_intro_candidates(body, roles, jd_terms, texts))
    if not candidates:
        print("error: no prune candidates — the JD matches everything in "
              "the master; nothing to machine-prune", file=sys.stderr)
        sys.exit(2)
    return body, roles, jd_terms, candidates


def main():
    """CLI entry: machine-prune, emit the tailor script, run the gates."""
    docx, jd_file, target, theme, equivalences = _parse_args(sys.argv[1:])
    skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    jd_text = read_jd_text(jd_file)
    validate_jd_contract(jd_text)
    apply_equivalences(equivalences)
    dst, meta = _build_meta(docx, jd_file, target, skill_root)
    if theme:
        meta["theme"] = theme
    body, roles, jd_terms, candidates = _load_candidates(docx, jd_text)
    plan = plan_phase_a(candidates, roles, jd_terms, body)
    plan["candidates"] = candidates
    _emit_and_run(plan, meta)
    stats = plan["stats"]
    print(f"AUTO-PRUNE: {stats['cut']} cut, {stats['trim']} trimmed, "
          f"{stats['stub']} stub(s), {stats['section']} section(s) "
          f"emptied — no cut report (SKILL Phase 1)")
    print(f"WROTE scripts/{meta['script_name']}")
    print(f"BUILD: {dst} — Phase 2 tailors this copy (never the master)")


if __name__ == "__main__":
    main()
