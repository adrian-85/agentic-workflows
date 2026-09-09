"""Flat-namespace argv helpers shared by the resume-tailoring scripts.

Lives outside validate_resume.py so docx_edit.py can import it without
the docx_edit -> validate_resume -> measure_resume -> docx_edit import
cycle. One parsing surface for every script: extract_common is the
standard --protect/--jd/positional loop, extract_flag/extract_flag_all/
parse_flag consume flags, flag_value reads without consuming.
"""

import sys
# pylint: disable=wrong-import-position,import-outside-toplevel
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.

# Whole-resume word cap for a tailored deliverable (SKILL Step 8).
# Home here (not validate_resume) so docx_edit's deliverable gate can
# apply the default without importing validate_resume (cycle break).
MAX_WORDS = 1000

# The match-rate target for the external ATS scan (SKILL Step 11): at or
# above it the literal-hosting work is done — stop adding hard/soft
# skills. A target to know when to stop, never a hard gate (a JD with
# genuinely-unhostable tools may top out below it). Override with
# ats_audit's --match-target; 0 disables.
MATCH_RATE_TARGET = 75


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
