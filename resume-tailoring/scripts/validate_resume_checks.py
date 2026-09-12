"""validate_resume's deterministic structural/punctuation/text-integrity checks. Split from validate_resume.py; imported one-way by validate_resume_master and the shim."""  # pylint: disable=line-too-long
# pylint: disable=invalid-name
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.

# pylint: disable=invalid-name
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.


import re
import sys
import unicodedata

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402

# (constant) TITLE_STYLE
TITLE_STYLE = "JobTitleBlock"   # job-title paragraph style; adapt per resume


# (constant) SUMMARY_STYLE
SUMMARY_STYLE = "Summary"       # summary paragraph style


# (constant) LIST_STYLES
LIST_STYLES = ("ListBullet",)   # paragraph styles whose bullets carry no numId


# (constant) DUP_K
DUP_K = 20                      # shared substring length that flags near-dups
_DUP_OVERLAP_MIN = 3            # shared content words that flag a repeat
_DUP_OVERLAP_RATIO = 0.4        # shared/min(|A|,|B|) content-word overlap
_DUP_STOP = frozenset(
    "the a an and or of in to on with for from by at as is are was were be "
    "been that this these those it its their our your we they he she his "
    "her via per across within without during over more most other some "
    "such only well using used which while when where then also both into "
    "from that this there their about would could should because through "
    "between each have has had not but all any can will just".split())


def _content_words(text):
    """Lowercased, punctuation-stripped content words (len>=4, not
    function words), singulars folded to plurals' stem — the overlap
    vocabulary for the near-duplicate repeat check."""
    out = set()
    for w in text.split():
        w = re.sub(r"[^a-z0-9#+]", "", w.lower())
        if len(w) < 4 or w in _DUP_STOP:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") else w)
    return out


# (constant) YEARS_RE
YEARS_RE = re.compile(r"(\d{1,2})\s*(?:\+)?\s*(?:years|yrs)", re.I)


# (constant) DATE_RANGE
DATE_RANGE = re.compile(r"\d{1,2}/\d{4}\s*[–\-]\s*\d{1,2}/\d{4}")


# (constant) MAX_BULLETS_PER_ROLE
MAX_BULLETS_PER_ROLE = mr.MAX_BULLETS_PER_ROLE


# (constant) PARA_WORD_CAP
PARA_WORD_CAP = 40


# (constant) _TOOLS_LABEL_RE
_TOOLS_LABEL_RE = re.compile(r"^Tools\s*&\s*Technologies\s*:")


# (constant) _ASCII_OK_CHARS
_ASCII_OK_CHARS = "‘’“”–—‐‑"


def _is_bullet(p):
    style, numId = de.style_and_numid(p)
    return (numId is not None and numId != "0") or style in LIST_STYLES


def _is_tools(p):
    t = de.text_of(p).strip().lower()
    return t.startswith("tool") and "technolog" in t


def _region(body):
    """Paragraphs between the Career Experience heading and the NEXT section
    heading (Education, or an Open Source / Projects section). Confines the
    role-structure rules to the role block so legitimate non-role sections
    (projects, open source) can't false-positive."""
    ps = de.paras(body)
    start = None
    for i, p in enumerate(ps):
        if de.text_of(p).strip() == mr.SECTION_CAREER:
            start = i
            break
    if start is None:
        return []
    region = []
    for p in ps[start + 1:]:
        style, _ = de.style_and_numid(p)
        if (style == "SectionHeading"
                or de.text_of(p).strip() == mr.SECTION_EDUCATION):
            break
        region.append(p)
    return region


def _summary_paragraph(body):
    for p in de.paras(body):
        style, _ = de.style_and_numid(p)
        if style == SUMMARY_STYLE:
            return p
    return None


def _prose_paragraphs(region, summary):
    """Non-empty prose paragraphs in document order: the Summary (if
    present) followed by bullets and role-intro text, excluding company
    headers and job titles. Yields (paragraph, text) pairs."""
    candidates = ([summary] if summary is not None else []) + [
        p for p in region
        if de.style_and_numid(p)[0] not in (mr.COMPANY_STYLE, TITLE_STYLE)
    ]
    for p in candidates:
        text = de.text_of(p)
        if text.strip():
            yield p, text


def _bullet_cap_errors(region):
    """Roles keeping more than MAX_BULLETS_PER_ROLE bullets (SKILL Step 8).

    The cap is enforced by count, not judgment: recency and accomplishment
    never exempt a role — a 1-year Staff role whose master block carries
    20+ bullets selects its strongest JD-aligned ones like everyone else
    (two real sessions let the most-recent role keep 16-19 bullets while
    JD-relevant older-role bullets died under page pressure). Returns one
    error per over-cap role, named by its company header.
    """
    errors = []
    company_text = None
    count = 0

    def _over():
        return (
            f"role {company_text!r} keeps {count} bullets — over the hard "
            f"cap of {MAX_BULLETS_PER_ROLE} (SKILL Step 8): prune to the "
            f"strongest JD-aligned bullets; time-in-role and volume of "
            f"accomplishment never exempt a role"
        )

    for p in region:
        style, _ = de.style_and_numid(p)
        if style == mr.COMPANY_STYLE:
            if company_text is not None and count > MAX_BULLETS_PER_ROLE:
                errors.append(_over())
            company_text = de.text_of(p).strip()
            count = 0
        elif _is_bullet(p):
            count += 1
    if company_text is not None and count > MAX_BULLETS_PER_ROLE:
        errors.append(_over())
    return errors


def _structural_errors(region):
    """Structural failures (exit 2) in the career region: orphan job titles,
    companies without a title, and content orphaned after a Tools line."""
    errors = []
    waiting_title = False
    company_text = None
    last_kind = None  # 'company' | 'title' | 'other' (bullet/tools/etc)
    for p in region:
        if not de.text_of(p).strip():
            continue
        style, _num_id = de.style_and_numid(p)
        if style == mr.COMPANY_STYLE:
            if waiting_title:
                errors.append(
                    f"company block has no job title before next company: "
                    f"{company_text!r}"
                )
            waiting_title = True
            company_text = de.text_of(p).strip()
            last_kind = 'company'
        elif style == TITLE_STYLE:
            if not waiting_title and last_kind != 'title':
                errors.append(
                    f"job title without a preceding company block: "
                    f"{de.text_of(p).strip()!r}"
                )
            waiting_title = False
            last_kind = 'title'
        else:
            if waiting_title:
                errors.append(
                    f"company block has no job title (next content is a "
                    f"bullet/tools line): {company_text!r}"
                )
                waiting_title = False
            if last_kind == 'tools':
                # Content after a role's Tools line with no new company:
                # a company+title block was removed but later bullets survived.
                errors.append(
                    f"content after a Tools line with no new company block "
                    f"(orphaned role content?): {de.text_of(p).strip()[:60]!r}"
                )
            if _is_tools(p):
                last_kind = 'tools'
            elif _is_bullet(p):
                last_kind = 'bullet'
            # intro paragraphs etc. keep state (last_kind unchanged)
    if waiting_title:
        errors.append(
            f"company block has no job title (end of section): "
            f"{company_text!r}"
        )
    return errors


def _near_duplicates(region):
    """Yield (bullet_a[:60], bullet_b[:60], description) for bullet pairs
    that read as repeats — a merge that left the source's old text beside
    the rewritten target, a literal duplicate, or two bullets doing the
    same job in different words. Two detectors, deduped per pair:
    (1) a shared DUP_K-char substring (the near-copy signature), and
    (2) stemmed content-word overlap (>= _DUP_OVERLAP_MIN shared words at
    >= _DUP_OVERLAP_RATIO of the shorter bullet) — catches paraphrased
    repeats that share no 20-char run (a real deliverable shipped
    'Performed contract testing to validate…' beside 'Performed contract
    testing for API integrations…' and the user cut one by hand)."""
    bullets = [de.text_of(p) for p in region if _is_bullet(p)]
    warned = set()
    subs = {}
    for i, t in enumerate(bullets):
        norm = re.sub(r"\s+", " ", t).strip()
        if len(norm) < DUP_K:
            continue
        for j in range(len(norm) - DUP_K + 1):
            s = norm[j:j + DUP_K]
            if not s.strip():
                continue
            if s in subs:
                k = subs[s]
                pair = tuple(sorted((i, k)))
                if pair not in warned:
                    warned.add(pair)
                    yield bullets[k][:60], t[:60], (
                        f"bullets share {DUP_K}+ chars ({s[:40]!r})")
            else:
                subs.setdefault(s, i)
    words = [_content_words(t) for t in bullets]
    for i, wi in enumerate(words):
        for j in range(i + 1, len(words)):
            pair = (i, j)
            if pair in warned or not wi or not words[j]:
                continue
            shared = wi & words[j]
            if len(shared) < _DUP_OVERLAP_MIN:
                continue
            if len(shared) / min(len(wi), len(words[j])) \
                    >= _DUP_OVERLAP_RATIO:
                warned.add(pair)
                yield bullets[i][:60], bullets[j][:60], (
                    f"bullets share {len(shared)} content words "
                    f"({', '.join(sorted(shared)[:5])}) — keep the stronger, "
                    "merge or cut the other (SKILL Step 7: merge, don't append)")


def _claim_years(text):
    m = YEARS_RE.search(text)
    return int(m.group(1)) if m else None


# Spelled-out years asks: "Five or more years of experience", "seven+",
# "ten years". The numeric YEARS_RE misses these, which made a real
# --jd-years pass look invented ("the JD text states no 'N+ years' ask")
# against a JD that stated the ask in words.
_WORD_YEARS_RE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|twenty)\s*(?:\+|or more)?\s*years\b",
    re.I)


def _jd_states_years_ask(jd_text):
    """True when the JD states a years ask — digits ("5+ years", YEARS_RE)
    or spelled out ("Five or more years"). Guards the --jd-years flag
    against a fabricated-ask warning on a legitimate ask."""
    if YEARS_RE.search(jd_text):
        return True
    return bool(_WORD_YEARS_RE.search(jd_text))


# A content word (>=5 chars, not in this stoplist) appearing twice within
# _REPEAT_WINDOW tokens of the same paragraph reads as repetition to a
# human reviewer — the validator's doubled-word check only catches
# ADJACENT repeats, and a real deliverable shipped "...testing...testing"
# twice in the Summary that the user cut by hand.
_REPEAT_WINDOW = 12
_REPEAT_STOP = frozenset(
    "which there their about would could should because through between "
    "things those these being every other others after under above "
    "against without within across during".split())


def _repeated_word_notes(region, summary):
    """Advisory notes for a content word repeated within _REPEAT_WINDOW
    tokens in the same prose paragraph (Summary first — it is what a
    human reviewer reads). Non-blocking guidance."""
    notes = []
    for p, text in _prose_paragraphs(region, summary):
        if _is_tools(p):
            continue
        # Filter to content words but keep ORIGINAL token positions, so
        # "within N words" means what a reader counts.
        words = [(i, re.sub(r"[^a-z0-9#+]", "", w.lower()))
                 for i, w in enumerate(text.split())]
        words = [(i, w) for i, w in words
                 if len(w) >= 5 and w not in _REPEAT_STOP]
        last = {}
        seen_warned = set()
        for i, w in words:
            if w in seen_warned:
                continue
            if w in last and i - last[w] <= _REPEAT_WINDOW:
                seen_warned.add(w)
                notes.append(("warn",
                    f"{w!r} repeats within {_REPEAT_WINDOW} words of "
                    f"itself ({'Summary' if p is summary else 'bullet'}): "
                    f"{text.strip()[:60]!r}... — reword one occurrence "
                    "(Step 9 re-read)"))
            last[w] = i
    return notes


def _punctuation_errors(region, summary):
    """Step 9 punctuation rule: periods and commas only. The Summary and
    the job-history prose (role intros, bullets, tools lines) must contain
    no em dash (—), double hyphen (--), semicolon (;), colon (:), ellipsis
    (... or …), or non-date en dash (–). Exempt: single hyphens inside
    compound words, en dashes inside date ranges, structural lines
    (company headers, job titles), and the structural "Tools &
    Technologies:" label (its colon separates the label from the value
    list, it is not prose punctuation) — plus anything outside the Summary
    and the career region (proficiencies, certifications, education)."""
    errors = []
    for _, text in _prose_paragraphs(region, summary):
        probe = DATE_RANGE.sub(" ", text)  # date ranges are exempt
        # The Tools line's colon is structural (label: values), not prose.
        label_line = bool(_TOOLS_LABEL_RE.match(probe))
        for pat, name in (
            (re.compile(r"—"), "em dash"),
            (re.compile(r"–"), "en dash"),
            (re.compile(r";"), "semicolon"),
            (re.compile(r"-{2,}"), "double hyphen"),
            (re.compile(r"\.{2,}"), "ellipsis / doubled period"),
            (re.compile(r"…"), "ellipsis character"),
        ) + (() if label_line else ((re.compile(r":"), "colon"),)):
            m = pat.search(probe)
            if m is not None:
                s = max(0, m.start() - 30)
                e = min(len(probe), m.end() + 30)
                errors.append(
                    f"{name} in prose — use periods and commas: "
                    f"...{probe[s:e]}..."
                )
    return errors


def _text_integrity_errors(region, summary):
    """Step 9 text-integrity rule: generated prose must be clean. Scans the
    Summary and job-history prose (same scope as _punctuation_errors) for
    mangling artifacts: unexpected non-ASCII characters, doubled
    punctuation, and doubled words."""
    errors = []
    for _, text in _prose_paragraphs(region, summary):
        for i, ch in enumerate(text):
            if ord(ch) < 128 or ch in _ASCII_OK_CHARS:
                continue
            if "LATIN" in unicodedata.name(ch, ""):
                continue  # accented Latin letters are legitimate
            s, e = max(0, i - 30), min(len(text), i + 30)
            errors.append(
                f"non-ASCII {ch!r} (U+{ord(ch):04X} "
                f"{unicodedata.name(ch, '?')}) in prose — likely a mangling "
                f"artifact: ...{text[s:e]}..."
            )
        for m in re.finditer(r"(,|;|:)\1", text):
            s, e = max(0, m.start() - 30), min(len(text), m.end() + 30)
            errors.append(
                f"doubled punctuation {m.group(0)!r} in prose: ...{text[s:e]}..."
            )
        for m in re.finditer(
                r"\b(\w+)\s+\1\b", text, re.IGNORECASE):
            s, e = max(0, m.start() - 30), min(len(text), m.end() + 30)
            errors.append(
                f"doubled word {m.group(0)!r} in prose: ...{text[s:e]}..."
            )
    return errors


def _readability_guidance(body, summary, *, region=None, master_input=False):
    """Advisory readability checks (SKILL Step 5 word cap + Step 6).

    Word count, not sentence count — the master input is exempt (it
    intentionally keeps everything); see PARA_WORD_CAP above.

    Returns [(severity, message)] — severity in warn|ok.
    These are NOT blocking (the agent may have a good reason to exceed
    the cap); they surface when the agent writes a paragraph or bullet
    without applying the SKILL's readability guidance.
    """
    notes = []
    summary_text = de.text_of(summary).strip() if summary is not None else ""
    if not master_input:
        for p, text in _prose_paragraphs(region or _region(body), summary):
            if _is_tools(p):
                continue
            n = len(text.split())
            if n <= PARA_WORD_CAP:
                continue
            notes.append(("warn",
                f"{'Summary' if p is summary else 'Bullet' if _is_bullet(p) else 'Paragraph'} has {n} words (cap {PARA_WORD_CAP}, SKILL Step 5): "
                f"{' '.join(text.split())[:60]!r}... — split or trim to {PARA_WORD_CAP} words"))
    if summary_text and len(summary_text.split()) <= PARA_WORD_CAP:
        notes.append(("ok",
            f"Summary has {len(summary_text.split())} words — within the "
            f"{PARA_WORD_CAP}-word cap"))

    # Same word twice within a window of the same paragraph reads as
    # repetition (Step 9's re-read catches this by eye; this makes it
    # mechanical).
    notes.extend(_repeated_word_notes(region or _region(body), summary))

    # Section between Summary and Technical Proficiencies: the SKILL
    # forbids inserting Core Strengths, Top Skills, or keyword-mirror
    # sections here (Step 6).
    ps = de.paras(body)
    summary_idx = None
    prof_idx = None
    for i, p in enumerate(ps):
        if p is summary:
            summary_idx = i
        if (summary_idx is not None
                and de.text_of(p).strip() == mr.SECTION_PROFICIENCIES):
            prof_idx = i
            break
    if summary_idx is not None and prof_idx is not None:
        inserted = []
        for p in ps[summary_idx + 1:prof_idx]:
            style, _ = de.style_and_numid(p)
            if style == "SectionHeading":
                inserted.append(de.text_of(p).strip())
        if inserted:
            notes.append(("warn",
                f"section(s) between Summary and Technical Proficiencies "
                f"({', '.join(repr(s) for s in inserted)}) — SKILL Step 6 "
                f"forbids inserting Core Strengths, Top Skills, or "
                f"keyword-mirror sections here; weave skills into role "
                f"bullets instead"))
    return notes


def _word_count(body):
    """Whole-resume word count: every paragraph's whitespace tokens with
    at least one alphanumeric character (a bullet dingbat or a stray
    ornament is not a word)."""
    total = 0
    for p in de.paras(body):
        total += sum(1 for t in de.text_of(p).split()
                     if re.search(r"[A-Za-z0-9]", t))
    return total
