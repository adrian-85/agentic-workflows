#!/usr/bin/env bash
# Render a .docx resume to PDF and verify the result.
#
# Usage:
#   ./scripts/render_pdf.sh <input.docx> [output.pdf] [outdir]
#   ./scripts/render_pdf.sh --verbose <input.docx>  # full output for final verify
#   TARGET_PAGES=2 ./scripts/render_pdf.sh <input.docx> [output.pdf] [outdir]
#
# Defaults:
#   output.pdf   = <input-basename>.pdf (same name, .pdf extension)
#   outdir       = /tmp
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
if [ "${1:-}" = "--verbose" ]; then
    VERBOSE=1
    shift
fi

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 [--verbose] <input.docx> [output.pdf] [outdir]" >&2
    echo "  Renders the .docx to PDF, prints page count, and reports" >&2
    echo "  overflow vs TARGET_PAGES (env, default 2)." >&2
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

BASENAME=$(basename "$INPUT" .docx)
OUTPUT="${2:-/tmp/${BASENAME}.pdf}"
OUTDIR="${3:-/tmp}"
TARGET="${TARGET_PAGES:-2}"

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
