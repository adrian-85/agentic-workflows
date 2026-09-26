
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.

#!/usr/bin/env python3
"""ATS audit — literal-phrase verification of the RENDERED deliverable.

The workflow's internal matchers (measure_resume.py, validate_resume.py)
judge JD alignment with stemmed/concept matching. Real ATS screeners
match literal phrases against the rendered text (abbreviations and
paraphrases frequently do not count). A resume can pass every internal
gate and still lose ATS points: topically relevant bullets can carry
zero literal hits for many hard skills, and the ATS score drops (SKILL
Step 12). This tool is the ground-truth backstop:
it runs the ATS-style literal check on the same text a parser sees.

usage:
    python3 scripts/ats_audit.py <resume.pdf|resume.txt> [--jd <jd.txt>]
        [--phrases-file <f>] [--report-json <f>] [--raised <review.json>]
        [--max-words N]

Checks (exit 0 clean, 1 findings, 2 usage/IO error):
  1. WORD COUNT — the whole-resume <=1000-word cap (SKILL Steps 3/9),
     counted with the shared external-ATS tokenizer (see _count_words).
     `--max-words 0`
     disables. With --report-json, the external report's wordCount is the
     cap authority for that exact uploaded file; without it, OUR count is
     used as the preflight authority.
  2. --jd LITERAL TERMS — qualification-line phrases mined from the JD
     (measure_resume's own qualification-line detection) checked literally
     against the rendered text. Zero-host terms include any hard skill
     whose last host died with a cut bullet or trimmed Tools line. A JD
     whose qualification lines mine no phrases makes the check vacuous:
     baseline warns, the final audit fails unless --phrases-file supplies
     the literal list.
  3. --phrases-file / --report-json EXTERNAL PHRASES — literal check of a
     curated phrase list (one per line) or an external ATS scan report
     JSON (findings + hard/soft skills). A skill's resumeCount, when the
     report carries one, is the authoritative host signal; otherwise the
     literal check decides. Hard-skill AND soft-skill zero-hits fail
     (soft skills are safe to infer — host the literal phrase where the
     action-verb evidence lives, SKILL Steps 2/4; a soft skill no kept
     bullet evidences gets a recorded raise/ignore disposition).
  4. --raised RECORDED DISPOSITIONS — the recorded Theme Review B JSON
     (workflow_gate.py review). Phrases dispositioned raise/ignore are
     the sanctioned not-hosted state: they report as "raised/ignored
     (recorded)" and do not fail, instead of re-FAILing a finished
     deliverable on every later audit.

Run on the PDF (pdftotext), not the .docx — the deliverable is what the
screener parses. Three classes of external finding are IGNORED by rule
(SKILL Step 12): contactEmail (the compact hyperlinked contact block is
deliberate design), specialCharacters (the typographic characters are
deliberate formatting the user chose — never reformat to satisfy a text
parser), and the education findings when the rendered resume has no
Education section (the drop was a Step 5.4 predicate decision the render
gate already sanctioned; the scan's generic advice does not re-open it).
"""

import json
from dataclasses import dataclass, field
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_asks  # noqa: E402
import workflow_gate  # noqa: E402
from script_args import (ATS_CONTACT_OFFSET, MAX_WORDS, MATCH_RATE_TARGET,
                         count_words, flag_value, maybe_help,
                         match_target_met, sha256_file)  # noqa: E402

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
    """Count the rendered text after removing PDF-only artifacts.

    The shared tokenizer uses external ATS compound-word semantics:
    hyphenated and slash-separated terms are single tokens, while
    apostrophe forms split into two tokens.
    """
    clean = _PAGE_WORD_RE.sub(" ", _ARTIFACT_RE.sub(" ", text))
    return max(0, count_words(clean) - ATS_CONTACT_OFFSET)


def _report_match_rate(data):
    """The report's matchRate.score value, or None when absent."""
    if not isinstance(data, dict):
        return None
    rate = data.get("matchRate")
    if isinstance(rate, dict) and isinstance(rate.get("score"), (int, float)):
        return int(rate["score"])
    return None


def _audit_match_rate(score, target, result):
    """The ≥75 match-rate target as a HARD STOP (2026-09-11): at or above
    it the hosting loop TERMINATES — no further hosting, keyword-driven
    rewording, or re-scans for score unless the user explicitly asks.
    Editing past a met target is forbidden; the old wording called the
    target "advisory, not a gate", and that framing is gone. Below
    the target, keep hosting. Configurable via --match-target; 0
    disables."""
    verdict = match_target_met(score, target)
    if verdict is None:
        return
    if verdict:
        result.ok_lines.append(
            f"match rate: {score} (target {target} MET — hosting loop "
            "CLOSED: stop score-driven edits now; no further hosting, "
            "rewording, or scans for score unless the user asks)")
    else:
        result.warns.append(
            f"match rate: {score} (below the {target} target — keep "
            "hosting literal phrases truthfully; see the no-host lists " "below for what to host)")


def _ceiling_check(score, target, resume_path, result):
    """Detect a stalled match rate: when two consecutive scans report the
    same score below target, the hosting loop has hit a ceiling and the
    agent MUST present the remaining skill checklist to the user before
    declaring the honest ceiling (SKILL Step 12). Score is persisted in
    a sidecar next to the resume PDF; on the first run there is no prior
    score, so no warning fires."""
    if score is None or target is None or not resume_path:
        return
    sidecar = pathlib.Path(resume_path + ".ceiling.json")
    prev = None
    try:
        prev = json.loads(sidecar.read_text(encoding="utf-8"))
        prev = prev.get("score") if isinstance(prev, dict) else None
    except (ValueError, OSError):
        prev = None  # no prior run (FileNotFoundError) or corrupt sidecar
    if prev == score and score < target:
        result.warns.append(
            f"CEILING DETECTED: match rate {score} unchanged from the "
            f"last scan — present the remaining hard/soft skill checklist "
            f"to the user before declaring the honest ceiling " f"(SKILL Step 12)")
    try:
        sidecar.write_text(json.dumps({"score": score}), encoding="utf-8")
    except OSError:
        pass  # best-effort; never blocks the audit


def _audit_word_count(text, max_words, report_count=None):
    """Apply the cap to an external report count when one is available."""
    local_count = _count_words(text)
    count = report_count if report_count is not None else local_count
    if max_words and count > max_words:
        return local_count, [f"{count} words exceeds the {max_words}-word cap by "
                             f"{count - max_words} — cut content, do not "
                             "shrink fonts (SKILL Steps 3/9)"]
    return local_count, []


def _hosted(text_low, phrase_low):
    """Literal phrase host — THE engine matcher (jd_asks.hosted). Kept
    as a wrapper: the audit's output IS the engine's positive-direction
    determination on the rendered text."""
    return jd_asks.hosted(text_low, phrase_low)


def _jd_literal_terms(jd_text):
    """Actionable literal skill phrases the JD asks for.

    Mined from the WHOLE posting (parse_asks's capitalized-mention and
    repetition gates need posting context — mining the qualification
    lines alone re-admits header/prose words as asks), then scoped to
    phrases whose text occurs in the qualification lines, so posting
    metadata and company-introduction prose never create audit failures.
    """
    qualification_lines = jd_asks.requirement_lines(jd_text)
    if not qualification_lines:
        return jd_asks.hard_phrases(jd_text)
    scope = jd_asks._norm_text(" ".join(qualification_lines))
    return [t for t in jd_asks.hard_phrases(jd_text)
            if jd_asks._norm_text(t) in scope]


def _audit_jd(text_low, jd_text):
    """Literal check of the JD's qualification terms. Returns (ok_count,
    missing)."""
    terms = _jd_literal_terms(jd_text)
    missing = [t for t in terms
               if not jd_asks._phrase_evidence(text_low, t, "hard")]
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


def _provenance_errors(data, resume_path, jd_path):
    """Reject an external report tied to different local scan inputs."""
    provenance = data.get("_scan_provenance") if isinstance(data, dict) else None
    if not isinstance(provenance, dict):
        return []
    errors = []
    for label, path, key in (
            ("resume", resume_path, "resume_sha256"),
            ("normalized JD", jd_path, "normalized_jd_sha256"),
            ("uploaded JD", provenance.get("uploaded_jd_path"),
             "uploaded_jd_sha256")):
        expected = provenance.get(key)
        if not expected or not path:
            continue
        try:
            actual = sha256_file(path)
        except OSError as exc:
            errors.append(f"cannot verify report provenance for {label}: {exc}")
            continue
        if actual != expected:
            errors.append(
                f"external report provenance mismatch for {label}: "
                "the report belongs to a different input")
    return errors


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
    (SKILL Step 12):

    - contactEmail — the hyperlinked contact block is deliberate design;
      a raw-text parser's fail is the known, accepted tradeoff.
    - specialCharacters — the Wingdings bullets, en-dash date ranges and
      curly apostrophes are the user's deliberate formatting ("it pops
      better with the current formatting"); NEVER reformat the resume
      to satisfy a text parser's character check.
    - the education findings (headingEducation, educationMatch) when the
      rendered resume has no Education section — the drop was a Step 5.4
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
                "alter it (SKILL Step 12)")
            continue
        if key == "specialcharacters":
            lines.append(
                f"  IGNORED specialCharacters ({status}): the typographic "
                "characters are the user's deliberate formatting — never "
                "reformat to satisfy a text parser (SKILL Step 12)")
            continue
        if key in ("headingeducation", "educationmatch") \
                and not education_present:
            lines.append(
                f"  IGNORED {name} ({status}): Education was dropped "
                "deliberately (Step 5.4 predicate; the render gate "
                "sanctioned it) — the scan's generic advice does not " "re-open that decision")
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
    baseline = "--baseline" in argv
    return {
        "path": argv[0],
        "max_words": 0 if baseline else flag_value(
            argv, "--max-words", cast=int, default=MAX_WORDS),
        "jd_path": flag_value(argv, "--jd"),
        "phrases_file": flag_value(argv, "--phrases-file"),
        "report_json": flag_value(argv, "--report-json"),
        "raised_file": flag_value(argv, "--raised"),
        "match_target": flag_value(argv, "--match-target", cast=int,
                                   default=MATCH_RATE_TARGET),
        "workflow_state": flag_value(argv, "--workflow-state"),
        "baseline": baseline,
    }


def _norm_phrase(phrase):
    """A review phrase in the audit's matching form: lowercase,
    whitespace-collapsed (record_audit normalizes the same way)."""
    return " ".join(str(phrase).lower().split())


def load_raised_phrases(path):
    """Phrases dispositioned raise/ignore in a recorded Theme Review B
    JSON (``workflow_gate.py review`` writes it; schema: kind "ats",
    one {phrase, decision, rationale} row per recorded finding).

    A recorded raise or ignore is the sanctioned not-hosted state for
    that phrase — the final audit reports it as recorded instead of
    re-FAILing a finished deliverable on every later audit. Returns
    (raised_set, error); a non-None error means exit 2."""
    try:
        with open(path, encoding="utf-8") as f:
            review = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot read --raised review {path}: {exc}"
    rows = review.get("dispositions") if isinstance(review, dict) else None
    if not isinstance(rows, list):
        return None, (
            f"--raised review {path} has no dispositions list — pass the "
            "recorded Theme Review B JSON (workflow_gate.py review)")
    raised = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("decision", "")).lower() in ("raise", "ignore"):
            phrase = row.get("phrase")
            if phrase:
                raised.add(_norm_phrase(phrase))
    return raised, None


@dataclass
class _AuditResult:
    """Holds the three audit result lists (errors, warns, ok_lines) so
    the section helpers pass one object instead of three separate lists."""

    errors: list = field(default_factory=list)
    warns: list = field(default_factory=list)
    ok_lines: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    vacuous_jd: bool = False


def _split_raised(missing, raised):
    """(truly_missing, raised_here) — missing terms split by the
    recorded raise/ignore set (normalized comparison)."""
    if not raised:
        return missing, []
    truly, hit = [], []
    for phrase in missing:
        (hit if _norm_phrase(phrase) in raised else truly).append(phrase)
    return truly, hit


def _note_raised(result, phrases, prefix=""):
    """Record the ok line for phrases dispositioned raise/ignore in a
    recorded review (the sanctioned not-hosted state)."""
    if phrases:
        result.ok_lines.append(
            f"{prefix}raised/ignored (recorded): " + ", ".join(phrases))


def _audit_jd_and_phrases(jd_path, phrases_file, text_low, result, raised):
    """JD literal-term and external-phrase checks (sections 2-3)."""
    if jd_path:
        with open(jd_path, encoding="utf-8", errors="replace") as f:
            jd_text = f.read()
        ok_n, missing = _audit_jd(text_low, jd_text)
        missing, raised_here = _split_raised(missing, raised)
        result.findings.extend(missing)
        _note_raised(result, raised_here)
        if missing:
            result.errors.append(
                "JD literal terms with NO host in the rendered text: "
                + ", ".join(missing)
                + " — host the exact phrase truthfully or raise the gap "
                "(never fabricate)")
        elif not ok_n:
            result.vacuous_jd = not phrases_file
        else:
            result.ok_lines.append(
                f"JD literal terms: {ok_n}/{ok_n + len(missing)} hosted")
    if phrases_file:
        with open(phrases_file, encoding="utf-8", errors="replace") as f:
            phrases = [ln.strip() for ln in f if ln.strip()]
        missing = _audit_phrases(text_low, phrases)
        missing, raised_here = _split_raised(missing, raised)
        result.findings.extend(missing)
        _note_raised(result, raised_here)
        if missing:
            result.errors.append("phrases with NO literal host: "
                                 + ", ".join(missing))
        else:
            result.ok_lines.append(
                f"phrases: {len(phrases)}/{len(phrases)} hosted")


def _audit_report_skills(report_data, text_low, text, result, raised):
    """Report hard/soft skill hosting check (sections 4-5). Mutates the
    three result lists in place."""
    if report_data is None:
        return
    hard, soft = _report_skills(report_data)
    hard_miss, hard_raised = _split_raised(
        [p for p, cnt in hard
         if not cnt and not _hosted(text_low, p.strip().lower())], raised)
    soft_miss, soft_raised = _split_raised(
        [p for p, cnt in soft
         if not cnt and not _hosted(text_low, p.strip().lower())], raised)
    result.findings.extend(hard_miss)
    result.findings.extend(soft_miss)
    for raised_here, label in ((hard_raised, "hard"), (soft_raised, "soft")):
        _note_raised(result, raised_here, f"report {label} skills ")
    if hard_miss:
        result.errors.append(
            "report hard skills with NO literal host: "
            + ", ".join(hard_miss))
    elif hard:
        result.ok_lines.append(f"report hard skills: {len(hard) - len(hard_raised)}"
                        f"/{len(hard)} hosted")
    if soft_miss:
        # A warning here let a deliverable ship with an unhosted soft
        # skill, so a soft-skill miss FAILs like a hard-skill one; the
        # sanctioned not-hosted state is a recorded raise/ignore
        # disposition (--raised).
        result.errors.append(
            "report soft skills with NO literal host (soft skills are "
            "safe to infer: host each literal phrase where the "
            "action-verb evidence lives, SKILL Steps 2/4; a soft skill "
            "no kept bullet evidences gets a recorded raise/ignore "
            "disposition, never silence): "
            + ", ".join(soft_miss))
    elif soft:
        result.ok_lines.append(f"report soft skills: {len(soft) - len(soft_raised)}"
                        f"/{len(soft)} hosted")
    for line in _report_findings(report_data, text):
        result.warns.append(line)


def _check_baseline_gate(args):
    """Require the prune theme review before a stateful baseline audit."""
    if not args["baseline"]:
        return True
    if not args["workflow_state"]:
        print("error: --baseline requires --workflow-state", file=sys.stderr)
        return False
    try:
        # require_at_least, not exact: the post-host baseline re-audit
        # (SKILL Step 4) runs after Theme Review B advanced the phase.
        workflow_gate.require_at_least(args["workflow_state"],
                                       "prune-theme-reviewed")
    except workflow_gate.GateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return False
    return True


def _note_vacuous_jd(result, baseline):
    """A vacuous JD literal check (no cue-syntax qual lines and no
    --phrases-file) is a baseline warning but a final FAIL: an unverified
    check must not report the deliverable clean."""
    msg = ("JD literal phrase mining found NO skill phrases (this JD's "
           "qualification lines use no cue syntax) — the literal check "
           "is vacuous; supply --phrases-file with the JD's named "
           "skills/tools")
    if baseline:
        result.warns.append(msg)
    else:
        result.errors.append(
            msg + " — a vacuous check cannot report the deliverable clean")


def _audit_words_and_report(args, text, result):
    """Read --report-json (with its provenance check) and audit the word
    count, returning the report data for the later skill checks."""
    report_data = None
    if args["report_json"]:
        with open(args["report_json"], encoding="utf-8", errors="replace") as f:
            report_data = json.load(f)
        result.errors.extend(_provenance_errors(
            report_data, args["path"], args["jd_path"]))
    report_wc = _report_word_count(report_data)
    count, wc_errors = _audit_word_count(
        text, args["max_words"], report_count=report_wc)
    result.ok_lines.append(f"words: {count}")
    result.errors.extend(wc_errors)
    if report_wc is not None:
        result.ok_lines.append(
            f"words (report cross-check): {report_wc} "
            f"({count - report_wc:+d} vs our count)")
    return report_data


def main(argv=None):

    """ATS-audit CLI entry point."""
    args = _parse_ats_args(argv)
    if args is None:
        print(__doc__)
        return 2
    if not _check_baseline_gate(args):
        return 2
    text = _extract_text(args["path"])
    text_low = text.lower().replace("\n", " ")
    result = _AuditResult()

    raised, raised_err = (load_raised_phrases(args["raised_file"])
                          if args["raised_file"] else (set(), None))
    if raised_err:
        print(f"error: {raised_err}", file=sys.stderr)
        return 2

    report_data = _audit_words_and_report(args, text, result)

    _audit_jd_and_phrases(args["jd_path"], args["phrases_file"], text_low,
                          result, raised)
    if result.vacuous_jd:
        _note_vacuous_jd(result, args["baseline"])
    _audit_report_skills(report_data, text_low, text, result, raised)
    score = _report_match_rate(report_data)
    _audit_match_rate(score, args["match_target"], result)
    _ceiling_check(score, args["match_target"], args["path"], result)

    print("== ATS AUDIT ==")
    for line in result.ok_lines:
        print(f"  ok: {line}")
    for line in result.warns:
        print(f"  WARNING: {line}")
    for line in result.errors:
        print(f"  FAIL: {line}")
    if args["baseline"]:
        try:
            workflow_gate.record_audit(
                args["workflow_state"], result.findings, args["path"])
        except workflow_gate.GateError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if result.errors:
        print(f"RESULT: {len(result.errors)} finding(s) — fix or raise")
        return 1
    print("RESULT: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
