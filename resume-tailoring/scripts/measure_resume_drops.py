"""measure_resume drop planning / fit audit / reclaim batching. Split from measure_resume.py; imported one-way by the measure_resume shim."""  # pylint: disable=line-too-long
# pylint: disable=wrong-import-position,import-outside-toplevel
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.



import contextlib
import io
import math
import re
from typing import NamedTuple
import shutil
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
from measure_resume_jd_terms import (CORE_TECH_NOUNS, JD_STOP,  # noqa: E402
    _concept_hits, _is_protected, _jd_capitalized, _jd_hits,
    _jd_hits_classified, _jd_kept, _vocab_terms, _weakness_key)
from measure_resume_format import (_norm, _page_fill, _page_lines,  # noqa: E402
    _preceding_role_key, _role_header_flat)

W = de.W

_DROP_ACTION = re.compile(r"^drop (\d+) bullet\(s\)")


def _suggest_drops(bullet_texts, budget, protect=(), jd_terms=()):
    """The `budget` weakest bullets (weakest first), deterministically.

    Bullets containing a ``protect`` phrase are **never** suggested — the
    budget is filled exclusively from unprotected bullets.  With ``jd_terms``
    (from --jd), bullets carrying STRONG JD evidence (a non-weak matched
    term or a JD practice phrase) are excluded the same way, while any
    non-JD bullet remains — so a Cypress bullet stops being cuttable the
    moment the JD asks for Cypress, while a bullet matched only by a term
    that hits half its own role (generic 'test' in a tester's role) stays
    cuttable.  Weakness is judged against ``bullet_texts`` (the role's own
    bullets).  When the budget exceeds the unprotected supply,
    returns only what is available (a short list); callers should surface
    the shortfall to the user.
    """
    if budget <= 0 or not bullet_texts:
        return []
    cuttable = [t for t in bullet_texts
                if not _is_protected(t, protect)
                and not _jd_kept(t, jd_terms, corpus=bullet_texts)]
    ranked = sorted(cuttable, key=_weakness_key)
    return ranked[:budget]


def _drop_suggestions(bullet_texts, budget, all_texts=None, protect=(),
                      jd_terms=()):
    """[(find_p_prefix, full_bullet_text)] for the `budget` weakest cuttable
    bullets — the structured form behind the DROP PLAN's copy-pasteable
    lines, consumed by squeeze_resume.py's auto loop so it applies exactly
    what the plan names.
    """
    out = []
    unique_against = all_texts if all_texts else bullet_texts
    for text in _suggest_drops(bullet_texts, budget, protect=protect,
                               jd_terms=jd_terms):
        try:
            idx = unique_against.index(text)
        except ValueError:
            continue
        prefix = de.shortest_unique_prefix(unique_against, idx, min_len=6)
        if prefix is None:
            continue
        out.append((prefix, text))
    return out


def _drop_plan_lines(bullet_texts, budget, all_texts=None, protect=(),
                     jd_terms=()):
    """Copy-pasteable find_p lines for the `budget` weakest bullets.

    Each line is ``find_p(ps, "<unique prefix>")  # <full bullet>`` so the
    agent can paste the exact cut into the tailor script with zero
    render-measure iterations. Uniqueness is checked against ``all_texts``
    (pass the FULL document's paragraph texts so the emitted prefix stays
    unique document-wide), falling back to the role's own bullets.
    ``protect`` phrases and ``jd_terms`` keep JD-critical bullets out of the
    suggestions.
    """
    return [
        f'find_p(ps, "{prefix}")  # {text}'
        for prefix, text in _drop_suggestions(
            bullet_texts, budget, all_texts=all_texts, protect=protect,
            jd_terms=jd_terms)
    ]


def _protected_count(bullets, protect=(), jd_terms=()):
    """How many of ``bullets`` carry STRONG JD/protect evidence (never
    suggested for cutting while weaker bullets remain). Weak matches — a
    term that hits half the role's own bullets — do not protect: every
    bullet in the role carries them, so counting them would shield the
    whole role from the plan (the exact over-protection two real sessions
    hit, where a 1-year role kept 16+ bullets and old JD-relevant bullets
    died instead)."""
    return sum(1 for b in bullets
               if _is_protected(b, protect)
               or _jd_kept(b, jd_terms, corpus=bullets))


def _iter_plan_roles(plan, roles):
    """Yield (role, m) per plan entry whose action is a drop-N-bullet and
    whose role still exists — shared by _dead_end_roles and squeeze_resume
    (dedupes the resolve/guard preamble)."""
    for key, action, _saved in plan:
        m = _DROP_ACTION.match(action)
        if not m:
            continue
        role = next((r for r in roles if r["key"] == key), None)
        if not role:
            continue
        yield key, role, m


def _dead_end_roles(plan, roles, protect=(), jd_terms=()):
    """Role keys whose "drop N bullet(s)" budget exceeds their unprotected
    bullets: meeting the budget means cutting JD-matched/protected content.
    The honest fixes are TOP-BLOCK RECLAIM CANDIDATES, a Tools-line trim,
    or a whole-role drop — not slicing kept bullets."""
    dead = []
    for key, role, m in _iter_plan_roles(plan, roles):
        bullets = role.get("bullet_texts") or []
        n = int(m.group(1))
        protected = _protected_count(bullets, protect=protect,
                                     jd_terms=jd_terms)
        if n > len(bullets) - protected and protected > 0:
            dead.append(key)
    return dead


def _plan_feasibility(plan, matched, per, protect, jd_terms):
    """Oldest-first pass over the plan: total line savings the listed cuts
    can actually deliver (dead-end budgets shrunk to unprotected counts),
    and the adjusted plan (whole-role drops kept, superseded dead-ends
    dropped for the top role). Returns (feasible, adjusted)."""
    feasible = 0.0
    adjusted = []
    for key, action, saved in plan:
        m = _DROP_ACTION.match(action)
        if not m:
            feasible += saved  # whole-role drop: feasible by definition
            adjusted.append((key, action, saved))
            continue
        take = _entry_take(matched, key, m, protect, jd_terms)
        if take > 0:
            feasible += take * per
        if key == matched[0][0]["key"]:
            continue  # superseded: the batch below is the authoritative sizing
        adjusted.append((key, action, saved))
    return feasible, adjusted


def _entry_take(matched, key, m, protect, jd_terms):
    """Max unprotected bullets the plan asks to cut from one role (capped
    at what the role actually has)."""
    by_key = {e[0]["key"]: e[0] for e in matched}
    role = by_key.get(key) or {}
    bullets = role.get("bullet_texts") or []
    unprotected = len(bullets) - _protected_count(bullets, protect=protect,
                                                  jd_terms=jd_terms)
    return min(int(m.group(1)), max(0, unprotected))


class Budget(NamedTuple):
    """Page-budget inputs for the reclaim planner (per rendered line, the
    required reclaim, and the non-bullet savings already counted)."""

    per: float
    required: float
    tools_savings: float
    top_block_count: int

    def shortfall_after(self, feasible: float) -> float:
        """The reclaim gap still open after ``feasible`` savings land."""
        return self.required - feasible


def _top_role_batch(matched, plan, budget, protect=(), jd_terms=()):
    """Size the most-recent role's trim batch — the residual-gap closer.

    The BATCH RECLAIM PLAN is oldest-first and stops as soon as its listed
    savings reach the gap. But dead-end budgets (JD-protected bullets)
    overstate what the oldest roles can actually give, and TOP-BLOCK lines
    and Tools de-wraps are the only other removal sources. When even those
    fall short of ``required``, the honest remaining source is the
    most-recent role's weakest UNPROTECTED bullets — the failure this
    replaces is the author inventing levers to close the gap (hand-
    shortening kept bullets from two rendered lines to one), because the
    tool's plan visibly cannot reach the target.

    Returns ``(batch_entry, adjusted_plan, feasible)`` where ``batch_entry``
    is ``(top_key, action, saved_lines)`` or ``None`` when the feasible
    cuts already close the gap (or the top role has no unprotected
    bullet to give); ``adjusted_plan`` drops any superseded dead-end entry
    for the top role (the batch is the authoritative sizing for it); and
    ``feasible`` is the total line savings the removals above can actually
    deliver (dead-end budgets shrunk to unprotected counts, + Tools
    de-wraps, + TOP-BLOCK lines) — so main() can state honestly when the
    gap cannot close without cutting JD-matched content.
    """
    if not matched:
        return None, list(plan), 0.0
    top_key = matched[0][0]["key"]  # matched is document order: most-recent first
    feasible, adjusted = _plan_feasibility(plan, matched, budget.per,
                                           protect, jd_terms)
    feasible += budget.tools_savings + budget.top_block_count
    shortfall = budget.shortfall_after(feasible)
    top_bullets = matched[0][0].get("bullet_texts") or []
    top_protected = _protected_count(top_bullets, protect=protect,
                                     jd_terms=jd_terms)
    unprotected = max(0, len(top_bullets) - top_protected)
    if shortfall <= 0 or unprotected <= 0:
        return None, adjusted, feasible
    n = min(unprotected, math.ceil(shortfall / budget.per))
    saved = n * budget.per
    return ((top_key, f"drop {n} bullet(s) (saves ~{saved:.0f} lines)", saved),
            adjusted, feasible)


def _apply_simulate(docx_path, drop_prefixes, out_path):
    """Copy ``docx_path`` to ``out_path`` and drop the WHOLE roles named by
    each prefix (docx_edit.drop_role) in the copy — the seniority-alignment
    what-if behind ``--simulate``. Returns ``(out_path, dropped)`` where
    ``dropped`` lists the company-header texts actually removed (prefixes
    that matched nothing are absent, with drop_role's stderr warning).
    The original file is never modified."""
    shutil.copyfile(docx_path, out_path)
    root, body, names, data, _ = de.load(out_path)
    dropped = []
    for prefix in drop_prefixes:
        ps = de.paras(body)
        anchor = de.find_p(ps, prefix)
        if anchor is None:
            continue  # drop_role already warned; nothing removed
        header = de.text_of(anchor)
        before = len(ps)
        de.drop_role(body, prefix)
        if len(de.paras(body)) < before:
            dropped.append(header)
    # docx_edit.save's "applied N edits" line describes the temp copy —
    # printed unqualified it reads like the user's file was mutated, so
    # capture and relabel it.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        de.save(out_path, root, names, data, drift=de.DriftMeta(drift_key="simulate-temp"))
    m = re.search(r"applied (\d+) edits", buf.getvalue())
    if m:
        print(f"simulated {m.group(1)} drop edit(s) — applied to the temp "
              f"copy only")
    return out_path, dropped


def _role_jd_evidence_lines(roles, header_text, jd_terms):
    """Per-dropped-role JD-evidence report for ``--simulate``. Returns
    warning lines listing each JD-matched bullet a drop would lose, or a
    clean-drop note when no evidence matches."""
    role = next((r for r in roles if r["raw"] == header_text), None)
    if role is None or not jd_terms:
        return []
    kept = [b for b in role["bullet_texts"]
            if _jd_kept(b, jd_terms, corpus=role["bullet_texts"])]
    if not kept:
        return [f"JD evidence: none of this role's "
                f"{len(role['bullet_texts'])} bullet(s) match the JD — "
                f"a clean drop candidate"]
    lines = [
        f"JD EVIDENCE LOST: this role carries {len(kept)} JD-matched "
        f"bullet(s) — trimming it to those bullets may beat dropping it "
        f"whole (SKILL Step 3):",
    ]
    for b in kept:
        lines.append(f"    - {b[:90]}")
    return lines


def _sentence_clauses(text):
    """Sentences of a bullet (split after . / ! / ? boundaries)."""
    return [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]


def _nonjd_terms_in(sentence, vocab, jd_terms):
    """Non-JD tech terms the sentence hosts, deterministically.

    A vocab term (proficiencies/Tools/job-title claimed tech) counts when
    the sentence hosts it (whole-word, plural-tolerant via _jd_hits), the
    JD does not name it, and it reads as a TECH NOUN: a core tech noun,
    a #/+ token (c#, c++), or a mid-sentence Capitalized token (tool
    names are proper nouns — the same heuristic _jd_capitalized applies
    to JD text). Generic lowercase prose (services, testing, automation)
    never flags, so the section stays signal, not noise.
    """
    low = sentence.lower()
    out = []
    for t in sorted(vocab - jd_terms):
        if len(t) < 2 or t in JD_STOP:
            continue
        if " " in t:
            hosted = t in low
        else:
            hosted = bool(_jd_hits(sentence, {t}))
        if not hosted:
            continue
        if (t in CORE_TECH_NOUNS or re.search(r"[#+]", t)
                or _jd_capitalized(sentence, t)):
            out.append(t)
    return out


def _keep_trim_candidates(role, jd_terms, vocab):
    """[(bullet, nonjd_terms, dead_sentences)] for one role.

    Only KEPT bullets (strong JD term or practice-phrase evidence) are
    scanned — OFF-JD/weak bullets are whole-cut candidates (JD-FIT AUDIT),
    not trim candidates. Within a kept bullet, sentences carrying a JD
    practice phrase are skipped entirely: their tokens may be the concept's
    only host (Kafka hosting "event-driven"), so they are never trim
    candidates.
    """
    bullets = role.get("bullet_texts") or []
    out = []
    for b in bullets:
        strong, _ = _jd_hits_classified(b, jd_terms, bullets)
        if not strong and not _concept_hits(b):
            continue
        nonjd, dead = [], []
        for s in _sentence_clauses(b):
            if _concept_hits(s):
                continue
            nonjd.extend(_nonjd_terms_in(s, vocab, jd_terms))
            if not _jd_hits(s, jd_terms):
                dead.append(s)
        if nonjd or dead:
            out.append((b, sorted(set(nonjd)), dead))
    return out


def _keep_trim_section(roles, jd_terms, body, protect=()):
    """WORD-LEVEL TRIM CANDIDATES — word-level pruning, deterministic.

    Compression was bullet-granular: a kept bullet carried its non-JD
    tools and dead sentences to the deliverable untouched (the user's
    TestNG/Playwright examples). This section names them per kept bullet:
    the non-JD tech the JD never asks for (strip from its clause) and the
    sentences with no JD evidence at all (cut whole). Copy-pasteable
    ``find_p`` anchors match the DROP PLAN's form. Skipped entirely:
    protected bullets (--protect) and sentences carrying a JD practice
    phrase (their tokens may host the concept).
    """
    if not jd_terms:
        return None
    vocab = _vocab_terms(body)
    all_texts = [de.text_of(p) for p in de.paras(body)]
    lines = []
    for role in roles:
        cand = []
        for b, nonjd, dead in _keep_trim_candidates(role, jd_terms, vocab):
            if _is_protected(b, protect):
                continue
            try:
                idx = all_texts.index(b)
                prefix = de.shortest_unique_prefix(all_texts, idx, min_len=6)
            except ValueError:
                prefix = None
            cand.append(f'    find_p(ps, "{prefix}")  # {b[:80]}'
                        if prefix else f"    - {b[:80]}")
            if nonjd:
                cand.append(f"      - JD does not name: "
                            f"{', '.join(nonjd)}")
            for s in dead:
                cand.append(f'      - sentence with no JD evidence: '
                            f'"{s[:80]}"')
        if cand:
            lines.append(f"  {role['key']}:")
            lines.extend(cand)
    if not lines:
        return None
    return ("WORD-LEVEL TRIM CANDIDATES (kept bullets still carrying "
            "non-JD content — prune to the word: cut the flagged "
            "sentence, strip the flagged tool from its clause; never "
            "strip a term the JD names or one that hosts a [weak]/"
            "covered ask; SKILL Step 8):\n" + "\n".join(lines))


def _jd_fit_audit(roles, jd_terms, protect=()):
    """Per-role JD-fit audit — printed for EVERY role when --jd is passed.

    Classifies every bullet by JD alignment strength: strong/practice-
    phrase hits carry JD evidence; weak-only hits (generic terms) are
    cuttable; ZERO hits means the bullet is OFF-JD — the prime first-pass
    cut candidate, or 1-bullet-stub material when dropping the role would
    open an employment gap. ``protect`` phrases (--protect) count as
    evidence: the user confirmed those facts, so they are never cut
    candidates.
    """
    if not jd_terms:
        return []
    sections = []
    for role in roles:
        section = _jd_fit_section(role, jd_terms, protect)
        if section:
            sections.append(section)
    return sections


def _jd_fit_section(role, jd_terms, protect):
    """The JD-FIT AUDIT block for one role, or empty when every bullet
    carries JD evidence (nothing to report)."""
    bullets = role.get("bullet_texts") or []
    if not bullets:
        return None
    off, weak, kept = [], [], 0
    for b in bullets:
        if _is_protected(b, protect):
            kept += 1
            continue
        strong, weak_hits = _jd_hits_classified(b, jd_terms, bullets)
        if strong or _concept_hits(b):
            kept += 1
        elif weak_hits:
            weak.append((b, weak_hits))
        else:
            off.append(b)
    if not off and not weak:
        return None
    lines = [f"JD-FIT AUDIT ({role['key']}): {kept} of {len(bullets)} "
             f"bullet(s) carry JD evidence"]
    for b in off:
        lines.append(f"  OFF-JD (no JD term, no practice phrase): "
                     f"{b[:68]}")
    for b, hits in weak:
        lines.append(f"  weak-match (cuttable): {b[:68]}  "
                     f"[weak: {' , '.join(hits)}]")
    if len(off) * 2 >= len(bullets):
        lines.append(
            "  STUB CANDIDATE: most of this role is off-JD — cut the "
            "OFF-JD bullets; if the role then carries no JD evidence "
            "at all, keep a 1-bullet stub ONLY to prevent an "
            "employment gap (SKILL Step 8).")
    else:
        lines.append(
            "  Cut or shorten these even when on target — JD alignment "
            "outranks the page math; 40 words is a ceiling, never a "
            "target (SKILL Step 8).")
    return "\n".join(lines)


def _jd_listing_lines(bullets, jd_terms):
    """Display lines for a role's JD-evidence bullets.

    'JD-matched (kept)' lists STRONG matches — they protect the bullet
    from the DROP PLAN. 'weak-match (cuttable)' lists bullets whose ONLY
    term hits are weak (each term hits >half the role's own bullets, so
    the match discriminates nothing — see :func:`_weak_jd_terms`): they
    stay cuttable, and the listing makes that visible instead of nominal
    protection. JD practice-phrase matches (mentorship, traceability, ...)
    are always strong.
    """
    if not jd_terms:
        return []
    strong_kept, weak_only, concept_kept = [], [], []
    for b in bullets:
        strong, weak_hits = _jd_hits_classified(b, jd_terms, bullets)
        if strong:
            strong_kept.append((b, strong))
        elif weak_hits:
            weak_only.append((b, weak_hits))
        elif _concept_hits(b):
            concept_kept.append((b, _concept_hits(b)))
    lines = []
    if strong_kept or concept_kept:
        lines.append("  JD-matched (kept) — never suggested while weaker "
                     "bullets remain:")
        for b, hits in strong_kept:
            lines.append(f"    - {b[:68]}  [{' , '.join(hits)}]")
        for b, hits in concept_kept:
            lines.append(f"    - {b[:68]}  [practice: {', '.join(hits)}]")
    if weak_only:
        lines.append("  weak-match (cuttable — each term below hits half "
                     "this role's bullets, so it protects nothing; the "
                     "human rule may still keep specific bullets):")
        for b, hits in weak_only:
            lines.append(f"    - {b[:68]}  [weak: {' , '.join(hits)}]")
    return lines


def _drop_sections(plan, roles, all_texts=None, protect=(), jd_terms=()):
    """Turn a BATCH RECLAIM PLAN into per-role DROP PLAN sections.

    Each "drop N bullet(s)" plan entry (keyed by role key) becomes a
    section listing the N weakest bullets as copy-pasteable ``find_p(ps, ...)``
    lines. "consider dropping the whole role" entries produce no section —
    the header/tools lines save more than any single bullet, and the
    seniority decision is the user's, not the ranker's.

    With ``jd_terms`` (--jd), JD-evidence bullets are excluded from the
    suggestions and listed under "JD-matched (kept)" with the terms that
    matched — so the plan shows WHY a bullet was kept instead of making the
    agent re-derive it by reading each suggestion against the JD.
    """
    sections = []
    for _key, role, m in _iter_plan_roles(plan, roles):
        n = int(m.group(1))
        section = _drop_entry_section(role, n, all_texts=all_texts,
                                      protect=protect, jd_terms=jd_terms)
        sections.append("\n".join(section))
    return sections


def _drop_entry_section(role, n, *, all_texts, protect, jd_terms):
    """The DROP PLAN section for one plan entry (the n weakest bullets of
    one role, plus the JD-evidence listing and protection notes)."""
    bullets = role.get("bullet_texts") or []
    protected_count = _protected_count(bullets, protect=protect,
                                       jd_terms=jd_terms)
    unprotected_count = len(bullets) - protected_count
    lines = _drop_plan_lines(bullets, n, all_texts=all_texts,
                             protect=protect, jd_terms=jd_terms)
    section = [f"DROP PLAN ({role['key']}): drop {n} of {len(bullets)} bullets"]
    section.extend(_jd_listing_lines(bullets, jd_terms))
    if n > unprotected_count and protected_count > 0:
        if not lines:
            section.append(
                f"  ALL {len(bullets)} bullet(s) protected — budget={n} "
                "cannot be met without cutting JD/protected content. "
                "Cuts can still come from ANY section: the TOP-BLOCK "
                "RECLAIM CANDIDATES (proficiencies/certs), a Tools-line "
                "trim, or a whole-role drop (seniority decision; check "
                "the gap warning in the BATCH RECLAIM PLAN)."
            )
        else:
            section.append(
                f"  NOTE: budget={n} but only {unprotected_count} "
                f"unprotected bullet(s) — {protected_count} excluded "
                f"(JD-matched/protected)."
            )
    if lines:
        section.append("  weakest-first (generic/no-number first — review each")
        section.append("  against the JD before cutting):")
        for line in lines:
            section.append(f"    {line}")
    return section


def _protected_top_role_section(matched, jd_terms):
    """Fallback listing when the top role has NO unprotected bullet to give
    (batch is ``None``) while the gap is still open: every JD-matched
    bullet of the top role, each with the terms that matched.

    JD-matching has false positives on generic terms ('new', 'build',
    'control' match almost any bullet), so 'fully protected' must not read
    as a dead end. The listing puts each match's evidence on the page — a
    generic term is visibly weak — so the human rule ('the scorer only
    ranks — you confirm against the JD') can OVERRIDE protection
    deliberately instead of the author hand-picking cuts with no data.
    Returns ``None`` when there is nothing to review (no --jd, or the top
    role carries no matched bullet)."""
    if not matched or not jd_terms:
        return None
    bullets = matched[0][0].get("bullet_texts") or []
    lines = _jd_listing_lines(bullets, jd_terms)
    if not lines:
        return None
    return "\n".join([
        "TOP-ROLE PROTECTED BULLETS (no unprotected bullet to give; "
        "matched terms shown — a generic match like 'new' or 'build' "
        "is weak evidence, the human rule may override protection):"
    ] + lines)


def _batch_section(batch, role, header, lines, jd_listing):
    """Render the TOP-ROLE TRIM BATCH section — the residual-gap closer.

    ``batch`` is ``(key, action, saved_lines)`` from
    :func:`_top_role_batch`; ``lines``/``jd_listing`` are the
    caller-computed copy-pasteable cut lines and JD-evidence listing
    (:func:`_drop_plan_lines` / :func:`_jd_listing_lines` — the caller
    holds the JD context). ``header`` is the caller-provided first line
    (e.g. 'TOP-ROLE TRIM BATCH (Acme; closes ...)'). Returns the section
    as a multi-line string, or ``None`` when the batch/role is empty.
    """
    _key, action, _saved = batch
    m = _DROP_ACTION.match(action)
    if not m or role is None:
        return None
    section = [header]
    section.extend(jd_listing)
    if lines:
        section.append("  weakest-first (generic/no-number first — review each")
        section.append("  against the JD before cutting):")
        for line in lines:
            section.append(f"    {line}")
    return "\n".join(section)


def _layout_hints(matched, pages_text, capacity):
    """Page-fill table plus widow/underfill notes.

    A widow in the render is a role header that is the LAST line of a page
    while its body starts the next page — the exact failure mode of a
    "role header stranded at the bottom" that a line-count budget cannot
    see. An underfilled page whose next page starts with a role header is
    usually the same keep-with/heading-pagination effect; report it with a
    concrete line-cut suggestion so the fix is a batch action, not a
    cut-render-cut loop.
    """
    fills = _page_fill(pages_text)
    out = _page_fill_table(fills, capacity, pages_text)
    out.extend(_widow_notes(matched, pages_text))
    return out


def _page_fill_table(fills, capacity, pages_text):
    """Per-page rendered-line fill lines, plus underfilled-page notes."""
    out = []
    for i, f in enumerate(fills, start=1):
        pct = (100 * f // capacity) if capacity else 0
        out.append(f"  page {i}: {f:3} lines ({pct}% of max {capacity})")
    if capacity and len(fills) > 1:
        for i, f in enumerate(fills[:-1], start=1):
            if f < 0.85 * capacity:
                nxt = _page_fill_next_first(pages_text, i)
                out.append(
                    f"  NOTE: page {i} underfilled — holds {f} of ~{int(capacity)} lines "
                    f"({(100 * f // capacity)}% of max); page {i + 1} starts "
                    f"with: {nxt} — likely a keep-with/widow break; "
                    f"trimming ~{max(1, int(0.85 * capacity - f))} earlier "
                    f"line(s) may pull it up"
                )
    return out


def _page_fill_next_first(pages_text, i):
    """First line of page i+1 (truncated), for the underfill note."""
    nxt = _page_lines(pages_text[i])
    return nxt[0][:60] if nxt else "(blank)"


def _widow_notes(matched, pages_text):
    """Widow notes: role headers stranded as the last line of a page."""
    out = []
    flat = [(pi, _norm(l), l) for pi, ptext in
            enumerate(pages_text, start=1)
            for l in _page_lines(ptext)]
    keys = [r["key"] for r, *_ in matched]
    for r, *_ in matched:
        idx = _role_header_flat(flat, r["key"])
        if idx is None or idx + 1 >= len(flat):
            continue
        on_page_break = flat[idx][0] != flat[idx + 1][0]
        at_page_end = idx == 0 or flat[idx][0] == flat[idx - 1][0]
        if not (on_page_break and at_page_end):
            continue
        prev = _preceding_role_key(flat, idx, keys)
        if prev:
            out.append(
                f"  WIDOW: {r['key'][:44]} header is the last line of page "
                f"{flat[idx][0]}; its body starts page {flat[idx + 1][0]} — "
                f"reclaim ~2 line(s) from the {prev[:44]} block (the "
                f"content preceding the widow) to pull the header up, "
                f"or merge bullets"
            )
        else:
            out.append(
                f"  WIDOW: {r['key'][:44]} header is the last line of page "
                f"{flat[idx][0]}; its body starts page {flat[idx + 1][0]} — "
                f"trim earlier content or merge bullets"
            )
    return out


def _sparse_last_page_note(total_pages, target, fills, capacity,
                           overflow_lines=0):
    """Signal to reconsider the page target when the last page is sparse.

    The failure mode (a real session): a senior/Staff resume was built to
    the agreed 3-page target — "ON target" — and the page-fill table showed
    the last page at 43%, then 20%, then 13% as compression passes landed.
    SKILL Step 3's "target 2; accept 3 for senior/Staff" gave no rule for
    WHEN to accept 3, so the agent waffled through ~8 extra measure/render
    cycles re-deciding the target mid-flight. The tool CAN see the one
    signal that settles it: a sparse final page. SKILL Step 3's rule (added
    alongside this note): re-target one page lower and re-measure BEFORE
    cutting any JD-matched bullet — cutting JD-matched content to fill a
    sparse page is the trap.

    Fires whenever the last page fills <50% of capacity on a multi-page
    document; at/under target the message points one page lower, over
    target it points out that the reclaim gap is roughly the sparse tail
    itself and a dead-ending DROP PLAN means the target — not the bullets —
    is what to revisit.
    """
    if not capacity or len(fills) < 2:
        return None
    last = fills[-1]
    pct = 100 * last // capacity
    if pct >= 50:
        return None
    if total_pages > target:
        return (f"TARGET NOTE: last page is only {pct}% full ({last} of "
                f"~{capacity} lines). The ~{overflow_lines}-line gap to "
                f"{target} page(s) is roughly this sparse tail itself; if "
                f"the DROP PLAN dead-ends on JD-matched content, revisit "
                f"the page target (one page lower) and re-measure BEFORE "
                f"cutting JD-matched bullets (SKILL Step 3).")
    lower = f" Re-target one page lower ({target - 1}) and re-measure" \
            if target > 1 else " Re-measure against a lower target"
    return (f"TARGET NOTE: last page is only {pct}% full ({last} of "
            f"~{capacity} lines) — a sparse final page reads as "
            f"unpolished.{lower} BEFORE cutting any JD-matched bullet to "
            f"fill it (SKILL Step 3).")


def _measured_lines_per_bullet(matched):
    """Average rendered lines per bullet, measured from THIS render.

    Attributes each role's rendered lines to bullets by subtracting a
    2-line header block (company + job title) and ~1 line for the Tools
    line (tailored tools lines are trimmed to one line; wrapping adds on
    average well under a line). Honest reclaim math: the old hardcoded
    "~2 lines per bullet" budget undercounted dense bullets, which is why
    compression turned into cut-render-cut cycles.
    """
    total_bullet_lines = 0.0
    bullet_count = 0
    for r, _sp, _ep, rendered in matched:
        n = r["bullets"]
        if not n:
            continue
        tools_len = 1.0 if r["has_tools"] else 0.0
        bullet_lines = max(1, rendered - 2.0 - tools_len)
        total_bullet_lines += bullet_lines
        bullet_count += n
    return total_bullet_lines / bullet_count if bullet_count else 2.0


def _reclaim_batch(matched, per_bullet, gap):
    """Oldest-first concrete cut list sized to `gap` (lines).

    The skill rule is: cut the OLDEST roles first. For each oldest role with
    2+ bullets, take as many bullet cuts as the budget needs (keeping at
    least one bullet per role); a 1-bullet role is cheaper to drop whole
    (header + tools + bullets) once it is the oldest — that is the cleanest
    page math and also compresses the timeline. Returns (plan, remaining)
    where plan is [(role_key, action, saved_lines)].
    """
    plan = []
    remaining = gap
    for r, _sp, _ep, rendered in reversed(matched):
        if remaining <= 0:
            break
        n = r["bullets"]
        key = r["key"]
        if n >= 2:
            take = min(n - 1, max(1, math.ceil(remaining / per_bullet)))
            saved = take * per_bullet
            plan.append((key, f"drop {take} bullet(s) (saves ~{saved:.0f} lines)", saved))
            remaining -= saved
        else:
            plan.append((key, f"consider dropping the whole role (saves ~{rendered:.0f} lines)", rendered))  # pylint: disable=line-too-long
            remaining -= rendered
    return plan, remaining
