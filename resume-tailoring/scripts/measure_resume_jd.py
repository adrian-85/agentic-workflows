"""measure_resume JD vocabulary / requirements / inference / title analysis. Split from measure_resume.py; imported one-way by measure_resume_drops + the shim."""

# pylint: disable=wrong-import-position,import-outside-toplevel,invalid-name
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.


import re
import textwrap
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
from measure_resume_format import BULLET_STYLES, COMPANY_STYLE, SECTION_PROFICIENCIES, _proficiency_block  # noqa: E402

W = de.W

SECTION_STYLE = "SectionHeading"  # career/education/proficiencies headings


VOCAB_STYLE = "JobTitleBlock"  # job-title paragraphs feed the --jd vocabulary


HEADLINE_STYLE = "Title"  # top-of-resume headline: 2nd 'Title' paragraph after the name


GENERIC_PHRASES = (
    "established", "coordinated", "enhanced", "presented", "mentored",
    "assisted", "advocated", "organized", "scheduled", "attended",
    "facilitated", "streamlined", "ensured", "participated",
)


_NUMBER = re.compile(r"\d|%")


JD_STOP = frozenset({
    # Vague résumé/JD nouns and generic ENGLISH PROSE. Tech words (rest,
    # api, java, sql, testing, ...) are deliberately NOT here: matching is
    # whole-word + capitalized-for-bullet-only-terms + a generic-hit-rate
    # guard, so a JD that names REST or Java now protects the bullets that
    # use them instead of being silenced by the stop list. The stop list is
    # only for words that are NEVER tech evidence.
    "experience", "senior", "staff", "team", "teams", "project",
    "projects", "process", "processes", "product", "products",
    "quality", "engineer", "engineers", "role", "roles", "end",
    "end-to-end", "e2e", "standard", "standards", "deliver",
    "delivered", "delivering", "deliveries",
    "and", "the", "for", "a", "an", "or", "of", "in", "to", "on",
    "with", "from", "into", "them", "they", "their", "each",
    "when", "while", "where", "which", "through", "throughout",
    "than", "then", "also", "both", "over", "more", "most",
    "other", "others", "some", "such", "only", "well", "work",
    "worked", "working", "works", "need", "needs", "using",
    "used", "uses", "across", "against", "within", "without",
    "via", "per", "plus", "near", "among", "along", "since",
    "until", "upon", "about", "after", "before", "during",
    # Qualification-section openers (line-initial caps that would mine as
    # 'skills' once line-start tokens are considered): never tech evidence.
    "approved", "willing", "able", "ready",
    "between", "internal", "external", "global", "globally",
    "international", "meeting", "meetings", "contact", "corporate",
    "clients", "client", "customers", "customer", "hour", "hours",
    "time", "lead", "leads", "leading", "flow", "flows", "gain",
    "gains", "approach", "approaches", "clearly", "clear",
    "required", "require", "requires", "requirement", "requirements",
    "commit", "commits", "committed", "resolution", "resolve",
    "resolved", "support", "supports", "supported", "supporting",
    "issue", "issues", "based", "multiple", "various", "several",
    "include", "includes", "included", "including", "deeply", "deep",
    "key", "core", "strong", "strongly", "solid", "proven",
    "ability", "abilities", "skill", "skills", "skilled",
    "knowledge", "understanding", "complex", "concepts", "concept",
    "bachelor", "degree", "education", "university", "college",
    "business", "businesses", "progress", "flexible", "flexibility",
    "learning", "collaborative", "environment", "environments",
    "practice", "practices", "types", "type", "internally",
})


JD_CONCEPTS = (
    "mentor", "mentoring", "mentorship", "shift-left", "shift left",
    "contract testing", "root-cause", "root cause", "risk-based",
    "exploratory", "chaos", "model-based", "code review", "design review",
    "traceability", "documentation gaps", "go-live", "go live",
    "instructor-led", "incomplete documentation",
)


CORE_TECH_NOUNS = frozenset({
    "api", "apis", "sql", "sdk", "graphql", "grpc", "rest", "soap",
    "json", "xml", "yaml", "integration", "integrations", "backend",
    "database", "databases", "sandbox",
    "regression", "end-to-end", "playwright", "cypress", "selenium",
    "karate", "postman", "jenkins", "docker", "kubernetes", "terraform",
})


JD_SHORT_WORDS = 100  # below this, a --jd file is likely a summary, not the posting


JD_SEQ_TERM_RE = re.compile(
    r"(?<![A-Za-z0-9+#])[A-Z][A-Za-z0-9+#.]+(?:[\s-]+[A-Z][A-Za-z0-9+#.]+)+")


JD_WORD_TERM_RE = re.compile(r"(?<![A-Za-z0-9+#])([A-Z][A-Za-z0-9+#.]+)")


JD_COMPANY_VOICE_RE = re.compile(r"\b(we|our|us|you|your)\b", re.I)


JD_QUAL_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*(?:required\s+|preferred\s+|minimum\s+)?"
    r"(?:qualifications|requirements|skills|experience)\b\s*:?\s*$"
    # A bare "Required:" / "Preferred:" / "Minimum:" heading line — a
    # common short-form JD format where the qualifier IS the whole heading.
    # Without this, such a line (which ends in ':') is read by the
    # collector as a section TERMINATOR instead of a heading, killing the
    # requirement-coverage map (and its never-fabricate guard) for the
    # entire posting.
    r"|^\s*#{0,6}\s*(?:required|preferred|minimum)\s*:?\s*$",
    re.I,
)


JD_SELF_ASSESSMENT = frozenset({
    "excellent", "outstanding", "exceptional", "effective",
    "effectively", "superior", "superb", "expert", "good", "great",
})


JD_SOFT_SKILL_RE = re.compile(
    r"\b(communication|stakeholder|leadership|mentorship|"
    r"collaboration|teamwork|interpersonal|presentation)\b", re.I)


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


def _line_terms(line):
    """Tech terms from one labeled line ("Label: values"): each comma/;
    chunk verbatim (so multi-word "GitHub Actions" stays a phrase) plus
    len>=3 words inside multi-word chunks. Label text (the "Label" side)
    also contributes len>=3 words — so an "API & Web Services" line yields
    "api"/"web"/"services" as claimed vocabulary."""
    terms = set()
    if ":" in line:
        label, value = line.split(":", 1)
    else:
        label, value = None, line
    if label:
        for word in re.findall(r"[a-z0-9][a-z0-9#.+]*", label.lower()):
            if len(word) >= 3 and not re.fullmatch(r"[0-9.]+\w*", word):
                terms.add(word)
    for chunk in re.split(r"[,;]", value):
        chunk = chunk.strip().lower()
        if not chunk:
            continue
        terms.add(chunk)
        if " " in chunk:
            for word in re.findall(r"[a-z0-9][a-z0-9#.+]*", chunk):
                if len(word) >= 3 and not re.fullmatch(r"[0-9.]+\w*", word):
                    terms.add(word)
    return terms


def _vocab_terms(body):
    """The candidate's claimed tech vocabulary: proficiency lines, every
    role's Tools & Technologies line, and job-title paragraphs."""
    terms = set()
    for line in _proficiency_block(body):
        terms |= _line_terms(line)
    for p in de.paras(body):
        t = de.text_of(p)
        if t.lower().startswith("tools") and "technolog" in t.lower():
            terms |= _line_terms(t)
        elif de.style_and_numid(p)[0] == VOCAB_STYLE:
            terms |= _line_terms(t)
    return terms


def _bullet_terms(body):
    """Single-word alnum tokens (len>=4, not stops/numeric) from every
    numbered bullet. This catches candidate tools that appear ONLY in a
    bullet (e.g. Snyk folded into the master, absent from the proficiency
    and Tools lists) — a gap the vocabulary intersection alone misses.
    Prose words are largely filtered by JD_STOP; the token must also appear
    in the JD to become a term, so misses only over-protect when the JD
    itself names a prose word."""
    terms = set()
    for text in _all_bullet_texts(body):
        for w in re.findall(r"[a-z0-9][a-z0-9#.+-]*", text.lower()):
            w = w.rstrip(".,;:!?'")
            if w in JD_STOP or len(w) < 4 or re.fullmatch(r"[0-9.]+\w*", w):
                continue
            terms.add(w)
    return terms


def _all_bullet_texts(body):
    """Texts of every numbered bullet in the document (document order)."""
    out = []
    for p in de.paras(body):
        style, numId = de.style_and_numid(p)
        if (numId in (None, "0") and style not in BULLET_STYLES):
            continue
        out.append(de.text_of(p))
    return out


def _jd_capitalized(jd_text, term):
    """True if ``term`` occurs in the JD as a mid-sentence Capitalized or
    ALL-CAPS token.

    Bullet-only terms (tools named nowhere in the proficiencies/Tools
    vocabulary, e.g. Snyk) must pass this test: tool names are proper
    nouns and stay capitalized mid-sentence in well-formed JDs, while the
    generic prose that floods JD matching (closely, critical, deliver)
    does not. Sentence-start capitals are rejected — every English
    sentence starts capitalized, which would re-admit the prose flood.
    """
    for m in re.finditer(
            r"(?<![A-Za-z0-9#.+-])" + re.escape(term) + r"(?![A-Za-z0-9#.+-])",
            jd_text, re.I):
        if not m.group(0)[0].isupper():
            continue
        pre = jd_text[:m.start()].rstrip()
        if pre and pre[-1] not in ".!?\n":
            return True
    return False


def _jd_terms(jd_text, body):
    """Candidate-technical terms the JD actually asks for: vocabulary and
    bullet-tool terms the JD also names, minus generic stopwords. Empty
    when jd_text is empty/garbage — callers fall back to the JD-blind
    ranking.

    Vocab-derived terms (proficiencies, Tools lines, job titles — the
    candidate's CLAIMED tech) match anywhere in the JD. Bullet-only terms
    must additionally pass _jd_capitalized: they are the prose-flood
    source, and a tool name is a proper noun.

    A GENERIC-HIT-RATE GUARD discards any surviving term that matches more
    than half of the document's bullets: such a term is prose the stop list
    missed, not technology — keeping it would "protect" half the resume and
    stall the DROP PLAN (the consulting-JD flood this guard exists for).
    """
    jd_low = jd_text.lower()
    terms = set()
    for t in _vocab_terms(body):
        # "c#"/"c++"/"f#" are length-2 but unambiguous tech terms.
        if (len(t) < 3 and not re.search(r"[#+]", t)) or t in JD_STOP \
                or re.fullmatch(r"[0-9.]+\w*", t):
            continue
        if t in jd_low:
            terms.add(t)
    for t in _bullet_terms(body):
        if t in jd_low and (_jd_capitalized(jd_text, t)
                            or t in CORE_TECH_NOUNS):
            terms.add(t)
    if terms:
        bullets = _all_bullet_texts(body)
        if len(bullets) >= 6:
            texts_low = [b.lower() for b in bullets]
            generic = set()
            for t in terms:
                hits = sum(1 for b in texts_low if _jd_hits(b, {t}))
                if hits > 0.5 * len(texts_low):
                    generic.add(t)
            terms -= generic
    return terms


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


def _jd_line_terms(line):
    """Tech-term candidates on one qualification line (lowercase): the
    capitalized sequences plus single capitalized tokens — the extraction
    :func:`_jd_missing_terms` mines for missing terms and
    :func:`_jd_requirement_coverage` matches against kept bullets. A
    single token is skipped when a sentence continuation precedes it
    (prose) or the JD's own 'or similar' hedge does (a stand-in for a
    CLASS of tools — reporting it invites fabrication).
    """
    seqs = [m.group(0) for m in JD_SEQ_TERM_RE.finditer(line)]
    terms = {s.lower() for s in seqs}
    seq_words = {w for s in seqs
                 for w in re.split(r"[\s-]+", s.lower())}
    for m in JD_WORD_TERM_RE.finditer(line):
        raw = m.group(1)
        low = raw.lower()
        if (len(low) < 3 and not re.fullmatch(r"[A-Z]{2,}", raw)) \
                or low in JD_STOP or low in JD_SELF_ASSESSMENT \
                or low in seq_words:
            continue
        prev = line[:m.start()]
        if re.search(r"[.!?]\s*$", prev.strip()) \
                or re.search(r"\bsimilar\s+$", prev, re.I):
            continue
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
    tmp_note = de.tmp_jd_note(jd_file)
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
                "JD terms with NO host in the resume (never fabricate — "
                "flag each to the user; the resume answers via 'similar' "
                "tooling only when that is truthful):")
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
                f"  - {term}: NO deterministic evidence — a genuine gap: "
                "raise to the user, do not fabricate")
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


def _jd_hits(text, jd_terms):
    """Sorted list of JD terms present in ``text`` (WHOLE-WORD match,
    lowercase).

    Word-boundary matching, not substring: the substring form made the
    generic token "lead" match "leader/leadership/leading" and "flow"
    match "workflow", protecting bullets that merely share a prose word
    with the JD. Multi-word terms keep their space-separated phrase form;
    single tokens must not be flanked by token characters
    (``[a-z0-9#.+-]``, the same class _bullet_terms tokenizes with).

    Plural tolerance is BIDIRECTIONAL — a singular/plural pair is the SAME
    evidence: a term ending in ``s`` also matches its singular stem as a
    whole word (the JD asks for "API integrations", the bullet says
    "integration test"), and a singular term also matches its ``s``-plural
    (JD: "integration"; bullet: "partner integrations"; JD: "API";
    resume line: "REST APIs"). Keeps genuinely-technical lines (an API
    proficiencies line vs the JD's "APIs") from being misread as off-JD
    cut candidates.
    """
    low = text.lower()
    out = []
    for t in jd_terms:
        if " " in t:
            if t in low:
                out.append(t)
            continue
        cands = {t}
        if len(t) >= 4 and t.endswith("s"):
            cands.add(t[:-1])
        if len(t) >= 3:
            cands.add(t + "s")
        for c in cands:
            if re.search(
                    r"(?<![a-z0-9#.+-])" + re.escape(c) + r"(?![a-z0-9#.+-])",
                    low):
                out.append(t)
                break
    return sorted(out)


def _concept_hits(text):
    """JD practice phrases present in ``text`` (JD_CONCEPTS)."""
    low = text.lower()
    return [c for c in JD_CONCEPTS if c in low]


def _weakness_key(text):
    """Deterministic weakness sort key for a bullet: weakest first.

    Order: (1) no hard number + generic phrasing (clearest drop), (2) no
    hard number, (3) hard number present (strongest — keep). Ties break
    toward LONGER text (cutting it saves more rendered lines).
    """
    low = text.lower()
    has_number = bool(_NUMBER.search(text))
    generic = any(phrase in low for phrase in GENERIC_PHRASES)
    return (1 if has_number else 0,
            0 if generic else 1,
            -len(text))


def _is_protected(text, protect):
    """True if ``text`` contains any ``protect`` phrase (case-insensitive)."""
    low = text.lower()
    return any(p.lower() in low for p in protect)


def _weak_jd_terms(bullets, jd_terms):
    """JD terms whose whole-word match hits MORE than half of ``bullets``.

    Inside that corpus the term cannot arbitrate between bullets — every
    "test engineer" bullet matches a testing JD's ``test`` — so a hit on a
    weak term is weak protection evidence (SKILL Step 8): it is displayed
    as ``[weak: term]`` and does NOT make a bullet immune to the DROP
    PLAN. Per-role, not global: ``test`` stays strong evidence in a role
    where it discriminates and is weak in a role where every bullet
    carries it. The global >50% guard in ``_jd_terms`` still removes
    resume-wide flood terms before this runs.

    CORE_TECH_NOUNS (api, sql, playwright, ...) are exempt — a specific
    technology noun matching every bullet of a role is genuine evidence,
    exactly what a whole-role drop must not remove (SKILL Step 3). The
    weak class is for generic single words (test, code, new, build, ...)
    whose resume-wide match rate is what made two real sessions shield a
    1-year role's 16+ bullets while JD-relevant older-role bullets died.
    """
    if not jd_terms or not bullets:
        return set()
    low = [b.lower() for b in bullets]
    weak = set()
    for t in jd_terms:
        if t in CORE_TECH_NOUNS:
            continue
        hits = sum(1 for b in low if _jd_hits(b, {t}))
        if hits > 0.5 * len(low):
            weak.add(t)
    return weak


def _jd_hits_classified(text, jd_terms, corpus):
    """(strong_hits, weak_hits) for ``text`` against ``jd_terms``.

    A hit is weak when its term matches >50% of ``corpus`` (the role's own
    bullets — see :func:`_weak_jd_terms`). Strong hits protect; weak hits
    are display-only evidence that the human rule may override.
    """
    hits = _jd_hits(text, jd_terms)
    if not hits:
        return [], []
    weak = _weak_jd_terms(corpus, jd_terms)
    strong = [h for h in hits if h not in weak]
    return strong, [h for h in hits if h in weak]


def _jd_kept(text, jd_terms, corpus=None):
    """True if STRONG JD evidence (a non-weak matched term or a JD practice
    phrase).

    ``corpus`` (the role's own bullet list) makes a matched term weak when
    it hits >half the role's bullets: such a match protects nothing (every
    bullet in the role matches it), so a bullet whose ONLY matches are
    weak is NOT kept — it stays cuttable and the plan names it directly
    instead of dead-ending on nominal protection.
    """
    if corpus is None:
        strong = _jd_hits(text, jd_terms)
    else:
        strong, _ = _jd_hits_classified(text, jd_terms, corpus)
    return bool(strong) or bool(_concept_hits(text))
