"""jd_sections — the fixed JD section contract (SKILL Step 1).

Every JD the user pastes in uses exactly these eight canonical headers,
each on its own line (an optional trailing colon is allowed). When the
posting omits that content, the user still includes the header with a
blank body — never a synonym, never a different phrasing. This replaces
the old per-JD calibrated heading regex (which grew a new pattern almost
every session as postings phrased "Required Experience" a new way) with
one deterministic contract: there is no fallback heading recognition here
by design — a header either matches this exact vocabulary or it doesn't.

A JD with NONE of these headers is a different, already-documented input
class (SKILL "When to Use": a recruiter's screening message / a bare
posting pasted without this structure) — its whole text is the ask
surface, handled by the caller, not this module.
"""

import re

SECTION_HEADERS = (
    "Position Title",
    "Company Overview",
    "Tech Stack",
    "Responsibilities",
    "Required Experience",
    "Additional Experience",
    "Required Education",
    "30/60/90 Day Expectations",
)

# The sections that carry ask/qualification evidence (jd_asks.requirement_lines).
# Position Title, Company Overview, Responsibilities, and the 30/60/90 section
# are context for the JD-theme read (SKILL Step 1), not qualification lines.
ASK_SECTIONS = (
    "Tech Stack",
    "Required Experience",
    "Additional Experience",
    "Required Education",
)

_HEADER_RE = {
    h: re.compile(r"^\s*" + re.escape(h) + r"\s*:?\s*$", re.I)
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


def is_sectioned(jd_text):
    """True when ``jd_text`` carries at least one canonical header."""
    return any(header_at(ln) for ln in jd_text.splitlines())


def parse_sections(jd_text):
    """Strict split into the 8 canonical sections.

    Returns a ``{header: body_text}`` dict (body_text stripped, empty
    string when the posting included the header with nothing under it).
    Returns None when ``jd_text`` carries NONE of the canonical headers
    (freeform JD / recruiter message — a different input class, not this
    function's job). Raises ValueError naming the missing header(s) when
    SOME but not all eight are present — the contract is all-or-nothing:
    every header is always included, blank when the posting omits that
    content.
    """
    found = {}
    current = None
    for ln in jd_text.splitlines():
        h = header_at(ln)
        if h:
            current = h
            found.setdefault(h, [])
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
    instead of the whole-file parse_sections contract."""
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
