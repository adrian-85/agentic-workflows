"""Flat-namespace argv helpers shared by the resume-tailoring scripts.

Lives outside validate_resume.py so docx_edit.py can import it without
the docx_edit -> validate_resume -> measure_resume -> docx_edit import
cycle. One parsing surface for every script: extract_common is the
standard --protect/--jd/positional loop, extract_flag/extract_flag_all/
parse_flag consume flags, flag_value reads without consuming.
"""

import hashlib
import re
import sys
# pylint: disable=import-outside-toplevel
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.

# Whole-resume word cap for a tailored deliverable (SKILL Step 9).
# Home here (not validate_resume) so docx_edit's deliverable gate can
# apply the default without importing validate_resume (cycle break).
MAX_WORDS = 1000

# The match-rate target for the external ATS scan (SKILL Step 12): at or
# above it the literal-hosting work is done — stop adding hard/soft
# skills. A target to know when to stop, never a hard gate (a JD with
# genuinely-unhostable tools may top out below it). Override with
# ats_audit's --match-target; 0 disables.
MATCH_RATE_TARGET = 75

# External ATS parsers count compound words as single tokens: hyphens and slashes
# bind tighter than spaces, so "CI/CD" and "test-automation" are one word each.
# Apostrophe forms such as "candidate's" split into two tokens.
_WORD_RE = re.compile(r"[\w]+(?:[-/][\w]+)*")


def word_tokens(text):
    """Return word tokens using the external ATS compound-token semantics."""
    return _WORD_RE.findall(text)


def count_words(text):
    """Count lexical word tokens shared by DOCX, PDF, and planning checks."""
    return len(word_tokens(text))


def sha256_file(path):
    """Return the SHA-256 digest of a file's binary contents."""
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def maybe_help(argv, usage_text=None):
    """Print usage and exit 0 when ``--help``/``-h`` is in ``argv``.

    The resume-tailoring scripts parse argv by hand (extract_common &
    friends), so without this a bare ``--help`` is consumed as the
    positional .docx path and dies as FileNotFoundError — a real session
    lost several tool calls to ``measure_resume.py --help``. Call this
    FIRST, before any positional scan."""
    if "--help" in argv or "-h" in argv:
        print(usage_text if usage_text is not None else __doc__ or "")
        raise SystemExit(0)

def match_target_met(score, target):
    """True when the score meets or exceeds the target. None when the
    check is not applicable (missing score or target disabled via 0).
    Centralizes the ≥75 match-rate target (SKILL Step 12) so ats_audit
    and ats_check agree on the verdict without duplicating the logic."""
    if not target or not isinstance(score, (int, float)):
        return None
    return score >= target


def parse_flag(argv, flag):
    """Remove a boolean flag from ``argv`` (in-place) and return True if it was present."""
    if flag in argv:
        argv.remove(flag)
        return True
    return False

def extract_flag(argv, flag):
    """Extract a flag + value pair from ``argv`` (in-place), returning the value or None."""
    if flag in argv:
        i = argv.index(flag)
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return None

def extract_flag_all(argv, flag):
    """Extract EVERY flag + value pair for a repeatable flag (in-place),
    returning the list of values (empty when absent)."""
    values = []
    while flag in argv:
        values.append(extract_flag(argv, flag))
    return values

def flag_value(argv, name, *, cast=str, default=None):
    """The value of ``name`` in ``argv`` WITHOUT consuming it (positionals
    and later argv scans stay untouched). Missing flag -> ``default``;
    flag present with no value -> SystemExit with a readable message
    (extract_flag's IndexError is not actionable). The single read-only
    variant lets ats_audit/ats_check read flags after their positional
    scan without disturbing it."""
    if name not in argv:
        return default
    i = argv.index(name)
    if i + 1 >= len(argv):
        raise SystemExit(f"error: {name} needs a value")
    return cast(argv[i + 1])

def read_jd_text(jd_file):
    """Read a --jd job-description file, exiting 2 on unreadable paths
    (shared by measure_resume + squeeze_resume; dedups identical blocks)."""
    try:
        with open(jd_file, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        print(f"error: cannot read --jd file {jd_file}: {e}",
              file=sys.stderr)
        sys.exit(2)

def extract_common(argv, extra_flags=()):
    """Split argv into (protect, jd_file, kept) using the standard --protect/
    --jd loop; extra_flags are single-value flags consumed but not returned.
    Mirrors measure_resume/squeeze_resume main() parsing exactly."""
    protect, jd_file = [], None
    kept = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--protect" and i + 1 < len(argv):
            protect.append(argv[i + 1])
            i += 2
        elif a == "--jd" and i + 1 < len(argv):
            jd_file = argv[i + 1]
            i += 2
        elif a in extra_flags:
            i += 1
        else:
            kept.append(a)
            i += 1
    return protect, jd_file, kept
