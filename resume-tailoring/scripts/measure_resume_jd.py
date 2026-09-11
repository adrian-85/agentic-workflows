"""measure_resume JD requirements / coverage / inference / title analysis. Split from measure_resume.py; term vocabulary/mining lives in measure_resume_jd_terms (imported one-way from there); imported one-way by measure_resume_drops + the shim."""  # pylint: disable=line-too-long  # (long string/help literal)
# pylint: disable=invalid-name
# invalid-name: JD vocabulary constants use the file's domain naming.
# wrong-import-position: flat-namespace sibling imports must follow the
#   sys.path bootstrap (spec 2026-09-07-pylint-clean-refactor).
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use. Lazy imports are deliberate (cycle
# avoidance / heavy deps) — see the rationale at each site.


import re
import textwrap
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
from docx_edit_gate import tmp_jd_note  # noqa: E402
from measure_resume_format import COMPANY_STYLE, SECTION_PROFICIENCIES  # noqa: E402
from measure_resume_jd_terms import (JD_CONCEPTS, JD_STOP,  # noqa: E402
                                     _concept_hits, _jd_hits)

W = de.W

SECTION_STYLE = "SectionHeading"  # career/education/proficiencies headings


HEADLINE_STYLE = "Title"  # top-of-resume headline: 2nd 'Title' paragraph after the name


JD_SHORT_WORDS = 100  # below this, a --jd file is likely a summary, not the posting


JD_SEQ_TERM_RE = re.compile(
    r"(?<![A-Za-z0-9+#])[A-Z][A-Za-z0-9+#.]+(?:[\s-]+[A-Z][A-Za-z0-9+#.]+)+")


JD_WORD_TERM_RE = re.compile(r"(?<![A-Za-z0-9+#])([A-Z][A-Za-z0-9+#.]+)")


JD_COMPANY_VOICE_RE = re.compile(r"\b(we|our|us|you|your)\b", re.I)


JD_QUAL_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*(?:required\s+|preferred\s+|minimum\s+)?"
    r"(?:qualifications|requirements|skills|experience)\b\s*:?\s*$"
    # Conversational heading forms ("Who you are", "What you'll do") —
    # common startup-style JD headings whose bullet lines are still asks.
    r"|^\s*(?:who\s+you\s+are|about\s+you|your\s+profile"
    r"|what\s+you.?ll\s+(?:do|bring))\s*:?\s*$"
    # A bare "Required:" / "Preferred:" / "Minimum:" heading line — a
    # common short-form JD format where the qualifier IS the whole heading.
    # Without this, such a line (which ends in ':') is read by the
    # collector as a section TERMINATOR instead of a heading, killing the
    # requirement-coverage map (and its never-fabricate guard) for the
    # entire posting.
    r"|^\s*#{0,6}\s*(?:required|preferred|minimum)\s*:?\s*$"
    # "You Bring" / "What You'll Bring" headings — a common modern JD
    # label for the qualification section (e.g. OnePay's QE Platform
    # posting). Without it the requirement-coverage map (and its
    # never-fabricate guard) silently stays silent for the whole posting.
    r"|^\s*#{0,6}\s*(?:what\s+)?you(?:'ll)?\s+bring\s*:?\s*$",
    re.I,
)


JD_SELF_ASSESSMENT = frozenset({
    "excellent", "outstanding", "exceptional", "effective",
    "effectively", "superior", "superb", "expert", "good", "great",
})


JD_SOFT_SKILL_RE = re.compile(
    r"\b(communication|stakeholder|leadership|mentorship|"
    r"collaboration|teamwork|interpersonal|presentation|reliability|"
    r"dependability|ownership|accountability|adaptability|autonomy)\b",
    re.I)


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
        if _jd_hits(t, jd_terms) or _concept_hits(t):
            continue
        prefix = de.shortest_unique_prefix(texts, i, min_len=6)
        if prefix is not None:
            out.append((prefix, t.strip()))
    return out


def _jd_requirement_lines(jd_text):
    """The JD's qualification lines — where skill asks live.

    Everything between a 'Required/Preferred Qualifications'-style
    heading and the next heading-like line. The title line, mission
    prose, and benefits are excluded by construction, so company and
    program names cannot surface as 'missing skills'. Returns [] when no
    qualification heading exists (a recruiter's message) — mining it
    would be unbounded prose, so the missing-terms check stays silent.
    """
    lines = jd_text.splitlines()
    out, collecting = [], False
    for line in lines:
        s = line.strip()
        if JD_QUAL_HEADING_RE.match(s):
            collecting = True
            continue
        if not s:
            continue
        if collecting:
            if s.endswith(":") or JD_QUAL_HEADING_RE.match(s):
                collecting = False
                continue
            if not JD_COMPANY_VOICE_RE.search(s):
                out.append(s)
    return out


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
    """Tech-term candidates on one qualification line (lowercase): the
    capitalized sequences plus single capitalized tokens — the extraction
    :func:`_jd_missing_terms` mines for missing terms and
    :func:`_jd_requirement_coverage` matches against kept bullets. A
    single token is skipped when a sentence continuation precedes it
    (prose) or the JD's own 'or similar' hedge does (a stand-in for a
    CLASS of tools — reporting it invites fabrication).
    """
    seqs = [m.group(0).rstrip(".") for m in JD_SEQ_TERM_RE.finditer(line)]
    terms = {s.lower() for s in seqs if len(s.rstrip(".")) >= 2
             and re.search(r"[A-Za-z]", s)}
    seq_words = {w for s in seqs
                 for w in re.split(r"[\s-]+", s.lower())}

    def _admit(low, raw_pos):
        if (len(low) < 3 and not re.fullmatch(r"[A-Z]{2,}", low)) \
                or low in JD_STOP or low in JD_SELF_ASSESSMENT \
                or low in seq_words:
            return False
        prev = line[:raw_pos]
        if re.search(r"[.!?]\s*$", prev.strip()) \
                or re.search(r"\bsimilar\s+$", prev, re.I):
            return False
        return True

    for m in JD_WORD_TERM_RE.finditer(line):
        if _admit(m.group(1).lower(), m.start(1)):
            terms.add(m.group(1).lower().rstrip("."))
    # camelCase/mixed-case tokens (macOS, iOS, PyAutoGUI) start lowercase
    # — invisible to the Capitalized-token regex (a real session's
    # no-host list missed 'macOS' for exactly this reason).
    for m in re.finditer(
            r"(?<![A-Za-z0-9+#])([A-Za-z][a-z0-9+#]*[A-Z][A-Za-z0-9+#]*)",
            line):
        low = m.group(1).lower().rstrip(".")
        if _admit(low, m.start(1)):
            terms.add(low)
    return terms


def _jd_missing_terms(jd_text, body, jd_terms):
    """JD-side skill terms the resume does not host anywhere.

    ``jd_terms`` is the intersection (JD ask ∩ resume vocabulary), so a
    required skill the resume cannot host — REST Assured against a
    Postman/Karate history — never appears in any JD-aware section: the
    omission surfaces only if the agent re-reads the JD, and a preferred
    qual can be missed entirely (one was, until a final-review grep).
    This mines the qualification lines for capitalized tech-term
    candidates and returns those with no host in the document, so the
    'never fabricate' flags are mechanical. Heuristic and advisory:
    review each against the posting before acting.
    """
    qual_lines = _jd_requirement_lines(jd_text)
    if not qual_lines:
        return []
    doc_low = re.sub(r"\s+", " ", " ".join(
        de.text_of(p) for p in de.paras(body))).lower()
    doc_flat = re.sub(r"[\s-]+", "", doc_low)

    def hosted(term_low):
        if re.search(rf"(?<![a-z0-9]){re.escape(term_low)}(?![a-z0-9])",
                     doc_low):
            return True
        return re.sub(r"[\s-]+", "", term_low) in doc_flat

    missing = set()
    for line in qual_lines:
        for t in _jd_line_terms(line):
            if t in jd_terms or hosted(t):
                continue
            if all(hosted(w) for w in re.split(r"[\s-]+", t)):
                continue
            missing.add(t)
    return sorted(missing)


def _jd_requirement_coverage(roles, body, jd_text):
    """Structured JD requirement → evidence map.

    Returns a list of ``(label, status, detail)`` tuples, one per
    qualification line — the caller decides the print format.

    Status values:
      covered  – a kept bullet hosts the ask (detail: up to 2 hosts)
      weak     – only a non-bullet line hosts it (detail: weave-in
                 guidance, SKILL Step 5)
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
                            "(SKILL Step 2)"))
            else:
                out.append((label, "by_hand", ""))
            continue
        hits = [(k, b) for k, b in bullet_hosts if _jd_hits(b, terms)]
        if hits:
            detail = f"{hits[0][0]}: {hits[0][1][:48]}"
            if len(hits) > 1:
                detail += f" (+{len(hits) - 1} more)"
            out.append((label, "covered", detail))
            continue
        if any(_jd_hits(t, terms) for t in non_bullet_texts):
            out.append((label, "weak",
                        "proficiency/Tools line only — weave into a "
                        "bullet where used (SKILL Step 5)"))
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


def _jd_report(jd_file, jd_text, jd_terms, body=None, evidence_text=None):
    """Lines describing the --jd ranking (printed before the page math).

    Prints the full extracted term list (not just the first 8) plus the JD's
    word count, so a term missing from a paraphrased or summarized JD file
    is visible at a glance. A file under JD_SHORT_WORDS words gets a
    fidelity note (advisory — a recruiter's message is legitimately short).

    With ``body``, also lists JD qualification terms the resume does not
    host anywhere (_jd_missing_terms) — the 'never fabricate' flags made
    mechanical instead of an agent re-reading the posting — followed by
    the deterministic INFERENCE MAP over those terms (master + LinkedIn
    evidence search; ``evidence_text``). "No literal host" is a flag to
    infer from, not a verdict.
    """
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
        missing = _jd_missing_terms(jd_text, body, jd_terms)
        if missing:
            lines.append(
                "JD terms with NO host in the resume (for each: infer "
                "from the evidence below, or ASK the user — the master/"
                "LinkedIn understate real experience; NEVER fabricate):")
            lines.append(textwrap.fill(
                ", ".join(missing),
                width=76,
                initial_indent="  - ",
                subsequent_indent="    "))
            lines.extend(_inference_map(missing, body, evidence_text))
    return lines


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


def _inference_map(missing_terms, body, evidence_text=None):
    """Lines of the INFERENCE MAP for the no-host JD terms.

    For each term: search the master paragraphs (and the LinkedIn dump
    when provided) for the term's morphological variants and its
    skill-family roots; print up to _INFERENCE_MATCH_CAP evidence lines
    per source. A term with any hit is a CANDIDATE (the agent verifies
    and hosts truthfully); one with none is a genuine gap to raise, not
    fabricate. Returns [] when nothing is missing.
    """
    if not missing_terms:
        return []
    ps = de.paras(body)
    master_texts = [de.text_of(p).strip() for p in ps
                    if de.text_of(p).strip()]
    evidence_lines = ([ln.strip() for ln in evidence_text.splitlines()
                       if ln.strip()] if evidence_text else [])
    sources = (("master", master_texts),
               ("linkedin", evidence_lines))
    out = [textwrap.fill(
        "INFERENCE MAP for no-host terms (deterministic evidence search "
        "over the master + LinkedIn; judge each candidate against the "
        "user's real experience before hosting — never fabricate):",
        width=76, initial_indent="  ", subsequent_indent="    ")]
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

        ev = []
        for label, texts in sources:
            ev.extend(f'{label}: "{m[:70]}"' for m in _hits(texts))
        if ev:
            out.append(f"  - {term}: CANDIDATE")
            out.extend(f"      {e}" for e in ev)
        else:
            out.append(
                f"  - {term}: NO deterministic evidence — do NOT treat as "
                "a closed gap: ASK the user (real experience is often "
                "lexically invisible in the master/LinkedIn — macOS, "
                "stress testing, and a user's 'Linux home lab' evidence "
                "were, in a real session); host only what the user "
                "confirms")
    out.append(textwrap.fill(
        "CANDIDATE = evidence exists; host the JD's literal phrase in the "
        "truthful bullet and present the whole map — candidates AND gaps — "
        "to the user in ONE message (SKILL Step 2).",
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
    """Best-effort extraction of the JD's position title.

    Prefers an explicit 'Job Title:'-style line anywhere in the posting;
    otherwise uses the first non-empty line (JDs normally open with the
    title). Lines beginning 'Posting URL:' are skipped — SKILL Step 1
    persists the job posting URL as the JD file's first line, and that
    metadata line must never become the title. Returns None when neither
    candidate is a plausible single-line title
    (<= TITLE_MAX_WORDS words, no lowercase sentence continuation) — the
    posting may be a recruiter message or boilerplate, so the check is
    skipped, never guessed.
    """
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
    """SKILL Step 4 signal: (severity, message) comparing the resume
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
                         "unchanged — apply SKILL Step 4 by hand if the "
                         "posting names a less-senior title")
    if headline.strip().lower() == jd_title.lower():
        return ("ok", f"resume headline {headline!r} matches the JD title "
                       "exactly — aligned")
    j_rank, h_rank = _title_rank(jd_title), _title_rank(headline)
    if j_rank < h_rank:
        return ("warn", f"resume headline {headline!r} is MORE SENIOR than "
                         f"the JD title {jd_title!r} — apply SKILL Step 4: "
                         "set the top title to the JD's exact title and "
                         "level the Summary's first-sentence echo. Never "
                         "adopt a MORE senior JD title. A generic posting "
                         "title may understate the level (e.g. 'Software "
                         "Engineer' for a senior role) — keep the headline "
                         "when the role is genuinely at that level.")
    if j_rank > h_rank:
        return ("ok", f"JD title {jd_title!r} is MORE SENIOR than the "
                       f"headline {headline!r} — keep the headline (never "
                       "adopt a more senior title; SKILL Step 4)")
    return ("ok", f"JD title {jd_title!r} is at the SAME level as the "
                   f"headline {headline!r} — same-level retitle to the "
                   "JD's exact name is optional per SKILL Step 4")
