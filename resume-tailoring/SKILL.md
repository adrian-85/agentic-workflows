---
name: resume-tailoring
description: Use when the user wants to customize their resume to match a specific job posting or recruiter screening message — tailoring a .docx master resume for a target role, JD, or employer. Also use when producing a submission-ready PDF from an existing .docx resume.
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

## Assets

Two user-supplied personal assets stay local (`*.docx` / `*.pdf` gitignored);
drop them into the skill root:

- `<userName> Master Resume.docx` — the master resume: the comprehensive
  data pool (all LinkedIn detail, expanded). Targeted scripts read this by name
  from the skill root and subtract from it. **Real experience belongs here**,
  not in per-target scripts — if a tailoring session authors a bullet for real
  work the user confirms they did, fold it into the master (via `clone_after`)
  so every future tailored resume can pull from it.
- `Profile.pdf` — a LinkedIn profile PDF export, useful as a cross-reference
  for content the resume may be missing (the LinkedIn data export CSVs are an
  even richer source when available).
- `scripts/tailor_resume.py` — the reference template for per-target tailoring scripts (see below).
- `scripts/docx_edit.py` — the in-place editor library (see Helper library).
- `scripts/render_pdf.sh` — renders the .docx to PDF, verifies page count against
  `TARGET_PAGES` (default 2). Compact by default; `--verbose` adds a page-boundary
  map and spilled-content dump (Steps 8 & 11).
- `scripts/measure_resume.py` — the **budgeting layer**: renders once, reports per-role
  line cost and the exact reclaim gap to a target page count, so cuts are planned as a
  batch (Step 8). Format constants at the top adapt to a different resume layout
  (README → Resume format assumptions).
- `scripts/diff_resume.py` — diffs a user-edited docx against a fresh regenerate so
  manual edits surface as text; `--tailor <script>` auto-regenerates in one command
  (Token-spend practices).
- `scripts/read_profile.sh` — extracts text from `Profile.pdf` (Step 1).
- `scripts/test_docx_edit.py` / `scripts/test_measure_resume.py` — unit tests; run from
  `scripts/` with `python3 -m unittest test_docx_edit test_measure_resume`.

Run scripts from the skill root so the relative `SRC` path resolves:

```bash
cd ~/.pi/agent/skills/resume-tailoring && python3 scripts/tailor_resume.py
```

## Helper library

`scripts/docx_edit.py` is a reusable, importable editor — open a .docx,
mutate its XML in place, save. Full docstrings live in the file; essentials:

- `load(path)` → `(root, body, names, data, W)`; `save(path, root, names, data)` — open / persist edits
- `paras(body)` / `text_of(p)` — iterate paragraphs / read their text
- `find_p(paras, startswith)` — find a paragraph by unique text prefix; returns `None` (stderr warning) if missing or ambiguous, so edits skip safely. Matches each paragraph's **original master text**, so a script's own earlier edits can't collide mid-run. Use `prefixes()` for guaranteed-unique prefixes
- `set_text(p, text)` — rewrite text, **preserving the first run's formatting**. **Not for `"Label: values"` lines** (collapses to all-bold) — use `set_labeled`
- `set_labeled(p, label, value)` — rewrite a proficiency line keeping the bold label / non-bold values split; on a `clone_after` line it derives the value formatting from the label run (font/size/color preserved)
- `clone_after(body, ref_p, text)` — add a new bullet inheriting an existing bullet's numbering/style
- `remove(body, p)` / `remove_empty(body, startswith=None)` — drop a paragraph / blank spacers (optionally after a given point) to reclaim space
- `paragraph_map(body)` / `prefixes(body)` — structure inspection / copy-pasteable, uniqueness-checked `find_p` prefixes for authoring scripts

CLI for inspection:

```bash
python3 scripts/docx_edit.py "<userName> Master Resume.docx" [--prefixes]
```

## The reference template

The subtractive pattern is demonstrated in `scripts/tailor_resume.py`
(bundled with this skill) — a **generic template** with placeholder content,
no company names or recruiter details. Read it before tailoring a new role;
it shows each primitive in order (summary → proficiencies → role re-anchor →
per-role compression → tools trims → spacers → PDF iteration), which the
Workflow steps below cover in detail.

### Do you need to write a per-target script?

Not always. A saved script is an **artifact of iteration**, not a requirement.
For a one-shot tailoring you will never touch again, making the edits as
one-off commands against the docx is fine — the `.docx` and `.pdf` are the only
deliverables. A script earns its keep when you expect to **iterate** (page-count
tuning, accuracy fixes, user edits) or re-tailor later when the master changes:
it is re-runnable from the untouched master in one shot, and it is a readable,
diff-able record of every edit. If you do write one, name it
`scripts/tailor_<target>.py` and read `SRC`/`DST` from the skill root.

**Caveat:** a per-target script pins to the master's bullet text prefixes
(`find_p(ps, "…")`). When the master is rewritten, those prefixes may no
longer exist — the `docx_edit` mutation helpers skip missing targets with a
stderr warning rather than crashing, so the script still runs and renders.
Skipped edits mean that bullet wasn't tailored this run — review the
warnings (run with `DOCX_EDIT_STRICT=1` to make any skipped edit fail with
exit 2) and update the prefixes (or accept the untailored bullet). Delete
stale scripts that no longer apply enough edits to be worth keeping.

## Token-spend practices

The tailoring loop is render-and-measure heavy. These habits cut tokens per
session; the deterministic parts are enforced by the tools, not by
instruction:

1. **Author scripts from `--prefixes` alone.** It prints every paragraph's
   full text, uniqueness-checked. The paragraph map only adds style/numId
   and is needed for rare layout checks — skip it when authoring.
2. **Before reusing a tailor script when the user edited the .docx, run
   `diff_resume.py --tailor` first** — one command surfaces manual edits
   (wording, dropped claims, added terms) that a blind re-run would wipe.

Tool-enforced (no instruction needed):

- `render_pdf.sh` prints compact output by default (page count, last-page
  check, overflow count, reclaim hint); run it with `--verbose` for the
  final verification render (page map, spilled content, last-page tail).
- `measure_resume.py`'s reclaim plan includes a +1-bullet wrapping-variance
  buffer — cut one bullet past the stated gap when planning the batch.

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
+1-bullet wrapping-variance buffer.)

Then use `remove` to drop the weakest bullets from roles 5+ years back; keep
the 2–3 bullets with hard numbers or framework-ownership signal, and drop
generic process bullets ("established meetings", "enhanced documentation",
"coordinated across teams") before quantified ones. Still a few lines over?
Trim the oldest roles' Tools lines to one line each (keep the 6–8 most
JD-relevant tools) and drop blank inter-role spacers with `remove_empty`.

Re-run `render_pdf.sh` (compact) to verify — measuring replaces iteration, it
does not replace the final verification render.

### 9. Fix grammar and typos in the same pass
Common catches: `to improving` → `improving` (infinitive),
`companies goal` → `company's goal`, `HIPPA` → `HIPAA`, `evangalist` →
`evangelist`, `testzing` → `testing`, `Github` → `GitHub` (official casing).
Don't rely on spellcheck for these — grep the text.

### 10. Save the tailored copy (as .docx, the working format)
Write to `<userName> Resume - <Target>.docx` (drop "Master" from the
master's name). Never overwrite the master.
The `.docx` is the working file for the session — iterate on it while tuning
the rendered PDF, then delete both after the resume is submitted. The master
is the permanent artifact; tailored copies are temp files scoped to the
session that created them.

### 11. Render the final PDF and verify
The `.docx` is the editing format; **the `.pdf` is the deliverable** — it is
what you submit to employers. Render and verify with:

```bash
./scripts/render_pdf.sh "<output>.docx"
```

`render_pdf.sh` is compact by default (page count, last-page check, overflow
count, reclaim hint) so re-renders during compression are cheap. Add
`--verbose` for the final verification render to see the page-boundary map,
the spilled-content dump, and the last-page tail. It renders via LibreOffice
headless and checks page count against `TARGET_PAGES` (env, default 2); when
over target it prints what spilled and a "drop ~N lines / ≈M bullets" hint.

If it overshoots the target, **compress one more older-role bullet** and
re-render until the last page is full. The `.pdf` is what you submit; the
tailored `.docx` is its editable source. Both are session-temp and deleted
once the resume is submitted — only the master resume is kept.

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

| Mistake | Fix |
|---|---|
| Rebuilding the .docx from scratch | Edit XML in place — `python-docx` drops styles, numbering, and hyperlinks |
| Using `set_text` on a `"Label: values"` line | It collapses to all-bold. Use `set_labeled` (Helper library) |
| Inflating verbs to match the JD ("designed from scratch" for a refactor) | Keep verbs truthful — see Accuracy |
| Inserting a Core Strengths/Top Skills section between Summary and Technical Proficiencies | Don't — weave required skills into role bullets as in-role evidence (Step 5) |
| Appending bullets when content overlaps an existing one | Merge into the existing bullet to respect the page budget (Step 6) |
| Bloating the top to "add content" | Reallocate: expand the senior role AND compress the oldest roles (Step 3) |
| Keeping stale per-target scripts that no longer apply edits | Mutation helpers skip missing targets with a stderr warning — review warnings, update prefixes where the bullet still exists, or delete the script (see "Do you need to write a per-target script?") |
| Authoring real-experience bullets in a per-target script via `clone_after` | Fold them into the master instead — the master is the comprehensive data pool (Assets) |
| Syncing per-target scripts to each other or to master changes | Don't. Each is an artifact of its own session; if the master changes, prefixes may drift and the defensive helpers skip broken edits with a warning |
| Ignoring stderr warnings from `docx_edit` helpers | A "target paragraph not found" warning means a `find_p` prefix drifted — the edit was silently skipped. Check stderr and the `save()` applied-vs-skipped summary; run with `DOCX_EDIT_STRICT=1` to make any skipped edit fail the run (exit 2) |
| A script's own earlier edits cause a mid-run `find_p` collision | `find_p` resolves against each paragraph's original master text, so edit order can't collide; a collision now means the ORIGINAL texts share the prefix — lengthen it (via `--prefixes`) or capture targets up front |
| Overwriting the master resume | Write to `<userName> Resume - <Target>.docx` — never the master filename |
| Relying on spellcheck for proper nouns | Grep the text for `GitHub`, `HIPAA`, etc. |
| A few lines spilling onto a sparse last page | Drop a weak older-role bullet; trim oldest-roles Tools lines to one line each; or remove blank inter-role spacers with `remove_empty` (Step 8) |
| Transcribing `find_p` prefixes by eye from the truncated paragraph map | Get exact, uniqueness-checked prefixes: `python3 scripts/docx_edit.py <docx> --prefixes` and paste them straight into the script |
| Skipping the PDF render check | Always verify page count and last-page overflow with `render_pdf.sh` (Step 11) |
