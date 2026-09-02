---
name: resume-tailoring
description: Use when the user wants to customize their resume to match a specific job posting or recruiter screening message, or needs an ATS-friendly tailored copy from a master .docx. Also use when producing a submission-ready PDF from an existing .docx resume.
---

# Resume Tailoring

Tailor a master `.docx` resume for a specific job posting without destroying its
formatting. The workflow edits the Word XML in place so fonts, sizes, paragraph
styles, list/bullet numbering, and hyperlinks all survive.

## Core principle

**The master resume is the comprehensive data pool; tailored resumes pull
from it and compress to ≤3 pages.** Copy the master, edit that copy's Word XML
in place (so formatting survives), and never overwrite the master — every run
writes a new file (e.g. `John Doe Resume - <Target>.docx`). Compression is
subtractive: cut from the oldest roles, never the most recent.

## When to Use

- User provides a job description and wants their resume tailored to it
- User forwards a recruiter's screening message (e.g. "top 3 skills in
  bullets") and wants the resume aligned to it
- User has a master `.docx` resume and needs a per-target customized copy
- User needs a submission-ready PDF from an existing `.docx` resume

## Quick Reference

| Step | Action | Tool |
|---|---|---|
| 1 | Read inputs (JD, master, LinkedIn) | `read_profile.sh` |
| 2 | Extract employer selling points | — |
| 3 | Decide length + seniority alignment | `measure_resume.py` (TIMELINE) |
| 4 | Rewrite Summary to lead with JD value | `set_text` |
| 5 | No sections between Summary & Proficiencies | — |
| 6 | Re-anchor senior role (merge, don't append) | `set_text`, `merge_into` |
| 7 | Expand role adjacent to JD industry/stage | `set_text` |
| 8 | Compress oldest roles (measure first) | `measure_resume.py` (DROP PLAN) |
| 9 | Fix grammar, typos, punctuation | grep + `validate_resume.py` |
| 10 | Save tailored copy (never overwrite master) | `save()` |
| 11 | Render + verify PDF | `render_pdf.sh` |

## Assets

User-supplied personal assets (`*.docx` / `*.pdf`, gitignored) live in the skill root:

- `<userName> Master Resume.docx` — the comprehensive data pool. Targeted scripts read it
  by name from the skill root and subtract from it. **Real experience belongs here** — if a
  session authors a bullet the user confirms, fold it into the master (via `clone_after`)
  so every future tailored resume can pull from it. Fold AFTER the per-target
  script is finished: a fold rewrites master text, which can invalidate the
  script's `find_p` prefixes — re-run the script under `DOCX_EDIT_STRICT=1`
  afterwards and re-dump `--prefixes` if any skip fires.
- `Profile.pdf` — richer than the resume for content to enrich/merge (Step 1). The LinkedIn
  data-export CSVs are an even richer source when available.

`scripts/` (each tool's docstring / usage is the reference; the steps below point at them):
`docx_edit.py` (Helper library) · `tailor_resume.py` (template) · `render_pdf.sh` (Steps 8, 11) ·
`measure_resume.py` (Step 8) · `validate_resume.py` (Steps 3, 11; `--master` auto-detects the
`* Master Resume.docx` next to the input) · `diff_resume.py` (Token-spend) · `read_profile.sh` (Step 1) ·
`test_*.py` unit tests (`python3 -m unittest test_docx_edit test_measure_resume test_validate_resume`,
from `scripts/`).

Run scripts from the skill root so the relative `SRC` path resolves:

```bash
cd ~/.pi/agent/skills/resume-tailoring && python3 scripts/tailor_resume.py
```

## Helper library

`scripts/docx_edit.py` edits the .docx XML in place so formatting survives; full
signatures, docstrings, and CLI usage live in the file — the CLI is the
reference. The non-obvious rules while authoring:

- **`set_text` vs `set_labeled`**: `set_text` collapses all text into the first
  (bold) run — never use it on "Label: values" proficiency lines (e.g.
  `Programming Languages: Java, Python`). Use `set_labeled` to preserve the
  bold-label / non-bold-value split.
- **`find_p` resolves by original text**: prefixes match each paragraph's text
  as of `load()` time, so a script's own earlier edits can't collide mid-run.
  Smart punctuation is collapsed (curly quotes/dashes match ASCII). For
  duplicate job titles, use `after=<company-header>` or `nth=N`.
- **`drop(body, prefixes)`**: removes by prefix and returns the refreshed
  list — `ps = drop(body, [...])`. Library replacement for per-script
  `_drop` helpers: every prefix resolves against a fresh `paras(body)`, so
  it can never "find" a paragraph an earlier call already detached (a `ps`
  list threaded across calls goes stale → false ambiguity on short
  prefixes, or silent edits on detached elements). Skipped prefixes are
  named in the warning, not a generic `(remove)`.
- **`save()` drift sidecar**: auto-maintains `<dst>.drift.json` keyed by the
  calling script. First run records the baseline; later runs warn (`DRIFT:`) if
  the applied-edit count changed. Warn-once, rebaseline; the blocking gate for
  a stopped-matching edit is the skipped-edit check (exit 2 under
  `DOCX_EDIT_STRICT=1`). Pass `src=SRC` and the sidecar also records the
  master's sha256, warning (`MASTER CHANGED:`) when the master differs from
  the script's last run — see `save()`'s docstring for why that matters.
- **`clone_after(body, ref_p, text)`**: add a NEW bullet to the master,
  inheriting numbering.
- **`merge_into(body, target, source, text)`**: rewrite `target` AND remove
  `source` in one op — prevents near-dup residue from a two-step
  `set_text` + `remove`.

Inspect/author with:

```bash
python3 scripts/docx_edit.py "<userName> Master Resume.docx" [--prefixes]
# Fold NEW confirmed bullets into the master without writing a bespoke script:
python3 scripts/docx_edit.py "<userName> Master Resume.docx" \
    --append-after "<ref prefix>" --with "<new bullet text>"
```

## The reference template

`scripts/tailor_resume.py` is a **generic template** (placeholder content, no company or
recruiter detail) showing the subtractive pattern in order: summary → proficiencies →
role re-anchor → per-role compression → tools trims → spacers → PDF iteration (the
Workflow steps below cover the same pattern in detail).

### Do you need a per-target script?

One-shot tailoring can be one-off commands — the `.docx`/`.pdf` are the only
deliverables. Write `scripts/tailor_<target>.py` when you'll **iterate**
(page-count tuning, accuracy fixes, user edits) or re-tailor later: it
re-runs from the untouched master and is a diff-able record of every edit.
**Caveat:** it pins to the master's bullet-text prefixes; when the master is
rewritten, `find_p` prefixes may drift (review warnings, or run with
`DOCX_EDIT_STRICT=1` to fail on any skip).

## Token-spend practices

The loop is render-and-measure heavy. The deterministic parts are tool-enforced; the
manual habits are:

1. **Author scripts from `--prefixes` alone** (uniqueness-checked copy-paste; the paragraph
   map adds style/numId — only for rare layout checks). For CUT decisions, take the DROP
   PLAN's `find_p` lines directly (Step 8) — the prefixes are already emitted,
   uniqueness-checked against the document.
2. **Before reusing a tailor script after the user edited the .docx, run `diff_resume.py --tailor`**
   first — one command surfaces manual edits a blind re-run would wipe. (The drift sidecar
   is the tripwire; diff_resume is the review.)

Tool-enforced (no instruction needed): `render_pdf.sh` refuses broken or unapproved-elimination
docs (validator, Step 11); `measure_resume.py` prints the BATCH RECLAIM PLAN, its DROP PLAN with
copy-pasteable `find_p` cut lines, and flags page widows / underfilled pages (Step 8).

## Workflow

### 1. Read inputs
- Read the **job description** (JD) **or the recruiter's message**. A
  recruiter's "top skills" list or screening email is a lighter-weight input
  than a full JD — treat the named skills/tools as the alignment target just
  the same.
- Read the **master resume**. If it is a `.docx`, use `docx_edit.py` to edit. If
  only a PDF is available, ask for the `.docx` source — PDFs can be read but
  not edited precisely.
- **Read the LinkedIn source before editing.** The resume is a compressed
  view; the LinkedIn export / profile PDF has the richer detail that lets you
  enrich and merge bullets. If a **LinkedIn data export** is available, read
  `Skills.csv`, `Positions.csv`, `Profile.csv`,
  `Endorsement_Received_Info.csv`, `Recommendations_Received.csv`. Otherwise
  read the bundled `Profile.pdf` (a LinkedIn profile PDF export) — it lists
  bullets and sub-roles the resume may have compressed away. `Profile.pdf` is
  binary; extract its text with the wrapper script:

  ```bash
  ./scripts/read_profile.sh            # print to stdout
  ./scripts/read_profile.sh > /tmp/profile.txt
  ```

### 2. Extract the employer's selling points
Ask the user (or infer from the JD) the handful of themes to sell on; these
themes drive every later edit. **If the input is a recruiter's named-skills
list rather than a JD, those skills/tools ARE the selling points** — every
later edit shows where each was used.

### 3. Decide length up front
- **Target 2 pages; accept 3 for senior/Staff; 4 is too long.**
- Length is reclaimed by **compressing the oldest roles**, never the most
  recent. Recruiters weight the most-recent role most; cut from the bottom
  (roles 5+ years back) and keep their 2–3 strongest, quantified bullets.
- Don't bloat the top to "add content" — instead *reallocate*: expand the
  senior role with JD-aligned content AND compress the oldest roles to make
  room. Done right, the resume gets *shorter* while the important part gets
  stronger. Decide the target page count now (Step 8 measures it before
  cutting).

**Seniority alignment — when the JD specifies fewer years than the candidate
has** (this session's case: a mid-level "Software Test Engineer" JD asking
"5+ years" against a 15-year Staff-engineer background). This is a distinct
decision, presented **up front and to the user** — not discovered mid-
compression when the page budget forces it:

1. **Compare the candidate's total years to the JD's ask.** `measure_resume.py`
   prints the resume's visible TIMELINE span; that — not the candidate's full
   history — is what a recruiter/screener compares against the JD line.
2. **Eliminate older work experience in contiguous blocks.** Remove *entire*
   oldest roles (header, job title, bullets, Tools line) so the visible
   timeline stays gapless and lands at roughly the JD's ask plus a buffer
   (e.g. "5+ years" → show ~7–8 years). Deleting a few bullets from a
   15-year span does not align the resume — the *years shown* are what a
   screener sees. The structural validator catches any orphaned title/bullets
   after each whole-role removal.
3. **Reduce number-of-years statements** to match the visible span ("15 years"
   → "7+ years" in the Summary; any other "N years" claim). The validator
   enforces this mechanically for the Summary and every paragraph.
4. **Check the JD for a degree/education substitution clause.** Many JDs accept
   "X years OR equivalent degree/education" when the applicant has less
   experience. With such a clause, compressing experience is low-risk and
   **Education becomes the substitute evidence — keep it prominent, never cut
   it** under this option. Without a clause, the degree doesn't replace
   experience: still compressible on a title basis, but flag to the user that
   a screener may notice the gap between stated years and the fuller
   background.

   **Drop Education entirely when the degree is not evidence for the role.**
   Education is three rendered lines at the tail of the document — exactly the
   cost of the last-page spills that cost real iterations. Decide by
   observable predicates, not habit:

   - **DROP** when ALL hold: the JD states *no* degree requirement, the degree
     does not evidence the role's core asks (e.g. a Bachelor of Arts against a
     Software Test Engineer JD demanding test-automation/CI/tooling skill), and
     no education-substitution clause is in play (this JD's ask is met by
     experience alone).
   - **KEEP** when ANY hold: the JD requires a degree or has an
     education-substitution clause, the role is in a credential-sensitive
     field (FDA/HIPAA/academic/regulated), the candidate is early-career (the
     degree is primary evidence), or the degree is the strongest available
     evidence for a JD ask (e.g. a CS degree for an engineering role).
   - If the resume's jd-fit verdict is "keep but it's weak", prefer dropping
     it when its 3 lines are the difference between a full last page and a
     page 3 spill — that's a clean card-for-lines trade.
   - Removing Education is a structural change (the Education section heading
     and entries are removed together; `validate_resume.py` treats a resume
     ending at the last role's Tools line as clean). Remind yourself this is
     reversible: the master still has it, and a later JD that needs the degree
     just regenerates from the master.

   This is distinct from Step 3's keep-under-substitution-clause rule: that
   rule is about making a *shorter experience timeline* defensible; this one is
   about whether the degree is evidence at all for THIS JD.
5. **Raise it to the user before acting.** Dropping whole roles changes the
   narrative materially. Present the choice with the numbers (JD asks N+,
   candidate has Y, propose showing ~Z contiguous years), get a yes/no.
   **Enforced, not a habit:** `validate_resume.py` detects whole-role elimination
   (visible span ≥2 years shorter than the master) and `render_pdf.sh` blocks the
   PDF until you record the approval with `--seniority-approved` (Step 11) — you
   cannot ship a PDF from a shortened timeline without the approval token.

### 4. Rewrite the Summary to lead with JD-aligned value
The Summary is the first thing read. Rewrite it so its first sentence hits the
JD's core ask (e.g. "owns quality end-to-end", "builds QA frameworks from
scratch rather than working within established ones"). Mirror the user's selling
points explicitly. Keep it to ~4–5 sentences.

### 5. Don't insert sections between the Summary and Technical Proficiencies

The Summary is the intro paragraph; Technical Proficiencies follows directly.
**Do not insert a Core Strengths, Top Skills, or keyword-mirror section between
them.** A separate keyword list duplicates the proficiencies below it and
competes with the role bullets for the reader's attention. ATS keyword
matching is already carried by the Summary's mirror of JD language plus the
Technical Proficiencies section — a third keyword surface between them adds
noise, not signal.

When a recruiter or JD names required skills/tools, weave each into the role
bullet where it was actually used (see Step 6) so the skill appears as in-role
evidence, not a bare list.

### 6. Re-anchor the most recent / senior role
That role carries the most weight. Rewrite its intro to emphasize
**ownership** and the JD's selling points.

Enrich its bullets with the strongest missing content from LinkedIn. Where new
content overlaps an existing bullet, **merge** rather than append — appending
blows the page budget; merging keeps the role tight.

When the recruiter or JD names specific tools, weave each into the role
bullet where it was actually used, naming the tool in-bullet — that is
stronger evidence than a keyword list and is what recruiters ask for when
they say "show where you used it."

### 7. Expand the role most adjacent to the JD's industry/stage
If the JD targets a specific industry/stage (e.g. startup, AI, FinTech,
healthcare), expand the most relevant past role to show those themes with
concrete framing — keep and reframe (via `set_text`) the bullets that make
the theme explicit. If the master is missing a theme the user confirms they
have, fold that content into the master first (real experience lives in the
master, not per-target scripts).

### 8. Compress the oldest roles
**Measure before cutting.** After the content edits (steps 4–7), run
`scripts/measure_resume.py <target.docx> [TARGET_PAGES]` — it renders once and
reports the per-role line cost and the **exact reclaim gap** to the target page
count, so you plan the oldest-role cuts as a batch instead of discovering them
through a cut-render-cut-render loop. (Its reclaim plan includes a
+1-bullet wrapping-variance buffer.) Use its **BATCH RECLAIM PLAN** (measured
lines-per-bullet from the actual render, oldest roles first) rather than
estimating savings, and read its **page-fill table**: an underfilled page or a
role header stranded as the last line of a page ("WIDOW") will not be fixed by
a line-count budget alone — trim earlier content or merge bullets so the next
role starts cleanly at the top of a page.

**Apply the DROP PLAN, not your own instinct.** The BATCH RECLAIM PLAN says
*how many* bullets to cut per role; the **DROP PLAN** section names *which*, as
copy-pasteable `find_p(ps, "…")` lines — ranked weakest-first by a deterministic
scorer (generic/no-number bullets first; quantified ones last; ties toward
longer text since it saves more lines). Pass `--protect "<JD-critical
phrase>"` (repeatable) for anything the scorer can't know is valuable — e.g.
`--protect "partner integrations" --protect "sandbox"` — so JD-critical
bullets never land on the cut list:

```bash
python3 scripts/measure_resume.py "<Target>.docx" 2 \
    --protect "partner integrations" --protect "sandbox"
```

Paste the DROP PLAN's `find_p` prefix strings straight into a
`drop(body, [...])` call (never re-derive them by hand), re-run the tailor
script, re-measure once to confirm the gap closed,
then render to verify. This replaces the cut-render-cut guesswork.

**Human rule still applies on top:** keep (or protect) the 2–3 bullets with hard
numbers or framework-ownership signal; drop generic process bullets
("established meetings", "enhanced documentation", "coordinated across teams")
before quantified ones. The scorer only ranks — you confirm against the JD.

The reclaim plan may also suggest **dropping a whole oldest role** (cleanest
page math). That is Step 3 seniority-alignment territory: confirm with the
user and record `--seniority-approved` at render time.

Still a few lines over? Trim the oldest roles' Tools lines to one line each
(keep the 6–8 most JD-relevant tools) and drop blank inter-role spacers with
`remove_empty`.

Re-run `render_pdf.sh` (compact) to verify — measuring replaces iteration, it
does not replace the final verification render.

### 9. Fix grammar and typos in the same pass
Common catches: `to improving` → `improving` (infinitive),
`companies goal` → `company's goal`, `HIPPA` → `HIPAA`, `evangalist` →
`evangelist`, `testzing` → `testing`, `Github` → `GitHub` (official casing).
Don't rely on spellcheck for these — grep the text.

**Punctuation rule — no em dashes, double hyphens, or semicolons.** In the
Summary and job-history prose, never use em dashes (`—`), double hyphens
(`--`), or semicolons (`;`). Rejoin with a period (split into a new
sentence) or a comma instead. **Single hyphens are fine** — they appear in
compound words (`test-automation`, `end-to-end`, `CI/CD`) and are never
flagged by the validator. En dashes are only allowed in date ranges
(`06/2025 – 07/2026`); in prose, treat them like em dashes (replace with a
period or comma). Structural lines (company headers, job titles) and
non-role sections (Technical Proficiencies, Certifications, Education) are
not subject to the rule. `validate_resume.py` enforces this on the Summary
and job-history prose — a violation blocks the PDF render (Step 11).

### 10. Save the tailored copy (as .docx, the working format)
Write to `<userName> Resume - <Target>.docx` (drop "Master" from the
master's name). Never overwrite the master.
The `.docx` is the working file for the session — iterate on it while tuning
the rendered PDF, then delete both after the resume is submitted. The master
is the permanent artifact; tailored copies are temp files scoped to the
session that created them.

### 11. Render the final PDF and verify
The `.docx` is the editing format; **the `.pdf` is the deliverable** — render and
verify with `render_pdf.sh` (compact by default; `--verbose` for the final
verification render: validation report, page map, spilled content, last-page tail):

```bash
./scripts/render_pdf.sh "<output>.docx"          # compact
./scripts/render_pdf.sh --target-pages 3 --verbose "<output>.docx"  # final verification
```

The render's default page target is 2; pass `--target-pages N` matching the
target agreed in Step 3, so the overflow report measures against the goal you
actually agreed on (3 for senior/Staff, not the 2-page default).

`render_pdf.sh` **validates first** (runs `validate_resume.py`): it refuses to
render on blocking errors — an orphan job title, a company without a title,
content orphaned after a Tools line, or **unapproved whole-role elimination**.
Fix the errors, then render.

**When the JD specifies years of experience** (Step 3), confirm alignment and
record approval in one command:

```bash
RESUME_VALIDATE_ARGS="--jd-years <N> --seniority-approved" \
  ./scripts/render_pdf.sh "<output>.docx"
```

`--jd-years <N>` reports the visible span vs the JD's ask ("~7.4 years vs the
JD's 5+ — aligned"), warns if under (underqualified), and notes a large
overshoot — the signal to offer Step 3's gapless oldest-role elimination.
`--seniority-approved` is the gate token: REQUIRED only when whole roles were
eliminated — without it the render is blocked, so the user-approved decision is
recorded, not assumed. The two flags are independent: `--jd-years` is an
optional advisory; the gate reads only the approval token.

**Final human review (what the tools can't judge).** After the last render,
re-read the full `--prefixes` dump top-to-bottom once: every kept bullet still
serves the JD, whole-role removals still read as a coherent timeline, and the
Summary's claims still match what the reader sees. Years-vs-timeline is
automated (`validate_resume.py`); JD-fit judgment of kept bullets is not — that
stays human.

If it overshoots the target, **compress one more older-role bullet** and
re-render until the last page is full (the `.pdf` is the deliverable; the `.docx` is
session-temp source — see Step 10).

## When NOT to use this skill

- The user only has a PDF resume (no `.docx` source). Offer to review and
  recommend edits, but don't attempt precise edits on a PDF.
- The user wants a brand-new resume from scratch. This skill tailors an
  existing master; it does not author one.
- The user wants LinkedIn profile edits only (skills, summary, headline). The
  `docx_edit.py` helpers do not apply; advise in chat instead.

## Accuracy: mirror the JD's verbs, but never overclaim

Tailoring rewrites bullets to hit JD language, but the verbs must stay
truthful. A JD that asks to "design and develop object-oriented automation
frameworks" invites the word *design* — but if the actual work was
**refactoring** an existing framework or **re-architecting** CI, say that, not
"designed from scratch". Reserve "designed/built from scratch" for work that
was genuinely greenfield (e.g. a startup SDK framework no one had written
before). The user has to stand behind every line in an interview; an inflated
verb that can't be defended is worse than a JD keyword that went unmirrored.

**Never fabricate a role bullet for a tool you haven't used.** If a recruiter
or JD names a tool the user doesn't have, omit it and flag it to the user
rather than inventing a bullet — the user must stand behind every line in an
interview, and a made-up tool usage is the easiest thing to catch.

## Common mistakes

The tools and workflow steps above already enforce most failure modes (validators,
the drift sidecar, `merge_into`; Steps 8 & 11). What's left is judgment:

| Mistake | Fix |
|---|---|
| Rebuilding the .docx from scratch | Edit XML in place — `python-docx` drops styles, numbering, hyperlinks |
| Using `set_text` on a `"Label: values"` line | Collapses to all-bold — use `set_labeled` (Helper library) |
| Hand-counting an edit budget (`expect_edits=N`) | Never count — `save()`'s drift sidecar records the baseline and warns on change |
| Chasing a skip warning as a library bug | Re-dump `--prefixes` on the master FIRST — it may have been edited since your dump (the `MASTER CHANGED:` sidecar warning fires on this); a prefix can also match a paragraph an earlier `drop` already removed if you thread a stale `ps` list — use `ps = drop(body, [...])` |
| Guessing WHICH bullets to cut from the reclaim gap | Use measure's DROP PLAN + `--protect "<JD ask>"`; paste its `find_p` lines (Step 8) |
| Inflating verbs to match the JD ("designed from scratch" for a refactor) | Keep verbs truthful — see Accuracy |
| Inserting a Core Strengths/Top Skills section between Summary and Technical Proficiencies | Don't — weave skills into role bullets (Step 5) |
| Appending bullets when content overlaps an existing one | Merge (`merge_into`) — appending blows the page budget (Step 6) |
| Overwriting the master resume | Write to `<userName> Resume - <Target>.docx` — never the master filename (Step 10) |
| Keeping Education when the degree isn't evidence for the JD | Evaluate the drop/keep predicates (Step 3.4) — a BA vs an engineering JD is a 3-line drop |
| Relying on spellcheck for proper nouns | Grep the text for `GitHub`, `HIPAA`, etc. (Step 9) |
| Em dash / double dash / semicolon in rewritten Summary or bullet prose | No em dashes, double hyphens, or semicolons — split into a new sentence or use a comma; single hyphens in compound words are fine (Step 9). `validate_resume.py` blocks the render |
| JD asks for fewer years than the candidate has | Offer Step 3 seniority alignment up front and record approval (`--seniority-approved`) — the render blocks without it |
