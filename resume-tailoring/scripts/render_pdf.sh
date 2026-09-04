#!/usr/bin/env bash
# Render a .docx resume to PDF and verify the result.
#
# Usage:
#   ./scripts/render_pdf.sh <input.docx> [output.pdf] [outdir]
#   ./scripts/render_pdf.sh --verbose <input.docx>  # full output for final verify
#   TARGET_PAGES=2 ./scripts/render_pdf.sh <input.docx> [output.pdf] [outdir]
#
# Defaults:
#   output.pdf   = <input-dir>/<input-basename>.pdf (next to the .docx)
#   outdir       = the .docx's directory
#   TARGET_PAGES = 2  (the length the resume is being compressed toward)
#
# Output (compact by default):
#   - Page count, last-page check, overflow count + reclaim hint, output path.
#   - `--verbose` adds: page-boundary map, the spilled-content dump, and the
#     last-page tail — use once for the final verification render.
#
# Requires: libreoffice (soffice), pdfinfo, pdftotext
set -euo pipefail

VERBOSE=0
TARGET_PAGES_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --verbose)
            VERBOSE=1
            shift
            ;;
        --target-pages)
            TARGET_PAGES_ARG="$2"
            shift 2
            ;;
        *)
            break
            ;;
    esac
done

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 [--verbose] [--target-pages N] <input.docx> [output.pdf] [outdir]" >&2
    echo "  Renders the .docx to PDF, prints page count, and reports" >&2
    echo "  overflow vs TARGET_PAGES (env, default 2). --target-pages" >&2
    echo "  overrides the env var for a single run." >&2
    echo "  Compact by default (page count, last-page check, overflow" >&2
    echo "  count, reclaim hint). --verbose adds the page-boundary map," >&2
    echo "  the spilled-content dump, and the last-page tail." >&2
    exit 2
fi

INPUT="$1"
if [ ! -f "$INPUT" ]; then
    echo "Error: input file not found: $INPUT" >&2
    exit 1
fi

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Structural/claim lint gate (A: validate_resume.py). Aborts the render on
# structural errors (orphan job titles, company blocks without titles,
# orphaned role content) or an unapproved whole-role elimination (Step 3
# seniority gate). Near-duplicate and claim warnings are shown under
# --verbose and otherwise pass. This makes the "applied vs intended" check
# mechanical: a dangling-title doc cannot reach the PDF step, and neither can
# a shortened timeline whose user approval was not recorded.
#
# Extra args for the validator come from RESUME_VALIDATE_ARGS (space-
# separated). The seniority gate needs only the approval token:
#   RESUME_VALIDATE_ARGS="--seniority-approved" ./scripts/render_pdf.sh "<out>.docx"
# Add --jd-years <N> for optional span-vs-JD feedback (independent of the
# gate), and --jd <JD.txt> to enable the education gate (Step 3.4) — it
# blocks the render when Education was dropped against a degree-requiring
# JD unless --education-approved records the override:
#   RESUME_VALIDATE_ARGS="--jd <JD.txt> --jd-years 5 --seniority-approved" \
#       ./scripts/render_pdf.sh "<out>.docx"
VALIDATE_OUT="$(python3 "$SELF_DIR/validate_resume.py" "$INPUT" \
    ${RESUME_VALIDATE_ARGS:-} 2>&1)" \
    && VALIDATE_RC=0 \
    || VALIDATE_RC=$?

# The education gate runs only with --jd; the seniority gate runs always.
# render_pdf.sh prints a NOTE when the education gate did not run.
case " ${RESUME_VALIDATE_ARGS:-} " in
    *" --jd "*) ;;
    *)
        echo "NOTE: education gate NOT run — no --jd in RESUME_VALIDATE_ARGS;" >&2
        echo "this render says nothing about the Education decision (Step 3.4)." >&2
        ;;
esac

if [ "$VALIDATE_RC" -ne 0 ]; then
    echo "Error: resume validation failed (exit $VALIDATE_RC). Fix the issues " >&2
    echo "before rendering:" >&2
    printf '%s\n' "$VALIDATE_OUT" >&2
    exit 1
fi
[ "$VERBOSE" -eq 1 ] && printf '%s\n' "$VALIDATE_OUT"

BASENAME=$(basename "$INPUT" .docx)
INPUT_DIR="$(cd "$(dirname "$INPUT")" && pwd)"
OUTPUT="${2:-${INPUT_DIR}/${BASENAME}.pdf}"
OUTDIR="${3:-${INPUT_DIR}}"
TARGET="${TARGET_PAGES_ARG:-${TARGET_PAGES:-2}}"

log() { if [ "$VERBOSE" -eq 1 ]; then echo "$@"; fi; }

mkdir -p "$OUTDIR"

# LibreOffice headless conversion. --outdir controls where the .pdf lands;
# it always names the output <input-basename>.pdf.
log "Rendering: $INPUT -> $OUTDIR/${BASENAME}.pdf"
libreoffice --headless --convert-to pdf "$INPUT" --outdir "$OUTDIR" >/dev/null 2>&1

RENDERED="$OUTDIR/${BASENAME}.pdf"
if [ ! -f "$RENDERED" ]; then
    echo "Error: PDF was not created at $RENDERED" >&2
    exit 1
fi

# If a custom output path was requested and differs, move it.
if [ "$RENDERED" != "$OUTPUT" ] && [ ! "$RENDERED" -ef "$OUTPUT" ]; then
    mv "$RENDERED" "$OUTPUT"
    RENDERED="$OUTPUT"
fi

log "Created: $RENDERED"

# Verify: page count
PAGES=$(pdfinfo "$RENDERED" 2>/dev/null | awk -F: '/^Pages/ {print $2}' | tr -d ' ')
echo "Pages: $PAGES (target: $TARGET)"

# Page-boundary map: first non-empty, non-footer content line of each page.
# Makes the page break visible at a glance (which role/bullet a page starts on).
if [ "$VERBOSE" -eq 1 ]; then
    echo "--- page boundaries ---"
    for p in $(seq 1 "$PAGES"); do
        first=$(pdftotext -f "$p" -l "$p" -layout "$RENDERED" - 2>/dev/null \
                | sed '/^[[:space:]]*$/d' | grep -v "Page [0-9]|" | head -1 \
                | sed 's/^[[:space:]]*//' | cut -c1-80)
        echo "  page $p starts: ${first:-(blank)}"
    done
fi

# Last-page sparsity check (unchanged behavior).
LAST_PAGE_LINES=$(pdftotext -f "$PAGES" -l "$PAGES" "$RENDERED" - 2>/dev/null | sed '/^[[:space:]]*$/d' | grep -cv "^Page ${PAGES}|")
echo "Last-page content lines: $LAST_PAGE_LINES"
if [ "$LAST_PAGE_LINES" -le 3 ]; then
    echo "WARNING: last page has only $LAST_PAGE_LINES lines — consider compressing one more older-role bullet to pull content onto the previous page."
fi

# Overflow report: when over target, show what spilled and how much to cut.
# This closes the compression loop in one command: the agent sees exactly
# which content sits on the overflow page and how many lines to reclaim,
# instead of running a separate pdftotext|sed cycle after every render.
if [ "$PAGES" -gt "$TARGET" ]; then
    OVER=$(pdftotext -f "$((TARGET + 1))" -l "$PAGES" -layout "$RENDERED" - 2>/dev/null \
           | sed '/^[[:space:]]*$/d' | grep -v "Page [0-9]|")
    OVER_LINES=$(printf '%s\n' "$OVER" | grep -c .)
    echo "--- OVERFLOW: $OVER_LINES line(s) spilled onto page(s) after target $TARGET ---"
    if [ "$VERBOSE" -eq 1 ]; then
        printf '%s\n' "$OVER" | sed 's/^/    /'
    fi
    # Rough reclaim hint: a dense role bullet wraps to ~2-3 rendered lines,
    # a one-line Tools line is 1-2. Give a concrete, actionable estimate with
    # a +1-bullet wrapping-variance buffer (undercounting cost extra
    # cut-render cycles in practice).
    bullets=$(( (OVER_LINES + 2) / 3 ))
    echo "  -> drop ~$OVER_LINES more rendered line(s) (≈$bullets bullet(s) + 1 for wrapping variance) to reach $TARGET page(s)."
fi

# Optional overflow check: show the tail of the last page for visual confirm
if [ "$VERBOSE" -eq 1 ]; then
    echo "--- last page tail ---"
    pdftotext -f "$PAGES" -l "$PAGES" -layout "$RENDERED" - 2>/dev/null | sed '/^[[:space:]]*$/d' | tail -5
fi

echo "$RENDERED"
