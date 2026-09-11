"""measure_resume JD vocabulary, term mining, and hit classification. Split from measure_resume_jd.py; imported one-way by the jd analysis module, measure_resume_drops, and the shim."""  # pylint: disable=line-too-long  # (long string/help literal)
# pylint: disable=invalid-name,wrong-import-position
# invalid-name: JD vocabulary constants use the file's domain naming.
# wrong-import-position: flat-namespace sibling imports must follow the
#   sys.path bootstrap (spec 2026-09-07-pylint-clean-refactor).
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use.


import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
from measure_resume_format import BULLET_STYLES, _proficiency_block  # noqa: E402

VOCAB_STYLE = "JobTitleBlock"  # job-title paragraphs feed the --jd vocabulary


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
    "sound", "proficiency", "proficient", "comfortable", "comfort",
    "depth", "hands", "treat", "background", "familiarity",
    "rigorous", "rigor", "commitment", "passion", "excitement",
    # Real-session artifacts: sentence-initial soft nouns of qual lines
    # ("Sound judgment on...", "Hands-on with...") mined as no-host
    # 'gaps'; buried the real asks. Tech words are deliberately NOT here.
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


def _line_terms(line):
    """Tech terms from one labeled line ("Label: values"): each comma/;
    chunk verbatim (so multi-word "GitHub Actions" stays a phrase) plus
    len>=3 words inside multi-word chunks. Label text (the "Label" side)
    also contributes len>=3 words — so an "API & Web Services" line yields
    "api"/"web"/"services" as claimed vocabulary.

    ALL-CAPS tokens of length>=2 are kept as acronyms regardless of
    length — a "CI/CD: Jenkins, ..." line must yield "ci", or the JD's
    "CI" ask never intersects the claimed vocabulary; a real
    Endpoint session cut CI evidence from every role this way.
    """
    terms = set()
    if ":" in line:
        label, value = line.split(":", 1)
    else:
        label, value = None, line
    if label:
        terms |= _acronym_terms(label)
        for word in re.findall(r"[a-z0-9][a-z0-9#.+]*", label.lower()):
            if len(word) >= 3 and not re.fullmatch(r"[0-9.]+\w*", word):
                terms.add(word)
    for chunk in re.split(r"[,;]", value):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Sentence-final punctuation must not ride inside a term: a
        # chunk 'KVM.' mined as 'kvm.' — a form no resume hosts.
        terms.add(chunk.rstrip(".,;:!?'").lower())
        if " " in chunk:
            terms |= _acronym_terms(chunk)
            for word in re.findall(r"[a-z0-9][a-z0-9#.+]*", chunk.lower()):
                if len(word) >= 3 and not re.fullmatch(r"[0-9.]+\w*", word):
                    terms.add(word)
    return terms


def _acronym_terms(text):
    """ALL-CAPS tokens (len>=2, trailing period stripped) of ``text``,
    lowercased — CI, CD, AWS. Unambiguous acronyms the length>=3 word
    scan drops; see :func:`_line_terms` for why "CI" must survive."""
    return {m.group(0).rstrip(".").lower()
            for m in re.finditer(r"[A-Z][A-Z0-9#+]*(?:\.[A-Z0-9#+]+)*\.?",
                                 text)
            if len(m.group(0).rstrip(".")) >= 2}


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

    A sentence-final period is a boundary, not a token char: ``.`` sits in
    the token class for versioned forms (``node.js``), which made
    "...built with Playwright." — the term at sentence END — unmatchable,
    and the bullet read as off-JD (a real matcher bug found 2026-09-11).
    The lookahead now rejects only a token char or a dot FOLLOWED by a
    token char (``node.js`` stays one token); a sentence-final period
    passes.
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
                    r"(?<![a-z0-9#.+-])" + re.escape(c)
                    + r"(?![a-z0-9#+-]|\.[a-z0-9#+-])",
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
