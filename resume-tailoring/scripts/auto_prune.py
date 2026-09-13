"""auto_prune — the MACHINE Phase A of the resume-tailoring workflow.

One command replaces the agent-driven prune pass end to end: it reads the
master + JD, machine-dispositions EVERY prune candidate (no agent keeps,
no overrides, no cut report), EMITS the first tailor script, and runs it
through run_tailor.sh's full gate chain (ast + find_p lint + prune-coverage
+ strict exec). The agent's work starts on the resulting lean base build
(SKILL Phase B) — it never negotiates a cut, never sees a disposition
checklist, and never page/word-measures the master.

Machine disposition rules (deterministic, no judgment):
  - bullet-cut (OFF-JD / weak-match): CUT every one.
  - word-trim (kept bullet with dead sentences): rewrite the bullet
    without the dead sentences, capped at WORD_CAP words.
  - list-trim (proficiencies/Tools line): strip the non-JD chunks; a line
    with NO surviving chunk is cut whole.
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
    BUILD: <userName> Resume - <Target>.docx  (Phase B measures this copy)

The agent should not read this file's plan internals — the SKILL contract
is: run the command, then work from the base build.
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_edit as de  # noqa: E402
from docx_edit import (SECTION_STYLE, drop_section, find_p, paras, remove,  # noqa: E402
                       set_labeled, set_text, shortest_unique_prefix,
                       text_of)
from measure_resume_drops import _sentence_clauses, _weakness_key, \
    prune_candidates  # noqa: E402
from measure_resume_format import (COMPANY_STYLE, SECTION_PROFICIENCIES,  # noqa: E402
                                   _roles)
from measure_resume_jd_terms import _concept_hits, _jd_hits, _jd_terms  # noqa: E402
from script_args import maybe_help, read_jd_text  # noqa: E402

WORD_CAP = 40      # a trimmed bullet carries at most this many words
PER_ROLE_CAP = 8   # hard per-role kept-bullet cap (SKILL Step 8)

USAGE = """usage: auto_prune.py "<userName> Master Resume.docx" jd_<target>.txt \\
        [--target "<Target Name>"]

Machine Phase A: machine-prunes the master against the JD, emits
scripts/tailor_<target>.py, and runs it through run_tailor.sh's gates.
--target names the deliverable (default: derived from the JD filename).
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
    """Stub-strength: JD evidence first, then the tool's weakness rank."""
    return (len(_jd_hits(text, jd_terms)), _weakness_key(text))


def _trim_bullet_text(text, jd_terms):
    """The bullet rewritten without dead sentences, capped at WORD_CAP.

    A sentence survives when it carries a JD term or a practice-phrase
    concept; survivors over the word cap are dropped fewest-JD-hits
    first (ties: longest first — removes the most words). Never returns
    a kept bullet with zero sentences (a kept bullet always has one
    JD-evidence or concept sentence); returns None when nothing
    survives (caller cuts the bullet instead).
    """
    keep = [s for s in _sentence_clauses(text)
            if _jd_hits(s, jd_terms) or _concept_hits(s)]
    if not keep:
        return None

    def _words(sents):
        return len(" ".join(sents).split())

    while _words(keep) > WORD_CAP and len(keep) > 1:
        victim = min(range(len(keep)),
                     key=lambda i: (len(_jd_hits(keep[i], jd_terms)),
                                    -len(keep[i])))
        keep.pop(victim)
    return " ".join(keep)


def _surviving_chunks(text, jd_terms):
    """Comma/semicolon chunks of a list line that a JD term or concept
    names — the set-labeled value. Empty → the whole line is cut."""
    if ":" not in text:
        return []
    value = text.split(":", 1)[1]
    out = []
    for chunk in re.split(r"[,;]", value):
        c = chunk.strip().rstrip(".,;:!?'\"")
        if c and (_jd_hits(c, jd_terms) or _concept_hits(c)):
            out.append(c)
    return out


def _top_sections(body):
    """(heading_text, [non-blank content texts]) per SectionHeading
    section from Technical Proficiencies to the career region — the
    whole-category cut scope (a section whose every line is cut goes
    entirely)."""
    out = []
    cur = None
    started = False
    for p in paras(body):
        style, _ = de.style_and_numid(p)
        t = text_of(p)
        if style == SECTION_STYLE:
            if started and cur:
                out.append(cur)
            cur = (t.strip(), []) if t.strip() else None
            started = started or t.strip() == SECTION_PROFICIENCIES
            continue
        if not started:
            continue
        if style == COMPANY_STYLE and t.strip():
            break  # career region begins
        if cur is not None and t.strip():
            cur[1].append(t.strip())
    if started and cur:
        out.append(cur)
    return out


def plan_phase_a(candidates, roles, jd_terms, body):
    """Machine-disposition every candidate; return the emitted-edit plan.

    Returns a dict:
      drops        [(prefix, text)]       — drop()-list entries
      removes      [(text, nth)]          — nth-disambiguated cuts
      keeps        [(anchor_head, why)]   — '# kept:' comment lines
      trims        [(anchor, new_text)]   — set_text rewrites
      list_trims   [(anchor, label, value)]
      section_drops [heading_prefix]      — drop_section calls
      stats        {cut, trim, stub, section}
    """
    all_texts = [text_of(p) for p in paras(body)]
    anchors = {}  # candidate text -> (prefix, nth), computed once
    for c in candidates:
        if c["text"] not in anchors:
            anchors[c["text"]] = _anchor_for(all_texts, c["text"])

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
        if bullets and all(b in cuts for b in bullets):
            stub = max(bullets, key=lambda b: _strength(b, jd_terms))
            stub_texts[role["key"]] = stub
            cut_texts_by_role[role["key"]] -= {stub}

    # --- per-role cap on the SURVIVING kept bullets ------------------- #
    cap_drops = []  # (role key, text)
    kept_by_role = {}
    for role in roles:
        cuts = cut_texts_by_role.get(role["key"], set())
        kept = [b for b in (role.get("bullet_texts") or []) if b not in cuts]
        kept_by_role[role["key"]] = kept
        if len(kept) > PER_ROLE_CAP:
            excess = sorted(kept, key=_weakness_key)[:len(kept) - PER_ROLE_CAP]
            cap_drops.extend((role["key"], t) for t in excess)
    cap_texts = {t for _r, t in cap_drops}

    # --- walk candidates ---------------------------------------------- #
    drops, removes, keeps, trims, list_trims = [], [], [], [], []
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
        kind, role, text = c["kind"], c["role"], c["text"]
        prefix, _nth = anchors[text]
        anchor_head = prefix if prefix else text[:24]
        if kind == "bullet-cut":
            if text not in cut_texts_by_role.get(role, set()):
                keeps.append((anchor_head,
                              "stub: role keeps its strongest bullet "
                              "(timeline gaplessness; auto-prune)"))
                continue
            _add_cut(c)
        elif kind == "word-trim":
            if text in cut_texts_by_role.get(role, set()) or \
                    text in cap_texts:
                _add_cut(c)  # cut here; the drop covers the candidate
                continue
            new = _trim_bullet_text(text, jd_terms)
            if new is None:
                _add_cut(c)
                continue
            trims.append(((prefix, text), new))
        elif kind == "list-trim":
            keep = _surviving_chunks(text, jd_terms)
            if not keep:
                _add_cut(c)
                continue
            label = text.split(":", 1)[0] + ": "
            list_trims.append(((prefix, text), label, ", ".join(keep)))
        elif kind == "top-block":
            _add_cut(c)

    # --- cap drops (non-candidate bullets included) -------------------- #
    for _role_key, text in cap_drops:
        prefix, nth = anchors.get(text) or _anchor_for(all_texts, text)
        if prefix is not None:
            if (prefix, text) not in drop_keys:
                drop_keys.add((prefix, text))
                drops.append((prefix, text))
        elif not any(t == text and n == nth for t, n in removes):
            removes.append((text, nth))

    # --- whole-category cuts: a section whose every line is cut -------- #
    section_drops, section_keeps = [], []
    cut_line_texts = {t for _p, t in drops} | {t for t, _n in removes}
    for heading, contents in _top_sections(body):
        if not contents or not all(t in cut_line_texts for t in contents):
            continue
        hprefix, _hn = _anchor_for(all_texts, heading)
        if hprefix is None:
            continue  # duplicate heading text: leave the line cuts as-is
        section_drops.append((hprefix, heading))
        # the line cuts move into the section drop — emit keep comments
        # so the coverage gate sees them addressed
        for t in contents:
            p2, _n2 = _anchor_for(all_texts, t)
            if p2:
                drops = [d for d in drops if d[0] != p2]
                drop_keys -= {(p2, t)}
            else:
                removes = [r for r in removes if r[0] != t]
            section_keeps.append((p2 if p2 else t[:24],
                                  f"removed with the emptied "
                                  f"'{heading}' section "
                                  f"(drop_section; auto-prune)"))
    return {"drops": drops, "removes": removes, "keeps": keeps,
            "trims": trims, "list_trims": list_trims,
            "section_drops": section_drops,
            "section_keeps": section_keeps,
            "stats": {"cut": len(drops) + len(removes),
                      "trim": len(trims) + len(list_trims),
                      "stub": len(stub_texts),
                      "section": len(section_drops)}}


# --------------------------------------------------------------------- #
# Script emission
# --------------------------------------------------------------------- #
_EMITTED_IMPORTS = (
    "import shutil\n"
    "\n"
    "from docx_edit import (\n"
    "    DriftMeta, drop, drop_section, find_p, load, paras, remove,\n"
    "    remove_empty, save, set_labeled, set_text,\n"
    ")\n"
)


def _py(s):
    """A double-quoted Python string literal for one emitted line."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_script(plan, src, dst, target, jd_name, script_name):
    """The first tailor script: machine cuts/trims + gate comments."""
    stats = plan["stats"]
    lines = [
        f'"""Auto-pruned base build for {target} — machine Phase A '
        f'(auto_prune.py).',
        "",
        f"JD: {jd_name}. Every PRUNE-PLAN candidate is addressed here by "
        f"the machine:",
        f"CUT {stats['cut']}, TRIM {stats['trim']}, stubs {stats['stub']}, "
        f"emptied sections {stats['section']}.",
        "No agent judgment and no cut report — the agent's work starts at "
        "SKILL Phase B",
        "on this build. Re-run:",
        "",
        f'    cd "$(dirname "$0")/.." && python3 scripts/{script_name}',
        "",
        f'Gates: scripts/run_tailor.sh "{src}" scripts/{script_name}',
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
        "    # ---- Phase A cuts (machine dispositions) ----------------- #",
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
    if plan["trims"] or plan["list_trims"]:
        lines.append("")
        lines.append("    # ---- word trims (dead sentences out, "
                     f"{WORD_CAP}-word cap) ----- #")
    for (prefix, _text), new in plan["trims"]:
        lines.append(f"    set_text(find_p(ps, {_py(prefix)}), {_py(new)})")
    if plan["list_trims"]:
        lines.append("")
        lines.append("    # ---- list trims (non-JD chunks stripped) "
                     "--------------------- #")
    for (prefix, _text), label, value in plan["list_trims"]:
        lines.append(f"    set_labeled(find_p(ps, {_py(prefix)}), "
                     f"{_py(label)}, {_py(value)})")
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
    return docx, jd_file, target


def main():
    """CLI entry: machine-prune, emit the tailor script, run the gates."""
    docx, jd_file, target = _parse_args(sys.argv[1:])
    skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    jd_text = read_jd_text(jd_file)
    user = re.sub(r"\s*Master Resume\.docx$", "",
                  os.path.basename(docx))
    dst = f"{user} Resume - {target}.docx"
    slug = re.sub(r"[^a-z0-9]+", "_", target.lower()).strip("_")
    script_name = f"tailor_{slug}.py"

    _, body, _, _, _ = de.load(docx)
    roles = _roles(body)
    jd_terms = _jd_terms(jd_text, body)
    if not jd_terms:
        print("error: no candidate-tech terms intersect the resume's "
              "vocabulary — check the JD file is the raw posting text",
              file=sys.stderr)
        sys.exit(2)
    candidates = prune_candidates(roles, jd_terms, body, protect=())
    if not candidates:
        print("error: no prune candidates — the JD matches everything in "
              "the master; nothing to machine-prune", file=sys.stderr)
        sys.exit(2)

    plan = plan_phase_a(candidates, roles, jd_terms, body)

    sidecar = docx + ".prune.json"
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump({"jd": os.path.basename(jd_file),
                   "candidates": candidates}, f, indent=1)

    script_path = os.path.join(skill_root, "scripts", script_name)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(emit_script(plan, os.path.basename(docx), dst, target,
                            os.path.basename(jd_file), script_name))

    runner = os.path.join(skill_root, "scripts", "run_tailor.sh")
    proc = subprocess.run(["bash", runner, os.path.basename(docx),
                           f"scripts/{script_name}"],
                          cwd=skill_root)
    if proc.returncode != 0:
        print(f"error: run_tailor.sh gates failed (exit {proc.returncode})",
              file=sys.stderr)
        sys.exit(proc.returncode)
    stats = plan["stats"]
    print(f"AUTO-PRUNE: {stats['cut']} cut, {stats['trim']} trimmed, "
          f"{stats['stub']} stub(s), {stats['section']} section(s) "
          f"emptied — no cut report (SKILL Phase A)")
    print(f"WROTE scripts/{script_name}")
    print(f"BUILD: {dst} — Phase B measures this copy (never the master)")


if __name__ == "__main__":
    main()
