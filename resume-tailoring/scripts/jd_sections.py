"""jd_sections — the fixed JD section contract (SKILL Step 1).

Every JD the user pastes in uses exactly these eight canonical headers,
each on its own line with a TRAILING COLON (case-insensitive, optional
surrounding whitespace). When the posting omits that content, the user
still includes the header with a blank body — never a synonym, never a
different phrasing. This replaces the old per-JD calibrated heading
regex (which grew a new pattern almost every session as postings
phrased "Required Experience" a new way) with one deterministic
contract: there is no fallback heading recognition here by design — a
header either matches this exact vocabulary or it doesn't. The colon
is REQUIRED, not optional: the one-word headers ("title", "role")
would otherwise match a body line that happens to be that bare word,
and a posting whose prose mentions "required experience" mid-sentence
must never open a section.

A JD with NONE of these headers is a different, already-documented input
class (SKILL "When to Use": a recruiter's screening message / a bare
posting pasted without this structure) — its whole text is the ask
surface, handled by the caller, not this module.
"""

import re

SECTION_HEADERS = (
    "title",
    "company",
    "role",
    "responsibilities",
    "required",
    "additional",
    "education",
    "expectations",
)

# The sections that carry ask/qualification evidence (jd_asks.requirement_lines).
# Title, Company, Role, Responsibilities, and Expectations are context for
# the JD-theme read (SKILL Step 1), not qualification lines.
ASK_SECTIONS = (
    "required",
    "additional",
    "education",
)

# The trailing colon is mandatory: a bare "title" or "role" in the
# posting body must never read as a section header.
_HEADER_RE = {
    h: re.compile(r"^\s*" + re.escape(h) + r"\s*:\s*$", re.I)
    for h in SECTION_HEADERS
}


def header_at(line):
    """The canonical header name ``line`` matches exactly, or None."""
    s = line.strip()
    for h, rx in _HEADER_RE.items():
        if rx.match(s):
            return h
    return None


def is_ask_header(line):
    """True when ``line`` is one of the ask-bearing canonical headers."""
    return header_at(line) in ASK_SECTIONS


def parse_sections(jd_text):
    """Strict split into the 8 canonical sections.

    Returns a ``{header: body_text}`` dict (body_text stripped, empty
    string when the posting included the header with nothing under it).
    Section order in the FILE does not matter — content is collected by
    header NAME into a dict, each body running until the next header
    line — but each header line must carry its trailing colon. Returns
    None when ``jd_text`` carries NONE of the canonical headers
    (freeform JD / recruiter message — a different input class, not this
    function's job). Raises ValueError naming the missing header(s) when
    SOME but not all eight are present — the contract is all-or-nothing:
    every header is always included, blank when the posting omits that
    content (a header present without its colon counts as missing). A
    REPEATED header also raises: each header appears exactly once —
    merge the content into a single block (a posting's tech-stack list
    joins its qualification lines under one ``required:``).
    """
    found = {}
    current = None
    for ln in jd_text.splitlines():
        h = header_at(ln)
        if h:
            if h in found:
                raise ValueError(
                    f"JD repeats canonical section header: {h} — "
                    "SKILL Step 1 requires each header exactly once; "
                    "merge the content into one block")
            current = h
            found[h] = []
            continue
        if current is not None:
            found[current].append(ln)
    if not found:
        return None
    missing = [h for h in SECTION_HEADERS if h not in found]
    if missing:
        raise ValueError(
            "JD missing canonical section header(s): "
            + ", ".join(missing)
            + " — SKILL Step 1 requires every header present in the JD "
              "file (blank body when the posting omits that content)")
    return {h: "\n".join(found[h]).strip() for h in SECTION_HEADERS}


def find_section(jd_text, header):
    """Lenient single-section lookup: the body text under ``header`` up
    to the next canonical header or EOF, or None when ``header`` never
    appears at all. Tolerant of a partial document — callers that need
    only one section's lines (jd_asks.requirement_lines) use this
    instead of the whole-file parse_sections contract. Repeated headers
    are a contract violation rejected by parse_sections; this lenient
    helper simply reads the first block."""
    collecting = False
    seen = False
    out = []
    for ln in jd_text.splitlines():
        h = header_at(ln)
        if h == header:
            collecting = True
            seen = True
            continue
        if h is not None:
            if collecting:
                break
            continue
        if collecting:
            out.append(ln)
    if not seen:
        return None
    return "\n".join(out).strip()
