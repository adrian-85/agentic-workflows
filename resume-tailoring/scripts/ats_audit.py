#!/usr/bin/env python3
"""ATS audit — literal-phrase verification of the RENDERED deliverable.

The workflow's internal matchers (measure_resume.py, validate_resume.py)
judge JD alignment with stemmed/concept matching. Real ATS screeners
match literal phrases against the rendered text (abbreviations and
paraphrases frequently do not count). A resume can pass every internal
gate and still lose ATS points — a real session kept topically relevant
bullets while 9 of 24 hard skills had zero literal hits, and the ATS
score DROPPED (SKILL Step 11). This tool is the ground-truth backstop:
it runs the ATS-style literal check on the same text a parser sees.

usage:
    python3 scripts/ats_audit.py <resume.pdf|resume.txt> [--jd <jd.txt>]
        [--phrases-file <f>] [--report-json <f>] [--max-words N]

Checks (exit 0 clean, 1 findings, 2 usage/IO error):
  1. WORD COUNT — the whole-resume <=1000-word cap (SKILL Steps 3/8),
     counted with the tool's own logic (see _count_words). `--max-words 0`
     disables. With --report-json, the report's wordCount is shown as a
     cross-check — the cap itself uses OUR count.
  2. --jd LITERAL TERMS — qualification-line phrases mined from the JD
     (measure_resume's own qualification-line detection) checked literally
     against the rendered text. Zero-host terms include any hard skill
     whose last host died with a cut bullet or trimmed Tools line.
  3. --phrases-file / --report-json EXTERNAL PHRASES — literal check of a
     curated phrase list (one per line) or an external ATS scan report
     JSON (findings + hard/soft skills). A skill's resumeCount, when the
     report carries one, is the authoritative host signal; otherwise the
     literal check decides. Hard-skill zero-hits fail; soft-skill
     zero-hits warn (several are deliberate no-evidence skips).

Run on the PDF (pdftotext), not the .docx — the deliverable is what the
screener parses. The report's contactEmail searchability finding is
IGNORED by rule (SKILL Step 11): the compact hyperlinked contact block is
a deliberate design the user chose for readability.
"""

import json
import re
import subprocess
import sys

DEFAULT_MAX_WORDS = 1000

# Private-use glyphs (bullet dingbats) and page footers ("Page 1|3",
# "P a g e 1 | 3") are tokens a text extractor emits that word-count
# logic does not count.
_ARTIFACT_RE = re.compile(r"[\ue000-\uf8ff]|(?:P\s*a\s*g\s*e\s*)?\d+\s*\|\s*\d+")
_PAGE_WORD_RE = re.compile(r"P\s*a\s*g\s*e", re.I)


def _extract_text(path):
    """Rendered text of a .pdf (pdftotext) or plain .txt/.audit input."""
    if path.lower().endswith(".pdf"):
        try:
            out = subprocess.run(
                ["pdftotext", path, "-"],
                capture_output=True, text=True, check=True)
        except FileNotFoundError:
            raise SystemExit("error: pdftotext not found — install poppler-utils") from None
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"error: pdftotext failed on {path}: {e.stderr}") from e
        return out.stdout
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _count_words(text):
    """Our own whole-resume word count, mirroring external ATS scorers:
    strip bullet glyphs and page footers, then count whitespace tokens
    containing at least one alphanumeric character. Calibrated against an
    external report on a real deliverable: raw pdftotext 1054 -> 989 with
    this logic, vs the report's own 949 (the residual spread is the
    parser's header/hyphenation handling; treat our count as primary and
    a report's wordCount as the cross-check)."""
    clean = _PAGE_WORD_RE.sub(" ", _ARTIFACT_RE.sub(" ", text))
    return sum(1 for t in clean.split() if re.search(r"[A-Za-z0-9]", t))


def _audit_word_count(text, max_words):
    """Whole-resume word cap. Returns (count, errors)."""
    count = _count_words(text)
    if max_words and count > max_words:
        return count, [f"{count} words exceeds the {max_words}-word cap by "
                       f"{count - max_words} — cut content, do not shrink "
                       "fonts (SKILL Steps 3/8)"]
    return count, []


def _hosted(text_low, phrase_low):
    """Literal phrase host, ATS-style: word-boundary substring, with a
    whitespace/hyphen-stripped fallback for MULTI-TOKEN phrases (a phrase
    wrapped across a pdftotext line break still parses as one token in
    most ATS) and an optional trailing plural on the last word — external
    scorers match stemmed ("triage" hosts "triages"). The fallback never
    applies to single words — "api" must not host inside "rapid"."""
    suffix = "" if phrase_low.endswith("s") else "(?:e?s)?"
    if re.search(rf"(?<![a-z0-9]){re.escape(phrase_low)}{suffix}(?![a-z0-9])",
                 text_low):
        return True
    if not re.search(r"[\s\-]", phrase_low):
        return False
    return re.sub(r"[\s\-]+", "", phrase_low) in re.sub(r"[\s\-]+", "",
                                                       text_low)


# Function words: an n-gram containing one is not a phrase. Unlike
# measure_resume's single-word JD_STOP, "quality" must stay usable here —
# "data quality" and "quality assurance" were a real session's top
# literal misses. A vague-content word only cannot carry a gram ALONE.
_STRUCTURE_STOP = frozenset({
    "and", "the", "for", "a", "an", "or", "of", "in", "to", "on",
    "with", "from", "into", "them", "they", "their", "each", "when",
    "while", "where", "which", "through", "throughout", "than", "then",
    "also", "both", "over", "more", "most", "other", "others", "some",
    "such", "only", "well", "using", "used", "uses", "across",
    "against", "within", "without", "via", "per", "plus", "near",
    "among", "along", "since", "until", "upon", "about", "after",
    "before", "during", "another", "related", "any", "all",
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
})
# QA/tech anchor words: a phrase must contain one to be a skill ask —
# the qualification section of a real JD also carries prose fragments
# ("assess whether code", "make sense") that literal-matching them
# would bury the signal in.
_TECH_ANCHORS = frozenset({
    "quality", "assurance", "test", "testing", "tests", "automation",
    "automated", "data", "database", "databases", "pipeline",
    "pipelines", "analytics", "framework", "frameworks", "regression",
    "integration", "hipaa", "phi", "sql", "python", "api", "apis",
    "agile", "validation", "software", "engineering", "developer",
    "development", "ci", "cd", "sdlc", "etl", "dashboard", "dashboards",
    "scripting", "backend", "frontend", "unit", "functional", "qa",
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


def _jd_literal_terms(jd_text):
    """Literal hard-skill PHRASES the JD's qualification lines name.

    ATS keyword matching is phrase-literal ("regression testing" does not
    match "regression frameworks"), so this mines 2–3-word n-grams — but
    ONLY from the tails of skill-introducing cues ("experience in",
    "proficiency in", "used for", …). Mining every anchored n-gram buried
    the signal in the qualification section's prose ("broader software
    engineering responsibilities", "including testing data"). Single
    tokens: measure's capitalized/tech-token regexes minus vague
    qualification nouns, minus sentence-initial capitals (a line-initial
    capital is prose, not a product name — "Assess whether…" must not
    mine "assess"), plus CORE_TECH_NOUNS/markers they might miss.
    """
    import measure_resume as mr  # sibling module
    stop_vague = _VAGUE_STOP | mr.JD_SELF_ASSESSMENT
    terms = set()
    for line in mr._jd_requirement_lines(jd_text):
        # Single tokens: capitalized/tech tokens anywhere in the line.
        for m in mr.JD_SEQ_TERM_RE.finditer(line):
            terms.add(m.group(0).lower())
        for m in mr.JD_WORD_TERM_RE.finditer(line):
            if m.start() == 0:
                continue
            low = m.group(1).lower()
            if low in stop_vague or low in mr.JD_STOP:
                continue
            if re.search(r"[.!?]\s*$", line[:m.start()].strip()):
                continue
            terms.add(low)
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9+#\-]*", line):
            low = tok.lower()
            if low in mr.CORE_TECH_NOUNS or re.search(r"[#+]", low) or (
                    len(low) >= 2 and low.isupper()):
                terms.add(low)
        # Phrases: only in the tails of skill-introducing cues. Commas
        # are phrase boundaries (a tool list must not fuse into one
        # literal phrase, "playwright selenium").
        for tail in _cue_tails(line):
            for size in (3, 2):
                for i in range(len(tail) - size + 1):
                    gram = tail[i:i + size]
                    if any(w in _STRUCTURE_STOP for w in gram):
                        continue
                    if all(w in mr.JD_STOP or w in stop_vague
                           for w in gram):
                        continue
                    if not any(w in _TECH_ANCHORS or w in mr.CORE_TECH_NOUNS
                               for w in gram):
                        continue
                    # A gram leading with a non-anchor gerund is a verb
                    # bridge, not a skill phrase ("implementing automated
                    # api") — "testing data pipelines" survives (anchor).
                    first = gram[0]
                    if (first.endswith("ing")
                            and first not in _TECH_ANCHORS
                            and first not in mr.CORE_TECH_NOUNS
                            and first not in mr.JD_STOP
                            and first not in stop_vague):
                        continue
                    if len(set(gram)) < size:
                        continue
                    terms.add(" ".join(gram))
    return sorted(terms)


def _audit_jd(text_low, jd_text):
    """Literal check of the JD's qualification terms. Returns (ok_count,
    missing)."""
    terms = _jd_literal_terms(jd_text)
    missing = [t for t in terms if not _hosted(text_low, t)]
    return len(terms) - len(missing), missing


def _report_skills(data):
    """[(phrase, resumeCount), ...] for hard and soft skills from an
    external ATS scan report JSON.

    ``resumeCount`` is the report's own hit count for the resume — the
    authoritative host signal when present (None for other layouts; the
    caller then falls back to its literal check). Handles three observed
    layouts: {skills: {hard, soft}}, {hardSkills, softSkills}, and
    {keywords: {hard, soft}}.
    """
    if not isinstance(data, dict):
        return [], []
    skills = data.get("skills") or {}
    if isinstance(skills, dict) and ("hard" in skills or "soft" in skills):
        return _skill_list(skills.get("hard")), _skill_list(skills.get("soft"))
    hard = _skill_list(data.get("hardSkills"))
    soft = _skill_list(data.get("softSkills"))
    if hard or soft:
        return hard, soft
    kw = data.get("keywords") or {}
    return _skill_list(kw.get("hard")), _skill_list(kw.get("soft"))


def _skill_list(items):
    """Extract (phrase, resumeCount) pairs from a skill list — items may
    be plain strings or dicts with various key names."""
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if isinstance(item, str):
            out.append((item, None))
        elif isinstance(item, dict):
            name = next((item[k] for k in ("keyword", "name", "text",
                                            "title", "term")
                         if isinstance(item.get(k), str)), None)
            if name is not None:
                cnt = item.get("resumeCount")
                out.append((name,
                            cnt if isinstance(cnt, (int, float))
                            else None))
    return out


def _audit_phrases(text_low, phrases):
    """Literal check of externally supplied phrases. Returns zero-hit
    list."""
    return [p for p in phrases if p.strip()
            and not _hosted(text_low, p.strip().lower())]


def _report_word_count(data):
    """The report's wordCount finding value, or None (cross-check only —
    the cap itself uses OUR count)."""
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(findings, list):
        return None
    for f in findings:
        if (isinstance(f, dict) and f.get("key") == "wordCount"
                and isinstance(f.get("variables"), dict)):
            value = f["variables"].get("wordCount")
            if isinstance(value, (int, float)):
                return int(value)
    return None


def _report_findings(data):
    """Report findings[] summary. contactEmail is IGNORED by rule (the
    hyperlinked contact block is deliberate design). Returns warn lines."""
    lines = []
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(findings, list):
        return lines
    for f in findings:
        if not isinstance(f, dict):
            continue
        name = f.get("name") or f.get("key") or "?"
        status = str(f.get("status", "")).lower()
        if status == "pass":
            continue
        if "contactemail" in re.sub(r"[_\s-]", "",
                                    str(f.get("key", ""))).lower():
            lines.append(
                f"  IGNORED contactEmail ({status}): the compact "
                "hyperlinked contact block is deliberate design — do not "
                "alter it (SKILL Step 11)")
            continue
        lines.append(f"  {status.upper()}: {name}")
    return lines


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    path = argv[0]

    def _flag(name, cast=str):
        if name not in argv:
            return None
        i = argv.index(name)
        if i + 1 >= len(argv):
            raise SystemExit(f"error: {name} needs a value")
        return cast(argv[i + 1])

    max_words = _flag("--max-words", int)
    if max_words is None:
        max_words = DEFAULT_MAX_WORDS
    jd_path = _flag("--jd")
    phrases_file = _flag("--phrases-file")
    report_json = _flag("--report-json")

    text = _extract_text(path)
    text_low = text.lower().replace("\n", " ")
    errors, warns, ok_lines = [], [], []

    report_data = None
    if report_json:
        with open(report_json, encoding="utf-8", errors="replace") as f:
            report_data = json.load(f)

    # 1. Word cap (hard rule) — OUR count; the report's wordCount, when
    # available, is shown as a cross-check only.
    count, wc_errors = _audit_word_count(text, max_words)
    ok_lines.append(f"words: {count}")
    errors.extend(wc_errors)
    if report_data is not None:
        report_wc = _report_word_count(report_data)
        if report_wc is not None:
            drift = count - report_wc
            ok_lines.append(
                f"words (report cross-check): {report_wc} "
                f"({drift:+d} vs our count)")

    # 2. JD literal terms.
    if jd_path:
        with open(jd_path, encoding="utf-8", errors="replace") as f:
            jd_text = f.read()
        ok_n, missing = _audit_jd(text_low, jd_text)
        if missing:
            errors.append(
                "JD literal terms with NO host in the rendered text: "
                + ", ".join(missing)
                + " — host the exact phrase truthfully or raise the gap "
                "(never fabricate)")
        elif not ok_n:
            # 0/0 is NOT a pass: the miner found no cue-tails in this JD's
            # qualification syntax, so the check is vacuous — a clean
            # verdict here would read as verified alignment.
            warns.append(
                "JD literal phrase mining found NO skill phrases (this "
                "JD's qualification lines use no cue syntax) — the literal "
                "check is vacuous; supply --phrases-file with the JD's "
                "named skills/tools")
        else:
            ok_lines.append(f"JD literal terms: {ok_n}/{ok_n + len(missing)} "
                            "hosted")

    # 3. External phrase lists.
    if phrases_file:
        with open(phrases_file, encoding="utf-8", errors="replace") as f:
            phrases = [ln.strip() for ln in f if ln.strip()]
        missing = _audit_phrases(text_low, phrases)
        if missing:
            errors.append("phrases with NO literal host: "
                          + ", ".join(missing))
        else:
            ok_lines.append(f"phrases: {len(phrases)}/{len(phrases)} hosted")

    if report_data is not None:
        hard, soft = _report_skills(report_data)
        # resumeCount, when the report carries it, is authoritative;
        # otherwise the literal check decides.
        hard_miss = [p for p, cnt in hard
                     if not cnt and not _hosted(text_low, p.strip().lower())]
        soft_miss = [p for p, cnt in soft
                     if not cnt and not _hosted(text_low, p.strip().lower())]
        if hard_miss:
            errors.append(
                "report hard skills with NO literal host: "
                + ", ".join(hard_miss))
        else:
            ok_lines.append(f"report hard skills: {len(hard) - len(hard_miss)}"
                            f"/{len(hard)} hosted")
        if soft_miss:
            warns.append(
                "report soft skills with NO literal host (advisory — "
                "no-evidence skips are deliberate): " + ", ".join(soft_miss))
        elif soft:
            ok_lines.append(f"report soft skills: {len(soft)}/{len(soft)} "
                            "hosted")
        for line in _report_findings(report_data):
            warns.append(line)

    print("== ATS AUDIT ==")
    for line in ok_lines:
        print(f"  ok: {line}")
    for line in warns:
        print(f"  WARNING: {line}")
    for line in errors:
        print(f"  FAIL: {line}")
    if errors:
        print(f"RESULT: {len(errors)} finding(s) — fix or raise to the user")
        return 1
    print("RESULT: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
