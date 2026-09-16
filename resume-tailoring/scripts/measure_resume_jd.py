"""measure_resume JD requirements / coverage / inference / title analysis.
Split from measure_resume.py; term vocabulary/mining lives in measure_resume_jd_terms
(imported one-way from there); imported one-way by measure_resume_drops + the shim."""
# pylint: disable=invalid-name
# invalid-name: JD vocabulary constants use the file's domain naming.
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.
# Lazy imports are deliberate (cycle avoidance / heavy deps) — see the
# rationale at each site.


import os
import re
import textwrap
import sys
from typing import NamedTuple

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
import jd_asks  # noqa: E402
import jd_sections  # noqa: E402
from docx_edit_gate import tmp_jd_note  # noqa: E402
from measure_resume_format import COMPANY_STYLE, SECTION_PROFICIENCIES  # noqa: E402
# The engine (jd_asks) owns JD parsing; this module consumes it and
# keeps only the names it uses.
from jd_asks import _phrase_terms, _single_token_terms  # noqa: E402
from measure_resume_jd_terms import (  # noqa: E402
    JD_CONCEPTS, _acronym_terms, _adjacent_bigrams, _jd_capitalized,
    JD_SOFT_SKILL_RE)
JD_SHORT_WORDS = jd_asks.JD_SHORT_WORDS

MISSING_REPORT_CAP = 24  # bounded no-host list (signal-ranked)

W = de.W

SECTION_STYLE = "SectionHeading"  # career/education/proficiencies headings


class InferenceSources(NamedTuple):
    """Evidence sources used for no-host JD terms."""
    linkedin_text: str | None = None
    master_body: object | None = None


HEADLINE_STYLE = "Title"  # top-of-resume headline: 2nd 'Title' paragraph after the name




INFERENCE_FAMILIES = (
    (("debug",),
     ("debug", "triage", "root cause", "diagnos", "resolved",
      "remediat", "defect")),
    (("data management", "data modeling", "query tuning"),
     ("test data", "sql", "query", "index", "data model", "etl")),
    (("aws", "cloud"),
     ("aws", "amazon web services", "cloud", "azure", "gcp")),
    (("ui", "frontend", "front end"),
     ("web", "user interface", "frontend", "browser", "desktop")),
    (("customer facing",),
     ("customer", "client", "production", "incident", "stakeholder")),
    (("problem solving", "solving problems", "troubleshooting"),
     ("problem", "troubleshoot", "root cause", "resolved", "issue")),
    (("llm", "genai", "generative"),
     ("llm", "prompt", "copilot", "gpt", "claude", "openai")),
    (("programming", "programming skills", "coding"),
     ("java", "python", "javascript", "typescript", "c#", "go",
      "coding", "programming")),
    (("software engineering",),
     ("software", "engineering", "engineer", "sdlc", "developed",
      "development")),
    # Real-session misses: an Endpoint JD's performance/stress testing,
    # OS-platform, endpoint-security, VM-tooling and GUI-automation asks
    # had master evidence but NO family — the map reported bare gaps.
    (("performance testing", "load testing", "stress testing",
      "stress-harness", "soak testing", "performance"),
     ("performance", "load", "stress", "soak", "gatling", "jmeter",
      "k6", "benchmark", "capacity")),
    (("reliability", "soak"),
     ("stability", "chaos", "fault", "resilien", "soak", "monitoring",
      "production", "uptime", "regression")),
    (("windows", "macos", "linux", "operating system", "os internals",
      "os behavior", "cross-platform"),
     ("linux", "wsl", "powershell", "windows", "macos", "image",
      "install", "upgrade", "lamp", "desktop", "server")),
    (("endpoint security", "edr", "dlp", "epp", "mdm", "endpoint agent",
      "security"),
     ("security", "snyk", "guardrails", "compliance", "hipaa", "phi",
      "monitoring", "grafana", "agent", "mitigation")),
    (("virtualization", "provisioning", "vm", "virtual machine",
      "image build", "test farm", "test fleet"),
     ("virtualization", "vm", "docker", "kubernetes", "provisioning",
      "codespaces", "container", "instance")),
    (("desktop gui", "gui automation", "pyautogui", "pywinauto",
      "uiautomation"),
     ("ui testing", "coded ui", "desktop", "browser", "cross-browser", "ui")),
    (("secure software development", "secure development", "secure sdlc",
      "secure coding"),
     ("security", "compliance", "fda", "hipaa", "mitigation", "snyk",
      "guardrails")),
)


_INFERENCE_MATCH_CAP = 2  # evidence lines printed per source


TITLE_MAX_WORDS = 10  # a longer first line is prose, not a JD title


TITLE_LABEL_RE = re.compile(
    r"^\s*(?:job\s+title|position|role|title)\s*[:：]\s*(.+?)\s*$",
    re.I,
)


TITLE_RANK_PATTERNS = (
    (re.compile(r"\bprincipal\b", re.I), 4.0),
    (re.compile(r"\bstaff\b", re.I), 3.0),
    (re.compile(r"\bmanager\b", re.I), 3.0),
    (re.compile(r"\blead\b", re.I), 2.5),
    (re.compile(r"\bsenior\b", re.I), 2.0),
)


def _top_block_candidates(body, jd_terms=()):
    """Cut candidates from the FIXED TOP BLOCK: Technical Proficiencies
    lines and certification lines carrying no JD evidence.

    The whole resume tailors to the JD — compression is NOT limited to
    role bullets. Each candidate is ``(find_p_prefix, text)``; a line that
    matches a JD term or practice phrase is NOT a candidate (it is doing
    JD work). The Certifications section heading itself is skipped (it is
    only cuttable together with its last line). Empty without --jd? No —
    without ``jd_terms`` every top-block line is a candidate (the caller
    labels them "review against the JD").
    """
    ps = de.paras(body)
    texts = [de.text_of(p) for p in ps]
    start = None
    for i, p in enumerate(ps):
        if texts[i].strip() == SECTION_PROFICIENCIES:
            start = i + 1
            break
    if start is None:
        return []
    out = []
    for i in range(start, len(ps)):
        p = ps[i]
        style, _ = de.style_and_numid(p)
        t = texts[i]
        if style == COMPANY_STYLE and t.strip():
            break  # career region begins
        if style == "SectionHeading" or not t.strip():
            continue
        if jd_asks.evidence_set(t.lower(), jd_terms):
            continue
        prefix = de.shortest_unique_prefix(texts, i, min_len=6)
        if prefix is not None:
            out.append((prefix, t.strip()))
    return out


def _jd_requirement_lines(jd_text):
    """The JD's qualification lines — engine-owned (jd_asks)."""
    return jd_asks.requirement_lines(jd_text)


def _jd_line_terms_map(jd_text):
    """(qualification line, extracted terms) per qual line, in the same
    order as :func:`_jd_requirement_coverage`'s output. The coverage
    printer zips this in to show WHICH terms the matcher extracted —
    an artifact like ``solid sql`` mined from "Solid SQL skills" is then
    visible in the report, no matcher debugging required."""
    return [(q, _jd_line_terms(q) | {c for c in JD_CONCEPTS
                                     if c in q.lower()})
            for q in _jd_requirement_lines(jd_text)]


def _jd_line_terms(line):
    """Engine asks on one qualification line: anchored/capitalized
    tokens, cue-tail phrases, and the calibrated adjacent bigrams —
    the same extraction parse_asks applies to the whole JD."""
    return (_single_token_terms(line) | _phrase_terms(line)
            | _adjacent_bigrams(line))


def _jd_missing_terms(jd_text, body, jd_terms=None):
    """The engine's positive direction: asks with NO host in the whole
    document — the mining queue and the never-fabricate flags.

    ``jd_terms`` is accepted for signature compatibility and ignored:
    the engine's ask list IS the determination (the old
    vocabulary-intersection + side-signal mining it parameterized is
    retired — prose the stop lists miss never becomes an ask, so it
    never surfaces as a missing hard skill)."""
    # pylint: disable=unused-argument
    asks = jd_asks.parse_asks(jd_text)
    doc_low = re.sub(r"\s+", " ", " ".join(
        de.text_of(p) for p in de.paras(body))).lower()
    return sorted(a.phrase for a in jd_asks.unhosted(doc_low, asks))


def _jd_requirement_coverage(roles, body, jd_text):
    """Structured JD requirement → evidence map.

    Returns a list of ``(label, status, detail)`` tuples, one per
    qualification line — the caller decides the print format.

    Status values:
      covered  – a kept bullet hosts the ask (detail: up to 2 hosts)
      weak     – only a non-bullet line hosts it (detail: the ask is
                 demonstrably the user's — weave the literal phrase
                 into a bullet, no user confirmation needed)
      uncovered – no host at all (detail: restore/raise, never fabricate)
      by_hand  – no extractable terms on the line (judge manually); a
                 soft-skill ask (communication, leadership, ...) gets a
                 detail pointing at the action-verb evidence rule —
                 presented/demoed/led/mentored/trained bullets are the
                 host, never the literal adjective (SKILL Step 2)

    Cutting off-JD content keeps the resume honest; this keeps it
    QUALIFIED — the resume must demonstrate each JD ask, not merely
    avoid fabricating it. Returns [] when the JD has no qualification
    section (recruiter message).
    """
    qual_lines = _jd_requirement_lines(jd_text)
    if not qual_lines:
        return []
    bullet_hosts = []
    role_bullet_set = set()
    for role in roles:
        for b in role.get("bullet_texts") or []:
            bullet_hosts.append((role["key"], b))
            role_bullet_set.add(b)
    non_bullet_texts = [de.text_of(p) for p in de.paras(body)
                   if de.text_of(p).strip()
                   and de.text_of(p) not in role_bullet_set]
    out = []
    for q in qual_lines:
        terms = _jd_line_terms(q)
        terms |= {c for c in JD_CONCEPTS if c in q.lower()}
        label = q[:64]
        if not terms:
            if JD_SOFT_SKILL_RE.search(q):
                out.append((label, "by_hand",
                            "soft-skill ask — covered by kept action-verb "
                            "evidence (presented, demoed, led, mentored, "
                            "trained); never the literal adjective "
                            "(SKILL Step 8)"))
            else:
                out.append((label, "by_hand", ""))
            continue
        hits = [(k, b) for k, b in bullet_hosts
                if jd_asks.evidence_set(b.lower(), terms)]
        if hits:
            detail = f"{hits[0][0]}: {hits[0][1][:48]}"
            if len(hits) > 1:
                detail += f" (+{len(hits) - 1} more)"
            out.append((label, "covered", detail))
            continue
        if any(jd_asks.evidence_set(t.lower(), terms)
               for t in non_bullet_texts):
            out.append((label, "weak",
                        "proficiency/Tools line only — the ask is "
                        "demonstrably the user's: weave the literal "
                        "phrase into a bullet where used (SKILL Step 6); "
                        "hosting needs no user confirmation"))
            continue
        out.append((label, "uncovered",
                    "no host — restore from the master or raise to "
                    "the user; never fabricate"))
    return out


def _boundaries_without_spacer(body):
    """Inter-role boundaries with no blank spacer paragraph before the
    next company header — the readability pause of SKILL Step 8's
    spacing step, reported instead of remembered. Returns
    (next_role_header, anchor_text) per gap: the anchor is the previous
    role's last non-empty paragraph (usually its Tools line), the
    ``clone_after`` anchor the SKILL prescribes. The first role is
    skipped: the Summary/Proficiencies block above it is not a role
    boundary. A boundary whose anchor is a SectionHeading (e.g. the
    Education heading before a college entry that shares the company
    style) is skipped too — the heading IS the pause.
    """
    ps = de.paras(body)
    out = []
    prev_header_idx = None
    for i, p in enumerate(ps):
        style, _ = de.style_and_numid(p)
        if style != COMPANY_STYLE or not de.text_of(p).strip():
            continue
        if prev_header_idx is not None:
            j = i - 1
            while j >= 0 and not de.text_of(ps[j]).strip():
                j -= 1
            if (j > prev_header_idx and j == i - 1
                    and de.style_and_numid(ps[j])[0] != SECTION_STYLE):
                out.append((de.text_of(p).strip(),
                            de.text_of(ps[j]).strip()))
        prev_header_idx = i
    return out


def _missing_report_block(jd_text, missing):
    """The bounded 'JD terms with NO host' display lines: proper-noun tech
    (ALL-CAPS acronyms, mid-sentence Capitalized — the class external ATS
    extractors find) first, then the rest, capped at MISSING_REPORT_CAP.
    An unbounded list on a narrative JD (a real six-session calibration
    run flagged 173) is an unusable checklist — the agent stops reading
    it."""
    acronyms = _acronym_terms(jd_text)
    tech = [t for t in missing if t in acronyms
            or _jd_capitalized(jd_text, t)]
    rest = [t for t in missing if t not in tech]
    ordered = tech + rest
    shown, overflow = ordered[:MISSING_REPORT_CAP], \
        ordered[MISSING_REPORT_CAP:]
    tail = ""
    if overflow:
        tail = f" (+{len(overflow)} more, strongest signals shown first)"
    lines = [
        "JD terms with NO host in the resume (for each: infer from the "
        "evidence below, or ASK the user — the master/LinkedIn understate "
        "real experience; NEVER fabricate):",
        textwrap.fill(
            ", ".join(shown) + tail,
            width=76,
            initial_indent="  - ",
            subsequent_indent="    "),
    ]
    return lines, shown


def _jd_report(jd_file, jd_text, jd_terms, body=None, sources=None,
               *, extra_missing=()):
    """Lines describing the --jd ranking (printed before the page math).

    Prints the full extracted term list (not just the first 8) plus the JD's
    word count, so a term missing from a paraphrased or summarized JD file
    is visible at a glance. A file under JD_SHORT_WORDS words gets a
    fidelity note (advisory — a recruiter's message is legitimately short).

    With ``body``, also lists JD qualification terms the resume does not
    host anywhere (_jd_missing_terms) — the 'never fabricate' flags made
    mechanical instead of an agent re-reading the posting — followed by
    the deterministic INFERENCE MAP over those terms. ``sources`` carries
    the adjacent master body and optional LinkedIn dump. Each no-host term
    gets a mechanical verdict: AUTO-HOST (evidence found — host it) or
    RAISE (no evidence — ask the user). "No literal host" is a flag to
    infer from, not a verdict. ``extra_missing`` carries external gap
    terms (the ATS gap queue) merged into that internal list before the
    map runs, so the map's verdicts cover the combined queue. Keyword-only
    to keep the positional signature at the lint cap.
    """  # pylint: disable=too-many-arguments
    tmp_note = tmp_jd_note(jd_file)
    words = len(jd_text.split())
    if not jd_terms:
        out = [
            f"JD-aware ranking: no candidate-tech terms in {jd_file} "
            f"intersect the resume's vocabulary — falling back to the "
            f"JD-blind ranking; check the file is the raw JD text.",
        ]
        if tmp_note:
            out.append(tmp_note)
        return out
    lines = [
        f"JD-aware ranking: {len(jd_terms)} term(s) matched from "
        f"{jd_file} ({words} words)",
        textwrap.fill(
            ", ".join(sorted(jd_terms)),
            width=76,
            initial_indent="  ",
            subsequent_indent="  ",
        ),
    ]
    if tmp_note:
        lines.append(tmp_note)
    if words < JD_SHORT_WORDS:
        lines.append(
            f"NOTE: {jd_file} is only {words} words — if it is the full "
            f"posting, verify it was pasted verbatim (paraphrasing can "
            f"drop match terms); a recruiter's message is fine."
        )
    if body is not None:
        missing = list(_jd_missing_terms(jd_text, body, jd_terms))
        for term in extra_missing:
            if term not in missing:
                missing.append(term)
        if missing:
            block, shown = _missing_report_block(jd_text, missing)
            lines.extend(block)
            sources = sources or InferenceSources()
            lines.extend(_inference_map(shown, body, sources))
    return lines


def adjacent_master_body(docx):
    """Load the sole adjacent master as evidence for a tailored copy."""
    directory = os.path.dirname(os.path.abspath(docx))
    candidates = [name for name in os.listdir(directory)
                  if name.endswith(" Master Resume.docx")]
    if len(candidates) != 1:
        return None
    try:
        _, body, _, _, _ = de.load(os.path.join(directory, candidates[0]))
    except (OSError, ValueError):
        return None
    return body


def fail_without_master(queue_label):
    """Exit 2 when the master is not adjacent to the tailored copy.

    The master leg of SKILL Step 8's source-first loop is mandatory,
    not optional: content Phase 1 cut lives ONLY in the master, so a
    mining queue run against the pruned tailored copy silently
    overstates gaps (two real sessions asked the user about evidence
    the master still hosted). A warning was scrollable past; this
    failure makes it impossible to mine without the master present."""
    print(
        f"error: {queue_label} found, but the master resume is not "
        "adjacent to the tailored copy — the JD gap mining queue cannot "
        "be run without searching the full master (SKILL Step 8: the "
        "master leg of the source-first loop is mandatory; content "
        "Phase 1 cut lives only there). Place '<userName> Master "
        "Resume.docx' next to the tailored copy and re-run.",
        file=sys.stderr)
    sys.exit(2)


def _inference_variants(term):
    """Morphological variants of a no-host term to search whole-word:
    the term itself, its singular form (each word's trailing 's'
    stripped, e.g. "llms" -> "llm"), and the hyphen-joined form for
    multiword terms ("customer facing" -> "customer-facing")."""
    words = re.split(r"[\s-]+", term.lower())
    sing = [re.sub(r"s$", "", w) if len(w) > 3 else w for w in words]
    out = {" ".join(words), " ".join(sing)}
    if len(words) > 1:
        out.add("-".join(words))
        out.add("-".join(sing))
    return {v for v in out if v}


def _family_roots(term):
    """Roots of the skill-family the no-host term belongs to, or ()."""
    low = term.lower()
    for keys, roots in INFERENCE_FAMILIES:
        for k in keys:
            if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", low):
                return roots
    return ()


def _inference_map(missing_terms, body, sources=None):
    """Lines of the INFERENCE MAP for the no-host JD terms.

    For each term: search the master paragraphs (and the LinkedIn dump
    when provided) for the term's morphological variants and its
    skill-family roots; print up to _INFERENCE_MATCH_CAP evidence lines
    per source. The verdict is mechanical, not a judgment call:
    AUTO-HOST when evidence was found in the master or LinkedIn material
    (host the JD's literal phrase without asking whether the user has the
    skill; choose the evidence's role, or Summary/Technical Proficiencies
    when no role is identifiable); RAISE when none was found (ask the
    user — real experience is often lexically invisible — and host only
    what they confirm). Returns [] when nothing is missing.
    """
    if not missing_terms:
        return []
    sources = sources or InferenceSources()
    master_loaded = sources.master_body is not None
    ps = de.paras(sources.master_body if master_loaded else body)
    master_texts = [de.text_of(p).strip() for p in ps
                    if de.text_of(p).strip()]
    source_lines = [("master", master_texts)]
    if sources.linkedin_text is not None:
        source_lines.append(("linkedin", [
            ln.strip() for ln in sources.linkedin_text.splitlines()
            if ln.strip()]))
    out = [textwrap.fill(
        "INFERENCE MAP for no-host terms (deterministic evidence search "
        "over the master + LinkedIn): follow the verdicts. AUTO-HOST "
        "terms are hosted without asking the user; the checklist "
        "presented to the user contains exactly the RAISE terms:",
        width=76, initial_indent="  ", subsequent_indent="    ")]
    if not master_loaded:
        out.append(textwrap.fill(
            "  WARNING: the master was NOT searched (no adjacent "
            "'* Master Resume.docx' next to the tailored copy) — the map "
            "searched the tailored copy instead, so content Phase 1 cut "
            "is invisible to it. Grep the raw master for every RAISE "
            "term before asking the user (SKILL Steps 8 and 11): the "
            "user's own history often evidences the ask in a bullet the "
            "prune removed.",
            width=76, initial_indent="  ", subsequent_indent="    "))
    for term in missing_terms:
        _variants = _inference_variants(term)
        _roots = _family_roots(term)

        def _hits(texts, variants=_variants, roots=_roots):
            matched = []
            for t in texts:
                low = t.lower()
                if any(re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])",
                                 low) for v in variants) or \
                        any(r in low for r in roots):
                    matched.append(t)
                    if len(matched) >= _INFERENCE_MATCH_CAP:
                        break
            return matched

        hits_by_source = [(label, _hits(texts))
                          for label, texts in source_lines]
        ev = [f'{label}: "{m[:70]}"'
              for label, matched in hits_by_source for m in matched]
        misses = [f"{label}: no match"
                  for label, matched in hits_by_source if not matched]
        if ev:
            out.append(f"  - {term}: AUTO-HOST — host the JD's literal "
                       "phrase in the bullet/role where this evidence "
                       "lives (merge, don't append); no skill "
                       "confirmation needed")
            out.extend(f"      {e}" for e in ev + misses)
        else:
            out.append(
                f"  - {term}: RAISE — no deterministic evidence — ASK "
                "the user (real experience is often lexically invisible "
                "in the master/LinkedIn — macOS, stress testing, and a "
                "user's 'Linux home lab' evidence were, in a real "
                "session); host only what the user confirms")
            out.extend(f"      {m}" for m in misses)
    out.append(textwrap.fill(
        "AUTO-HOST = evidence exists in master or LinkedIn material — "
        "host without asking about the skill; RAISE = ask about the "
        "skill itself. If no role is identifiable, use Summary/Technical "
        "Proficiencies or ask only about role placement. Host AUTO-HOST "
        "terms first, then present the RAISE checklist (SKILL Step 8).",
        width=76, initial_indent="    ", subsequent_indent="    "))
    return out


def _title_rank(title):
    """Seniority rank of a title string (1=mid/none .. 4=principal)."""
    rank = 1.0
    for rx, r in TITLE_RANK_PATTERNS:
        if rx.search(title):
            rank = max(rank, r)
    return rank


def _jd_title(jd_text):
    """The JD's position title.

    Deterministic under the fixed section contract: the Position Title
    section's body (jd_sections) when present. Otherwise (a recruiter's
    message or a bare posting without the template) the old heuristics
    apply: an explicit 'Job Title:'-style label anywhere, else the first
    non-empty line, skipping 'Posting URL:' lines (SKILL Step 1 persists
    the URL as the file's first line). Returns None when neither
    candidate is a plausible single-line title
    (<= TITLE_MAX_WORDS words, no lowercase sentence continuation).
    """
    position = jd_sections.find_section(jd_text, "Position Title")
    if position:
        for line in position.splitlines():
            if line.strip():
                return line.strip()
    lines = [l.strip() for l in jd_text.splitlines() if l.strip()
             and not l.lstrip().lower().startswith("posting url:")]
    if not lines:
        return None
    for l in lines:
        m = TITLE_LABEL_RE.match(l)
        if m:
            cand = m.group(1).strip().strip('"').strip("'")
            if cand and len(cand.split()) <= TITLE_MAX_WORDS:
                return cand
    cand = re.sub(r"^[\s\-*•\d.)]+", "", lines[0]).strip()
    if (cand and len(cand.split()) <= TITLE_MAX_WORDS
            and not re.search(r"[.!?]\s+[a-z]", cand)):
        return cand
    return None


def _headline_text(body):
    """The headline under the name: the SECOND 'Title'-style paragraph
    (HEADLINE_STYLE); the first is the name line. None when the resume has
    no headline (zero or one Title-style paragraph)."""
    titles = [p for p in de.paras(body)
              if de.style_and_numid(p)[0] == HEADLINE_STYLE]
    if len(titles) < 2:
        return None
    return de.text_of(titles[1]).strip()


def title_alignment_notes(body, jd_text):
    """SKILL Step 5 signal: (severity, message) comparing the resume
    headline against the JD's named title. Severity in warn|ok|note; never
    blocks: extraction and the ladder are heuristics, and a posting may use
    a generic title for a senior role (the message says when to keep the
    headline)."""
    headline = _headline_text(body)
    if headline is None:
        return ("note", "no headline title found (a second "
                         f"'{HEADLINE_STYLE}'-style paragraph after the "
                         "name); skipping the JD-title alignment check")
    jd_title = _jd_title(jd_text)
    if jd_title is None:
        return ("note", f"JD title not extractable (first line or a "
                         f"'Job Title:'-style label, <= {TITLE_MAX_WORDS} "
                         f"words); resume headline {headline!r} left "
                         "unchanged — apply SKILL Step 5 by hand if the "
                         "posting names a less-senior title")
    if headline.strip().lower() == jd_title.lower():
        return ("ok", f"resume headline {headline!r} matches the JD title "
                       "exactly — aligned")
    j_rank, h_rank = _title_rank(jd_title), _title_rank(headline)
    if j_rank < h_rank:
        return ("warn", f"resume headline {headline!r} is MORE SENIOR than "
                         f"the JD title {jd_title!r} — apply SKILL Step 5: "
                         "set the top title to the JD's exact title and "
                         "level the Summary's first-sentence echo. Never "
                         "adopt a MORE senior JD title. A generic posting "
                         "title may understate the level (e.g. 'Software "
                         "Engineer' for a senior role) — keep the headline "
                         "when the role is genuinely at that level.")
    if j_rank > h_rank:
        return ("ok", f"JD title {jd_title!r} is MORE SENIOR than the "
                       f"headline {headline!r} — keep the headline (never "
                       "adopt a more senior title; SKILL Step 5)")
    return ("ok", f"JD title {jd_title!r} is at the SAME level as the "
                   f"headline {headline!r} — same-level retitle to the "
                   "JD's exact name is optional per SKILL Step 5")
