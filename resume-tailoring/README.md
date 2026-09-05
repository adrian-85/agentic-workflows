# Resume Tailoring

A workflow for tailoring a master `.docx` resume to a specific job posting or
recruiter message without destroying its formatting. The master is edited via
its Word XML in place (fonts, sizes, paragraph styles, list/bullet numbering,
and hyperlinks all survive), and tailoring is **subtractive and JD-driven**:
every role — including the most recent — is pruned to its JD-relevant bullets
under a hard per-role bullet cap of 8 kept bullets; whole-role cuts come
from the oldest roles when seniority alignment calls for them. JD alignment
first, readability second; time-in-role and recency are only tiebreakers.

The full 11-step workflow — reading inputs, rewriting the Summary, weaving
JD-required tools into role bullets, measuring before cutting, grammar passes,
and PDF verification — is documented in [`SKILL.md`](SKILL.md).

## Directory layout

| File | Purpose |
|---|---|
| `SKILL.md` | The complete workflow manual (when to use, step-by-step process, accuracy rules, common mistakes). |
| `scripts/docx_edit.py` | Reusable in-place `.docx` editor library (load/save, `find_p` with smart-punctuation tolerance + `after=`/`nth=`, `set_text`, `set_labeled`, `replace_text`, `clone_after`, `remove`, `remove_empty`). Also a CLI: inspect paragraph structure / generate `find_p` prefixes, and `--append-after "<ref>" --with "<text>"` to fold new bullets into the master. `save()` auto-maintains a drift sidecar so an edit count that changes between runs warns. On tailor-script saves (`src=` passed) the **deliverable gate** runs validate_resume's blocking checks in memory BEFORE writing — a gated state is never written, and the stale master copy at the path is removed, so no `.docx` exists to convert by hand; approval tokens go in `RESUME_VALIDATE_ARGS` (same env as the render gate). |
| `scripts/tailor_resume.py` | Reference template for per-target tailoring scripts (`tailor_<target>.py`). Copy it, fill the `<placeholder>`s from the job description or recruiter message, and run — no `expect_edits` literal to maintain (drift sidecar). |
| `scripts/measure_resume.py` | Budgeting layer: renders once and reports per-role rendered-line cost and the exact reclaim gap to a target page count, then prints a **DROP PLAN** — the exact weakest-first bullets to cut as copy-pasteable `find_p` lines (`--protect "<JD ask>"` keeps JD-critical bullets off the cut list). Also emits **TOP-BLOCK RECLAIM CANDIDATES** (off-JD proficiencies/cert lines as copy-pasteable cuts), **gap warnings** when an interior whole-role drop would open an employment gap, and a **JD TITLE vs HEADLINE** line when the JD's title is less senior than the resume headline (SKILL Step 4; advisory). JD-term extraction uses whole-word matching, plural stemming, and a generic-hit-rate guard to avoid flooding. Keys off five **resume-format constants** at the top of the file (section headings, role-header style, date format, bullet styles) — adjust those to match your own resume. |
| `scripts/render_pdf.sh` | Renders the `.docx` to PDF (LibreOffice headless), verifies page count, flags a sparse last page, and reports overflow past `TARGET_PAGES` with a reclaim hint. Compact by default; add `--verbose` for the page-boundary map and spilled-content dump. |
| `scripts/squeeze_resume.py` | Auto-tightens a tailored resume to a page budget, ending the cut-render-cut-render loop. Each iteration renders, applies the JD-aware oldest-first DROP PLAN, and repeats until on target or no JD-safe cuts remain — at which point it signals a whole-role drop (seniority alignment) or a Tools-line trim. Logs every cut to `<docx>.squeeze.json` as copy-pasteable `find_p` prefixes to fold back into the tailor script. |
| `scripts/diff_resume.py` | Diffs a user-edited tailored `.docx` against a fresh regenerate so manual edits surface as text and can be folded back into the tailor script. `--tailor <script>` auto-regenerates to a temp file and diffs in one command. |
| `scripts/validate_resume.py` | Structural validator: catches orphan job titles, company blocks without titles, orphaned content after a Tools line, **role-integrity violations** (kept roles missing title or bullets; removed roles whose bullets survive), roles over the **8-bullet hard cap** (SKILL Step 8; the master as input is exempt), unapproved whole-role elimination, and quantified-claim mismatches against the master. With `--jd` it also warns when the resume headline is **MORE SENIOR** than the JD's named title (SKILL Step 4 title alignment; advisory) and gates Education drops against degree-requiring JDs. Enforces the punctuation rule (periods and commas only in Summary/job-history prose — no em dashes, double hyphens, semicolons, colons, or ellipses; compound hyphens, date-range en dashes, and the Tools line's `Label: values` colon exempt). `render_pdf.sh` runs it before rendering and refuses broken output. |
| `scripts/read_profile.sh` | Dumps the LinkedIn data-export folder (`Basic_LinkedInDataExport_*/` CSVs) as one readable stream, used as a content cross-reference. |
| `scripts/test_docx_edit.py` | Unit tests for `docx_edit.py`. |
| `scripts/test_measure_resume.py` | Unit tests pinning `measure_resume.py`'s default format assumptions and proving the constants adapt to a different resume. |
| `scripts/test_squeeze_resume.py` | Unit tests for `squeeze_resume.py`'s auto-loop and JD-safe-stop logic. |
| `scripts/test_validate_resume.py` | Unit tests for `validate_resume.py`'s structural checks, role-integrity lint, and seniority-gate logic. |

Run the full suite from the `scripts` directory:

```bash
python3 -m unittest test_docx_edit test_measure_resume test_validate_resume test_squeeze_resume
```

## Requirements

- Python 3 (standard library only for `docx_edit.py`; no third-party packages)
- `libreoffice` (headless PDF rendering)
- `pdftotext` / `pdfinfo` (poppler-utils) for page verification and measurement

## Quick start

1. **Drop in your personal assets** — `<userName> Master Resume.docx` (and
   optionally a `Basic_LinkedInDataExport_*` folder, a LinkedIn data export). These are gitignored
   and stay local.
2. **Inspect the master** — run the paragraph map and get copy-pasteable,
   uniqueness-checked prefixes:

   ```bash
   python3 scripts/docx_edit.py "<userName> Master Resume.docx" --prefixes
   ```

3. **Create a per-target script** — copy the template and fill the
   placeholders with choices driven by *this* session's job description:

   ```bash
   cp scripts/tailor_resume.py scripts/tailor_<target>.py
   ```

4. **Run it from the skill root** (so the relative `SRC`/`DST` paths resolve):

   ```bash
   python3 scripts/tailor_<target>.py
   ```

   Every run copies the master to `<userName> Resume - <Target>.docx` and
   edits that copy — the master is never overwritten.
5. **Verify every edit applied** — `DOCX_EDIT_STRICT=1` makes any skipped
   edit fail the run (exit 2) instead of shipping a partial resume. After a
   fold into the master (or a user edit between sessions), the next run is
   auto-strict: the `MASTER CHANGED:` gate exits 2 on any skipped edit even
   without the env var.
6. **Render and size-check** the PDF, iterating until the last page is full:

   ```bash
   TARGET_PAGES=2 ./scripts/render_pdf.sh "<userName> Resume - <Target>.docx"
   ```

   Measure before cutting with `measure_resume.py` to plan every role's cuts
   as a batch (its weak-match listing names generic-term matches that no
   longer protect); `--simulate "<company prefix>"` what-ifs a whole-role
   drop (seniority alignment) without touching the file. Verification is
   text-only — `--verbose` page map, page-fill table, `pdftotext` — never
   rendered page images.

## Resume format assumptions

`measure_resume.py` is the only script coupled to a resume's structure. It
keys off eight layout constants at the top of that file, with defaults matching
the reference layout:

- `SECTION_CAREER` — the section heading that opens the roles (default `Career Experience`)
- `SECTION_EDUCATION` — the section heading that closes the roles (default `Education`)
- `SECTION_PROFICIENCIES` — the proficiencies heading that brackets the roles' top (default `Technical Proficiencies`)
- `COMPANY_STYLE` — the paragraph style of role-header lines (default `CompanyBlock`)
- `VOCAB_STYLE` — the paragraph style of job-title lines, which feed the `--jd` vocabulary (default `JobTitleBlock`)
- `HEADLINE_STYLE` — the style of the top-of-resume headline, used for the JD-title-vs-headline seniority check (default `Title`; the 2nd such paragraph after the name)
- `DATE_RE` — the date format on role headers (default `MM/YYYY`)
- `BULLET_STYLES` — paragraph styles whose bullets carry no per-paragraph numbering (default `ListBullet`)

Everything else locates content by unique text prefixes, so any `.docx`
whose master matches the `<userName> Master Resume.docx` naming convention
works — tailor scripts and `docx_edit.py` are format-agnostic. If your
resume uses different headings or styles, edit the five constants instead
of forking the script. The unit tests (`test_measure_resume.py`) build
their fixtures from the current constants, so re-configuring the constants
keeps the suite green.

## Accuracy

Tailoring mirrors the JD's language, but never overclaims: "designed from
scratch" is reserved for greenfield work, and a bullet is never fabricated
for a tool the user hasn't used. See the Accuracy section in `SKILL.md`.

## Privacy

Personal assets (the master resume, LinkedIn exports, tailored outputs) are
never version-controlled — `.docx` and `.pdf` are gitignored, and this repo
ships code and documentation only. Users drop their own files into the skill
root.

## License

See the repository root [`LICENSE`](../LICENSE).