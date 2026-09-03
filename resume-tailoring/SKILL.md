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
| 4 | Align top title to JD title (less senior); rewrite Summary to lead with JD value | `set_text` |
| 5 | No sections between Summary & Proficiencies | — |
| 6 | Re-anchor senior role (merge, don't append) | `set_text`, `merge_into` |
| 7 | Expand role adjacent to JD industry/stage | `set_text` |
| 8 | Compress any section (measure first): oldest-role bullets, then off-JD proficiencies/certs | `measure_resume.py` `--jd` (DROP PLAN + TOP-BLOCK CANDIDATES); `squeeze_resume.py` for the residual gap |
| 9 | Fix grammar, typos, punctuation | grep + `validate_resume.py` |
| 10 | Save tailored copy (never overwrite master) | `save()` |
| 11 | Render + verify PDF | `render_pdf.sh` |

## Assets

User-supplied personal assets (`*.docx` / `*.pdf`, gitignored) live in the skill root:

- `<userName> Master Resume.docx` — the comprehensive data pool. Targeted scripts read it
  by name from the skill root and subtract from it. **Real experience belongs here** — if a
  session authors a bullet the user confirms, fold it into the master (via `clone_after` or
  the `--set-text`/`--append-after` CLI) so every future tailored resume can pull from it.
  Fold AFTER the per-target script is finished: a fold rewrites master text, which can
  invalidate the script's `find_p` prefixes. This ordering is ENFORCED, not a habit —
  after any fold (or a user edit between sessions), the next tailor run detects the
  changed master (`MASTER CHANGED:`) and runs auto-strict: skipped edits exit 2 without
  needing `DOCX_EDIT_STRICT=1`. If the master change was the USER's, respect it — re-dump
  `--prefixes`, fix drifted prefixes in the tailor script, never re-fold over their text.
- `Basic_LinkedInDataExport_*/` — the LinkedIn data export (CSVs), the richer source than
  the resume for content to enrich/merge (Step 1).

`scripts/` (each tool's docstring / usage is the reference; the steps below point at them):
`docx_edit.py` (Helper library) · `tailor_resume.py` (template) · `render_pdf.sh` (Steps 8, 11) ·
`measure_resume.py` (Step 8; `--jd` makes its DROP PLAN JD-aware) · `squeeze_resume.py` (Step 8;
auto-tightens to the page budget) · `validate_resume.py` (Steps 3, 11; `--master` auto-detects the
`* Master Resume.docx` next to the input) · `diff_resume.py` (Token-spend) · `read_profile.sh` (Step 1) ·
`test_*.py` unit tests (`python3 -m unittest test_docx_edit test_measure_resume test_validate_resume test_squeeze_resume`,
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
  named in the warning, not a generic `(remove)`. Takes prefix STRINGS
  (the copy-pasteable `find_p` lines from the `--prefixes` dump / DROP
  PLAN); a `find_p(...)` element also works (the code derives the prefix
  and prints a note — same on `drop_role`/`drop_section`).
- **`drop_role(body, "<company-header prefix>")`**: removes an ENTIRE role —
  company header, title, bullets, Tools line, trailing spacer — stopping
  BEFORE the next company header or section heading. The library
  replacement for hand-rolled role-drop helpers, which got the block
  grammar wrong under real use (a boundary check placed after the append
  swallowed the following `SectionHeading`, silently eating Education).
  Handles duplicate job titles with no `after=`/`nth=` anchor (the block is
  contiguous from the role's OWN header). Seniority alignment (Step 3) is
  a sequence of these.
- **`drop_section(body, "<heading prefix>")`**: removes a whole SECTION
  (e.g. Education) from its `SectionHeading` to just before the next one.
  Same boundary guarantee as `drop_role`.
- **`save()` drift sidecar**: auto-maintains `<dst>.drift.json` keyed by the
  calling script. First run records the baseline; later runs warn (`DRIFT:`) if
  the applied-edit count changed. Warn-once, rebaseline; the blocking gate for
  a stopped-matching edit is the skipped-edit check (exit 2 under
  `DOCX_EDIT_STRICT=1`). Pass `src=SRC` and the sidecar also records the
  master's sha256, warning (`MASTER CHANGED:`) when the master differs from
  the script's last run — a fold landed between runs, or (most often) the
  USER edited the master between sessions. **That warning is also a GATE**:
  a run against a changed master is auto-strict — any skipped edit exits 2
  even without `DOCX_EDIT_STRICT=1`, so a mid-flight master edit can never
  silently strand drifted prefixes. Re-dump `--prefixes`, review what
  changed (respect the user's edits — never re-fold over them), fix any
  drifted prefix in the tailor script, re-run.
- **`clone_after(body, ref_p, text)`**: add a NEW bullet to the master,
  inheriting numbering.
- **`merge_into(body, target, source, text)`**: rewrite `target` AND remove
  `source` in one op — prevents near-dup residue from a two-step
  `set_text` + `remove`.

Paragraphs are XML elements — read their text with `text_of(p)`, never
`p.text`/`p.text_`.

Inspect/author with:

```bash
python3 scripts/docx_edit.py "<userName> Master Resume.docx" [--prefixes]
# Default mode (no range/flag) prints the FULL PARAGRAPH MAP — index,
# style, numId, text. That is how you discover the block-boundary styles
# (CompanyBlock, SectionHeading) drop_role/drop_section key on:
python3 scripts/docx_edit.py "<userName> Master Resume.docx" --style SectionHeading
# Read a paragraph's COMPLETE text before rewriting it (the default map
# truncates at 90 chars / --prefixes at ~70). Use a range to see several:
python3 scripts/docx_edit.py "<userName> Master Resume.docx" 8 --full
python3 scripts/docx_edit.py "<userName> Master Resume.docx" 26-50 --full
# Fold NEW confirmed bullets into the master without writing a bespoke script:
python3 scripts/docx_edit.py "<userName> Master Resume.docx" \
    --append-after "<ref prefix>" --with "<new bullet text>"
# One-shot rewrite of an existing bullet (NOT for "Label: values" lines —
# set_text collapses the bold split; use a script with set_labeled there):
python3 scripts/docx_edit.py "<userName> Master Resume.docx" \
    --set-text "<ref prefix>" --with "<new bullet text>"
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
   uniqueness-checked against the document. To read a paragraph's FULL text before
   rewriting it (Summary, senior-role intro, a bullet), use
   `docx_edit.py "<docx>" <idx> --full` (or `<start>-<end> --full`) rather than ad-hoc
   inline python — it is one command and shows the exact string you are replacing.
2. **Run `measure_resume.py <MASTER> <target> --jd <JD.txt>` at AUTHORING time**, before
   writing the tailor script, and paste its DROP PLAN `find_p` lines verbatim into the
   script's `drop()` calls. Running measure on the master (not the target) plans all the
   cuts up front instead of discovering them after the first build. `--jd` protects JD
   evidence automatically (see Step 8), so the plan doesn't fight the JD.
3. **Before reusing a tailor script after the user edited the .docx, run `diff_resume.py --tailor`**
   first — one command surfaces manual edits a blind re-run would wipe. (The drift sidecar
   is the tripwire; diff_resume is the review.)
4. **Over-cut by 1–2 bullets per batch; if still over, drop a whole oldest role.** Never
   hand-shorten sentences to chase a page break — it's the lowest-leverage, highest-cycle
   edit. When only a few lines over, run `squeeze_resume.py` (Step 8) to close the residual
   gap automatically instead of trimming by hand.

Tool-enforced (no instruction needed): `render_pdf.sh` refuses broken or unapproved-elimination
docs (validator, Step 11); `measure_resume.py` prints the BATCH RECLAIM PLAN, its JD-aware DROP PLAN
with copy-pasteable `find_p` cut lines, and flags page widows / underfilled pages (Step 8);
`squeeze_resume.py` closes the residual page gap automatically.

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
  view; the LinkedIn data export has the richer detail that lets you enrich
  and merge bullets. Read the export folder `Basic_LinkedInDataExport_*/`:
  - `Positions.csv` — the full role history with description bullets: the
    richest source for restoring sub-roles and extra bullets the resume
    compressed away.
  - `Profile.csv` — headline and career summary.
  - `Skills.csv` / `Certifications.csv` / `Education.csv` — skills, certs, degrees.
  The CSVs are plain text. If you want them as one readable stream, dump the
  folder with the wrapper script:

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
- **Present only a feasibility-measured target.** Before recommending a
  page count to the user, run the what-if (measure `--simulate` with the
  candidate whole-role drops, at the candidate target) and check the
  projected page count. A real session recommended "2 pages" up front,
  the user approved, and the simulation THEN showed 4 pages after the
  approved drops — forcing either a silent re-target (a trust breach)
  or mid-flight target waffle. The user's approval is only as good as
  the numbers it is based on; simulate first, present the measured
  target, then ask.
- **Don't waffle between page targets.** If the LAST page renders under
  50% full, re-target one page lower BEFORE cutting any JD-matched bullet
  (measure emits `TARGET NOTE`). Once chosen, don't revisit the target
  mid-compression unless the note fires. (This prevents the 8-cycle
  waffle a 3-page senior build triggered when a 43% last page went
  unaddressed.)
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

   **Compute the resulting span BEFORE editing.** Pass each whole-role drop
   to measure as a what-if — it drops the roles in a temp copy, renders
   THAT, and prints the resulting TIMELINE, so the year math is the tool's,
   not hand-derived in chat (the file on disk is never modified)::

   ```bash
   python3 scripts/measure_resume.py "<Master>.docx" 3 --jd "<JD>.txt" \
       --simulate "Acme Corp, Austin, TX" --simulate "Globex, Chicago, IL"
   ```

   **Apply the drops with `drop_role` — never a hand-rolled helper.**
   Whole-role removal is a library primitive (`docx_edit.drop_role`): it
   owns the block grammar (company header → Tools line + trailing spacer,
   boundary paragraph excluded) and handles duplicate job titles with no
   anchor. Education goes with `drop_section`. See Common mistakes for the
   failure this replaces.
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
     education-substitution clause the visible span does not already
     satisfy (see the ambiguity note below), the role is in a credential-sensitive
     field (FDA/HIPAA/academic/regulated), the candidate is early-career (the
     degree is primary evidence), or the degree is the strongest available
     evidence for a JD ask (e.g. a CS degree for an engineering role).
   - If the resume's jd-fit verdict is "keep but it's weak", prefer dropping
     it when its 3 lines are the difference between a full last page and a
     page 3 spill — that's a clean card-for-lines trade.
   - **Ambiguity resolved mechanically:** when the JD offers "degree OR
     equivalent experience", the clause is satisfied by experience ONLY when
     the visible span exceeds the ask — at/below the ask the clause is
     load-bearing and Education is KEEP. `validate_resume.py --jd <JD.txt>`
     enforces this: a degree-requiring JD blocks the render when Education
     was dropped (`--education-approved` records the override), and warns
     when an equivalent clause is load-bearing.
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
   PDF until the approval is recorded with `--seniority-approved` (Step 11) — you
   cannot ship a PDF from a shortened timeline without the approval token.
   **The token's authority comes from OUTSIDE you.** Approval is valid only from
   (a) the user's reply in this chat, or (b) explicit pre-authorization in the
   original request (e.g. "seniority alignment approved" or the user naming the
   target span). Passing `--seniority-approved` on your own authority is not a
   judgment call — it is a bypass that turns the gate into decoration. Same rule
   for `--education-approved` (Step 3.4). In a single-turn/autonomous session
   (the whole task arrived in one message and no user turn is available):
   complete everything EXCEPT the final PDF, report the proposed span with the
   numbers, and hand the user the exact render command — the PDF is deferred,
   not self-approved.

### 4. Align the top title to the JD's, then rewrite the Summary to lead with JD-aligned value
The name/title line is what a screener compares against the posting's level
first. **When the JD names a title LESS SENIOR than the headline** (a
mid-level "Software Test Engineer" posting against "Staff Engineer"), set the
`[Title]` paragraph under the name to the JD's exact title
(`set_text(find_p(ps, "<title prefix>"), "<JD title>")`); same-level retitles
are also safe. **Never adopt a MORE senior title**; if the JD names no title,
leave the headline unchanged. Only the positioning headline changes —
history-block `JobTitleBlock` titles stay the real titles. The top title
often shares its prefix with the most-recent role's title ("Staff Engineer"
vs "Staff Engineer – Quality Automation & Engineering Enablement"), so
`after=` alone will NOT disambiguate it: `after=` means "strictly after
this paragraph in document order", not "the next paragraph", and both
candidates sit after the name line. Anchor by occurrence instead:
`find_p(ps, "Staff Engineer", nth=1)` — the headline is the FIRST match.

Level the title's echo in the Summary's first sentence so the pair reads
consistently ("Results-driven Staff engineer…" → "Results-driven Software Test
Engineer…"). `measure_resume.py --jd` and `validate_resume.py --jd` print a
`JD TITLE vs HEADLINE` WARNING when the headline is more senior — act on it.

Then rewrite the Summary so its first sentence hits the JD's core ask (e.g.
"owns quality end-to-end", "builds QA frameworks from scratch rather than
working within established ones"). Mirror the user's selling points explicitly.
Keep it to ~4–5 sentences.

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

### 8. Compress — the WHOLE resume tailors to the JD
**Cuts can come from ANY section, not just job bullets.** Technical
Proficiencies lines, Certifications, Tools lines, blank spacers, and
role bullets are all first-class cuts — the same rendered line cost.
Compression order: (1) oldest-role bullets via DROP PLAN, (2) TOP-BLOCK
CANDIDATES lines (off-JD proficiencies/certs), (3) Tools line trims, (4)
blank spacers. Go in that order; don't hand-pick.

**The plan is a sum of REMOVALS, and measure emits it.** Every line in
the plan's math is a paragraph the tailor script deletes. When the
oldest-first plan cannot close the gap, measure emits a TOP-ROLE TRIM
BATCH (the most-recent role's weakest unprotected bullets, sized to the
residual gap) and, when even that cannot close it, a NOTE saying so —
paste its `find_p` lines into the script's first pass and take the NOTE
back to the user (whole-role drops / JD-matched tradeoffs). Kept
bullets' text is final; hand-shortening kept bullets from two rendered
lines to one is not a cut and never closes a measured gap.

**Measure before cutting.** After the content edits (steps 4–7), run
`scripts/measure_resume.py <target.docx> [TARGET_PAGES]` — it renders once and
reports the per-role line cost and the **exact reclaim gap** to the target page
count, so you plan the oldest-role cuts as a batch instead of discovering them
through a cut-render loop. Pass the agreed Step-3 target positionally
(`measure_resume.py <target.docx> 3`) — measuring against the 2-page default
while over it prints a NOTE and over-reports the gap. Use its **BATCH RECLAIM PLAN** (measured
lines-per-bullet from the actual render, oldest roles first) rather than
estimating savings, and read its **page-fill table**: an underfilled page or a
role header stranded as the last line of a page ("WIDOW") will not be fixed by
a line-count budget alone — the WIDOW note names the block to reclaim from
(the content preceding the stranded header); trim those ~2 lines or merge
bullets so the next role starts cleanly at the top of a page.

**Apply the DROP PLAN, not your own instinct.** The BATCH RECLAIM PLAN says
*how many* bullets to cut per role; the **DROP PLAN** section names *which*, as
copy-pasteable `find_p(ps, "…")` lines — ranked weakest-first by a deterministic
scorer (generic/no-number bullets first; quantified ones last; ties toward
longer text since it saves more lines).

**Run `--jd <raw-JD.txt>` so the DROP PLAN is JD-aware.** The scorer alone is
JD-blind: it ranks by numbers and generic phrasing, so a bullet like
"Championed the adoption of Cypress" (a named JD qual) or a "Mentored junior
QA engineer" bullet (the JD requires mentorship) can land on the cut list and
be silently cut under page pressure. `--jd` extracts the candidate-tech terms
the JD asks for (matched against the resume's proficiency/Tools/title
vocabulary plus bullet-only tools) and excludes JD-evidence bullets from the
suggestions, listing them under "JD-matched (kept)" with the terms that
matched. It also prints the FULL extracted term list plus the file's word
count — scan that list against the posting to confirm the JD file is the
verbatim text, not a paraphrase: a summarized JD silently drops whole skill
areas from the DROP PLAN (paste the posting verbatim; a short file gets a
fidelity note, and a recruiter's message is legitimately short):

```bash
python3 scripts/measure_resume.py "<Target>.docx" 2 --jd "<JD>.txt"
```

Pass `--protect "<phrase>"` (repeatable) only for JD-critical facts the raw JD
text cannot name — candidate-specific evidence like a confirmed Snyk duty or
"sandbox" — so those bullets never land on the cut list:

```bash
python3 scripts/measure_resume.py "<Target>.docx" 2 --jd "<JD>.txt" \
    --protect "partner integrations" --protect "sandbox"
```

The scorer already protects what the JD text itself names — including core
tech nouns JDs use lowercase mid-sentence ("Perform API, service,
integration, and backend validation" protects API/integration bullets),
proficiency-LABEL vocabulary (an "API & Web Services" line is evidence when
the JD asks for API work), and singular/plural pairs ("integration" ↔
"partner integrations"). `--protect` is for what the JD text CANNOT name.

**Check DEAD-END PLANS before cutting anything.** A role whose DROP PLAN
budget exceeds its unprotected bullets cannot meet the budget without
cutting JD-matched content — measure flags these at the top
("DEAD-END PLANS: … cannot meet their cut budget …"). The honest fixes are
the TOP-BLOCK candidates, a Tools-line trim, or a whole-role drop — NOT
slicing kept bullets to fill the gap.

**Also check the TOP-BLOCK RECLAIM CANDIDATES** in the same measure output:
every Technical Proficiencies or Certifications line with no JD evidence, as a
copy-pasteable `find_p` cut (~1 line each). Cut those before touching any
JD-matched bullet — the list is deterministic; don't evaluate whether a line
"evidence" the JD.

**Residual gap: run `squeeze_resume.py`, don't trim by hand.** When only a few
lines over after the planned old-role cuts, the tool automates the remaining
cut-render-cut loop: each iteration applies the same JD-aware oldest-first
DROP PLAN, re-measures, and repeats until on target or no JD-safe cuts remain
(it backs up to `<docx>.pre-squeeze.docx`, logs every cut to
`<docx>.squeeze.json`, and prints a ready-to-paste `ps = drop(body, [...])`
block at the end — no hand-transcription). It STOPS — never overriding page
pressure — when every
remaining bullet is JD-matched/protected, signaling a whole-role drop
(seniority alignment, Step 3) or a Tools-line trim instead:

```bash
python3 scripts/squeeze_resume.py "<Target>.docx" 2 --jd "<JD>.txt"
```

Paste the printed fold-back block (or the DROP PLAN's `find_p` prefix strings)
straight into a `drop(body, [...])` call in the tailor script (never re-derive
them by hand), re-run the tailor
script, re-measure once to confirm the gap closed,
then render to verify. This replaces the cut-render-cut guesswork.

**Human rule still applies on top:** keep (or protect) the 2–3 bullets with hard
numbers or framework-ownership signal; drop generic process bullets
("established meetings", "enhanced documentation", "coordinated across teams")
before quantified ones. The scorer only ranks — you confirm against the JD.

The reclaim plan may also suggest **dropping a whole oldest role** (cleanest
page math). That is Step 3 seniority-alignment territory: confirm with the
user and record `--seniority-approved` at render time — only with the user's
authority (Step 3.5); in a single-turn session, defer the render to the user
instead. The plan annotates
any interior whole-role drop with a **gap warning** (the employment gap its
removal opens between surviving neighbors) — an interior drop that opens a
gap is a sign to cut from the oldest role instead, or restore a lean stub of
the removed role (header/title + strongest bullet) to keep the timeline
gapless.

Still a few lines over? Trim the oldest roles' Tools lines to one line each
(TOOLS LINES THAT WRAP reports the measured char budget per line — cut to
it, not to a tool count) and drop blank inter-role spacers with
`remove_empty`. Re-check the **TOP-BLOCK RECLAIM CANDIDATES** section of the
measure output: it lists every Technical Proficiencies / Certifications line
that carries NO JD evidence as a copy-pasteable `find_p` cut (~1 line each).
Cut those before cutting another JD-matched bullet.

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
(`01/2023 – 12/2024`); in prose, treat them like em dashes (replace with a
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
content orphaned after a Tools line, **unapproved whole-role elimination**, or
**Education dropped against a degree-requiring JD** (when `--jd` is passed).
Fix the errors, then render. The rendered PDF lands next to the `.docx`.

**When the JD specifies years of experience** (Step 3), confirm alignment and
record approval in one command:

```bash
RESUME_VALIDATE_ARGS="--jd <JD.txt> --jd-years <N> --seniority-approved" \
  ./scripts/render_pdf.sh "<output>.docx"
```

`--jd-years <N>` reports the visible span vs the JD's ask ("~7.4 years vs the
JD's 5+ — aligned"), warns if under (underqualified), and notes a large
overshoot — the signal to offer Step 3's gapless oldest-role elimination.
`--seniority-approved` is the gate token: REQUIRED only when whole roles were
eliminated — without it the render is blocked, so the user-approved decision is
recorded, not assumed. **Pass it only with the user's authority** (their chat
reply, or pre-authorization in the original request — Step 3.5). Without that
authority, finish the .docx and give the user this command to run themselves.
The two flags are independent: `--jd-years` is an
optional advisory; the gate reads only the approval token.
`--jd-years` is ONLY for a JD that states a number of years. If the
posting names no years ask, do NOT pass it (and never invent a value "to
see what happens"): every span comparison is then measured against a
fabricated ask, producing false *underqualified* verdicts and a false
load-bearing education warning. `validate_resume.py` warns when
`--jd-years` is passed but the JD text states no "N+ years" ask.

**Verification is TEXT-ONLY — never render pages to images.** This harness
reads no images, so converting the PDF to PNGs and "viewing" them fails
every time (observed in two sessions). The text path already covers what a
visual check would: `render_pdf.sh --verbose` prints the page-boundary map
and last-page tail, and `measure_resume.py` prints the page-fill table with
widow/underfill detection. Read those, plus `pdftotext` per page if you need
to inspect content placement.

**Final human review (what the tools can't judge).** After the last render,
re-read the full `--prefixes` dump top-to-bottom once: every kept bullet still
serves the JD, whole-role removals still read as a coherent timeline, the top
title's level matches the JD's title (Step 4), and the Summary's claims still
match what the reader sees. Years-vs-timeline is
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
| Waffling between the 2-page and 3-page target mid-compression | Settle it with the page-fill table: a last page under 50% full means re-target one page lower and re-measure BEFORE cutting JD-matched bullets (measure prints `TARGET NOTE`; Step 3) — don't revisit the target again unless the note fires |
| Using `set_text` on a `"Label: values"` line | Collapses to all-bold — use `set_labeled` (Helper library) |
| Hand-counting an edit budget (`expect_edits=N`) | Never count — `save()`'s drift sidecar records the baseline and warns on change |
| Hand-rolling whole-role removal in the tailor script | Use `drop_role(body, "<company prefix>")` / `drop_section(body, "Education")` — the library owns the block grammar. A hand-rolled helper that appends before checking the boundary (or only treats Heading1/2 as boundaries) swallows the next `SectionHeading` (Education) and strands later edits as "not found" skips |
| Verifying the PDF by rendering pages to images | Never works — this harness reads no images. Use `render_pdf.sh --verbose` (page map, last-page tail), `measure_resume.py`'s page-fill table, and `pdftotext` |
| Chasing a skip warning as a library bug | Re-dump `--prefixes` on the master FIRST — it may have been edited since your dump (the `MASTER CHANGED:` sidecar warning fires on this); a prefix can also match a paragraph an earlier `drop` already removed if you thread a stale `ps` list — use `ps = drop(body, [...])` |
| Guessing WHICH bullets to cut from the reclaim gap | Use measure's DROP PLAN with `--jd "<JD>.txt"` + `--protect "<fact>"`; paste its `find_p` lines, or run `squeeze_resume.py` for the residual gap (Step 8) |
| Cutting only job bullets — leaving off-JD proficiencies/certs while JD-matched bullets die | Cuts span the WHOLE resume: check measure's TOP-BLOCK RECLAIM CANDIDATES and the Tools lines before cutting another JD-matched bullet (Step 8) |
| Dropping an interior role and leaving a timeline gap | Check the plan's gap warning; cut from the oldest role instead, or restore a lean stub (header/title + strongest bullet) of the dropped role (Step 8) |
| Passing `find_p(ps, ...)` results into `drop()`/`drop_role()` | Works now — the element's own text is derived as the prefix (stderr note names it). Still prefer pasting the DROP PLAN's `find_p` lines verbatim: the string is the documented form and the note noise is zero (Helper library) |
| Iterating Tools-line trims because a trimmed line still wraps | Rare now: TOOLS LINES THAT WRAP reports the MEASURED budget per line ("value is N chars, wraps after ~M — cut ~N-M chars"), so the first trim lands. Trim to the reported budget, not a tool count — the proportional font makes "~8 tools" unreliable (Step 8) |
| Inflating verbs to match the JD ("designed from scratch" for a refactor) | Keep verbs truthful — see Accuracy |
| Inserting a Core Strengths/Top Skills section between Summary and Technical Proficiencies | Don't — weave skills into role bullets (Step 5) |
| Headline still says "Staff" against a less-senior JD title | Rewrite the top title to the JD's title and level its summary echo (Step 4) — the first line is what the screener compares |
| Appending bullets when content overlaps an existing one | Merge (`merge_into`) — appending blows the page budget (Step 6) |
| Overwriting the master resume | Write to `<userName> Resume - <Target>.docx` — never the master filename (Step 10) |
| Keeping Education when the degree isn't evidence for the JD | Evaluate the drop/keep predicates (Step 3.4) — a BA vs an engineering JD is a 3-line drop |
| Relying on spellcheck for proper nouns | Grep the text for `GitHub`, `HIPAA`, etc. (Step 9) |
| Em dash / double dash / semicolon in rewritten Summary or bullet prose | No em dashes, double hyphens, or semicolons — split into a new sentence or use a comma; single hyphens in compound words are fine (Step 9). `validate_resume.py` blocks the render |
| JD asks for fewer years than the candidate has | Offer Step 3 seniority alignment up front and record approval (`--seniority-approved`) — the render blocks without it. The token needs the user's authority: their chat reply or pre-authorization in the request; never pass it on your own |
