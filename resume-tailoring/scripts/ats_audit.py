# pylint: disable=wrong-import-position,import-outside-toplevel
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.

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
     zero-hits warn as ACTIONABLE (soft skills are safe to infer — host
     the literal phrase where the action-verb evidence lives, SKILL
     Steps 2/11).

Run on the PDF (pdftotext), not the .docx — the deliverable is what the
screener parses. Three classes of external finding are IGNORED by rule
(SKILL Step 11): contactEmail (the compact hyperlinked contact block is
deliberate design), specialCharacters (the typographic characters are
deliberate formatting the user chose — never reformat to satisfy a text
parser), and the education findings when the rendered resume has no
Education section (the drop was a Step 3.4 predicate decision the render
gate already sanctioned; the scan's generic advice does not re-open it).
"""

import json
from dataclasses import dataclass, field
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure_resume as mr  # noqa: E402
from script_args import MAX_WORDS, MATCH_RATE_TARGET, flag_value, maybe_help, match_target_met  # noqa: E402

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


def _report_match_rate(data):
    """The report's matchRate.score value, or None when absent."""
    if not isinstance(data, dict):
        return None
    rate = data.get("matchRate")
    if isinstance(rate, dict) and isinstance(rate.get("score"), (int, float)):
        return int(rate["score"])
    return None


def _audit_match_rate(score, target, result):
    """The ≥75 match-rate TARGET (advisory, not a gate): at/above it the
    literal hosting work is DONE — the session can stop weaving hard and
    soft skills without chasing the residual no-host list (most of which
    is genuine never-fabricate gaps and parser artifacts anyway). Below
    it, keep hosting. Configurable via --match-target; 0 disables."""
    verdict = match_target_met(score, target)
    if verdict is None:
        return
    if verdict:
        result.ok_lines.append(
            f"match rate: {score} (target {target} MET — literal hosting "
            "is done; stop adding hard/soft skills)")
    else:
        result.warns.append(
            f"match rate: {score} (below the {target} target — keep "
            "hosting literal phrases truthfully; see the no-host lists "
            "below for what to host)")


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
    whitespace/hyphen/slash-stripped fallback for MULTI-TOKEN phrases (a
    phrase wrapped across a pdftotext line break still parses as one token
    in most ATS, and standard spellings split with a slash — the JD says
    "CI/CD pipelines", the resume legitimately renders "CI/CD") and an
    optional trailing plural on the last word — external scorers match
    stemmed ("triage" hosts "triages"). The fallback never applies to
    single words — "api" must not host inside "rapid"."""
    suffix = "" if phrase_low.endswith("s") else "(?:e?s)?"
    if re.search(rf"(?<![a-z0-9]){re.escape(phrase_low)}{suffix}(?![a-z0-9])",
                 text_low):
        return True
    if not re.search(r"[\s\-]", phrase_low):
        return False
    return re.sub(r"[\s\-/]+", "", phrase_low) in re.sub(r"[\s\-/]+", "",
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


def _single_token_terms(line, stop_vague):
    """Capitalized/tech single tokens in a JD requirement line."""
    terms = set()
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
    return terms


def _phrase_terms(line, stop_vague):
    """2-3 word skill phrases in the tails of skill-introducing cues."""
    terms = set()
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
    return terms


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

    Mined tokens are stripped of trailing punctuation: the token regexes
    keep sentence-final periods ("apis.", "c#.", "locust." from a real
    JD) which no resume can literally host and which only padded the FAIL
    list with parser artifacts.
    """
    stop_vague = _VAGUE_STOP | mr.JD_SELF_ASSESSMENT
    terms = set()
    for line in mr._jd_requirement_lines(jd_text):
        terms.update(_single_token_terms(line, stop_vague))
        terms.update(_phrase_terms(line, stop_vague))
    return sorted(t.rstrip(".,;:!?\"'") for t in terms)


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


def _has_education_heading(text):
    """A line starting with "Education" in the rendered text — the
    section is present. A miss on prose that happens to start a line is
    the conservative direction: the education findings are then REPORTED
    (the pre-rule behavior), not ignored."""
    return bool(re.search(r"(?m)^\s*education\b", text, re.I))


def _report_findings(data, resume_text=""):
    """Report findings[] summary. Three classes are IGNORED by rule
    (SKILL Step 11):

    - contactEmail — the hyperlinked contact block is deliberate design;
      a raw-text parser's fail is the known, accepted tradeoff.
    - specialCharacters — the Wingdings bullets, en-dash date ranges and
      curly apostrophes are the user's deliberate formatting ("it pops
      better with the current formatting"); NEVER reformat the resume
      to satisfy a text parser's character check.
    - the education findings (headingEducation, educationMatch) when the
      rendered resume has no Education section — the drop was a Step 3.4
      predicate decision, and validate_resume's education gate already
      blocks any UNSANCTIONED drop at render time; a PDF without
      Education therefore reached the audit only through an approved
      drop. The scan's generic "add an Education section" advice does
      not re-open that decision. When Education IS present, the findings
      report normally.

    Returns warn lines."""
    lines = []
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(findings, list):
        return lines
    education_present = _has_education_heading(resume_text)
    for f in findings:
        if not isinstance(f, dict):
            continue
        name = f.get("name") or f.get("key") or "?"
        status = str(f.get("status", "")).lower()
        if status == "pass":
            continue
        key = re.sub(r"[_\s-]", "", str(f.get("key", ""))).lower()
        if key == "contactemail":
            lines.append(
                f"  IGNORED contactEmail ({status}): the compact "
                "hyperlinked contact block is deliberate design — do not "
                "alter it (SKILL Step 11)")
            continue
        if key == "specialcharacters":
            lines.append(
                f"  IGNORED specialCharacters ({status}): the typographic "
                "characters are the user's deliberate formatting — never "
                "reformat to satisfy a text parser (SKILL Step 11)")
            continue
        if key in ("headingeducation", "educationmatch") \
                and not education_present:
            lines.append(
                f"  IGNORED {name} ({status}): Education was dropped "
                "deliberately (Step 3.4 predicate; the render gate "
                "sanctioned it) — the scan's generic advice does not "
                "re-open that decision")
            continue
        lines.append(f"  {status.upper()}: {name}")
    return lines


def _parse_ats_args(argv):
    """Parse ats_audit CLI arguments. Returns a dict, or None when argv is
    empty/only-flags (the caller should print usage and exit 2)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    maybe_help(argv, __doc__)
    if not argv or argv[0].startswith("-"):
        return None
    return {
        "path": argv[0],
        "max_words": flag_value(argv, "--max-words", cast=int,
                                 default=MAX_WORDS),
        "jd_path": flag_value(argv, "--jd"),
        "phrases_file": flag_value(argv, "--phrases-file"),
        "report_json": flag_value(argv, "--report-json"),
        "match_target": flag_value(argv, "--match-target", cast=int,
                                   default=MATCH_RATE_TARGET),
    }


@dataclass
class _AuditResult:
    """Holds the three audit result lists (errors, warns, ok_lines) so
    the section helpers pass one object instead of three separate lists."""

    errors: list = field(default_factory=list)
    warns: list = field(default_factory=list)
    ok_lines: list = field(default_factory=list)


def _audit_jd_and_phrases(jd_path, phrases_file, text_low, result):
    """JD literal-term and external-phrase checks (sections 2-3)."""
    if jd_path:
        with open(jd_path, encoding="utf-8", errors="replace") as f:
            jd_text = f.read()
        ok_n, missing = _audit_jd(text_low, jd_text)
        if missing:
            result.errors.append(
                "JD literal terms with NO host in the rendered text: "
                + ", ".join(missing)
                + " — host the exact phrase truthfully or raise the gap "
                "(never fabricate)")
        elif not ok_n:
            result.warns.append(
                "JD literal phrase mining found NO skill phrases (this "
                "JD's qualification lines use no cue syntax) — the literal "
                "check is vacuous; supply --phrases-file with the JD's "
                "named skills/tools")
        else:
            result.ok_lines.append(
                f"JD literal terms: {ok_n}/{ok_n + len(missing)} hosted")
    if phrases_file:
        with open(phrases_file, encoding="utf-8", errors="replace") as f:
            phrases = [ln.strip() for ln in f if ln.strip()]
        missing = _audit_phrases(text_low, phrases)
        if missing:
            result.errors.append("phrases with NO literal host: "
                                 + ", ".join(missing))
        else:
            result.ok_lines.append(
                f"phrases: {len(phrases)}/{len(phrases)} hosted")


def _audit_report_skills(report_data, text_low, text, result):
    """Report hard/soft skill hosting check (sections 4-5). Mutates the
    three result lists in place."""
    if report_data is None:
        return
    hard, soft = _report_skills(report_data)
    errors = result.errors
    warns = result.warns
    ok_lines = result.ok_lines
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
            "report soft skills with NO literal host (ACTIONABLE — "
            "soft skills are safe to infer: host each literal phrase "
            "where the action-verb evidence lives, SKILL Steps 2/11; "
            "hosting these moved a real session's live match rate "
            "59→86): " + ", ".join(soft_miss))
    elif soft:
        ok_lines.append(f"report soft skills: {len(soft)}/{len(soft)} "
                        "hosted")
    for line in _report_findings(report_data, text):
        warns.append(line)


def main(argv=None):

    """ATS-audit CLI entry point."""
    args = _parse_ats_args(argv)
    if args is None:
        print(__doc__)
        return 2
    text = _extract_text(args["path"])
    text_low = text.lower().replace("\n", " ")
    result = _AuditResult()

    report_data = None
    if args["report_json"]:
        with open(args["report_json"], encoding="utf-8", errors="replace") as f:
            report_data = json.load(f)

    count, wc_errors = _audit_word_count(text, args["max_words"])
    result.ok_lines.append(f"words: {count}")
    result.errors.extend(wc_errors)
    if report_data is not None:
        report_wc = _report_word_count(report_data)
        if report_wc is not None:
            drift = count - report_wc
            result.ok_lines.append(
                f"words (report cross-check): {report_wc} "
                f"({drift:+d} vs our count)")

    _audit_jd_and_phrases(args["jd_path"], args["phrases_file"], text_low,
                          result)
    _audit_report_skills(report_data, text_low, text, result)
    _audit_match_rate(_report_match_rate(report_data), args["match_target"],
                      result)

    print("== ATS AUDIT ==")
    for line in result.ok_lines:
        print(f"  ok: {line}")
    for line in result.warns:
        print(f"  WARNING: {line}")
    for line in result.errors:
        print(f"  FAIL: {line}")
    if result.errors:
        print(f"RESULT: {len(result.errors)} finding(s) — fix or raise")
        return 1
    print("RESULT: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
