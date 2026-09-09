"""Deliverable-gate integration for docx_edit.save() (validate_resume glue).

Split from docx_edit.py so the editor core stays focused and under the
module-size lint cap. Imports the core one-way is NOT possible here (the
gate calls validate_resume, which imports docx_edit) — so this module
imports only os/sys/shlex + script_args, never docx_edit; save() calls
into this module, keeping the dependency direction docx_edit -> gate.

The gate refuses to WRITE a deliverable that validate_resume would
block: it runs BEFORE the zip write, on the in-memory tree, so a gated
state (broken structure, punctuation prose, 8-bullet-cap violation,
unapproved whole-role elimination) never becomes a file.
"""
# pylint: disable=wrong-import-position,import-outside-toplevel
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.



import importlib
import os
import shlex
import sys

from script_args import MAX_WORDS, extract_flag, extract_flag_all, flag_value, parse_flag


def tmp_jd_note(jd_path):
    """The /tmp JD persistence note (SKILL Step 1), or None. Shared by
    measure_resume's --jd report and the deliverable gate so the two
    warnings stay word-for-word in sync."""
    if jd_path and jd_path.startswith("/tmp/"):
        return (
            f"NOTE: --jd {jd_path} is in /tmp — this path may not persist "
            "across sessions. Copy the JD to the skill root as "
            "jd_<target>.txt (SKILL Step 1) before continuing.")
    return None


def _script_records_jd(jd_path):
    """Whether the calling script mentions the JD filename — the
    docstring-records-RESUME_VALIDATE_ARGS convention (SKILL Step 1),
    checked mechanically instead of trusted to prose. Matched on the
    basename so a relative-vs-absolute path difference cannot
    false-positive. An unreadable caller stays silent (soft convention)."""
    try:
        with open(sys.argv[0], encoding="utf-8") as f:
            return os.path.basename(jd_path) in f.read()
    except OSError:
        return True


def _approval_env():
    """Parse the RESUME_VALIDATE_ARGS env var (the same args render_pdf.sh
    passes to validate_resume.py) into gate flags, so ONE approval
    environment governs the save-time gate and the render gate:

        RESUME_VALIDATE_ARGS="--jd <JD.txt> --jd-years <N> --seniority-approved"

    Returns (jd_path, jd_years, seniority_approved, education_approved,
    protect, max_words) — ``protect`` is the list of --protect phrases
    (repeatable), forwarded so the gate's JD-FIT check honors the same
    candidate-specific facts measure did; ``max_words`` is the
    whole-resume word cap (None disables, --max-words 0).
    Approval tokens passed here must carry the USER's authority (their chat
    reply or pre-authorization in the original request) — never self-granted;
    the gate message says so.
    """
    raw = os.environ.get("RESUME_VALIDATE_ARGS", "")
    if not raw.strip():
        return None, None, False, False, [], None
    argv = shlex.split(raw)
    jd_path = extract_flag(argv, "--jd")
    jd_years = None
    if "--jd-years" in argv:
        try:
            jd_years = float(extract_flag(argv, "--jd-years"))
        except (TypeError, ValueError):
            jd_years = None
    seniority_approved = parse_flag(argv, "--seniority-approved")
    education_approved = parse_flag(argv, "--education-approved")
    protect = extract_flag_all(argv, "--protect")
    max_words = flag_value(argv, "--max-words", cast=int,
                           default=MAX_WORDS) or None
    return (jd_path, jd_years, seniority_approved, education_approved,
            protect, max_words)


def _deliverable_gate(path, root, src):
    """Refuse to WRITE a deliverable that validate_resume would block.

    The render gate alone is not much of a gate: by render time the .docx
    already exists on disk and the user can convert it themselves. This
    gate runs BEFORE the zip write, on the in-memory tree, so a gated
    state (broken structure, punctuation-rule prose, a role over the
    8-bullet cap, unapproved whole-role elimination) never becomes a file.

    Fires only on tailor-script saves (``src`` passed — the master the
    script copied from). Tool-internal saves (measure --simulate,
    squeeze, tests) pass no ``src`` and stay ungated; writes to the
    master itself are exempt (the master intentionally keeps everything).

    Approval tokens come from RESUME_VALIDATE_ARGS (see _approval_env) —
    the same env var the deferred render flow already documents. On a
    block: nothing is written, the blocking report lines go to stderr,
    and the run exits 2.
    """
    if src is None or path.endswith("Master Resume.docx"):
        return
    # Lazy, importlib-based: validate_resume imports docx_edit at load
    # (static cycle), so a from-import here would be a real cycle;
    # importlib keeps the load deferred to gate time with no static edge.
    vr = importlib.import_module("validate_resume")
    jd_path, jd_years, seniority_approved, education_approved, protect, \
        max_words = _approval_env()
    tmp_note = tmp_jd_note(jd_path)
    if tmp_note:
        print(tmp_note, file=sys.stderr)
    if jd_path and not _script_records_jd(jd_path):
        print(
            f"NOTE: {os.path.basename(sys.argv[0])} does not record the "
            f"JD path ({jd_path}) in its docstring — record "
            "RESUME_VALIDATE_ARGS there so the path is discoverable "
            "across sessions (SKILL Step 1).",
            file=sys.stderr,
        )
    try:
        result = vr.validate_tree(path, root, vr.TreeOptions(
            master_path=src, jd_path=jd_path, jd_years=jd_years,
            seniority_approved=seniority_approved,
            education_approved=education_approved, protect=protect,
            max_words=max_words))
    except Exception as e:  # validator crashed — do not silently pass the gate
        print(
            f"DELIVERABLE GATE: validation error ({e!r}) — fix the "
            f"validator before writing {path}",
            file=sys.stderr,
        )
        raise SystemExit(2) from e
    if result["blocking"]:
        _report_blocking(path, result)

def _report_blocking(path, result):
    """Print the gate-blocked report and exit 2 (nothing is written).

    A tailor run copies the master to DST before editing, so a stale
    (ungated) copy may sit at path from this run's own shutil.copy. It is
    removed here so NO deliverable — docx or pdf — can be produced from a
    gated state by any path.
    """
    blocking_lines = [l for l in result["lines"] if "ERROR" in l]
    stale = False
    if os.path.exists(path):
        try:
            os.remove(path)
            stale = True
        except OSError:
            pass
    print(
        f"DELIVERABLE GATE: {path} NOT written — validate_resume "
        f"blocks this state ({result['blocking']} blocking error(s)). "
        "No .docx exists to convert by hand; fix the errors and "
        "re-run. Approval-requiring decisions (seniority alignment, "
        "education override) need the USER's reply or pre-authorization, "
        "then re-run with RESUME_VALIDATE_ARGS carrying the token:",
        file=sys.stderr,
    )
    if stale:
        print(
            f"  removed the stale copy at {path} (this run's "
            f"master copy — the master itself is untouched)",
            file=sys.stderr,
        )
    for line in blocking_lines:
        print(f"  {line}", file=sys.stderr)
    raise SystemExit(2)
