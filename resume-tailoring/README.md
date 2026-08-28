# Resume Tailoring

A workflow for tailoring a master `.docx` resume to a specific job posting or
recruiter message without destroying its formatting. The master is edited via
its Word XML in place (fonts, sizes, paragraph styles, list/bullet numbering,
and hyperlinks all survive), and tailoring is **subtractive**: content is
compressed toward the target role by cutting from the oldest roles, never the
most recent.

The full 11-step workflow — reading inputs, rewriting the Summary, weaving
JD-required tools into role bullets, measuring before cutting, grammar passes,
and PDF verification — is documented in [`SKILL.md`](SKILL.md).

## Directory layout

| File | Purpose |
|---|---|
| `SKILL.md` | The complete workflow manual (when to use, step-by-step process, accuracy rules, common mistakes). |
| `scripts/docx_edit.py` | Reusable in-place `.docx` editor library (load/save, `find_p`, `set_text`, `set_labeled`, `replace_text`, `clone_after`, `remove`, `remove_empty`). Also a CLI for inspecting paragraph structure and generating unique `find_p` prefixes. |
| `scripts/tailor_resume.py` | Reference template for per-target tailoring scripts (`tailor_<target>.py`). Copy it, fill the `<placeholder>`s from the job description or recruiter message, and run. |
| `scripts/measure_resume.py` | Budgeting layer: renders once and reports per-role rendered-line cost and the exact reclaim gap to a target page count (with a +1-bullet wrapping-variance buffer in the reclaim plan), so compression cuts are planned as a batch instead of discovered by iteration. Keys off five **resume-format constants** at the top of the file (section headings, role-header style, date format, bullet styles) — adjust those to match your own resume. |
| `scripts/render_pdf.sh` | Renders the `.docx` to PDF (LibreOffice headless), verifies page count, flags a sparse last page, and reports overflow past `TARGET_PAGES` with a reclaim hint. Compact by default; add `--verbose` for the page-boundary map and spilled-content dump. |
| `scripts/diff_resume.py` | Diffs a user-edited tailored `.docx` against a fresh regenerate so manual edits surface as text and can be folded back into the tailor script. `--tailor <script>` auto-regenerates to a temp file and diffs in one command. |
| `scripts/read_profile.sh` | Extracts text from the optional `Profile.pdf` (a LinkedIn profile export) used as a content cross-reference. |
| `scripts/test_docx_edit.py` | Unit tests for `docx_edit.py`. |
| `scripts/test_measure_resume.py` | Unit tests pinning `measure_resume.py`'s default format assumptions and proving the constants adapt to a different resume. |

Run the full suite from the `scripts` directory:

```bash
python3 -m unittest test_docx_edit test_measure_resume
```

## Requirements

- Python 3 (standard library only for `docx_edit.py`; no third-party packages)
- `libreoffice` (headless PDF rendering)
- `pdftotext` / `pdfinfo` (poppler-utils) for page verification and measurement

## Quick start

1. **Drop in your personal assets** — `<userName> Master Resume.docx` (and
   optionally `Profile.pdf`, a LinkedIn profile export). These are gitignored
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
   edit fail the run (exit 2) instead of shipping a partial resume.
6. **Render and size-check** the PDF, iterating until the last page is full:

   ```bash
   TARGET_PAGES=2 ./scripts/render_pdf.sh "<userName> Resume - <Target>.docx"
   ```

   Measure before cutting with `measure_resume.py` to plan the oldest-role
   cuts as a batch.

## Resume format assumptions

`measure_resume.py` is the only script coupled to a resume's structure. It
keys off five constants at the top of that file, with defaults matching the
reference layout:

- `SECTION_CAREER` — the section heading that opens the roles (default `Career Experience`)
- `SECTION_EDUCATION` — the section heading that closes the roles (default `Education`)
- `COMPANY_STYLE` — the paragraph style of role-header lines (default `CompanyBlock`)
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