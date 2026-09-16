"""jd_asks — the ONE rules engine for JD ask determination.

Every consumer (auto_prune's machine prune, measure's coverage/missing
reports, ats_audit's literal audit) runs the SAME determination in two
directions over the same content:

  positive — an ask with no host in the deliverable is a MINING QUEUE
             item (host it truthfully or raise the gap; never fabricate);
  negative — content unit (bullet/sentence/line) evidencing no ask is CUT.

One extraction (parse_asks), one matcher (hosted), one evidence rule
(evidence). The engine has two Ask classes:
  hard    — literal tech phrases/tokens; matched by hosted() everywhere
            (word-boundary + trailing plural + punctuation-stripped
            fallback — the external ATS ground truth);
  concept — JD practice phrases (shift-left, root cause, mentorship...)
            matched by stem-aware concept evidence on both sides.

Soft-skill lines are intentionally a separate qualification-line
classification (`soft_lines`), not Ask records: soft skills never protect
content during Phase 1, while Phase 2 hosts their literal phrases from
action-verb evidence.

Extraction sources: qualification lines (cue-tail n-grams + anchored
tokens — the strict form) and whole-posting repetition (a token/bigram
the JD names twice or more, gated by tech anchors / capitalization /
acronym status — prose like 'help'/'new'/'high' never becomes an ask).
"""

import re
import sys
from collections import Counter
from typing import NamedTuple

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from measure_resume_jd_terms import (CORE_TECH_NOUNS, JD_CONCEPTS,  # noqa: E402
                                     JD_METRIC_HEADS, JD_SOFT_SKILL_RE,
                                     JD_STOP, _acronym_terms,
                                     _adjacent_bigrams, _jd_term_freq,
                                     _norm_text)

# --------------------------------------------------------------------- #
# Qualification-section detection (moved from measure_resume_jd — the
# engine owns JD parsing; measure_resume_jd re-imports these).
# --------------------------------------------------------------------- #
JD_SHORT_WORDS = 100  # below this, a --jd file is likely a summary

JD_SEQ_TERM_RE = re.compile(
    r"(?<![A-Za-z0-9+#])[A-Z][A-Za-z0-9+#.]+(?:[\s-]+[A-Z][A-Za-z0-9+#.]+)+")

JD_WORD_TERM_RE = re.compile(r"(?<![A-Za-z0-9+#])([A-Z][A-Za-z0-9+#.]+)")

JD_COMPANY_VOICE_RE = re.compile(r"\b(we|our|us|you|your)\b", re.I)

JD_QUAL_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*(?:required\s+|preferred\s+|minimum\s+)?"
    r"(?:qualifications|requirements|skills(?:\s*/\s*experience)?|experience)\b\s*:?\s*$"
    # Conversational heading forms ("Who you are", "What you'll do") —
    # common startup-style JD headings whose bullet lines are still asks.
    r"|^\s*(?:who\s+you\s+are|about\s+you|your\s+profile"
    r"|what\s+you(?:.{0,2}ll|\s+will)\s+(?:do|bring)"
    r"|what\s+we(?:'re|\s+are)\s+looking\s+for"
    r"|what\s+will\s+set\s+you\s+apart)\s*:?\s*$"
    # A bare "Required:" / "Preferred:" / "Minimum:" heading line — a
    # common short-form JD format where the qualifier IS the whole heading.
    r"|^\s*#{0,6}\s*(?:required|preferred|minimum)\s*:?\s*$"
    # "You Bring" / "What You'll Bring" / "You Have" headings — the
    # "You Have:" form is Workday/agency-common (Merkle QA Lead JD).
    r"|^\s*#{0,6}\s*(?:what\s+)?you(?:'ll)?\s+(?:bring|have)\s*:?\s*$"
    # "What makes you a fit" — HubSync-style fit heading; its lines ARE asks.
    r"|^\s*what\s+makes\s+you\s+(?:a\s+)?fit\s*:?\s*$"
    # A bare section word heading ("Level") — terminates the section.
    r"|^\s*#{0,6}\s*level\s*:?\s*$"
    # Workday-style sections whose lines are asks (six-session calibration).
    r"|^\s*#{0,6}\s*(?:essential\s+functions|basic\s+requirements"
    r"|minimum\s+requirements|key\s+requirements"
    r"|knowledge,?\s+skills,?(?:\s+and|\s*&)?\s+abilities?)\s*:?\s*$"
    r"|^\s*#{0,6}\s*craft\s*(?:&|and)\s*technical\s+requirements\s*:?\s*$",
    re.I,
)

JD_NEGATED_HEADING_RE = re.compile(
    r"^\s*what\s+this\s+role\s+is\s+(?:not|n[o']t)\s*:?\s*$", re.I)


def requirement_lines(jd_text):
    """The JD's qualification lines — where skill asks live (moved from
    measure_resume_jd verbatim; see that module's history)."""
    lines = jd_text.splitlines()
    out, collecting = [], False
    for line in lines:
        s = line.strip()
        if JD_NEGATED_HEADING_RE.match(s):
            collecting = False
            continue
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


# --------------------------------------------------------------------- #
# Hard-ask extraction (ported from ats_audit's calibrated filters)
# --------------------------------------------------------------------- #
# Function words: an n-gram containing one is not a phrase. Unlike the
# single-word JD_STOP, "quality" must stay usable here — "data quality"
# and "quality assurance" were a real session's top literal misses.
_STRUCTURE_STOP = frozenset({
    "and", "the", "for", "a", "an", "or", "of", "in", "to", "on",
    "with", "from", "into", "them", "they", "their", "each", "when",
    "while", "where", "which", "through", "throughout", "than", "then",
    "also", "both", "over", "more", "most", "other", "others", "some",
    "such", "only", "well", "using", "used", "uses", "across",
    "against", "within", "without", "via", "per", "plus", "near",
    "among", "along", "since", "until", "upon", "about", "after",
    "before", "during", "another", "related", "any", "all", "as",
    "whether", "that", "this", "these", "those", "how", "why",
    "should", "would", "can", "could", "will", "must", "may", "might",
    "every", "not", "no",
})

# Vague qualification nouns: never evidence alone, but fine inside a
# phrase ("quality assurance", "test automation").
_VAGUE_STOP = frozenset({
    "experience", "minimum", "years", "proficiency", "proficient",
    "ability", "abilities", "skill", "skills", "skilled", "knowledge",
    "understanding", "degree", "bachelor", "education", "relevant",
    "strong", "solid", "proven", "excellent", "required", "preferred",
    "demonstrated", "working", "field", "areas", "area", "role",
    "roles", "team", "teams", "environment", "candidate", "candidates",
    "master",  # 'a Master's degree' — education, not a skill ask
    # Ambient nouns (the retired AMBIENT_TECH_NOUNS): never asks alone,
    # fine inside a phrase ("AWS services", "platform engineering").
    "service", "services", "server", "servers", "tool", "tools",
    "tooling", "platform", "platforms", "management",
})

# QA/tech anchor words: a phrase must contain one to be a skill ask, and
# a repeated lowercase token must be one to become an ask at all — the
# gate that keeps responsibility-prose ('help', 'new', 'high', 'leader')
# out of the ask list (a real consulting JD's 98-term list was mostly
# this prose; it "protected" every bullet and stalled the prune).
_TECH_ANCHORS = frozenset({
    "quality", "assurance", "test", "testing", "tests", "automation",
    "automated", "data", "database", "databases", "pipeline",
    "pipelines", "analytics", "framework", "frameworks", "regression",
    "integration", "hipaa", "phi", "sql", "python", "api", "apis",
    "agile", "validation", "software", "engineering", "developer",
    "development", "ci", "cd", "sdlc", "etl", "dashboard", "dashboards",
    "scripting", "backend", "frontend", "unit", "functional", "qa",
    # AI-era asks: a JD names these repeatedly in prose, and they are
    # the asks — not noise.
    "ai", "ml", "llm", "llms", "genai", "agent", "agents", "agentic",
    "model", "models", "prompt", "prompts", "defect", "defects",
    "code", "analysis", "observability", "governance", "nlp",
    "prediction", "predictive", "context", "harness", "harnesses",
    "request", "requests", "linux", "bash", "batch", "windows",
})

# Seniority/level words: mid-sentence Capitalized ('Staff or Senior') is a
# LEVEL, never a skill ask — never mine as a capitalized mention.
_LEVEL_WORDS = frozenset({
    "staff", "senior", "principal", "junior", "remote", "hybrid",
    "onsite", "mid",
})

# Skill-introducing cues: literal skill asks follow these. Phrases are
# mined ONLY from the tails they introduce.
_CUE_RE = re.compile(
    r"\b(?:experience|proficiency|knowledge|familiarity)\s+"
    r"(?:of|in|with|testing|performing|designing|establishing|building)?"
    r"|\b(?:including|such as|used for|with)\b", re.I)
_TAIL_STRIP_RE = re.compile(r"^(?:a|an|the|their|and|or|like)\s+", re.I)


def _cue_tails(line):
    """Tokenized windows (max 5 words, first 3 comma segments) after each
    skill-introducing cue."""
    tails = []
    for m in _CUE_RE.finditer(line):
        tail = line[m.end():].lstrip()
        for segment in tail.split(",")[:3]:
            segment = _TAIL_STRIP_RE.sub("", segment.lstrip())
            words = [w.lower()
                     for w in re.split(r"[^A-Za-z0-9+#\-]+", segment)
                     if len(w) > 1][:5]
            if words:
                tails.append(words)
    return tails


def _single_token_terms(line):
    """Capitalized/tech single tokens in a JD line."""
    terms = set()

    def _clean(t):
        return t.lower().rstrip(".")

    # SEQ matching runs per sentence: the sequence regex's char class
    # includes '.', so without the split "Kubernetes. Docker. AWS" glued
    # into one cross-sentence "product name".
    for part in re.split(r"(?<=[.!?])\s+", line):
        for m in JD_SEQ_TERM_RE.finditer(part):
            terms.add(_clean(m.group(0)))
    for m in JD_WORD_TERM_RE.finditer(line):
        low = m.group(1).lower().rstrip(".")
        # A line-initial capital is prose ('Assess whether...') — unless
        # it opens a comma list ('Java, Python, C#'), where it is an ask.
        if m.start() == 0 and not re.match(r"[A-Za-z0-9+#.]+,\s", line):
            continue
        if low in _VAGUE_STOP or low in JD_STOP:
            continue
        if re.search(r"[.!?]\s*$", line[:m.start()].strip()):
            continue
        terms.add(low)
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9+#\-]*", line):
        low = tok.lower().rstrip(".")
        if low in CORE_TECH_NOUNS or re.search(r"[#+]", low) or (
                len(low) >= 2 and low.isupper()):
            terms.add(low)
    # camelCase/mixed-case tokens (macOS, iOS, PyAutoGUI) start lowercase
    # — invisible to the Capitalized-token regex (a real session's
    # no-host list missed 'macOS' for exactly this reason).
    for m in re.finditer(
            r"(?<![A-Za-z0-9+#])([A-Za-z][a-z0-9+#]*[A-Z][A-Za-z0-9+#]*)",
            line):
        low = m.group(1).lower().rstrip(".")
        if low in _VAGUE_STOP or low in JD_STOP:
            continue
        if re.search(r"[.!?]\s*$", line[:m.start()].strip()):
            continue
        terms.add(low)
    return terms


def _phrase_terms(line):
    """2-3 word skill phrases in the tails of skill-introducing cues."""
    terms = set()
    for tail in _cue_tails(line):
        for size in (3, 2):
            for i in range(len(tail) - size + 1):
                gram = tail[i:i + size]
                if any(w in _STRUCTURE_STOP for w in gram):
                    continue
                if all(w in JD_STOP or w in _VAGUE_STOP for w in gram):
                    continue
                if not any(w in _TECH_ANCHORS or w in CORE_TECH_NOUNS
                           for w in gram):
                    continue
                first = gram[0]
                if (first.endswith("ing")
                        and first not in _TECH_ANCHORS
                        and first not in CORE_TECH_NOUNS
                        and first not in JD_STOP
                        and first not in _VAGUE_STOP):
                    continue
                if len(set(gram)) < size:
                    continue
                terms.add(" ".join(gram))
    return terms


def _capitalized_mention(jd_text, term):
    """True when ``term`` occurs Capitalized mid-sentence (not
    line/sentence-initial).

    Product/ask names stay capitalized wherever they appear ('Hands-on
    Cypress. CI/CD with Jenkins.' names both) — sentence-final
    punctuation after the word is normal text, not a token boundary.
    Sentence-start capitals are rejected: every English sentence starts
    capitalized, which would re-admit the prose flood."""
    for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(term) +
                         r"(?![A-Za-z0-9])", jd_text, re.I):
        if not m.group(0)[0].isupper():
            continue
        pre = jd_text[:m.start()].rstrip(" \t")
        if pre and pre[-1] in ".!?\n":
            continue  # sentence/line-initial capital: prose, not an ask
        # a post-colon capital ('Required: Python and SQL.') is a LIST
        # item — the heading/label owns the colon, the capital is an ask.
        return True
    return False


def _first_heading_offset(jd_text):
    """Character offset of the first recognized qualification heading
    (None when the posting has none — a recruiter message)."""
    pos = 0
    for ln in jd_text.splitlines(keepends=True):
        if JD_QUAL_HEADING_RE.match(ln.strip()):
            return pos
        pos += len(ln)
    return None


def _repeated_terms(jd_text):
    # too-many-locals/branches: the admission gates are the engine's
    # calibrated rules; splitting them hides the ask decision from review.
    # pylint: disable=too-many-locals,too-many-branches
    """Whole-posting asks.

    A capitalized mid-sentence mention is an ask at any frequency after
    the JD's first heading ('Exposure to ... Snyk'), and at frequency
    >= 2 before it (mission-statement company names like 'At AcmeCo, we
    build things' name nothing askable). Lowercase anchor/CORE tokens
    ask at variant frequency >= 2 ('agents', 'harness/harnesses' — the
    variant-aware counter is what made intro-hosted asks visible).
    Line- and sentence-initial capitals never qualify: every English
    sentence starts capitalized."""
    jd_low = jd_text.lower()
    out = set()
    heading_offset = _first_heading_offset(jd_text)

    def _post_heading(term):
        if heading_offset is None:
            return True
        return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(term)
                              + r"(?![A-Za-z0-9])",
                              jd_text[heading_offset:], re.I))

    stream = []
    for ln in jd_text.splitlines():
        words = [w.strip(".,;:!?'\"()").lower() for w in ln.split()]
        stream.extend(words[1:])
    counts = Counter(w for w in stream if w)

    def _admit(w):
        if w in JD_STOP or w in _VAGUE_STOP or w in _LEVEL_WORDS:
            return False
        if len(w) < 3 and not re.search(r"[#+]", w):
            return False
        if re.fullmatch(r"[0-9.]+\w*", w):
            return False
        return not (w.endswith("ly") or JD_SOFT_SKILL_RE.search(w))

    for w in counts:
        if not _admit(w):
            continue
        freq = _jd_term_freq(w, jd_low)
        if _capitalized_mention(jd_text, w):
            if freq >= 2 or _post_heading(w):
                out.add(w)  # a JD-named product/ask
        elif (w in _TECH_ANCHORS or w in CORE_TECH_NOUNS) and freq >= 2:
            out.add(w)
    # Product-name sequences (multi-word proper nouns: 'GitHub Actions',
    # 'REST Assured', 'Azure DevOps') are never prose — mine them over the
    # posting from the first recognized heading onward (mission-statement
    # labels like 'About Us' name no ask), per sentence so '.' glue cannot
    # fuse items.
    if heading_offset is not None:
        seq_text = jd_text[heading_offset:]
    else:
        seq_text = jd_text
    for ln in seq_text.splitlines():
        if not ln.strip() or JD_QUAL_HEADING_RE.match(ln.strip()) \
                or JD_NEGATED_HEADING_RE.match(ln.strip()):
            continue
        for part in re.split(r"(?<=[.!?])\s+", ln):
            for m in JD_SEQ_TERM_RE.finditer(part):
                out.add(m.group(0).lower().rstrip("."))
    # Acronyms only as STANDALONE tokens ('RCA' yes; the 'NG' inside
    # 'TestNG' is not an acronym occurrence).
    out |= {a for a in _acronym_terms(jd_text)
            if not a.endswith("ly")
            and re.search(rf"(?<![A-Za-z0-9#+]){re.escape(a)}"
                          rf"(?![A-Za-z0-9#+])", jd_low)}
    return out

def _subsumed(terms):
    """Drop a term that is a word-prefix of a longer term."""
    return {t for t in terms
            if not any(o != t and o.startswith(t + " ") for o in terms)}


def _bigram_gate(bg):
    """Ask-worthy bigram: carries an anchor/core/metric-head word and no
    structure word or adverb ('cycle time' yes; 'assess whether' /
    'agent dramatically' are prose)."""
    words = bg.split()
    if any(w in _VAGUE_STOP or w in _STRUCTURE_STOP or w.endswith("ly")
           for w in words):
        return False
    return any(w in _TECH_ANCHORS or w in CORE_TECH_NOUNS
               or w in JD_METRIC_HEADS for w in words)


def parse_asks(jd_text):
    """The ONE ask extraction. Returns hard and concept Ask records;
    soft skills are line-classified separately by soft_lines().

    Sources: qualification lines are EXPLICIT asks (anchored tokens,
    cue-tail phrases, ask-worthy bigrams); the whole posting adds
    capitalized mentions and anchor tokens named twice or more.
    Subsumption runs WITHIN the cue-tail phrases only (overlapping cue
    windows mine 'selenium driving' beside 'selenium driving
    parallelized' — true duplicates): a token under a phrase ask stays
    matchable, because hosting 'Python' does not host 'Python
    scripting'."""
    jd_norm = _norm_text(jd_text)
    tokens, phrases = set(), set()
    qual = requirement_lines(jd_text)
    # No recognized heading (a recruiter's message / freeform posting):
    # the WHOLE posting is the ask section — its named skills are the
    # alignment target (SKILL Step 1).
    ask_lines = qual or [ln.strip() for ln in jd_text.splitlines()
                         if ln.strip()]
    for line in ask_lines:
        tokens |= _single_token_terms(line)
        phrases |= _phrase_terms(line)
        phrases |= {bg for bg in _adjacent_bigrams(line)
                    if _bigram_gate(bg)}
    phrases = _subsumed(phrases)
    repeated = _repeated_terms(jd_text)
    repeated |= {bg for bg in _adjacent_bigrams(jd_text)
                 if _bigram_gate(bg) and jd_norm.count(bg) >= 2}
    hard = tokens | phrases | repeated
    hard = {t.rstrip(".,;:!\"'") for t in hard}
    asks = [Ask(t, "hard") for t in sorted(hard)]
    jd_low = jd_text.lower()
    asks.extend(Ask(c, "concept") for c in JD_CONCEPTS if c in jd_low)
    return asks


class Ask(NamedTuple):
    """One JD ask and its matching rule. Soft lines are separate."""

    phrase: str
    kind: str    # "hard" | "concept"


def soft_lines(jd_text):
    """Qualification lines that are soft-skill asks (action-verb evidence,
    never bullet protection; the add side hosts the literal phrase)."""
    return [ln for ln in requirement_lines(jd_text)
            if JD_SOFT_SKILL_RE.search(ln)]


# --------------------------------------------------------------------- #
# THE matcher and the evidence rule
# --------------------------------------------------------------------- #
# These are alternatives within one JD ask, not a second pruning rule. The
# existing ask matcher uses them in both directions: a source paragraph that
# carries a truthful equivalent protects the paragraph from Phase 1 cuts, and
# the same equivalent can satisfy the later no-host audit.
_EVIDENCE_FAMILIES = {
    "component-level testing": (
        "component-level testing", "component testing", "unit testing",
        "unit test", "isolated component", "isolated ui"),
    "level testing": (
        "level testing", "component testing", "unit testing", "unit test",
        "isolated component", "isolated ui"),
    "python scripting": (
        "python scripting", "python script", "python scripts", "python"),
    "scripting": ("scripting", "script", "scripts"),
    "linux bash": ("linux bash", "bash", "linux", "wsl"),
    "windows batch": ("windows batch", "batch"),
    "visual regression testing": (
        "visual regression testing", "visual regression", "manual visual",
        "visual checks", "visual verification"),
}


def _evidence_candidates(phrase_low):
    """Return the literal/equivalent forms for one existing JD ask."""
    return _EVIDENCE_FAMILIES.get(phrase_low, (phrase_low,))


def hosted(text_low, phrase_low):
    """Literal phrase host, ATS-style: word-boundary substring, with a
    punctuation-stripped fallback for MULTI-TOKEN phrases (a phrase
    wrapped across a pdftotext line break still parses as one token in
    most ATS, standard spellings split with a slash — the JD says
    "CI/CD pipelines", the resume legitimately renders "CI/CD" — and
    parentheticals inside the JD's own phrasing) and an optional
    trailing plural on the last word — external scorers match stemmed
    ("triage" hosts "triages"). The fallback never applies to single
    words — "api" must not host inside "rapid"."""
    suffix = "" if phrase_low.endswith("s") else "(?:e?s)?"
    if re.search(rf"(?<![a-z0-9]){re.escape(phrase_low)}{suffix}(?![a-z0-9])",
                 text_low):
        return True
    if not re.search(r"[\s\-]", phrase_low):
        return False
    return re.sub(r"[^a-z0-9]+", "", phrase_low) in re.sub(
        r"[^a-z0-9]+", "", text_low)


_CONCEPT_SUFFIXES = ("ship", "ability", "ility", "ing", "ion", "ed",
                     "es", "s")


def _concept_stem(word):
    for suf in _CONCEPT_SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 5:
            return word[:-len(suf)]
    return word


def _concept_hosted(text_low, phrase_low):
    """Concept asks match by substring OR shared word stem (>=5 chars):
    the calibrated JD_CONCEPTS behavior extended so 'Mentored' hosts the
    JD's 'mentorship' ask and 'traceable' hosts 'traceability' — a
    morphological variant is the SAME practice evidence. Identical on
    both sides of the engine."""
    if phrase_low in text_low:
        return True
    text_words = set(re.findall(r"[a-z0-9#+]{5,}", text_low))
    for w in re.split(r"[^a-z0-9+#]+", phrase_low):
        if len(w) < 5:
            continue
        stem = _concept_stem(w)
        if any(tw.startswith(stem) or stem.startswith(tw)
               for tw in text_words):
            return True
    return False


def _phrase_evidence(text_low, phrase, kind):
    """Apply the engine's matcher for one ask phrase and its equivalents."""
    matcher = _concept_hosted if kind == "concept" else hosted
    return any(matcher(text_low, candidate)
               for candidate in _evidence_candidates(phrase))


def evidence_set(text_low, phrases):
    """String-based evidence: the subset of ``phrases`` the text hosts.

    Kind resolves by JD_CONCEPTS membership — the same rule parse_asks
    applies — so callers that pass ask phrases as a plain set (the shim's
    ``jd_terms``) get exactly the engine's determination."""
    return {p for p in phrases
            if _phrase_evidence(text_low, p,
                                "concept" if p in JD_CONCEPTS else "hard")}


def unhosted(doc_text_low, asks):
    """The positive direction: asks with NO host in the whole document —
    the mining queue (add side) and the never-fabricate flags."""
    hosted_phrases = evidence_set(doc_text_low, {a.phrase for a in asks})
    return [a for a in asks if a.phrase not in hosted_phrases]


def hard_phrases(jd_text):
    """Sorted hard-ask phrases (ats_audit's literal term list)."""
    return sorted(a.phrase for a in parse_asks(jd_text) if a.kind == "hard")
