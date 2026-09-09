"""Auto-tighten a tailored resume to a page budget, ending the
cut-render-cut-render loop.

The tailor script gets a resume to ~the right length; squeezing the last
few lines by hand means one script-run + measure per sentence trimmed.
This tool automates that residual loop: each iteration renders, takes the
JD-aware BATCH RECLAIM PLAN's oldest-first bullet cuts, applies them to the
.docx, and re-measures until on target or no JD-safe cuts remain.

Usage::

    python3 scripts/squeeze_resume.py <resume.docx> [TARGET_PAGES] \
        [--jd <raw-JD.txt>] [--protect "<phrase>"]... [--plan-only]

Flags mirror measure_resume.py (see its docstring): --jd excludes JD-evidence
bullets (candidate-term or practice matched) from every batch; --protect
adds candidate-specific facts the JD text cannot name. The loop STOPS
instead of cutting JD-critical content: when every remaining bullet is
JD-matched/protected it reports that the next step is a whole-role drop
(seniority alignment — user approval required) or a Tools-line trim.

``--plan-only`` runs the identical loop against a throwaway copy of the
in-memory state: it plans exactly what apply mode would cut and prints the
same fold-back block WITHOUT touching the .docx (no backup, no log, no
edit). Use it at AUTHORING time to harvest the fold-back block before the
tailor script's first run — apply mode rewrites the .docx directly, which
then can only be reproduced by folding the cuts back into the script by
hand. Reserve apply mode for a doc you will NOT regenerate from the
tailor script.

Safety and reproducibility:
  - A backup of the pre-squeeze .docx is written to ``<docx>.pre-squeeze.docx``
    before any edit (apply mode only).
  - Every applied cut is logged to ``<docx>.squeeze.json`` as copy-pasteable
    ``find_p(ps, "...")`` prefixes (with full bullet texts), AND printed at
    the end as a ready-to-paste ``drop(body, [...])`` block — paste it into
    the tailor_<target>.py script so the final state reproduces from the
    untouched master (the tailor script remains the diff-able record). No
    hand-transcription: the printed block is the fold.

Requires libreoffice + pdftotext (like measure_resume.py).
"""



import json
from typing import NamedTuple
import os
import shutil
import sys
import tempfile

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402
from script_args import extract_common, read_jd_text  # noqa: E402


def _apply_drops(body, suggestions):
    """Remove the paragraphs named by ``suggestions`` = [(find_p prefix,
    full text)]. Prefixes that no longer resolve are skipped (never a
    silent mis-edit). Returns (applied_count, skipped_prefixes)."""
    applied = 0
    skipped = []
    for prefix, _text in suggestions:
        p = de.find_p(de.paras(body), prefix)
        if p is None:
            skipped.append(prefix)
            continue
        de.remove(body, p)
        applied += 1
    return applied, skipped


def _next_batch(roles, plan, all_texts, protect=(), jd_terms=()):
    """[(prefix, full_text)] for the plan's 'drop N bullet(s)' entries,
    oldest-role-first (plan order), JD-aware. Whole-role plan entries yield
    nothing (the seniority decision is the user's)."""
    out = []
    for _key, role, m in mr._iter_plan_roles(plan, roles):
        out.extend(mr._drop_suggestions(
            role.get("bullet_texts") or [], int(m.group(1)),
            all_texts=all_texts, protect=protect, jd_terms=jd_terms))
    return out


def _print_foldback(foldback):
    """Print the paste-ready ``drop(body, [...])`` block for the tailor
    script. ``foldback`` is the in-order list of (prefix, full text) pairs
    that squeeze applied. The full text in the comment is what makes the
    block reviewable — an author pasting it can see each bullet they are
    committing to cut, not just opaque prefixes."""
    if not foldback:
        print("No cuts applied — nothing to fold back into the tailor script.")
        return
    print("Fold-back block — paste into tailor_<target>.py so the script "
          "reproduces this exact state:")
    print("ps = drop(body, [")
    for prefix, text in foldback:
        print(f"    {prefix!r},  # {text}")
    print("])")


def _squeeze_jd_setup(jd_file, docx, plan_only):
    jd_terms = set()
    if jd_file:
        jd_text = read_jd_text(jd_file)
        _root, body0, _n, _d, _ = de.load(docx)
        jd_terms = mr._jd_terms(jd_text, body0)
        print(f"JD-aware ranking: {len(jd_terms)} term(s) matched from "
              f"{jd_file}")

    # Safety: preserve the pre-squeeze state (the .docx is session-temp, but
    # a mistaken auto-cut should never be unrecoverable). --plan-only never
    # writes the file, so there is nothing to back up.
    if not plan_only:
        shutil.copy(docx, docx + ".pre-squeeze.docx")
    return jd_terms


class _SqueezeCfg(NamedTuple):
    """Immutable squeeze-loop config."""
    docx: str
    target: int
    max_iters: int
    plan_only: bool
    protect: list
    jd_terms: set


def _squeeze_setup(argv):
    """Parse squeeze_resume args and load the docx. Returns (cfg, root,
    body, names, data). Exits 2 on usage error."""
    plan_only = "--plan-only" in argv
    protect, jd_file, kept = extract_common(
        argv, extra_flags=("--plan-only",))
    if not kept:
        print("usage: squeeze_resume.py <resume.docx> [TARGET_PAGES] "
              "[--jd <raw-JD.txt>] [--protect \"<phrase>\"] [--plan-only]",
              file=sys.stderr)
        sys.exit(2)
    docx = kept[0]
    target = int(kept[1]) if len(kept) > 1 else int(
        os.environ.get("TARGET_PAGES", "2"))
    max_iters = int(os.environ.get("SQUEEZE_MAX_ITERS", "8"))
    jd_terms = _squeeze_jd_setup(jd_file, docx, plan_only)
    cfg = _SqueezeCfg(docx, target, max_iters, plan_only, protect, jd_terms)
    root, body, names, data, _ = de.load(docx)
    return cfg, root, body, names, data


def _render_iter(cfg, root, names, data):
    """Render the in-memory docx state to page text. In plan-only mode a
    throwaway probe copy is rendered so the input file stays untouched."""
    with tempfile.TemporaryDirectory() as td:
        if cfg.plan_only:
            probe = os.path.join(td, "plan_probe.docx")
            de.save(probe, root, names, data)
            pdf = mr._render_pdf(probe, td)
        else:
            pdf = mr._render_pdf(cfg.docx, td)
        return mr._pdf_pages_text(pdf)


def _next_squeeze_batch(body, roles, pages_text, cfg):
    """Compute the next JD-safe bullet cut batch. Returns the batch list
    (possibly empty) — an empty batch means no safe cuts remain."""
    overflow = sum(len(mr._page_lines(p)) for p in pages_text[cfg.target:])
    matched = mr._match_roles_to_pages(roles, pages_text)
    per = mr._measured_lines_per_bullet(matched)
    plan, _remaining = mr._reclaim_batch(matched, per, overflow + per)
    all_texts = [de.text_of(p) for p in de.paras(body)]
    return _next_batch(roles, plan, all_texts, protect=cfg.protect,
                       jd_terms=cfg.jd_terms)


def _squeeze_finalize(cfg, log, foldback):
    """Write the squeeze log / foldback report (plan-only vs apply mode)."""
    if cfg.plan_only:
        print("plan-only: no edits written — the .docx on disk is unchanged.")
        return
    log["drop_texts"] = [[p, t] for p, t in foldback]
    log_path = cfg.docx + ".squeeze.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    print(f"log: {log_path}")
    _print_foldback(foldback)


def main():
    """Squeeze-resume CLI entry point."""
    cfg, root, body, names, data = _squeeze_setup(list(sys.argv[1:]))
    log = {"docx": cfg.docx, "target_pages": cfg.target, "jd_file": None,
           "protect": list(cfg.protect), "jd_terms": sorted(cfg.jd_terms),
           "iterations": [], "drop_texts": [], "final_pages": None}
    foldback = []
    for it in range(1, cfg.max_iters + 1):
        pages_text = _render_iter(cfg, root, names, data)
        total = len(pages_text)
        print(f"[iter {it}] pages: {total} (target {cfg.target})")
        if total <= cfg.target:
            log["final_pages"] = total
            break
        batch = _next_squeeze_batch(body, mr._roles(body), pages_text, cfg)
        if not batch:
            print("  no JD-safe bullet cuts remain — every remaining bullet "
                  "is JD-matched or protected. Cuts can still come from ANY "
                  "section: run measure_resume.py for the TOP-BLOCK RECLAIM "
                  "CANDIDATES (off-JD proficiency/certification lines), trim "
                  "a Tools line, or drop a whole role (seniority alignment; "
                  "user approval recorded at render — check the gap warning "
                  "in measure's BATCH RECLAIM PLAN).", file=sys.stderr)
            log["final_pages"] = total
            break
        applied, skipped = _apply_drops(body, batch)
        if applied == 0:
            print(f"  0 drops applied (skipped={skipped}) — stopping to "
                  "avoid a loop; check that the tailor script prefixes still "
                  "match the docx.", file=sys.stderr)
            log["final_pages"] = total
            break
        if not cfg.plan_only:
            de.save(cfg.docx, root, names, data)
        log["iterations"].append({
            "iteration": it, "pages_before": total, "applied": applied,
            "skipped": skipped, "drops": [p for p, _ in batch],
        })
        foldback.extend(batch)
        print(f"  dropped {applied} bullet(s):")
        for prefix, text in batch:
            print(f"    find_p(ps, {prefix!r})  # {text[:64]}")
        if it == cfg.max_iters:
            print(f"  stopped at max iterations ({cfg.max_iters}); still "
                  "{total} pages — raise SQUEEZE_MAX_ITERS or cut a whole "
                  "role.", file=sys.stderr)
    _squeeze_finalize(cfg, log, foldback)


if __name__ == "__main__":
    main()
