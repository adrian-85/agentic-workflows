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

This workflow uses two user-supplied personal assets that stay local —
`*.docx` / `*.pdf` are gitignored, so the public repo ships scripts and docs
only, and the user drops their own files into the skill root:

- `<userName> Master Resume.docx` — the master resume: the comprehensive
  data pool (all LinkedIn detail, expanded). Targeted scripts read this by name
  from the skill root and subtract from it. **Real experience belongs here**,
  not in per-target scripts — if a tailoring session authors a bullet for real
  work the user confirms they did, fold it into the master (via `clone_after`)
  so every future tailored resume can pull from it.
- `Profile.pdf` — a LinkedIn profile PDF export, useful as a cross-reference
  for content the resume may be missing (the LinkedIn data export CSVs are an
  even richer source when available).
- `scripts/tailor_resume.py` — a reference template for per-target tailoring scripts (see below).
- `scripts/docx_edit.py` — the reusable editor library.
- `scripts/render_pdf.sh` — renders the .docx to PDF and verifies page count;
  prints a page-boundary map, and when over `TARGET_PAGES` (env, default 2)
  reports the spilled content and a "drop ~N lines / ≈M bullets" reclaim
  hint, so the compression loop closes in one command.
- `scripts/measure_resume.py` — the **budgeting layer**: renders once and
  reports the per-role rendered-line cost and the exact reclaim gap to a
  target page count. Run it after the content edits but *before* the
  compression cuts to plan them as a batch, so cuts are measured rather than
  iterated.
- `scripts/diff_resume.py` — diffs a user-edited tailored .docx against a
  fresh regenerate from the tailor script, so manual edits (grammar
  tweaks, a dropped overclaim, a JD-required term only the user knows
  they have) surface as text and can be folded back into the script.

Run scripts from the skill root so the relative `SRC` path resolves:

```bash
cd ~/.pi/agent/skills/resume-tailoring && python3 scripts/tailor_resume.py
```

## Helper library

`scripts/docx_edit.py` is a reusable, importable editor. It provides the
primitives you need so you don't have to rewrite OOXML manipulation each time:

- `load(path)` → `(root, body, names, data, W)` — open a .docx for in-place edit
- `save(path, root, names, data)` — serialize mutations back to a .docx
- `paras(body)` / `text_of(p)` — iterate paragraphs and read their text
- `find_p(paras, startswith)` — locate a paragraph by a unique text prefix;
  returns `None` (with a stderr warning naming the candidates) if the prefix
  is missing or matches more than one paragraph, so `set_text`/`set_labeled`/
  `remove` **skip the edit instead of mutating the wrong paragraph**. Prefixes
  resolve against each paragraph's **original master text** (captured at
  `load`), so a script's own earlier edits cannot rewrite one paragraph's
  text to start with another target's prefix and collide mid-run — trimming
  two roles' Tools lines to the same start is order-independent. Use
  `prefixes()` for guaranteed-unique prefixes
- `set_text(p, text)` — rewrite a paragraph's text, **preserving the first run's
  formatting** (rPr: font, size, bold). For bullets/intros. **Do NOT use this on
  proficiency/"Label: values" lines** — they use a two-run bold-label /
  non-bold-value structure that `set_text` collapses to all-bold; use
  `set_labeled` instead.
- `set_labeled(p, label, value)` — rewrite a `"Label: values"` proficiency line
  while keeping the bold label / non-bold values split intact
- `clone_after(body, ref_p, text)` — clone a bullet (preserving its pPr and
  numbering id, so the cloned bullet keeps the same bullet style) and insert it
  after the reference; use this to **add new bullets** that inherit styling
- `remove(body, p)` — drop a paragraph (use to compress older roles)
- `remove_empty(body, startswith=None)` — drop blank spacer paragraphs
  (optionally only those at/after a given paragraph) to reclaim vertical space
  when the resume overflows by a few lines
- `paragraph_map(body)` — inspect structure (`idx | style | numId | text`)
- `prefixes(body)` — emit copy-pasteable, **uniqueness-checked**
  `find_p(ps, "…")` prefixes for every paragraph, so you don't transcribe a
  prefix by eye from the truncated paragraph map (a common bug — a wrong
  word, wrong casing, a dropped subword like "QnD"). Use this when authoring
  the `_drop`/`set_text` prefix lists in a per-target script.

CLI for inspection (run this first to see the paragraph map):

```bash
python3 scripts/docx_edit.py <path-to-resume.docx>
```

Inspect the bundled master resume (relative to the skill root):

```bash
cd ~/.pi/agent/skills/resume-tailoring
python3 scripts/docx_edit.py "<userName> Master Resume.docx"
```

Get exact, copy-pasteable `find_p` prefixes (uniqueness-checked) before
authoring a per-target script's prefix lists:

```bash
python3 scripts/docx_edit.py "<userName> Master Resume.docx" --prefixes
```

## The reference template

The subtractive pattern is demonstrated in `scripts/tailor_resume.py`
(bundled with this skill). It is a **generic template** — no company names,
no recruiter details, no specific tool lists — just each primitive in order
with placeholder content. It is NOT a tailoring of any specific job.

Read it before tailoring a new role. It demonstrates the complete
**subtractive** pattern: rewrite the Summary to lead with the target's skill
areas, retrim Technical Proficiencies so JD-relevant tools lead, re-anchor the
most-recent/senior role intro around ownership, weave each required tool into
the role bullet where it was actually used (merge, don't append — no separate
skills/keyword section between Summary and Technical Proficiencies), compress
every role to its most JD-aligned / quantified bullets via `remove`, trim the
oldest roles' Tools lines to one line each, drop blank inter-role spacer
paragraphs, and iterate the PDF render until ≤3 pages with a full last page.

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
(`find_p(ps, "…")`). When the master is rewritten (e.g. expanded from
LinkedIn), those prefixes may no longer exist. The `docx_edit` mutation
helpers (`set_text`, `set_labeled`, `clone_after`, `remove`) are defensive:
if a target paragraph isn't found they skip the edit with a stderr warning
rather than crashing, so the script still runs and renders. Skipped edits
mean that bullet wasn't tailored this run — review the warnings (run with
`DOCX_EDIT_STRICT=1` to make any skipped edit fail the run with exit 2) and
update the prefixes (or accept the untailored bullet). Delete stale scripts
that no longer apply enough edits to be worth keeping.

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
**Measure before cutting.** After the content edits (steps 4–7) but before
any compression, run `scripts/measure_resume.py <target.docx> [TARGET_PAGES]`
(or `TARGET_PAGES=2 python3 scripts/measure_resume.py <target.docx>`). It
renders once and reports the per-role rendered-line cost and the **exact
reclaim gap** to the target page count, so you plan the oldest-role cuts as a
batch instead of discovering them through a cut-render-cut-render loop.

Then use `remove` to drop the weakest bullets from roles 5+ years back. Keep
the 2–3 bullets with hard numbers or framework-ownership signal. Drop generic
process bullets ("established meetings", "enhanced documentation",
"coordinated across teams") before dropping quantified ones.

If you are still a few lines over after dropping bullets, two more reclaim
moves are high-leverage and cost little signal:

- **Trim the oldest roles' exhaustive Tools lines to one line each.** Roles
  5+ years back often carry a 15+ item tools list that wraps to two rendered
  lines; keeping the 6–8 most JD-relevant tools (plus the stack's signature
  one, e.g. Spring Boot / LAMP) drops one line per role with no real loss for
  a role that old.
- Drop the blank spacer paragraphs between roles in the lower half with
  `remove_empty` (a tool in `docx_edit.py`).

Re-run `render_pdf.sh` after cutting to verify — measuring replaces
iteration, it does not replace the final verification render.

### 9. Fix grammar and typos in the same pass
Common catches: `to improving` → `improving` (infinitive),
`companies goal` → `company's goal`, `HIPPA` → `HIPAA`, `evangalist` →
`evangelist`, `testzing` → `testing`, `Github` → `GitHub` (official casing).
Don't rely on spellcheck for these — grep the text.

### 10. Save the tailored copy (as .docx, the working format)
Write to `<userName> Resume - <Target>.docx` (drop "Master" from the
master's name). Never overwrite the master.
Keep the `.docx` around as the editable working file — you may need to iterate
on it after reviewing the rendered PDF.

### 11. Render the final PDF and verify
The `.docx` is the editing format; **the `.pdf` is the deliverable** — it is
what you submit to employers. Render and verify with:

```bash
./scripts/render_pdf.sh "<output>.docx" [output.pdf] [outdir]
```

This single script renders via LibreOffice headless, prints the page count,
flags a sparse last page (a sign of unwanted overflow), prints a
page-boundary map, and when over `TARGET_PAGES` (env, default 2) reports the
spilled content and a "drop ~N lines / ≈M bullets" reclaim hint.

Equivalent manual commands:
```bash
libreoffice --headless --convert-to pdf "<output>.docx" --outdir /tmp
pdfinfo "/tmp/<output>.pdf" | grep -i pages
pdftotext -layout "/tmp/<output>.pdf" - | sed -n '/Page 3|/,p'   # check overflow
```

If it overshoots the target page count, **compress one more older-role bullet**
and re-render. Iterate until the last page is full (not one line spilling over).

Deliver **both** files to the user: the tailored `.docx` (so they can make
manual edits later) and the rendered `.pdf` (the version they submit).

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
| Using `set_text` on a proficiency `"Label: values"` line | It collapses the line to all-bold. Use `set_labeled(p, label, value)` to keep the bold label / non-bold values split |
| Inflating verbs to match the JD ("designed from scratch" for a refactor) | Use the truthful verb — "refactored", "re-architected", "migrated" — and reserve "from scratch" for greenfield work |
| Inserting a Core Strengths/Top Skills section between Summary and Technical Proficiencies | Don't — weave required skills into role bullets as in-role evidence; the Summary + Technical Proficiencies already carry ATS keywords |
| Appending bullets when content overlaps an existing one | Merge into the existing bullet to respect the page budget |
| Bloating the top to "add content" | Reallocate: expand the senior role AND compress the oldest roles |
| Keeping stale per-target scripts that no longer apply edits | The mutation helpers skip missing targets with a warning instead of crashing — review warnings, update prefixes where the bullet still exists, or delete a script that no longer applies enough edits to be worth keeping |
| Authoring real-experience bullets in a per-target script via `clone_after` | Fold them into the master instead — the master is the comprehensive data pool, and per-target scripts should be purely subtractive. A bullet that lives only in one script is invisible to every other tailoring run |
| Syncing per-target scripts to each other or to master changes | Don't. Each per-target script is an artifact of its own session, driven by the JD provided then — it does not depend on other scripts. If the master changes, a script's prefixes may drift; the defensive helpers skip broken edits with a stderr warning. Re-run a per-target script only when you re-tailor that target, not proactively to keep it "in sync" |
| Ignoring stderr warnings from `docx_edit` helpers | A "target paragraph not found" warning means a `find_p` prefix drifted from the master's actual text — the edit was silently skipped, so a bullet the script intended to cut/drop is still in the resume. After every run, check stderr and the `save()` applied-vs-skipped summary; grep the rendered PDF for content you intended to drop. Run with `DOCX_EDIT_STRICT=1` to make any skipped edit fail the run (exit 2) instead of shipping a partial resume |
| A script's own earlier edits cause a mid-run `find_p` collision | `find_p` resolves prefixes against each paragraph's original master text (captured at load), so trimming one role's Tools line to start like another's can no longer collide — edit order is irrelevant. A collision now means the two paragraphs' ORIGINAL texts genuinely share the prefix: lengthen it (get exact prefixes from `--prefixes`) or capture targets up front
| Overwriting the master resume | Write to `<userName> Resume - <Target>.docx` — never the master filename |
| Relying on spellcheck for proper nouns | Grep the text for `GitHub`, `HIPAA`, etc. |
| A few lines spilling onto a sparse last page | Drop a weak older-role bullet; trim oldest-roles Tools lines to one line each; or remove blank inter-role spacer paragraphs with `remove_empty`. `render_pdf.sh` prints the spilled content and a "drop ~N lines" reclaim hint; `measure_resume.py` reports the gap before you cut |
| Compressing blind — cut-render-cut-render loop | Measure first: run `measure_resume.py` after content edits, plan the oldest-role cuts as a batch from its reclaim gap, then cut once. Measuring replaces iteration |
| Transcribing `find_p` prefixes by eye from the truncated paragraph map | Get exact, uniqueness-checked prefixes: `python3 scripts/docx_edit.py <docx> --prefixes` and paste them straight into the script |
| Assuming the master spells a repeated line one way | The master previously mixed `Tools & Technologies:` / `Tools and Technologies:` / `Tool and Technologies:` (typo); now standardized. Grab exact prefixes from `--prefixes` before authoring — a mismatched `set_labeled` label is skipped (stderr warning) |
| Skipping the PDF render check | Always verify page count and last-page overflow with `render_pdf.sh` |
