# Resume Tailoring — Tool Reference

Mechanical procedures, commands, and API details extracted from SKILL.md. SKILL.md contains the
judgment (when to act, what to decide); this file contains the execution (which command, what flag,
how to read output).

## Helper library

`scripts/docx_edit.py` edits the .docx XML in place so formatting survives; full signatures,
docstrings, and CLI usage live in the file — the CLI is the reference. The non-obvious rules while
authoring:

- **`set_text` vs `set_labeled`**: `set_text` collapses all text into the first (bold) run — never
  use it on "Label: values" proficiency lines (e.g. `Programming Languages: Java, Python`). Use
  `set_labeled` to preserve the bold-label / non-bold-value split. The label is normalized to end
  with `": "` — a bare label (`"Tools & Technologies"`) or a bare-colon label (`"Tools:"`) gets
  the separator appended automatically, so label and values can never glue together.
- **`set_text` replaces, never inserts**: calling it to "add" content rewrites the anchor
  paragraph instead — the original line is gone. To ADD a new bullet/paragraph, anchor on a unique
  neighbor and use `clone_after`.
- **`find_p` resolves by original text**: prefixes match each paragraph's text as of `load()`
  time, so a script's own earlier edits can't collide mid-run. Smart punctuation is collapsed
  (curly quotes/dashes match ASCII). For duplicate job titles, use `after=<company-header>` or
  `nth=N`.
- **Return-value asymmetry**: `drop`/`drop_role`/`drop_section` return the refreshed paragraph
  list (assign them: `ps = drop(body, [...])`); `set_text`/`set_labeled`/`replace_text` return
  None — never assign their return (`ps = set_text(...)` threads None into the next `find_p`,
  which now raises a targeted TypeError naming the cause, instead of a bare `'NoneType' object is
  not iterable` three frames deep).
- **`drop(body, prefixes)`**: removes by prefix and returns the refreshed list — `ps = drop(body,
  [...])`. Library replacement for per-script `_drop` helpers: every prefix resolves against a
  fresh `paras(body)`, so it can never "find" a paragraph an earlier call already detached (a `ps`
  list threaded across calls goes stale → false ambiguity on short prefixes, or silent edits on
  detached elements). Skipped prefixes are named in the warning, not a generic `(remove)`. Takes
  prefix STRINGS (the copy-pasteable `find_p` lines from the `--prefixes` dump / DROP PLAN); a
  `find_p(...)` element also works (the code derives the prefix and prints a note — same on
  `drop_role`/`drop_section`).
- **`drop_role(body, "<company-header prefix>")`**: removes an ENTIRE role — company header,
  title, bullets, Tools line, trailing spacer — stopping BEFORE the next company header or section
  heading. The library replacement for hand-rolled role-drop helpers, which got the block grammar
  wrong under real use (a boundary check placed after the append swallowed the following
  `SectionHeading`, silently eating Education). Handles duplicate job titles with no
  `after=`/`nth=` anchor (the block is contiguous from the role's OWN header). Seniority alignment
  (Step 5) is a sequence of these. **Preferred order when extending an emitted script:** remove
  all `set_text`/`set_labeled` edits for the dropped role, including its Tools-line edits. The
  prune gate associates Tools-line candidates with their owning role, so `drop_role()` covers them
  as well as bullet candidates. If generated edits are temporarily retained, place `drop_role()`
  AFTER them and immediately before `save()`; calling it first removes their targets and makes
  `DOCX_EDIT_STRICT=1` report `target paragraph not found` skips.
- **`drop_section(body, "<heading prefix>")`**: removes a whole SECTION (e.g. Education) from its
  `SectionHeading` to just before the next one. Same boundary guarantee as `drop_role`.
- **`save()` drift sidecar**: auto-maintains `<dst>.drift.json` keyed by the calling script. First
  run records the baseline; later runs warn (`DRIFT:`) if the applied-edit count changed.
  Warn-once, rebaseline; the blocking gate for a stopped-matching edit is the skipped-edit check
  (exit 2 under `DOCX_EDIT_STRICT=1`). Pass `src=SRC` and the sidecar also records the master's
  sha256, warning (`MASTER CHANGED:`) when the master differs from the script's last run — a fold
  landed between runs, or (most often) the USER edited the master between sessions. **That warning
  is also a GATE**: a run against a changed master is auto-strict — any skipped edit exits 2 even
  without `DOCX_EDIT_STRICT=1`, so a mid-flight master edit can never silently strand drifted
  prefixes. Re-dump `--prefixes`, review what changed (respect the user's edits — never re-fold
  over them), fix any drifted prefix in the tailor script, re-run.
- **`clone_after(body, ref_p, text)`**: add a NEW bullet to the master, inheriting numbering. With
  `text=""`, it adds a managed blank spacer that survives a later `remove_empty(body)` pass.

  **Return-value idiom (the recurring gotcha):** `clone_after` returns the NEW paragraph element —
  NOT a refreshed paragraph list. Two sessions poisoned `ps` with `ps = clone_after(...)` and spent
  five debug calls recovering. The correct patterns:

  ```python
  # editing the clone LATER: chain off the RETURNED element, never find_p
  new = clone_after(body, find_p(ps, "<ref bullet>"), "New bullet text")
  set_text(new, "Rewritten text")            # or keep new for a later edit
  # finding a clone you added earlier: find_p DOES resolve script-created
  # paragraphs via the original-text registry, and it matches current text
  # as a fallback — but prefer keeping the returned element in a variable.
  # find_p / --lint-script resolve MASTER paragraphs; a prefix that only
  # exists because YOUR script creates it lints as a MISS (expected) and
  # must be reached through the returned element, not a literal prefix.
  ```
- **`merge_into(body, target, source, text)`**: rewrite `target` AND remove `source` in one op —
  prevents near-dup residue from a two-step `set_text` + `remove`.

Paragraphs are XML elements — read their text with `text_of(p)`, never `p.text`/`p.text_`.

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

## Script inventory

Each tool's docstring is its own reference; this is the tool → step map.

`docx_edit.py` (Helper library) · `tailor_resume.py` (template) · `render_pdf.sh` (Steps 4, 12) ·
`auto_prune.py` (Step 2 PHASE A — the machine prune; the ONLY sanctioned master consumer; emits and
runs the first tailor script through `run_tailor.sh`'s gates) · `measure_resume.py` (Step 3/5 page
math on the tailored copy; `--jd` on the MASTER is the machine pipeline's prune-plan mode — the
agent never runs it; `--linkedin <dump>` feeds the INFERENCE MAP for no-host terms in Step 4) ·
`squeeze_resume.py` (Step 9 backstop; auto-tightens only within the theme-scoped page pass) ·
`validate_resume.py` (Steps 5, 12; `--master` auto-detects the `* Master Resume.docx` next to the
input) · `diff_resume.py` (Token-spend; `--cutset` for the master-vs-build cut set) ·
`read_profile.sh` (Step 4) · `ats_audit.py` (Steps 4 and 12; baseline and final literal-phrase
audits of the rendered PDF + word cap) · `ats_check.py` (Step 12; runs the external ATS scan via the
user's saved credentials, saves the report JSON) · `workflow_gate.py` (per-target ordered state
gates, plus `template` for pre-filled review skeletons) · `test_*.py` unit tests
(`python3 -m unittest test_docx_edit test_auto_prune test_measure_resume test_validate_resume \
test_squeeze_resume test_ats_audit test_ats_check`, from `scripts/`).

## Workflow state gates

### workflow_gate.py — ordered workflow state

Also in this section: `diff_resume.py --cutset` (Theme Review A's master-vs-build cut set, one
command — see [SKILL Step 3](../SKILL.md)).

`workflow_gate.py` stores `<Target>.docx.workflow.json` beside the tailored build and enforces the
mechanical phase order. The state transitions are:

```text
pruned → prune-theme-reviewed → ats-audited → ats-theme-reviewed
       → seniority-approved → budgets-closed → spacers-closed
```

`auto_prune.py` creates the state at `pruned`; its `--theme` value is recorded as provenance only and
does not alter machine pruning. The two agent reviews are JSON records, not free-form notes:

```json
{"kind":"prune", "theme_anchors":["..."],
 "dispositions":[{"item":"...", "decision":"restore|cut|keep",
                    "rationale":"..."}]}
{"kind":"ats", "findings":[{"phrase":"...", "decision":"host|ignore|raise",
                               "rationale":"..."}]}
```

Generate either skeleton pre-filled instead of hand-building the JSON — the ATS template prints
every recorded baseline phrase (from the baseline audit) so the exact-set match holds by
construction; stdout is the skeleton, stderr carries the fill hints:

```bash
python3 scripts/workflow_gate.py template prune <state> > theme_review_<target>.json
python3 scripts/workflow_gate.py template ats <state> > theme_review_<target>_ats.json
```

Record them in order:

```bash
python3 scripts/workflow_gate.py review <state> theme_review_<target>.json
python3 scripts/ats_audit.py <pdf> --jd <JD.txt> --baseline --workflow-state <state>
python3 scripts/workflow_gate.py review <state> theme_review_<target>_ats.json
python3 scripts/workflow_gate.py advance <state> seniority-approved
python3 scripts/workflow_gate.py budgets <state> --words <N> --spill-lines <N> \
    [--attempted-page-removal]
python3 scripts/workflow_gate.py spacers <state> \
    [--omitted "<full role header>;<full role header>..."]
```

The baseline audit records every no-host phrase and the ATS review must disposition exactly that
set. `budgets` enforces the 1,000-word cap (`MAX_WORDS`) and permits a page-removal attempt only for
a positive spill of five rendered lines or fewer. `spacers` rejects a pass that creates a new page;
`--omitted` records boundaries where page pressure legitimately kept the spacer out (SKILL Step 9 —
omit the spacer, never theme-aligned content), and final-phase validation exempts exactly the
recorded boundaries. Theme quality and truthful wording remain agent/user judgments; the gate
enforces that those judgments are recorded and occur in order.

### State-aware shell gates

Phase 2 `run_tailor.sh` requires `RESUME_WORKFLOW_STATE` at least through `ats-theme-reviewed`
(`auto_prune.py` sets `RESUME_TAILOR_PHASE=prune` for its own Phase A run, which precedes the state).
Baseline rendering is explicitly separate from final rendering:

```bash
RESUME_RENDER_PHASE=baseline RESUME_WORKFLOW_STATE=<state> \
    ./scripts/render_pdf.sh <build.docx>
RESUME_RENDER_PHASE=final RESUME_WORKFLOW_STATE=<state> \
    ./scripts/render_pdf.sh --verbose <build.docx>
```

Baseline rendering and baseline `ats_audit.py --baseline` skip the word-cap gate internally because
word closure is later. Final rendering and the non-baseline ATS audit enforce the normal 1,000-word
cap. The workflow does not use a user-supplied word-cap bypass flag for this phase distinction.

## Reference template

`scripts/tailor_resume.py` is a **generic template** (placeholder content, no company or recruiter
detail) showing the subtractive pattern in order: summary → proficiencies → role re-anchor →
per-role compression → tools trims → spacers → PDF iteration (the Workflow steps in SKILL.md cover
the same pattern in detail). Import only the helpers the planned edits use — the script is re-run
after every revision, and pruning an unused import mid-iteration costs a full edit-plus-rerun cycle
for zero behavior change.

### Do you need a per-target script?

One-shot tailoring can be one-off commands — the `.docx`/`.pdf` are the only deliverables. Write
`scripts/tailor_<target>.py` when you'll **iterate** (page-count tuning, accuracy fixes, user edits)
or re-tailor later: it re-runs from the untouched master and is a diff-able record of every edit.
**Caveat:** it pins to the master's bullet-text prefixes; when the master is rewritten, `find_p`
prefixes may drift (review warnings, or run with `DOCX_EDIT_STRICT=1` to fail on any skip).

## Step 5 procedures — Seniority alignment (run on the PRUNED copy)

### Simulation (what-if whole-role drops)

Compute the resulting span BEFORE editing. Pass each whole-role drop to measure as a what-if — it
drops the roles in a temp copy, renders THAT, and prints the resulting TIMELINE, so the year math is
the tool's, not hand-derived in chat (the file on disk is never modified):

```bash
python3 scripts/measure_resume.py "<Tailored>.docx" 3 --jd "<JD>.txt" \
    --jd-years <N> \
    --simulate "Acme Corp, Austin, TX" --simulate "Globex, Chicago, IL"
```

Pass `--jd-years <N>` here whenever the JD states a years ask (e.g. "8+ years"): the TIMELINE is
then compared against the real ask at measure time, not first at render time — this is also what
makes the Education equivalent-experience check give a correct verdict.

With `--jd` the simulation also prints each drop's JD-evidence cost. A `JD EVIDENCE LOST:` line
means: restore that role trimmed to its JD bullets instead of eliminating it — and expect the
restored years to keep the span above the JD's ask (that is fine; the years carry the evidence).

### Applying whole-role drops

Apply the drops with `drop_role` — never a hand-rolled helper. Whole-role removal is a library
primitive (`docx_edit.drop_role`): it owns the block grammar (company header → Tools line + trailing
spacer, boundary paragraph excluded) and handles duplicate job titles with no anchor. Education goes
with `drop_section`. See Common mistakes in SKILL.md for the failure this replaces.

### Education drop predicates

**Establish mechanically whether the JD requires a degree at all before applying the predicates
below** — grep the JD text for degree language (`degree`, `Master`, `Bachelor`, `will accept`,
`H-1B`). Visa-attestation boilerplate is easy to misread; the validator is the gate, this grep only
saves the cycle. Then decide by observable predicates, not habit:

- **DROP** when ALL hold: the JD states *no* degree requirement, the degree does not evidence the
  role's core asks (e.g. a Bachelor of Arts against a Software Test Engineer JD demanding
  test-automation/CI/tooling skill), and no education-substitution clause is in play (this JD's
  ask is met by experience alone).
- **KEEP** when ANY hold: the JD requires a degree or has an education-substitution clause the
  visible span does not already satisfy (see the ambiguity note below), the role is in a
  credential-sensitive field (FDA/HIPAA/academic/regulated), the candidate is early-career (the
  degree is primary evidence), or the degree is the strongest available evidence for a JD ask
  (e.g. a CS degree for an engineering role).
- If the resume's jd-fit verdict is "keep but it's weak", prefer dropping it when its 3 lines are
  the difference between a full last page and a page 3 spill — that's a clean card-for-lines
  trade.
- **Ambiguity resolved mechanically:** when the JD offers "degree OR equivalent experience", the
  clause is satisfied by experience ONLY when the visible span exceeds the ask — at/below the ask
  the clause is load-bearing and Education is KEEP. `validate_resume.py --jd <JD.txt>` enforces
  this: a degree-requiring JD blocks the render when Education was dropped (`--education-approved`
  records the override), and warns when an equivalent clause is load-bearing.
- **"AND" is not "OR":** an AND construction ("degree AND N years", e.g. visa attestation) is a
  degree REQUIREMENT with no substitution path — Education is KEEP regardless of the span. Only an
  OR construction ("degree OR N years") opens the substitution path above.
- Removing Education is a structural change (the Education section heading and entries are removed
  together; `validate_resume.py` treats a resume ending at the last role's Tools line as clean).
  Remind yourself this is reversible: the master still has it, and a later JD that needs the
  degree just regenerates from the master.

### Approval tokens

`validate_resume.py` detects whole-role elimination (visible span ≥2 years shorter than the master)
and `render_pdf.sh` blocks the PDF until the approval is recorded with `--seniority-approved` (Step
11) — you cannot ship a PDF from a shortened timeline without the approval token.

**The token's authority comes from OUTSIDE you.** Approval is valid only from (a) the user's reply
in this chat, or (b) explicit pre-authorization in the original request (e.g. "seniority alignment
approved" or the user naming the target span). Passing `--seniority-approved` on your own authority
is not a judgment call — it is a bypass that turns the gate into decoration. Same rule for
`--education-approved`. In a single-turn/autonomous session (the whole task arrived in one message
and no user turn is available): present the proposed span with the numbers and STOP — the
deliverable gate (Step 11) refuses to write the .docx itself without the token, so there is no file
to hand over and nothing to convert by hand. After the user approves, re-run the tailor script with
the token in `RESUME_VALIDATE_ARGS` (it writes then), then render.

## Step 9 procedures — Theme-scoped page and word closure (measure the TAILORED copy, never the master)

### Reading measure output

After the content edits (Steps 5–7), run `scripts/measure_resume.py <target.docx> [TARGET_PAGES]` —
it renders once and reports the per-role line cost and the **exact reclaim gap** to the target page
count, so you plan the oldest-role cuts as a batch instead of discovering them through a cut-render
loop. Pass the agreed Step-4 target positionally (`measure_resume.py <target.docx> 3`) — measuring
against the 2-page default while over it prints a NOTE and over-reports the gap. Use its **BATCH
RECLAIM PLAN** (measured lines-per-bullet from the actual render, oldest roles first) rather than
estimating savings, and read its **page-fill table**: an underfilled page or a role header stranded
as the last line of a page ("WIDOW") will not be fixed by a line-count budget alone — the WIDOW note
names the block to reclaim from (the content preceding the stranded header); trim those ~2 lines or
merge bullets so the next role starts cleanly at the top of a page.

### Applying the DROP PLAN

**Treat the DROP PLAN as input to Step 9's theme judgment, not as the decision.** The BATCH RECLAIM
PLAN says *how many* bullets to cut per role; the **DROP PLAN** section names *candidates*, as
copy-pasteable `find_p(ps, "…")` lines — ranked weakest-first by a deterministic scorer
(generic/no-number bullets first; quantified ones last; ties toward longer text since it saves more
lines). Theme judgment decides which candidates actually go: never cut a theme anchor (Theme Review
A's list) to follow the rank order, and never keep a bullet the rank protects when it reads
off-theme.

**Run `--jd <raw-JD.txt>` so the DROP PLAN is JD-aware.** The scorer alone is JD-blind: it ranks by
numbers and generic phrasing, so a bullet like "Championed the adoption of Cypress" (a named JD
qual) or a "Mentored junior QA engineer" bullet (the JD requires mentorship) can land on the cut
list and be silently cut under page pressure. `--jd` extracts the candidate-tech terms the JD asks
for (matched against the resume's proficiency/Tools/title vocabulary plus bullet-only tools) and
excludes JD-evidence bullets from the suggestions, listing them under "JD-matched (kept)" with the
terms that matched. The JD file uses the fixed 8-section template (SKILL Step 1: `jd_sections.py` —
title, company, role, responsibilities, required, additional, education, expectations; one-word
headers, each with a required trailing colon; every header present, blank body when the posting
omits that content; header order in the file is free, each header appears exactly once — repeats
fail the contract; no fallback synonym recognition). It also prints the FULL extracted term list
plus the file's word count — scan that list against the posting to confirm the JD file is the
verbatim text, not a paraphrase: a summarized JD silently drops whole skill areas from the DROP PLAN
(paste the posting verbatim; a short file gets a fidelity note, and a recruiter's message is
legitimately short):

```bash
python3 scripts/measure_resume.py "<Target>.docx" 2 --jd "<JD>.txt"
```

Pass `--protect "<phrase>"` (repeatable) only for JD-critical facts the raw JD text cannot name —
candidate-specific evidence like a confirmed Snyk duty or "sandbox" — so those bullets never land on
the cut list:

```bash
python3 scripts/measure_resume.py "<Target>.docx" 2 --jd "<JD>.txt" \
    --protect "partner integrations" --protect "sandbox"
```

The scorer already protects what the JD text itself names — including core tech nouns JDs use
lowercase mid-sentence ("Perform API, service, integration, and backend validation" protects
API/integration bullets), proficiency-LABEL vocabulary (an "API & Web Services" line is evidence
when the JD asks for API work), and singular/plural pairs ("integration" ↔ "partner integrations").
`--protect` is for what the JD text CANNOT name.

### Squeezing the residual gap

When only a few lines over after the planned theme-scoped cuts, run `squeeze_resume.py` (Step 9) to
close the residual gap automatically instead of trimming by hand.

**Harvest the plan with `--plan-only` BEFORE the tailor script's first run.** Apply mode rewrites
the .docx directly — running it on the tailored output leaves the script unable to reproduce the
state, and folding the cuts back in by hand costs a repair cycle. `--plan-only` runs the identical
loop against a throwaway in-memory copy and prints the same fold-back block WITHOUT touching the
.docx (no backup, no log, no edit):

```bash
python3 scripts/squeeze_resume.py "<Target>.docx" 3 --jd "<JD>.txt" \
    --protect "<concept-level ask>" --plan-only
```

`--protect` works exactly as in measure — pass it for JD asks that are real responsibilities but
name no extractable term (squeeze plans cut ETL data-layer, security-posture, and test-data
bullets: all JD responsibilities no JD term names).

(Without `--plan-only`, it backs up to `<docx>.pre-squeeze.docx` and logs every cut to
`<docx>.squeeze.json`; reserve apply mode for a doc you will NOT regenerate from the tailor script.)

**JD-judge every fold-back line before pasting it.** Squeeze is page-math-only — its plan is sized
to the page budget and cannot see concept-level asks. Drop any fold-back line that carries such
evidence before it reaches the script; the block is a page-budget suggestion, not a JD-fit verdict.

Paste the printed fold-back block (or the DROP PLAN's `find_p` prefix strings) straight into a
`drop(body, [...])` call in the tailor script (never re-derive them by hand), re-run the tailor
script, re-measure once to confirm the gap closed, then render to verify. This replaces the
cut-render-cut guesswork.

### TOP-ROLE TRIM BATCH

When the oldest-first plan cannot close the gap, measure emits a TOP-ROLE TRIM BATCH (the
most-recent role's weakest unprotected bullets, sized to the residual gap) and, when even that
cannot close it, a NOTE saying so — paste its `find_p` lines into the script's first pass and take
the NOTE back to the user (whole-role drops / JD-matched tradeoffs).

### PRUNE PLAN (master input — the only sanctioned measure run on the master)

Relevance and page math are different decisions, and mixing them is how a build ships non-JD
sentences the user then hand-cuts. The master is measured ONLY with `--jd`, in PRUNE-PLAN mode: the
JD assessment alone (requirement coverage, JD-FIT AUDIT with `find_p` anchors on every cut
candidate, WORD-LEVEL TRIM CANDIDATES, TOP-BLOCK PRUNE CANDIDATES) — no PAGES, no reclaim plan, no
word budget, no PDF render:

```bash
python3 scripts/measure_resume.py "<userName> Master Resume.docx" --jd jd_<target>.txt
```

The master without `--jd` exits 2; `--simulate` on the master exits 2 (seniority what-ifs run on the
base build, Step 5). An explicit page target is ignored with a note. **The agent does not run this
mode** — Phase 1's `auto_prune.py` (SKILL Step 2) is the machine prune's only consumer: it
machine-dispositions every candidate (no agent keeps, no overrides, no cut report), emits the first
tailor script, and runs it through `run_tailor.sh`. A `# kept:` line in an emitted script is always
machine-generated, never an agent negotiation, and covers three cases: a role's stub keep (it would
otherwise lose every bullet; timeline gaplessness), a bullet kept WHOLE unmodified (every sentence
carries JD evidence and it is already within the word cap), and a proficiency/Tools line kept WHOLE
unmodified (it hosts at least one JD-evidenced item). A user-approved whole-role drop is represented
by `drop_role()` itself, never by a fake `# kept:` comment; per-bullet edits inside that role must
not remain in the script.

**Machine prune sidecar + coverage gate.** The internal `--jd` machinery writes
`<master>.prune.json`, one candidate record per bullet/list/section candidate. `auto_prune.py`
consumes that data and generates all CUT/TRIM edits itself. The agent does not run the master mode,
fill a disposition checklist, or negotiate `# kept:` reasons. A `# kept:` line in a generated script
is always machine-generated (stub, whole-bullet, whole-line, or whole-section keep), never an agent
negotiation.

**Enforced, not a habit:** `run_tailor.sh` runs `docx_edit.py <master> --lint-prune <script>` before
executing the tailor script. It exits 2 while any candidate has neither an edit, an enclosing
`drop_role()`, nor a machine-generated keep explanation, and 2 on a STALE sidecar (a candidate
anchor no longer resolves — the master changed since the plan; re-run `auto_prune.py`). Whole-role
dispositions are reported separately from keeps. The sidecar is an internal gate artifact, not an
agent-facing planning deliverable.

### WORD-LEVEL TRIM CANDIDATES

`measure_resume.py --jd` emits this section after the JD-FIT AUDIT. It names non-JD content inside
kept bullets and list lines (Technical Proficiencies, role Tools lines) that survived Phase 1's
row/sentence/ whole-category pruning but still carry irrelevant tool mentions or dead sentences.
Phase 1 (`auto_prune.py`) never rewrites a surviving sentence or line at the word/phrase level — it
only drops whole dead sentences and keeps or cuts a list line whole; anything this section flags is
backstop cleanup for the agent to apply by hand in the theme-scoped Phase 2 budget pass (Step 9),
not something the machine already did.

**Bullet-level output:**
```
WORD-LEVEL TRIM CANDIDATES (kept bullets and list lines still
carrying non-JD content after the row/sentence prune — cut the
flagged sentence WHOLE; a list line hosting any JD evidence stays
whole, never reduced to a subset. Sub-sentence wording changes are
Phase 2 agent work during Theme Review B or Step 9, done only when already adding a
host to that line — never strip a term the JD names or one that
hosts a [weak]/covered ask):
  Acme, City:
    find_p(ps, "Built ")  # Built Selenium suites with Java, TestNG.
      - JD does not name: testng
      - sentence with no JD evidence: "Mentored interns on agile rituals"
```

**List-line output:**
```
  list lines (Technical Proficiencies / Tools & Technologies):
    find_p(ps, "Tools ")  # Tools & Technologies: Selenium, Java, TestNG
      - JD does not name: testng — line kept whole; reword only when
        adding a host here (Theme Review B)
```

A list line with NO JD term at all prints a whole-line cut note (`no JD term on this line —
whole-line cut (TOP-BLOCK rule), not token trimming`) — the line is a TOP-BLOCK RECLAIM CANDIDATE,
not a token-trim candidate.

**Guards (deterministic):**
- **Protected bullets** (`--protect`) are never flagged.
- **Concept sentences** — sentences carrying a JD practice phrase (`_concept_hits`) are skipped
  entirely; their tokens may host the concept (Kafka hosting `root-cause` analysis).
- **Concept list lines** — a list line whose label matches a practice phrase is skipped entirely.
- **Tech-noun gate** — a vocab token is only flagged when it reads as a tech noun: in
  CORE_TECH_NOUNS, contains `#+`, or appears capitalized mid-sentence (`_jd_capitalized`). Generic
  lowercase prose (services, testing, automation) never flags.

### JD REQUIREMENT COVERAGE

The coverage map matches the JD's extracted terms as **literal phrases**: a qual line flips to
covered only when a kept bullet (or, as `[weak]`, a proficiencies/Tools line) contains the phrase
itself. Concept evidence does not flip it — "Kafka and MSMQ in a Tools line" does not cover
"event-driven architecture", and adjacent tooling does not cover a named tool. So when a qual you
know is demonstrated still prints `[UNCOVERED]`, the fix is to host the JD's literal phrase in a
truthful bullet — at AUTHORING time, from the master-measure's list — not to debug the matcher. A
`[weak]` line means the ask is demonstrably the user's (a proficiencies or Tools line hosts it):
weave the literal phrase into a bullet where used — hosting from that evidence needs no user
confirmation. Self-assessment-adjective qual lines ("Excellent communication, ...") extract no skill
terms and print `[by hand]` with the soft-skill inference rule — judge them on kept action-verb
evidence (the Hosting reference in SKILL.md), never by chasing the adjective.

### INFERENCE MAP — evidence for no-host JD terms

"No literal host" is not "no evidence": the master and LinkedIn may contain experience that the
tailored copy no longer shows. The INFERENCE MAP is the deterministic fix: it searches those
approved sources and prints a per-term verdict the agent follows, rather than declaring gaps or
re-asking about obvious lexical variants.

**How it works.** For each term in the "JD terms with NO host" list, `measure_resume.py` searches
the master paragraphs (and an optional LinkedIn dump) via two mechanisms:

1. **Morphological variants** — the term itself, its singular form (each word's trailing 's'
   stripped: `llms` → `llm`), and the hyphen-joined form for multiword terms (`customer facing` →
   `customer-facing`). Matched whole-word in the corpus.
2. **Skill-family roots** — an in-code table (`INFERENCE_FAMILIES`) mapping term families to
   related evidence roots. A no-host term matching a family key (whole-word) is searched for its
   family's roots as substrings in the corpus. The families cover the sessions' actual failure
   modes:

| Family keys | Evidence roots |
|---|---|
| `debug` | debug, triage, root cause, diagnos, resolved, remediat, defect |
| `data management`, `data modeling`, `query tuning` | test data, sql, query, index, data model, etl |
| `aws`, `cloud` | aws, amazon web services, cloud, azure, gcp |
| `ui`, `frontend`, `front end` | web, user interface, frontend, browser, desktop |
| `customer facing` | customer, client, production, incident, stakeholder |
| `problem solving`, `solving problems`, `troubleshooting` | problem, troubleshoot, root cause, resolved, issue |
| `llm`, `genai`, `generative` | llm, prompt, copilot, gpt, claude, openai |
| `software engineering` | software, engineering, engineer, sdlc, developed, development |
| `performance testing`, `load testing`, `stress testing`, `soak testing`, `performance` | performance, load, stress, soak, gatling, jmeter, k6, benchmark, capacity |
| `reliability`, `soak` | stability, chaos, fault, resilien, soak, monitoring, production, uptime, regression |
| `windows`, `macos`, `linux`, `operating system`, `os internals`, `os behavior`, `cross-platform` | linux, wsl, powershell, windows, macos, image, install, upgrade, lamp, desktop, server |
| `endpoint security`, `edr`, `dlp`, `epp`, `mdm`, `endpoint agent`, `security` | security, snyk, guardrails, compliance, hipaa, phi, monitoring, grafana, agent, mitigation |
| `virtualization`, `provisioning`, `vm`, `virtual machine`, `image build`, `test farm`, `test fleet` | virtualization, vm, docker, kubernetes, provisioning, codespaces, container, instance |
| `desktop gui`, `gui automation`, `pyautogui`, `pywinauto`, `uiautomation` | ui testing, coded ui, desktop, browser, cross-browser, ui |
| `secure software development`, `secure development`, `secure sdlc`, `secure coding` | security, compliance, fda, hipaa, mitigation, snyk, guardrails |

Roots are substring-matched (loose) — `sql` matches `SQL Server`, `index` matches `indexed` — so
weak lexical/family matches remain hostable evidence. The verdict is mechanical; role placement can
still require a placement question when the source does not identify a role.

**Per-source cap:** up to `_INFERENCE_MATCH_CAP` (2) evidence lines are printed per source (master,
LinkedIn) to keep output scannable.

**Output format:**
```
INFERENCE MAP for no-host terms (deterministic evidence search over the
  master + LinkedIn): follow the verdicts. AUTO-HOST terms are hosted
  without asking whether the user has the skill; the checklist contains
  exactly the RAISE terms:
  - aws services: AUTO-HOST — host the JD's literal phrase in the
    bullet/role where this evidence lives (merge, don't append)
      master: "Cloud & Containers: AWS, GCP, Azure, Docker, Kubernetes"
      linkedin: "AWS"
  - ontology: RAISE — no deterministic evidence — ASK the user (real
    experience is often lexically invisible in the master/LinkedIn);
    host only what the user confirms
    AUTO-HOST = evidence exists in an approved source. If the source
    does not identify a role, use Summary/Technical Proficiencies or ask
    only about role placement. RAISE = ask about the skill itself.
```

**LinkedIn evidence.** Pass `--linkedin <profile-dump.txt>` (the `read_profile.sh` output) so the
map also searches the LinkedIn export — the richer source for content the resume compressed away (the
Elasticsearch fold, for example, is justified from Skills.csv via this path):

```bash
python3 scripts/measure_resume.py "<Target>.docx" 3 --jd "<JD>.txt" \
    --linkedin /tmp/profile.txt
```

Without `--linkedin`, only the master is searched. The map still prints terms with no evidence as
genuine gaps — the flag adds a second evidence source, it does not change the judgment.

### Readability spacing

After content, ATS, seniority, page, and word decisions are closed, add one blank spacer paragraph
between roles only when it does not create a new page:

```bash
# clone_after with empty text produces a blank line
clone_after(body, find_p(ps, "<a NON-bullet paragraph near the role
boundary, e.g. the Tools line>"), "")
```

Anchoring on a non-bullet paragraph keeps the clone from inheriting bullet numbering. Then
re-measure to confirm the resume still meets the target. Fixed priority order: (1) JD-aligned work
experience, (2) the page target, (3) this spacing — when a spacer would create a new page, omit the
spacer, never theme-aligned content.

**Ordering when the script also contains list/word trims:**

1. `clone_after(..., "")` registers managed blank spacers, so a later `remove_empty(body)` pass
   no longer deletes them. Adding spacer clones after cleanup remains the clearest ordering and
   keeps the script easy to read.
2. `find_p` lint resolves prefixes against the MASTER before rewrites. An anchor based on
   shortened Tools-line text may resolve at runtime but fail lint; `after=` does not change that
   lint-time check.

Capture each reference element early, while its master-text prefix resolves, then clone after
`remove_empty()`:

```python
# Use unique prefixes copied from the current master's --prefixes output.
tools_ref_1 = find_p(ps, "<unique master-text Tools-line prefix 1>")
tools_ref_2 = find_p(ps, "<unique master-text Tools-line prefix 2>")

# ... list trims, word trims, and role drops ...

remove_empty(body)
clone_after(body, tools_ref_1, "")
clone_after(body, tools_ref_2, "")
```

Re-run `render_pdf.sh` (compact) to verify — measuring replaces iteration, it does not replace the
final verification render.

## Step 12 procedures — Render and verify

The `.docx` is the editing format; **the `.pdf` is the deliverable** — render and verify with
`render_pdf.sh` (compact by default; `--verbose` for the final verification render: validation
report, page map, spilled content, last-page tail):

```bash
RESUME_RENDER_PHASE=baseline RESUME_WORKFLOW_STATE=<state> \
  ./scripts/render_pdf.sh "<output>.docx"          # baseline, before word closure
RESUME_RENDER_PHASE=final RESUME_WORKFLOW_STATE=<state> \
  ./scripts/render_pdf.sh --target-pages 3 --verbose "<output>.docx"  # final verification
```

The render's default page target is 2; pass `--target-pages N` matching the target agreed in Step 5,
so the overflow report measures against the goal you actually agreed on (3 for senior/Staff, not the
2-page default).

`render_pdf.sh` **validates first** (runs `validate_resume.py`): it refuses to render on blocking
errors — an orphan job title, a company without a title, content orphaned after a Tools line,
**unapproved whole-role elimination**, **a retained role without a Tools value row**, **a missing
persisted inter-role spacer** (unless the spacers gate recorded that boundary via `--omitted`), or
**Education dropped against a degree-requiring JD** (when `--jd` is passed). Tools rows are
presentation invariants even when their values are not JD terms. The spacer and Tools-row checks
apply to final-phase renders; baseline renders remain available while those final layout decisions
are still open. Fix the errors, then render. The rendered PDF lands next to the `.docx`.

**The two gates have different trigger conditions.** The seniority gate runs unconditionally; the
education gate runs ONLY when `--jd` is passed (via `RESUME_VALIDATE_ARGS`) — `render_pdf.sh` prints
a NOTE whenever the education gate did not run.

**Env vs CLI — same flags, two delivery paths.** `render_pdf.sh` and `run_tailor.sh` read their gate
flags from the `RESUME_VALIDATE_ARGS` ENVIRONMENT variable (they forward it to the save/render
gates); `validate_resume.py` invoked DIRECTLY takes the same flags as CLI arguments (`python3
scripts/validate_resume.py "<docx>" 2 --jd <JD.txt> --seniority-approved`). Putting the flags in the
env for a direct validate call (or vice versa) silently drops them.

**When the JD specifies years of experience** (Step 5), confirm alignment and record approval in one
command:

```bash
RESUME_VALIDATE_ARGS="--jd <JD.txt> --jd-years <N> --seniority-approved" \
  ./scripts/render_pdf.sh "<output>.docx"
```

`--jd-years <N>` reports the visible span vs the JD's ask ("~7.4 years vs the JD's 5+ — aligned"),
warns if under (underqualified), and notes a large overshoot — the signal to offer Step 5's gapless
oldest-role elimination. `--seniority-approved` is the gate token: REQUIRED only when whole roles
were eliminated — without it the render is blocked, so the user-approved decision is recorded, not
assumed. **Pass it only with the user's authority** (their chat reply, or pre-authorization in the
original request — Step 5). Without that authority, the deliverable gate has already refused to
write the .docx (Step 11) — present the plan, and after the user's reply re-run the tailor script
with the token in `RESUME_VALIDATE_ARGS`, then render. The two flags are independent: `--jd-years`
is an optional advisory; the gate reads only the approval token. `--jd-years` is ONLY for a JD that
states a number of years. If the posting names no years ask, do NOT pass it: every span comparison
is then measured against a fabricated ask, producing false *underqualified* verdicts and a false
load-bearing education warning. `validate_resume.py` warns when `--jd-years` is passed but the JD
text states no "N+ years" ask.

**Whole-resume word cap** (SKILL Step 9): the validator counts every paragraph's alphanumeric
tokens and blocks over `MAX_WORDS` (1,000) for tailored resumes — the master input is exempt, like
the bullet cap. The baseline render/audit phase suppresses this check internally because page and
word closure occur later. The final render and non-baseline `ats_audit.py` enforce the cap; the
workflow never passes a user-facing bypass flag.

**Tokenizer details.** `validate_resume.py`, `measure_resume.py`, and `ats_audit.py` share the
same word-count logic. Hyphenated and slash-separated terms count as single tokens
(`test-automation`, `CI/CD`, and date-like `01/2026` are each one word), while apostrophe forms
split (`candidate's` = 2 tokens). Page furniture ("Page 1|3", bullet glyphs) is stripped before
counting. The result matches the external ATS report's `wordCount` for the exact uploaded PDF.

## Step 12 procedures — ATS verification (literal phrases + external scan)

The internal matchers are term/concept-based; external ATS screeners match literal phrases against
the rendered text. A resume can pass every internal gate and lose ATS points (e.g. 9 of
24 hard skills at zero literal hits while the external score drops). Two tools close the gap:

### ats_audit.py — the local ground-truth audit (always run)

```bash
python3 scripts/ats_audit.py "<output>.pdf" --jd <JD.txt> \
    [--phrases-file <f>] [--report-json <report.json>] \
    [--baseline --workflow-state <state>] [--match-target N]
```

Checks, on the pdftotext output of the DELIVERABLE (what a screener parses, not the .docx): (1) the
whole-resume word cap in normal/final mode (baseline mode skips this gate internally — word closure
is later); (2) with `--jd`, literal hosting of the JD qualification lines' skill phrases (cue-tail mining: phrases
are extracted only from the text following skill-introducing cues like "experience in" and
"proficiency in", avoiding surrounding prose — see `_jd_literal_terms` for the full precision
rules); zero-host terms mean a cut killed the last host (the machine protects JD-named chunks, Step
2) or the phrase was never mirrored — host the exact phrase truthfully or raise the gap, never
fabricate; and before raising a no-host term as a genuine gap, grep the MASTER for it (including
bullets the first pass cut — see SKILL Step 12 for the rationale and an example); (3) with
`--phrases-file` (one phrase per line) or `--report-json` (an external scan report, below), literal
checks of externally supplied phrases — a skill's `resumeCount` from the report is the authoritative
host signal, the literal check is the fallback. Report soft-skill no-hosts warn as ACTIONABLE (SKILL
Steps 8/11: soft skills are safe to infer — host each literal phrase where the action-verb evidence
lives). With `--report-json`, also prints the **match-rate target** (default 75, `--match-target N`
to change, `0` disables). The target is a **hard stop** (2026-09-11): score ≥ target ⇒ the hosting
loop closes: stop hosting, stop keyword- driven rewording, and stop re-scanning for score. Below
target ⇒ keep hosting literal phrases truthfully — hosting them is what moves the rate. The verdict
message (`hosting loop CLOSED: stop score-driven edits now`) is the enforcement signal; further
score-driven edits resume only when the user explicitly asks.

**Match-rate state and the ceiling signal.** Each run persists the match rate in a sidecar,
`<resume>.ceiling.json` (written best-effort, never blocks the audit; any score change resets it).
When two consecutive audits report the SAME score below target, the audit prints **CEILING
DETECTED** — the remaining hard/soft skill checklist must be presented to the user before declaring
the honest ceiling (SKILL Step 12); delete the sidecar to clear the state. Its counterpart on the
measure side is the **REQUIREMENTS SUMMARY** one-liner (`measure_resume.py`): the
unconfirmed-hard-skills call-to-action prints ONLY when that count is above 0 — a fully-covered run
prints the counts alone. Exit 0 clean, 1 findings, 2 usage/IO error.

IGNORED by rule: the report's contactEmail searchability finding — the compact hyperlinked contact
block is a deliberate design (Step 12, SKILL.md); never alter the contact block to satisfy a literal
text parser.

### ats_check.py — the external scan (when configured)

Runs at Step 12 as the final cross-check, and OPTIONALLY once earlier (SKILL Step 5): an early scan
on the seniority-approved baseline-rendered build front-loads the external scanner's phrase gaps
into the Step 4 mining loop (`measure --ats-report` merges them with the internal no-host list),
converting post-final rework into mid-flow work at the cost of one extra scan.

```bash
python3 scripts/ats_check.py scan "<output>.pdf" <JD.txt> \
    [--jd <JD.txt>] [--source-jd <verbatim-JD.txt>] [--out <report.json>]
python3 scripts/ats_check.py check      # validate the saved config, no scan
```

Submits the deliverable (PDF preferred — it is the submitted format) to the user's ATS scan service,
waits for the match report, and saves its JSON next to the resume (`<resume>.ats-check.json`); feed
that back into `ats_audit.py --report-json` for the authoritative cross-check. The chain is
reconstructed from the user's OWN saved cURL exports in the skill root's `.ats-check/curl.txt` (five
requests: resume upload, job description, opportunity, opportunity update, report GET) — the tool classifies them by
shape, templates fresh ids, rotates the session cookies through a curl cookie jar, and re-derives
the CSRF header from the jar before every request. No service specifics are hardcoded; when a scan
returns 401/403 the credentials expired — the user re-exports the five requests from a logged-in
browser session and deletes `.ats-check/cookies.txt` to re-seed. The service dedupes an identical
resume + JD pair (409) and the tool reuses the returned opportunity. When `jd_<target>_source.txt`
exists beside the normalized JD, it is uploaded to preserve the posting's original structure;
`--source-jd` selects another source. The report records hashes for the resume, normalized JD,
and uploaded JD. `ats_audit.py --report-json` rejects a report whose local input hashes do not
match the current inputs. The scan output prints the
match rate, the report's wordCount (matches the local count — feed it to
`ats_audit.py --report-json` for the cap check), and the
identified target ATS; the latter requires the job posting URL persisted with the JD (Step 1) — a
real URL on the `Posting URL:` line, never a placeholder: the function returns whatever is on the
line, but the caller PATCHes only when the line is present and truthy. A placeholder PATCHed to the
service is garbage in the report (`url=(not)`); SKILL Step 1: own the line
entirely when the URL is unknown.

**URL-optional: ATS knowledge reuse across scans.** The URL is optional — the scan always runs
without it. Its job is ATS identification, and that is company-scoped knowledge: when this JD has no
Posting URL line but a prior scan (this session or an earlier one) identified the ATS for the same
company, `ats_check.py` reuses the known posting URL for the metadata PATCH and prints the reuse. A
URL-less second posting for an already-scanned company would run with NO ATS identified and
NO keyword-matching mode at all — a large match-rate drop against the same system. The known-ATS
mapping is persisted in `.ats-check/known-ats.json` (gitignored, durable
across sessions). `--company` overrides the company detection from the JD's `Company:` line.

**Fix tool bugs in the session that finds them.** If a script in this skill misbehaves or
contradicts its documented behavior, do not route around it: fix the script and add a regression
test in the same session (then continue the tailoring run on the fixed tool). A workaround leaves
the bug armed for the next session.

**Verification is TEXT-ONLY — never render pages to images.** This harness reads no images, so
converting the PDF to PNGs and "viewing" them fails every time. The text
path already covers what a visual check would: `render_pdf.sh --verbose` prints the page-boundary
map and last-page tail, and `measure_resume.py` prints the page-fill table with widow/underfill
detection. Read those, plus `pdftotext` per page if you need to inspect content placement.
