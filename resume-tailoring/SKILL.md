---
name: resume-tailoring
description: Use when the user wants to customize their resume to match a specific job posting or
 recruiter screening message, or needs an ATS-friendly tailored copy from a master .docx. Also use
 when producing a submission-ready PDF from an existing .docx resume.
---

# Resume Tailoring

Tailor a master `.docx` resume for a specific job posting while preserving its formatting. The
workflow edits the Word XML in place so fonts, sizes, paragraph styles, list/bullet numbering, and
hyperlinks all survive.

## Core principle

**The existing machine filter prunes; the agent tailors; nothing irrelevant ever reaches the
build.** Copy the master, never overwrite it — every run writes a new file (e.g. `John Doe Resume -
<Target>.docx`). Phase 1 (`auto_prune.py`, Step 2) machine-dispositions EVERY paragraph of the
master against the JD — every bullet, dead sentence, proficiency/Tools line, and
certification/section line — and emits and runs the first tailor script through the full gate chain.
Every disposition is row/sentence/whole-category granular — the machine never rewords a surviving
sentence or line; that is Phase 2 agent work, done only when adding a host there (Step 2 has the
exact rules) — and the agent never page/word-measures the master. **The machine's dispositions are
the STARTING POINT, not a verdict: the agent's theme judgment owns every edit on top of them.** Step
3's theme review checks the prune's output against the Step-1 brief — restoring theme-relevant
content the matcher cut (as a fresh, purpose-written host, or by fixing the matcher's evidence
families and re-running when truthful equivalents were wrongly cut) and cutting theme-irrelevant
survivors the matcher kept — and every later edit round gets the same check. The single ask/evidence
matcher stays the only MACHINE rule: do not add a second independent preservation filter; fix its JD
evidence families when truthful equivalents such as Python/Python scripting, Linux/WSL/Linux bash,
unit/component testing, or visual checks/visual regression testing are being cut. The goal of every
edit — prune review, hosting, squeeze, render — is a resume built towards the central theme, not
just a keyword collection that passes ATS: after each edit round, re-read the round's changes
against the theme brief and strengthen the theme's representation where it weakened.

The theme is an explicit decision layer, not a keyword decoration. The required execution order is:
(1) machine prune, (2) Theme Review A of the prune, (3) baseline ATS audit, (4) Theme Review B of
the audit with any theme-aligned edits, (5) seniority review in theme context, (6) title and
positioning edits, (7) theme-scoped page closure, (8) theme-scoped word closure only when the build
exceeds 1,000 words, (9) the limited page-removal assessment, and (10) spacers only when they do
not create a new page. A final render/ATS run verifies the result; it must not reopen a score-driven
editing loop. Each gate must be complete before the next one begins.

Agent work continues on the resulting LEAN BASE BUILD: Theme Review A owns the prune overrides,
Theme Review B owns ATS-related hosts, seniority protects unique theme evidence, and every later
edit is checked against the brief. Restores are theme-review or gap-driven, and always land as
fresh, purpose-written hosts. The single ask/evidence matcher remains the only MACHINE rule; the
agent's theme reviews are judgment gates, not a second matcher. JD alignment is king, readability
second, and theme coherence is the tie-breaker when keyword coverage and narrative strength
conflict. Time-in-role and recency are only tiebreakers, never a cut signal and never an exemption.

## Editing phases

**Phase 1 — relevance assembly.** `auto_prune.py` builds a JD-relevant base from the master. It
removes unevidenced content, whole dead sentences from a kept bullet, and whole non-JD
proficiency/Tools lines — never a sub-sentence word/phrase edit and never a partial value list
within a kept line. It never drops a whole role and does not perform page/word-budget iteration. Its
dispositions are deterministic and complete — Step 3 theme-reviews them against the Step-1 brief and
overrides where warranted (Core principle).

**Phase 2 — final tailoring.** Starting from the Phase 1 base, the agent performs every remaining
edit: title/Summary positioning, less-obvious master/LinkedIn mining, literal ATS hosts, JD tone and
word choice, page and word budgets, rendering, and final ATS verification. Every edit round gets the
Core principle's theme check; there is no separate restore phase.

## When to Use

- User provides a job description and wants their resume tailored to it
- User forwards a recruiter's screening message (e.g. "top 3 skills in bullets") and wants the
  resume aligned to it
- User has a master `.docx` resume and needs a per-target customized copy
- User needs a submission-ready PDF from an existing `.docx` resume

## Quick Reference

| Step | Action | Tool |
|---|---|---|
| 1 | Read the WHOLE JD, saved in the fixed 8-section template (persist to skill root + posting URL); write the company-focus theme brief + any term equivalences. The master and LinkedIn export stay UNREAD | `jd_sections.py` contract |
| 2 | PHASE A — the independent machine prune (enforces the 8-header contract; `--theme` is provenance only; `--equivalence` extends the matcher): dispositions every candidate, emits the first tailor script, runs it through the gates, writes the lean base build. No cut report | `auto_prune.py` (runs `run_tailor.sh`) |
| 3 | Theme Review A: measure the BASE BUILD, diff master vs build, and disposition the prune against the theme before any seniority or budget decision | `measure_resume.py`, `docx_edit.py --prefixes` |
| 4 | Baseline ATS audit, then Theme Review B: classify every finding through the theme and make only truthful, theme-aligned hosts or raises | `render_pdf.sh`, `ats_audit.py --jd`, `read_profile.sh` |
| 5 | Decide length + seniority alignment with the theme in view; preserve roles carrying unique theme evidence | `measure_resume.py --simulate` |
| 6 | Align top title to JD title (less senior); preserve the user’s Summary/intro unchanged | `set_text` for title only |
| 7 | Re-anchor senior role and industry/stage story, then close page/word budgets with theme-scoped edits | `set_text`, `merge_into`, `measure_resume.py` |
| 8 | Assess page removal only when spill is ≤5 rendered lines; add spacers last only when they do not create a new page | `render_pdf.sh --verbose`, `clone_after` |
| 9 | Fix grammar, typos, punctuation | grep + `validate_resume.py` |
| 10 | Save tailored copy (never overwrite master) | `save()` |
| 11 | Render + verify PDF | `render_pdf.sh` |
| 12 | Close the session with the master untouched; user-owned master edits happen outside this workflow | — |

## Assets

User-supplied personal assets (`*.docx` / `*.pdf`, gitignored) live in the skill root:

- `<userName> Master Resume.docx` — the comprehensive data pool and the formatting/structure
  source. No separate per-target template is needed: Phase 1 copies this document and edits the
  tailored copy in place while preserving its XML styles. **The workflow never writes the
  master.** `auto_prune.py` reads it to build the per-target copy; later gap mining reads it as an
  evidence source. The user owns all master updates: a user edit changes the source content and
  can invalidate tailor-script `find_p` prefixes, so the next run detects the changed master
  (`MASTER CHANGED:`), runs auto-strict, and must re-run `auto_prune.py` (Step 2). Never overwrite
  or fold into the master from this workflow.
- `Basic_LinkedInDataExport_*/` — the LinkedIn data export (CSVs), the richer source than the
  resume for content to enrich/merge — read ONLY in Step 8, when a surfaced gap needs evidence
  (Step 1 does not touch it).

`scripts/` (each tool's docstring / usage is the reference; the steps below point at them):
`docx_edit.py` (Helper library) · `tailor_resume.py` (template) · `render_pdf.sh` (Steps 8, 11) ·
`auto_prune.py` (Step 2 PHASE A — the machine prune; the ONLY sanctioned master consumer; emits and
runs the first tailor script through `run_tailor.sh`'s gates) · `measure_resume.py` (Step 3/4 page
math on the tailored copy; `--jd` on the MASTER is the machine pipeline's prune-plan mode — the
agent never runs it; `--linkedin <dump>` feeds the INFERENCE MAP for no-host terms in Step 8) ·
`squeeze_resume.py` (Step 7A backstop; auto-tightens only within the theme-scoped page pass) ·
`validate_resume.py` (Steps 4, 11; `--master` auto-detects the `* Master Resume.docx` next to the
input) · `diff_resume.py` (Token-spend) · `read_profile.sh` (Step 8) · `ats_audit.py` (Steps 3A and
11; baseline and final literal-phrase audits of the rendered PDF + word cap) · `ats_check.py` (Step
11; runs the external ATS scan via the user's saved credentials, saves the report JSON) ·
`test_*.py` unit tests (`python3 -m unittest test_docx_edit test_auto_prune test_measure_resume \
test_validate_resume test_squeeze_resume test_ats_audit test_ats_check`, from `scripts/`).

Run scripts from the skill root so the relative `SRC` path resolves:

```bash
cd ~/.pi/agent/skills/resume-tailoring && python3 scripts/tailor_resume.py
```

## Helper library & reference template

`docx_edit.py` helpers (`set_text`, `set_labeled`, `find_p`, `drop`, `drop_role`, `drop_section`,
`save`, `clone_after`, `merge_into`), the CLI reference, and the `tailor_resume.py` template are
documented in [docs/api.md](docs/api.md). Read the api reference before authoring a tailor script;
import only the helpers the planned edits use.

## Token-spend practices

The loop is render-and-measure heavy. The deterministic parts are tool-enforced; the manual habits
are:

1. **Author edits from `--prefixes` alone** (uniqueness-checked copy-paste; the paragraph map
   adds style/numId — only for rare layout checks). Phase 1 hands you the base build and its
   emitted `tailor_<target>.py`; your later edits (Steps 5–8) EXTEND that script — dump
   `--prefixes` on the BASE BUILD, not the master. To read a paragraph's FULL text before
   rewriting it (Summary, senior-role intro, a bullet), use `docx_edit.py "<docx>" <idx> --full`
   (or `<start>-<end> --full`) rather than ad-hoc inline python — it is one command and shows the
   exact string you are replacing.
2. **Never run the prune yourself.** `auto_prune.py` (Step 2) is the only sanctioned master
   consumer: it machine-dispositions every candidate (bullet cuts, whole dead sentences dropped
   from kept bullets, whole-category proficiency/Tools-line keeps or cuts, stub keeps), emits
   `tailor_<target>.py`, and runs it through `run_tailor.sh`'s gate chain in one command. There
   is no disposition checklist to fill and no cut report to read — the base build IS the
   disposition. Re-running the command after a user edit refreshes the prune sidecar the coverage
   gate enforces. That Step-3 measure run on the base build is also the term-coverage drift
   check: its **JD terms with NO host** list is the mining queue Step 8 works from.
3. **Before reusing a tailor script after the user edited the .docx, run `diff_resume.py
   --tailor`** first — one command surfaces manual edits a blind re-run would wipe. (The drift
   sidecar is the tripwire; diff_resume is the review.)
4. **Over-cut by 1–2 bullets per batch; if still over, drop a whole oldest role.** Never
   hand-shorten sentences to chase a page break — it's the lowest-leverage, highest-cycle edit.
   When only a few lines over, run `squeeze_resume.py` (Step 7A) to close the residual gap
   automatically instead of trimming by hand.
5. **Slice files, not re-runs.** Output you will read in sections — measure's DROP PLAN /
   page-fill table, a full `--prefixes` dump — goes to a file once (`measure_resume.py … >
   /tmp/measure.txt 2>&1`), then read the file with grep/sed. Never pipe a dump you will author
   from through `head`: the tail is silently lost and the missing paragraphs resurface as skipped
   edits.
6. **Syntax-check and lint a tailor script the moment it is written.** For Phase 2, run
   `RESUME_WORKFLOW_STATE="<Name> Resume - <Target>.docx.workflow.json" scripts/run_tailor.sh
   "<master>.docx" scripts/tailor_<target>.py` — it requires Theme Review B, then ast.parses the
   script and verifies EVERY `find_p` target resolves against the master (`--lint-script`), verifies
   EVERY prune-plan candidate is addressed by an edit or a recorded `# kept:` reason (`--lint-prune`
   — output format, sidecar, and exit codes: [docs/api.md](docs/api.md)), then executes it under
   `DOCX_EDIT_STRICT=1` in one command (`RESUME_VALIDATE_ARGS` passes through). Syntax-check
   alone (without the lints) is the fallback: `python3 -c "import ast;
   ast.parse(open('scripts/tailor_<target>.py').read())"`. On corruption, do not repair
   incrementally with `edit` — rewrite the whole file in one bash heredoc and re-check.
7. **Before each `edit` of a script, view only the target region** (`sed -n 'A,Bp'`, or `grep -n`
   to find it) — not a full re-read. A session re-read its 300-line tailor script seventeen times
   across edit rounds; targeted views keep the edit anchors exact at a fraction of the tokens.
   Full re-read only when paragraph/script indices shifted and the anchor's position is genuinely
   unknown.
8. **After any multi-edit round on a script, count the anchors before the syntax check.** `grep
   -c` the expected number of each anchor string that should now exist — an edit meant to ADD a
   `set_text` block can silently REPLACE its neighbor (a wasted repair round), and one
   non-matching oldText fails the entire call. When adding a new block, anchor it against a
   unique existing line.

Tool-enforced (no instruction needed): `auto_prune.py` REFUSES non-master input (exit 2) — the
tailored copy is its OUTPUT, never its input — REFUSES a JD that violates the 8-section template
(exit 2 naming the missing headers), and its emitted script runs under the full gate chain
(`run_tailor.sh`: ast + find_p lint + prune-coverage + strict exec). `measure_resume.py` FAILS (exit
2) when a JD mining queue exists and no adjacent `* Master Resume.docx` sits next to the tailored
copy — the master leg of Step 8's source-first loop is mandatory, never skippable.
`measure_resume.py` REFUSES full-master page/word measurement (exit 2 without `--jd`; on the master,
`--jd` is the machine pipeline's prune-plan mode) and, on a tailored copy, prints the BATCH RECLAIM
PLAN, its JD-aware DROP PLAN with copy-pasteable `find_p` cut lines, the per-role **JD-FIT AUDIT**
(unevidenced bullets in every role, even on target), **JD REQUIREMENT COVERAGE** (each qualification
line → its kept hosts; [weak] = proficiencies/Tools-line host only, [UNCOVERED] = demonstrate it or
raise the gap), **JD terms with NO host in the resume** (the never-fabricate flags — Step 8's mining
queue), and flags page widows / underfilled pages + **SPACER OPPORTUNITIES** (Step 8 backstop); its
**REQUIREMENTS SUMMARY** one-liner flags the count of unanswered hard skills — any count above 0
means present the two-state checklist (Step 8) before claiming done; `validate_resume.py` re-reports
the JD-FIT count at render/save time (the render gate is not skippable); `squeeze_resume.py` closes
the residual page gap automatically.

## Workflow

### 1. Read the JD — nothing else
- Read the **job description** (JD) **or the recruiter's message**, saved in the **fixed 8-section
  template** — the user provides the section headers every time, with the posting's material under
  each (blank body when the posting omits that content; **never** a differently-phrased synonym).
  Each header is one word with a **required trailing colon** (case-insensitive):

  ``` title: company: role: responsibilities: required: additional: education: expectations: ```

  `title:` carries just the job title; `company:` the company overview; `role:` the role overview
  — what the job entails generally (mission text a posting opens with); `responsibilities:` the
  day-to-day duties; `required:` / `additional:` / `education:` / `expectations:` the
  qualification and onboarding material. Header ORDER in the file does not matter: the parser
  collects bodies by header name, each body running until the next header line.

  There is **no fallback heading recognition** by design: the parser (`jd_sections.py`) matches
  exactly this vocabulary, and `auto_prune.py` exits 2 naming any missing header — a mis-pasted JD
  (a typo like `Teck Stack:`, a bare header missing its colon, an omitted or repeated section)
  fails at the pipeline's entry instead of silently mis-collecting asks. **Do not silently
  normalize or restructure the user's paste**: surface the parser's failure and have the user
  re-supply the corrected sections. The colon is mandatory precisely because the one-word headers
  must not match a bare body word. A recruiter's "top skills" message uses the same template (the
  named skills go under `required:`) — one input format everywhere.
- **Persist the JD in the skill root, not /tmp.** Save it as `jd_<target>.txt` (e.g.
  `jd_acme.txt`) before anything else. Every downstream tool references that path for the whole
  session, and re-run instructions outlive it. The code warns when `--jd` points at `/tmp`; the
  tailor script's docstring records the JD path used.
- **Persist the job posting URL with the JD.** Ask for it ONCE, when the user provides only
  posting text — if the reply doesn't include it, omit the line and proceed (the scan always runs
  without it); never re-ask mid-session. Put `Posting URL: <url>` as the FIRST line of
  `jd_<target>.txt`. The external ATS scan (Step 11) extracts it to identify the target company's
  ATS — its ATS-specific guidance and several findings depend on that match, and without the URL
  the match fails (the report degrades to generic advice). The line sits outside the qualification
  sections, so the internal matchers ignore it. **When the URL is unknown, OMIT the line entirely
  — never write a placeholder** (`Posting URL: (not provided)`, `…(ask user)`): a placeholder
  reaches the scan service as `url=(not)` and garbles the report. The function returns whatever is
  on the line — the caller skips the PATCH when the line is absent, but a placeholder on the line
  passes through. The doc rule is the guard, not a parser: line present means a real URL; omit the
  line when unknown. **The URL is optional, not required — the scan always runs without it.** Its
  job is ATS identification, and that is company-scoped knowledge: when this JD has no Posting URL
  line but a prior scan (this session or an earlier one) identified the ATS for the same company,
  `ats_check.py` reuses that known posting URL for the metadata PATCH and prints the reuse.
- **Characterize the JD's theme BEFORE Phase 1 — reading the ENTIRE JD, every section.** Theme
  cannot be assessed without taking the entire JD into context, so no section is skippable. Write
  a company-focus theme brief covering:
  - **Company focus:** what the company does and the domain it serves.
  - **Differentiator:** what makes its approach, product, stage, or operating model distinctive
    in that domain.
  - **Role mission/outcomes:** what the company needs this position to accomplish beyond listing
    tools and primary skills.
  - **Capability connection:** how the testing, automation, reliability, collaboration, and
    domain requirements help the company sustain its specific focus.

  Do **not** put seniority in the theme brief — Step 4 owns seniority alignment. Hand the brief to
  Phase 1 as `--theme "<company-focus theme brief>"` for provenance in the emitted tailor
  script's docstring only. `auto_prune.py` does not use the flag to decide cuts; Theme Review A is
  the required post-prune alignment gate. Any JD-specific terminology equivalence the whole-JD read
  surfaces (for example, a government JD's "IV&V" meaning testing for that posting) goes in a
  repeatable `--equivalence "IV&V=testing,quality validation"` flag — extending the ONE ask/evidence
  matcher for that run, never a second filter. The theme also steers Phase 2's judgment calls (Step
  7's industry expansion, Step 8's host placement).
- **The master resume and the LinkedIn export are NOT inputs here.** Phase 1's `auto_prune.py`
  (Step 2) is the only sanctioned master consumer until Step 3's theme review unlocks the master's
  paragraph map (the cut-set diff) and Step 8's mining unlocks both sources in full — the agent
  that reads the master before the prune runs starts justifying keeps from it, which is how the
  prune gets ignored.

### 2. PHASE A — run the machine prune
One command. No judgment, no dispositions, no cut report:

```bash
python3 scripts/auto_prune.py "<userName> Master Resume.docx" jd_<target>.txt \
    --target "<Target Name>" --theme "<Step 1's company-focus theme brief>" \
    [--equivalence "<term>=<alt1>[,<alt2>...]"]...
```

The JD file must satisfy the 8-section contract — the command exits 2 naming any missing header
before touching the master.

What the machine does (deterministic; the agent has no lever here):
- **CUT** every unevidenced bullet (the most recent role included) and every no-JD-evidence
  proficiencies/cert line; a section whose every line is cut goes whole — an entire
  technical-proficiency category may go.
- **TRIM** kept bullets by dropping whole dead SENTENCES (never a sub-sentence word or phrase),
  enforcing the ≤40-word bullet cap by dropping more whole sentences when needed. A
  proficiency/Tools line hosting ANY JD-evidenced item is kept WHOLE and unmodified; a line
  hosting NONE is cut whole — never a partial value list. Word-choice tailoring of a surviving
  sentence or line is Phase 2 agent work (Step 8), done only when adding a host to that line.
- **NEVER drops a whole role** — a role left with zero bullets keeps a one-bullet stub
  (header/title + strongest bullet), so the timeline stays gapless and the seniority gate (Step 4)
  sees every role.
- **Enforces the per-role 8-bullet cap** on the survivors.
- **Emits `scripts/tailor_<target>.py`** and runs it through `run_tailor.sh` (ast + find_p lint +
  prune-coverage gate + strict exec). A gate failure is a pipeline-input bug (JD file, master) —
  never hand-edit the emitted cuts.

Output is deliberately minimal — `WROTE scripts/tailor_<target>.py` and `BUILD: <dst>`. **There is
no cut report.** Over-cutting is not corrected by argument or restore-from-report: Step 3's theme
review catches theme-relevant losses (via the master-vs-build prefix diff), and a later phase that
genuinely needs cut content gets it through Step 8's gap-driven mining, as a fresh, purpose-written
host — which tailors better than preserved master prose anyway.

The machine protects hosts by construction: any SENTENCE carrying a JD term or a practice-phrase
concept survives every trim (whole, unmodified) and any proficiency/Tools LINE carrying one is kept
whole, so a JD-named hard skill's last host is never cut (Step 11's `ats_audit.py --jd` backstop
still verifies post-build).

### 3. Theme Review A — review the prune against the theme before any budget or seniority decision
- Run `measure_resume.py` on the BASE BUILD (never the master — the tool refuses it): page-fill
  table, TIMELINE, word budget. The machine prune already removed everything without JD evidence,
  so the build lands JD-evidenced content only by construction, but Phase 1 does not enforce page
  or whole-resume word budgets. Measure the result for diagnosis; perform all budget iteration in
  Phase 2.
- Read the coverage report's [UNCOVERED] and [weak] lists and the **JD terms with NO host** list —
  that list is Step 8's mining queue. It is not something to fix by keeping more content up front.
- **Theme-review the prune (the judgment layer).** The machine matched terms; only the agent can
  judge theme. Diff the master's paragraph map against the base build's (`docx_edit.py
  "<master>.docx" --prefixes` vs the build's — the delta IS the cut set) and judge both sides
  against the Step-1 theme brief:
  - **Theme-relevant content the prune cut** → restore it as a fresh, purpose-written host in
    the role where it lived (the Step-8 hosting pattern, available from here for theme
    restores), or, when the matcher cut a truthful equivalent, fix `--equivalence`/evidence
    families and re-run `auto_prune.py` rather than hand-rebuilding.
  - **Theme-irrelevant content the prune kept** (term-matched but off-theme) → cut it in the
    positioning pass; the JD-FIT AUDIT's unevidenced bullets are the first candidates, but theme
    judgment may go beyond them. Record each override's theme rationale as a comment in the
    tailor script. This review — not the machine — is what makes the deliverable read as a
    resume built towards a theme rather than a keyword collection that passes ATS.

**Theme Review A is a gate, not a note.** Before simulating role drops, aligning the title, mining
sources, or editing for page/word budgets, record the meaningful dispositions in the tailor script
comments or a short per-target review note:

- **Cut but theme-relevant:** restore it as a fresh host in its original role, or correct the
  evidence family and rerun Phase 1 only when the matcher missed a truthful equivalent.
- **Kept but theme-irrelevant:** remove it in the positioning pass, even if it matched a JD term.
- **Kept and theme-supporting:** state the theme role it plays when the rationale is not obvious.
- **Theme anchor:** identify the roles, outcomes, domain evidence, and capability connections that
  must survive later seniority and budget edits.

The review must include the master-vs-build cut set, not just the build's coverage report. Do not
advance until the review's restores, cuts, and keep rationales are applied or explicitly recorded.
The prune emits `<Name> Resume - <Target>.docx.workflow.json` in phase `pruned`; record the review
with a JSON file and advance the gate:

```bash
python3 scripts/workflow_gate.py review \
    "<Name> Resume - <Target>.docx.workflow.json" theme_review_<target>.json
```

The JSON must contain `{"kind":"prune", "theme_anchors":[...], "dispositions":[...]}`. Each
disposition needs an item, a `restore`, `cut`, or `keep` decision, and a non-empty theme rationale.
The gate validates that the review exists; it does not make the semantic judgment for the agent.

### 3A. Baseline ATS audit, then Theme Review B
Render the Theme Review A build sufficiently to run the literal audit, then run:

```bash
RESUME_RENDER_PHASE=baseline \
RESUME_WORKFLOW_STATE="<Name> Resume - <Target>.docx.workflow.json" \
    ./scripts/render_pdf.sh "<Name> Resume - <Target>.docx"
python3 scripts/ats_audit.py "<Name> Resume - <Target>.pdf" \
    --jd jd_<target>.txt --baseline \
    --workflow-state "<Name> Resume - <Target>.docx.workflow.json"
```

This is the **baseline ATS audit**, not the final deliverable check. Baseline rendering and auditing
skip the word-cap gate internally because word closure intentionally happens later. Review every
no-host finding through the theme before editing. For each finding, record one disposition:

- **Theme-aligned host:** truthful evidence exists and the exact phrase strengthens the central
  story. Host it in the evidence-bearing bullet, merging rather than appending.
- **Theme-aligned concept, missing literal wording:** add the phrase only if it improves both ATS
  coverage and the theme narrative.
- **Off-theme or parser noise:** do not distort the resume to host it. Record why it is ignored.
- **Unsupported:** search the master and complete LinkedIn export first, then raise it if no
  truthful evidence exists.

The source-first mining and hosting rules in Step 8 are executed here, during Theme Review B, before
seniority or budget edits. Re-run the audit after approved hosts land until no further theme-aligned
host remains. Do not move to seniority while a no-host finding is merely unreviewed. A final
post-render audit later verifies the finished document but never reopens score-driven editing.
Record Theme Review B before seniority:

```bash
python3 scripts/workflow_gate.py review \
    "<Name> Resume - <Target>.docx.workflow.json" theme_review_<target>_ats.json
```

The ATS review JSON must contain `{"kind":"ats", "findings":[...]}`. Every finding needs a phrase,
a `host`, `ignore`, or `raise` decision, and a non-empty rationale. The review command advances the
state only after the baseline audit has been recorded.

### 4. Decide seniority and positioning with the theme in view
Run this step only after Theme Review B closes the baseline ATS findings. Record the user's approved
role-drop decision before editing the script:

```bash
python3 scripts/workflow_gate.py advance \
    "<Name> Resume - <Target>.docx.workflow.json" seniority-approved
```

The seniority proposal must preserve any role that carries unique company-focus, domain, mission, or
capability evidence, even when that evidence has few literal JD matches.

- **Target 2 pages; accept 3 for senior/Staff; 4 is too long.** The target is a MAX, never a
  requirement — a resume that lands under it is always fine, and never add or keep content to fill
  pages. "Senior" is mechanical, not a judgment call: the JD's stated title is
  Senior/Staff/Principal, OR the candidate's visible background is Staff-level — EITHER condition
  targets 3. A JD asking "7-10 years" (a range starting at 7) is itself a seniority signal
  favoring 3. When in doubt, default to 3 and let the measure's page-fill table decide. If the
  selected target is exceeded, measure the rendered spill before considering page removal. A
  theme-scoped trim pass is allowed only when the spill is five rendered lines or fewer.
- **Present only a feasibility-measured target.** Before recommending a page count to the user,
  run the what-if (`measure --simulate` with the candidate whole-role drops at the candidate
  target) and check the projected page count. The user's approval is only as good as the numbers
  it is based on; simulate first, present the measured target, then ask.
- **Don't launch broad compression for a large spill.** When the rendered spill exceeds five
  lines, retain the page or return to the approved target decision. Do not cut JD-matched bullets
  merely to force a page reduction.
- Length is reclaimed by the machine prune (Step 2 — already done before this measurement), then
  by whole-role drops at the bottom when seniority alignment calls for them. Recency and
  time-in-role are tiebreakers only — they decide which of two otherwise-equal bullets survives,
  never whether the most-recent role is exempt from pruning.
- Don't bloat the top to "add content" — instead *reallocate*: expand the senior role with
  JD-aligned content AND keep every role pruned under the per-role cap, then trim off-JD
  proficiencies, Tools lines, and spacers to make room. Done right, the resume gets *shorter*
  while the important part gets stronger. Measure the tailored copy with the agreed target (Step 8
  re-measures it on the build after the content edits).

**Seniority alignment — when the JD specifies fewer years than the candidate has** (e.g. a mid-level
"Software Test Engineer" JD asking "5+ years" against a 15-year Staff-engineer background). This is
a distinct decision, presented **to the user before the tailor script is authored** — not discovered
mid-compression when the page budget forces it:

1. **Compare the candidate's total years to the JD's ask.** `measure_resume.py` prints the
   resume's visible TIMELINE span; that — not the candidate's full history — is what a
   recruiter/screener compares against the JD line.
2. **Eliminate older work experience in contiguous blocks — but only roles that carry no JD
   evidence.** Age is the tiebreaker, JD evidence is the rule: a whole-role drop must not remove
   the resume's strongest evidence for a JD-named requirement. Run the what-if WITH `--jd` —
   measure prints each dropped role's JD-matched bullets (`JD EVIDENCE LOST:`). A role flagged
   with evidence is **trimmed to its JD-relevant bullets**, not dropped whole; pick whole-role
   drops from roles reported as clean. Remove *entire* roles (header, job title, bullets, Tools
   line) so the visible timeline stays gapless and lands at roughly the JD's ask plus a buffer
   (e.g. "5+ years" → show ~7–8 years). Deleting a few bullets from a 15-year span does not align
   the resume — the *years shown* are what a screener sees. The structural validator catches any
   orphaned title/bullets after each whole-role removal.

   The approved `drop_role()` calls also dispose of the dropped roles' per-bullet and Tools-line
   prune candidates — preferred practice is to remove their `set_text`/`set_labeled` edits and `#
   kept:` comments; the prune gate associates role Tools-line candidates with the owning role, so
   an enclosing `drop_role()` covers them as a whole-role disposition (docs/api.md). If generated
   edits are temporarily retained, place the `drop_role()` calls after those edits, immediately
   before `save()`, so strict mode does not report skipped targets.

   **Compute the resulting span BEFORE editing.** Pass each whole-role drop to measure as a
   what-if — it drops the roles in a temp copy, renders THAT, and prints the resulting TIMELINE,
   so the year math is the tool's, not hand-derived in chat. One `--simulate` flag PER dropped
   role (not positional), and the agreed page target as a positional before `--jd`:

   ```bash python3 scripts/measure_resume.py "<Target>.docx" <TARGET_PAGES> \ --jd
   "jd_<target>.txt" --simulate "Acme Corp, Austin, TX" \ --simulate "Globex, Chicago, IL" ```

   Add `--jd-years <N>` only when the JD states a years requirement. See
   [docs/api.md](docs/api.md) for the full simulation reference, `JD EVIDENCE LOST`
   interpretation, and `drop_role`/`drop_section` usage.
3. **Reduce number-of-years statements** to match the visible span ("15 years" → "7+ years" in
   the Summary; any other "N years" claim). The validator enforces this mechanically for the
   Summary and every paragraph.
4. **Check the JD for a degree/education substitution clause.** See [docs/api.md](docs/api.md)
   for the full Education drop/keep predicates and the validator's enforcement. The short
   version: DROP when the JD states no degree requirement and the degree doesn't evidence the
   role; KEEP when the JD requires a degree, has a substitution clause the visible span doesn't
   satisfy, or the field is credential-sensitive. The validator blocks the render when Education
   is dropped against a degree-requiring JD; `--education-approved` records the override.
5. **Raise it to the user before acting — the DROP LIST, not just the span, as ONE question,
   before authoring the tailor script.** Whole-role elimination changes the narrative materially;
   a plan the user corrects piecemeal mid-build ("target 3 pages", then "keep Company X") costs a
   re-simulation and a re-plan of every downstream cut. Present in ONE message: the measured
   target page count, each proposed whole-role drop BY NAME with its years, and the resulting
   visible span — then wait for the reply before writing the tailor script. Steering replies (a
   page target, "keep X") are NOT seniority approval — EXCEPT when the steering reply itself
   names the complete revised drop set (e.g. "drop Acme and Globex, keep Initech"): naming every
   role to drop IS approval of that set, so re-present the measured numbers and proceed without a
   second approval round-trip. Also approved without a second round-trip: a general approval
   ("approved, proceed", "go ahead", "Drop plan approved, proceed") when exactly ONE drop set was
   presented as the recommendation — the user approved that recommendation. Only when two or more
   options were left open does a general approval need the user to pick one first. **Enforced,
   not a habit:** `validate_resume.py` detects whole-role elimination (visible span ≥2 years
   shorter than the master) and `render_pdf.sh` blocks the PDF until the approval is recorded
   with `--seniority-approved` (Step 11) — you cannot ship a PDF from a shortened timeline
   without the approval token. See [docs/api.md](docs/api.md) for the full approval-token rules
   and single-turn session behavior.

### 5. Align the top title to the JD's; the Summary stays untouched
The name/title line is what a screener compares against the posting's level first. The positioning
pass (this step, the Step 7 senior-role re-anchor, and the Education decision) is applied
immediately after the user approves whole-role drops, before the first post-drop run; measure and
close the page/word budgets only after it. **When the JD names a title LESS SENIOR than the
headline** (a mid-level "Software Test Engineer" posting against "Staff Engineer"), set the
`[Title]` paragraph under the name to the JD's exact title (`set_text(find_p(ps, "<title prefix>"),
"<JD title>")`); same-level retitles are also safe. **Never adopt a MORE senior title**; if the JD
names no title, leave the headline unchanged. Only the positioning headline changes — history-block
`JobTitleBlock` titles stay the real titles. The top title often shares its prefix with the
most-recent role's title ("Staff Engineer" vs "Staff Engineer – Quality Automation & Engineering
Enablement"), so `after=` alone will NOT disambiguate it: `after=` means "strictly after this
paragraph in document order", not "the next paragraph", and both candidates sit after the name line.
Anchor by occurrence instead: `find_p(ps, "Staff Engineer", nth=1)` — the headline is the FIRST
match. The `--prefixes` dump marks it for you (`# HEADLINE (positioning title, not the name)`) — the
name line shares the Title style, so the mark, not the index, tells you which Title is the headline.

`measure_resume.py --jd` and `validate_resume.py --jd` print a `JD TITLE vs HEADLINE` WARNING when
the headline is more senior — act on it.

**Never edit the user’s Summary/intro paragraph.** It is the human-positioning asset, not an ATS
keyword surface: do not rewrite it, add to it, remove from it, or score-driven-compress it. Exclude
this immutable paragraph from the 40-word cap and from word-level pruning. The title may still be
aligned to the JD, but the Summary must be copied byte-for-byte from the master unless the user
edits it. Cap every other editable prose paragraph and individual bullet at 40 words.
`validate_resume.py` must report any over-cap editable paragraph before rendering; do not claim
completion while one remains.

### 6. Don't insert sections between the Summary and Technical Proficiencies

The Summary is the intro paragraph; Technical Proficiencies follows directly. **Do not insert a Core
Strengths, Top Skills, or keyword-mirror section between them.** A separate keyword list duplicates
the proficiencies below it and competes with the role bullets for the reader's attention. ATS
keyword matching is already carried by the Summary's mirror of JD language plus the Technical
Proficiencies section — a third keyword surface between them adds noise, not signal.
`validate_resume.py`'s GUIDANCE section warns when a SectionHeading appears between Summary and
Technical Proficiencies.

When a recruiter or JD names required skills/tools, they belong in the role bullet where they were
actually used — never a bare keyword list (Step 7's weave rule).

### 7. Re-anchor the most recent / senior role, and expand the role most adjacent to the JD's industry/stage
That role carries the most weight. Rewrite its intro to emphasize **ownership** and the JD's selling
points.

**The most-recent role is NOT exempt from machine pruning.** Weight is not immunity: recency
protects a role from whole-role elimination, never from bullet selection. A 1-year Staff role with
heavy AI leverage can genuinely accomplish more than a 3-year one — time served is never a cut
signal, and volume of accomplishment never justifies keeping a bullet. It was pruned under the same
machine rule as every other role (Step 2).

Enrichment is NOT part of this step — new content from the master/LinkedIn enters only through
Theme Review B's source-first hosting pass, never a general pass. Where new content overlaps an
existing bullet, **merge** rather than append — appending blows the page budget; merging keeps the
role tight.

When the recruiter or JD names specific tools, weave each into the role bullet where it was actually
used, naming the tool in-bullet — that is stronger evidence than a keyword list and is what
recruiters ask for when they say "show where you used it."

If the JD targets a specific industry/stage (e.g. startup, AI, FinTech, healthcare), ALSO expand the
most relevant past role to show those themes with concrete framing — keep and reframe (via
`set_text`) the bullets that make the theme explicit. If the master is missing a theme the user
confirms they have, stop and ask the user to add it to the master directly. After the user edit,
re-run Phase 1; do not write the fact into the master or a per-target script from this workflow.

### 7A. Close page and word budgets with theme-scoped edits
Run this section only after the user approves the seniority plan and Steps 5–7 positioning edits
are applied. The page target is the maximum allowed. Re-measure the positioned build and edit toward
the agreed target using the theme anchors from Theme Review A:

- **Page closure first:** cut or merge only content that is off-theme, redundant, or weaker than
  another host for the same theme outcome. Never remove a unique domain, mission, capability, or
  role-continuity anchor merely because it has fewer literal JD terms.
- **Word closure second:** if and only if the build exceeds the 1,000-word cap, make a separate
  theme-scoped word pass. Keep headroom for the rendered-PDF counter, and record the theme reason
  for every cut or merge. If the build is at or below 1,000 words, do not make score-driven word
  edits.
- **Page-removal assessment:** if an extra page remains, measure the rendered spill. Attempt a
  trim-to-remove-page pass only when the spill is **five rendered lines or fewer**. When the spill
  is greater than five lines, retain the page or return to the approved target decision; do not
  launch a broad compression loop.
- **Spacers last:** after content and budgets settle, add one spacer at each inter-role boundary
  only when it does not create a new page or exceed the agreed target. If a spacer spills, omit the
  spacer, never theme-aligned content.

Every page, word, page-removal, or spacer edit gets one final read against the theme brief before
rendering. Close the measurable budget gate with the measured PDF word count and spill:

```bash
python3 scripts/workflow_gate.py budgets \
    "<Name> Resume - <Target>.docx.workflow.json" \
    --words <rendered-word-count> --spill-lines <spill-lines>
```

Add `--attempted-page-removal` only when attempting to remove a page. The command rejects counts
above 1,000 and rejects a page-removal attempt unless its positive spill is five lines or fewer.
After spacers are added and confirmed not to create a page, close the final layout gate:

```bash
python3 scripts/workflow_gate.py spacers \
    "<Name> Resume - <Target>.docx.workflow.json"
```

The final render and ATS audit are verification only.

### 8. Source-first hosting reference — execute during Theme Review B
**This section unlocks the LinkedIn export and full master mining.** (The master's paragraph map has
been readable since Theme Review A; the source-first loop itself executes during Theme Review B,
before seniority and budget work.)
The mining trigger is a SURFACED GAP during Theme Review B: the build measure's **JD terms with NO
host** list or `ats_audit.py --jd`'s baseline no-host report. A later external scan may confirm a
gap, but it cannot reopen the closed hosting loop. Mining is gap-driven ONLY, and the surfaced list
is a work order for thematic review, not permission to ask or host immediately.
Before raising ANY term, perform this source-first loop — **in this order, and the master leg is a
checked step, not a habit**:

1. **Read the current master for the term — literally.** Run the inference map (`--linkedin
   <dump>`), which searches the adjacent master automatically and now names, per term, which
   sources were searched (`master: "..."` on a hit; `master: no match` on a RAISE). Then GREP the
   raw master text for every RAISE-candidate term yourself (`docx_edit.py "<master>.docx"
   --prefixes | grep -i "<term>"`) — the map's variants/family roots miss paraphrased evidence
   the raw text still shows. **Mining without the master is a FAILURE, not a warning: the master
   must sit next to the tailored copy, and `measure_resume.py` exits 2 when a mining queue exists
   and no adjacent master is found** (content Phase 1 cut lives only in the master — mining
   without it silently overstates gaps).
2. Read the complete LinkedIn dump and run the inference map for the current build and current
   gap list.
3. AUTO-HOST every term with source evidence, without asking the user.
4. Only then put genuinely unsupported terms in one RAISE checklist — each with the master-grep
   result noted ("not in master, not in LinkedIn"), so the user sees the search actually
   happened.
5. After every hosting edit or new ATS scan, repeat the map and source check for the changed gap
   list. Never reuse a stale map from an earlier build.

The master and LinkedIn are evidence sources for the surfaced asks, never a general enrichment pool.
The JD's selling-point themes come from the same surfaces.

- Run the LinkedIn dump once per mining round and read the whole file — never hand-`cat`
  individual CSVs:

  ```bash ./scripts/read_profile.sh > /tmp/profile.txt   # the whole export, one stream ```

  `Positions.csv` is the richest source (role detail the resume compressed away); `Skills.csv` is
  keyword evidence only; `Certifications.csv`/`Education.csv` back the credential asks;
  `Recommendations_Received.csv` is quotable support for regulated/leadership claims a JD
  emphasizes.

**Every surfaced JD hard and soft skill ends in exactly one of two states:**
1. **Hosted** — the literal phrase lives in a truthful bullet/Summary line (hard skill:
   user-confirmed experience; soft skill: action-verb evidence, safe to infer).
2. **Raised and unanswered** — put to the user, awaiting their answer.

The INFERENCE MAP decides which terms land in which state — follow its verdicts; do not re-ask what
the map already answered. Read measure's **INFERENCE MAP** (`--linkedin <profile-dump.txt>`) on
every mining round: "no literal host" may not be "no evidence" — the map deterministically searches
the current master and LinkedIn dump for each term's morphological variants and skill-family roots
and prints the evidence it finds (see [docs/api.md](docs/api.md)), then prints a mechanical verdict
per term:

- **AUTO-HOST** — evidence found in the master or LinkedIn material. Host the literal phrase in
  the bullet/role where the evidence lives (merge, don't append) **without asking whether the user
  has the skill**. Weak lexical/family matches are still hostable, so do not ask about plural
  forms such as `defects` or obvious evidence such as SQL. If the evidence does not identify a
  role, use the Summary or Technical Proficiencies section. Ask about placement only when a
  role-specific claim truly requires it. Note where 'similar' tooling truthfully answers the ask
  (Postman/Karate for "SoapUI or REST API testing tools").
- **RAISE** — no deterministic evidence anywhere. The only terms that reach the user's checklist:
  never mark them "gap, closed" and never fabricate — real experience is often lexically
  invisible, so ask and host only what the user confirms.

Present the RAISE checklist to the user in ONE message, after the AUTO-HOST hosts have landed.

**Soft-skill asks are inferred from action-verb evidence, not keyword-matched — host the literal
phrase by DEFAULT.** A qual line like "Excellent communication, stakeholder management, and
technical leadership skills" is demonstrated by the kept bullets' structural evidence — presenting,
demoing, leading, mentoring, training (the master is full of them). When the action-verb evidence
exists, host the JD's literal phrase in the bullet or Summary where that evidence lives, in this
same hosting pass. One user confirmation ("my communication was excellent at every position") covers
every role at once — do not re-ask per company. External ATS tools score the literal phrase, not the
concept; the never-fabricate rule is for tools and employers (Appium, LoadRunner) — not for soft
skills backed by the candidate's own demonstrated history.

**Host in-bullet first.** A mined host lands as a rewrite or extension of the kept bullet where the
evidence lives — mirroring the JD's literal phrase only when Theme Review B approves it — never as
resurrected master prose and never as a keyword list (Step 6). Every bullet stays under the 40-word
cap. When no kept bullet can truthfully host the ask, author a fresh bullet in the role where the
experience lives (merge, don't append). Do not trade or cut content inside this hosting loop to
solve page or word budgets. Record the host, finish Theme Review B, and handle all budget changes
later in Step 7A.

**Budget reference only.** The hard per-role cap remains eight bullets and the whole-resume cap
remains 1,000 words, but all page and word decisions execute in Step 7A after seniority and
positioning. Do not use this source-mining section to launch a weakest-first or score-driven reclaim
loop. If `squeeze_resume.py --protect "<JD-critical phrase>"` is used in Step 7A, review every
fold-back line against the theme before applying it.

Spacer insertion is specified in Step 7A and happens only after the theme, ATS, seniority, page,
and word decisions are closed. Use `measure_resume.py`'s **SPACER OPPORTUNITIES** and
`validate_resume.py`'s GUIDANCE output, run `clone_after(body, find_p(ps, "<Tools line>"), "")`
after `remove_empty(body)`, and omit any spacer that would create a new page.
### 9. Fix grammar and typos in the same pass
Common catches: `to improving` → `improving` (infinitive), `companies goal` → `company's goal`,
`evangalist` → `evangelist`, `testzing` → `testing`, `Github` → `GitHub` (official casing). Don't
rely on spellcheck for these — grep the text.

**Re-read every editable paragraph you generated.** The Summary/intro is immutable and is not part
of this edit pass. Before declaring the build done, dump each changed role intro and bullet from the
actual final `.docx` with `docx_edit.py "<docx>" <idx> --full`, count its words, and verify it reads
clean. Do this again after any user edit. The validator's TEXT INTEGRITY section catches non-ASCII
mangling, doubled punctuation, and doubled words; the re-read must catch awkward phrasing, malformed
possessives, missing words, wrong tense, and sentence fragments. A cap violation or unresolved
grammar warning blocks completion.

**Punctuation rule — periods and commas only.** In the Summary and job-history prose, never use em
dashes (`—`), double hyphens (`--`), semicolons (`;`), colons (`:`), or ellipses (`...` or the `…`
character). Rejoin with a period (split into a new sentence) or a comma instead. **Single hyphens
are fine** — they appear in compound words (`test-automation`, `end-to-end`, `CI/CD`) and are never
flagged by the validator. En dashes are only allowed in date ranges (`01/2023 – 12/2024`); in prose,
treat them like em dashes (replace with a period or comma). Exempt from the rule: structural lines
(company headers, job titles), non-role sections (Technical Proficiencies, Certifications,
Education), and the Tools line's `Label: values` colon — the colon there separates a bold label from
a value list, it is not prose punctuation.

### 10. Save the tailored copy (as .docx, the working format)
Write to `<userName> Resume - <Target>.docx` (drop "Master" from the master's name). Never overwrite
the master. **The deliverable gate runs at save time.** A tailor script's `save(..., src=SRC)`
validates BEFORE writing: a state that would fail validation is never written, and the stale master
copy is removed — nothing to convert by hand. Approval tokens go in `RESUME_VALIDATE_ARGS` (same env
the render gate reads). Master writes are outside this workflow and must be made directly by the
user. The `.docx` is the working file for the session — iterate on it while tuning the rendered PDF,
then delete both after the resume is submitted. The master is the permanent artifact; tailored
copies are temp files scoped to the session that created them.

### 11. Render the final PDF and verify
The `.docx` is the editing format; **the `.pdf` is the deliverable** — render and verify with
`render_pdf.sh`:

```bash
RESUME_VALIDATE_ARGS="--seniority-approved --jd jd_<target>.txt" \
    TARGET_PAGES=<TARGET_PAGES> ./scripts/render_pdf.sh \
    "<Name> Resume - <Target>.docx"
```

Use the agreed page target for `TARGET_PAGES`. The JD and approval token go inside
`RESUME_VALIDATE_ARGS` (the save-time gate reads the same env). [docs/api.md](docs/api.md) has the
full render reference: `--verbose`, `--target-pages`, the approval-token rules, and what each gate
NOTE means.

`render_pdf.sh` **validates first** (runs `validate_resume.py`): it refuses to render on blocking
errors — orphan content, unapproved whole-role elimination, or Education dropped against a
degree-requiring JD. Fix the errors, then render. The seniority gate runs unconditionally; the
education gate runs only with `--jd`.

**Fix tool bugs in the session that finds them.** If a script misbehaves or contradicts its
documented behavior, do not route around it: fix the script and add a regression test in the same
session (then continue the tailoring run on the fixed tool). A workaround leaves the bug armed for
the next session.

**Verification is TEXT-ONLY — never render pages to images.** This harness reads no images; the text
path covers what a visual check would: `render_pdf.sh --verbose` prints the page-boundary map and
last-page tail, and `measure_resume.py` prints the page-fill table with widow/underfill detection.

**ATS verification — the internal matchers are not the ground truth.** The workflow's term/concept
matching overestimates alignment — a build can pass every internal gate while its hard skills carry
zero literal hits and the external ATS score drops (one scan: 9 of 24 hard skills at zero hits).
After the final render, run the literal-phrase audit on the PDF a screener parses:

```bash
python3 scripts/ats_audit.py "<Name> Resume - <Target>.pdf" --jd jd_<target>.txt
```

It checks the whole-resume word cap and actionable qualification-line phrases literally (host the
exact phrase truthfully or raise the gap — never fabricate). Posting metadata, company-introduction
prose, and generic fragments are excluded from the normal phrase list and cannot affect the exit
status. JD-named terms with no host mean a cut killed the last host (the machine protects JD-named
sentences/lines whole, but a hosting rewrite can kill one — Step 8's in-bullet rule) or the phrase
was never mirrored — fix or raise. **Before raising a no-host term as a genuine gap, grep the MASTER
for it — including content Phase 1 cut, from dropped roles AND from roles still kept in the build.**
Cut-first means the master still hosts what the deliverable lost: the only truthful host of a term
is often a bullet Phase 1 cut (a security bullet behind `cybersecurity`, a test-documentation bullet
in a role the build kept) — hosting it from the master clears the gap in one edit, while raising it
to the user costs a round-trip and, unchecked, reports as a gap something the candidate's own
history already evidences. The report's soft-skill no-hosts are ACTIONABLE (Step 8's inference rule;
soft skills are safe to infer) — not advisory. Its findings summary auto-IGNOREs the by-rule noise
(contactEmail, specialCharacters, education findings on an Education-free PDF — see below), so the
remaining findings are the actionable ones.

**External ATS scan (when configured).** `scripts/ats_check.py scan "<resume>.pdf" jd_<target>.txt`
submits the deliverable to the user's ATS scan service and saves the match-report JSON next to the
resume (`<...>.ats-check.json`); feed it back for the authoritative cross-check:
`.ats-check/cookies.txt` to re-seed). Below the 75 target, feed the saved report back through the
current-build measure run:

```bash
python3 scripts/measure_resume.py "<Name> Resume - <Target>.docx" \
  <TARGET_PAGES> --jd jd_<target>.txt --linkedin /tmp/profile.txt \
  --ats-report "<Name> Resume - <Target>.ats-check.json"
```

That command merges the external hard/soft gaps with the internal no-host list, runs the
master/LinkedIn inference map over the combined queue, and writes `<resume>.gap.json` (resume/report
fingerprinted — a stale artifact never passes for a fresh build). `ats_check.py` also prints both
missing lists at scan time. Those lists are the next source-mining queue — not optional, and not
displaced by a different `ats_audit.py` no-host list. The report's `wordCount` is a CROSS-CHECK only
— the service's PDF parser inflates counts (it splits labeled values into fragments), so the cap is
always `ats_audit.py`'s own count. The scan output names the target company's ATS when it identified
one (`target ATS:` line, from the report's atsTip finding) — that identification needs the posting
URL persisted with the JD (Step 1): the chain PATCHes it onto the opportunity and reports which of
three ATS metadata states applies (identified / URL unmatched by the service / URL missing). When
the service cannot match the posting to a known ATS (e.g. postings hosted on job boards rather than
an ATS), ATS-specific findings are simply unavailable — the keyword findings still apply. And when
the JD file carries no URL at all, the scan reuses the company's prior-scan identification (Step 1's
URL-optional rule) — never re-run a URL-less scan for a company whose ATS an earlier scan already
identified without checking that reuse.

**The match-rate target is 75.** `ats_audit.py` and `ats_check.py` enforce the stop: at or above it,
the hosting loop closes and score-driven edits halt — the residual actionable no-host list at that
point contains genuine never-fabricate gaps. Below 75, keep hosting literal phrases truthfully. See
[docs/api.md](docs/api.md) for `--match-target` overrides.

**The honest ceiling — declared only WITH the user, never alone.** When the match rate stays below
target and every remaining no-host is (per Step 8's two-state rule) raised and unanswered, STOP
hosting — do not loop, and do not self-declare the score final. Present the remaining hard AND soft
skill checklist to the user and get their explicit confirmation that nothing else can be hosted
truthfully. Only that confirmation closes the loop: report the final rate as "the honest ceiling for
this target", name the confirmed gaps, and let the user weigh applying. `ats_audit.py` enforces the
gate mechanically: when two consecutive audits report the same below-target score it prints
**CEILING DETECTED** — at that signal the checklist presentation is mandatory, not judgment.

**The word cap has TWO counters — keep headroom for the stricter one.** `validate_resume.py` counts
the .docx paragraphs; `ats_audit.py` counts the RENDERED PDF text (its count is authoritative for
the cap). The two drift ±1–2% on header/footer and hyphenation handling, so a .docx count of 999 can
render at 1001 and FAIL the audit. Keep the validator count at ~990 or below so the render-time
audit count stays under 1000; when planning cuts, use measure's **WORD BUDGET** section
(validator-equivalent per-role totals + wordiest bullets) instead of hand-counting across blocked
re-run cycles.

**IGNORED by rule: three classes of external finding.**

1. **contactEmail** (searchability). The compact hyperlinked contact block (link text "Email"
   over a `mailto:` target) is a deliberate design the user chose for readability — NEVER widen
   columns, unwrap the header, or rewrite link display text to satisfy a literal text parser. The
   address lives in the hyperlink target, which many ATS parsers extract; a raw-text parser's
   `contactEmail` fail is the known, accepted tradeoff.
2. **specialCharacters** (formatting). The resume's typographic characters (Wingdings bullets,
   en-dash date ranges, curly apostrophes) are the user's deliberate formatting — "it pops better
   with the current formatting, so ignore". NEVER reformat the resume to satisfy a text parser's
   character check; the finding is noise in every external report.
3. **The education findings** (`headingEducation`, `educationMatch`) when the rendered resume has
   no Education section. The drop was a Step 4.4 predicate decision and the render gate already
   sanctioned it — the scan's generic "add an Education section" advice does not re-open that
   decision. When Education IS present, the findings report normally.

`ats_audit.py` prints each ignored finding as `IGNORED` with its rule; never act on one, and never
re-litigate the underlying decision at scan time.

**Final human review (what the tools can't judge).** After the last render, re-read the full
`--prefixes` dump top-to-bottom once: every kept bullet still serves the JD and reads on-theme,
whole-role removals still read as a coherent timeline, the top title's level matches the JD's title
(Step 5), and the Summary's claims still match what the reader sees. Years-vs-timeline is automated
(`validate_resume.py`); JD-fit judgment of kept bullets is not — that stays human. The post-build
measure run's **JD-FIT AUDIT** narrows where to look: any OFF-JD bullet it lists gets cut or
shortened even when the page target is met, or kept with a one-line reason tied to the JD. **Re-read
the machine's `# kept:` stub lines first** — the only keeps in the build, recorded where a role
would otherwise have lost every bullet (Step 2's stub rule). They are the deliverable's
least-verified content: at final review a stub whose bullet no longer reads as the role's strongest
— or that a hosting edit superseded — gets cut, and the role with it if no JD evidence remains
(seniority gate permitting).

If it overshoots the target, **compress one more older-role bullet** and re-render until the last
page is full (the `.pdf` is the deliverable; the `.docx` is session-temp source — see Step 10).

### 12. Leave the master untouched
The tailoring session ends with the tailored `.docx` and rendered `.pdf`. This workflow never edits
the master, including confirmed experience, proficiency lines, or user-confirmed additions. Do not
call `clone_after`, `--set-text`, or `--append-after` against the master as part of tailoring. If
the user wants to retain a new fact for future targets, the user edits the master directly.

If the user edits the master directly, a later tailoring run detects the change, refreshes the
machine prune, and rebuilds the target from the updated source.

## When NOT to use this skill

- The user only has a PDF resume (no `.docx` source). Offer to review and recommend edits, but
  don't attempt precise edits on a PDF.
- The user wants a brand-new resume from scratch. This skill tailors an existing master; it does
  not author one.
- The user wants LinkedIn profile edits only (skills, summary, headline). The `docx_edit.py`
  helpers do not apply; advise in chat instead.

## Accuracy: mirror the JD's verbs, but never overclaim

Tailoring rewrites bullets to hit JD language, but the verbs must stay truthful. A JD that asks to
"design and develop object-oriented automation frameworks" invites the word *design* — but if the
actual work was **refactoring** an existing framework or **re-architecting** CI, say that, not
"designed from scratch". Reserve "designed/built from scratch" for work that was genuinely
greenfield (e.g. a startup SDK framework no one had written before). The user has to stand behind
every line in an interview; an inflated verb that can't be defended is worse than a JD keyword that
went unmirrored.

**Never fabricate a role bullet for a tool you haven't used.** If a recruiter or JD names a tool the
user doesn't have, omit it and flag it to the user rather than inventing a bullet — a made-up tool
usage is the easiest thing to catch.

**Soft-skill claims are the user's word, evidenced by their history.** The never-fabricate rule
governs tools and employers. Communication, leadership, and stakeholder management are different:
the master's presented/demoed/led/mentored/trained bullets ARE the evidence (Step 8's inference
rule), and that action-verb evidence itself authorizes hosting the JD's literal phrase — by default,
no explicit statement required (soft skills are safe to infer; Step 8). Declining to state a skill
the user has confirmed — or re-asking after they confirmed it — is over-caution that costs
round-trips and leaves JD lines flagged for no reason.

## Common mistakes

The tools and workflow steps above already enforce most failure modes (validators, the drift
sidecar, `merge_into`; Steps 8 & 11). What's left is judgment:

| Mistake | Fix |
|---|---|
| Rebuilding the .docx from scratch | Edit XML in place — `python-docx` drops styles, numbering, hyperlinks |
| Using `set_text` on a `"Label: values"` line | Collapses to all-bold — use `set_labeled` (Helper library) |
| Hand-counting an edit budget (`expect_edits=N`) | Never count — `save()`'s drift sidecar records the baseline and warns on change |
| Hand-rolling whole-role removal in the tailor script | Use `drop_role(body, "<company prefix>")` / `drop_section(body, "Education")` — the library owns the block grammar. A hand-rolled helper that appends before checking the boundary (or only treats Heading1/2 as boundaries) swallows the next `SectionHeading` (Education) and strands later edits as "not found" skips |
| Verifying the PDF by rendering pages to images | Never works — this harness reads no images. Use `render_pdf.sh --verbose` (page map, last-page tail), `measure_resume.py`'s page-fill table, and `pdftotext` |
| Editing the tailor script with ad-hoc `python3 - <<'EOF' s.replace(...)` heredocs | Use the `edit` tool on a targeted view (`sed -n 'A,Bp'`). The one-heredoc FULL rewrite is for corruption recovery only (Token-spend #6) |
| Chasing a skip warning as a library bug | Re-dump `--prefixes` on the master FIRST — it may have been edited since your dump (the `MASTER CHANGED:` sidecar warning fires on this); a prefix can also match a paragraph an earlier `drop` already removed if you thread a stale `ps` list — REBIND `ps = drop(body, [...])`, never concatenate (`ps = drop(...) + ps` duplicates the list and every later `find_p` matches twice) |
| Reading "no unprotected bullet to give" as a dead end | The engine has one rule (hosts an ask or not) — there is no second relevance threshold to negotiate; the dead-end fix is a TOP-BLOCK cut, a Tools-line trim, or a user-approved whole-role drop (Step 8 backstop) |
| Running squeeze in apply mode on the tailored .docx and then folding cuts back into the script by hand | Harvest with `--plan-only` BEFORE the script's first run — same loop, same fold-back block, file untouched (Step 8) |
| Cutting only job bullets — leaving off-JD proficiencies/certs while JD-matched bullets die | Cuts span the WHOLE resume: check measure's TOP-BLOCK RECLAIM CANDIDATES and the Tools lines before cutting another JD-matched bullet (Step 8) |
| Pruning only the oldest roles while the most-recent role keeps 15+ bullets | The machine prune and the hard per-role cap (8) apply to EVERY role (Step 2) — check the build's JD-FIT AUDIT for the top role's unevidenced bullets (Step 8 backstop) |
| Treating a proficiencies/Tools-line host as proof of a JD ask | JD REQUIREMENT COVERAGE prints [weak] for non-bullet hosts — weave the skill into the bullet where it was used (Step 7); [UNCOVERED] means demonstrate it or raise the gap, never fabricate |
| "Keep N" with a drop list that doesn't add up | intended keep + len(drop list) == the role's master bullet count (23 − 16 = 7, not 8); a built role whose count differs from intent is a MISS to fix, not a counting convention (Step 8) |
| Cutting a bullet because the role is short, or keeping one because it is recent | Time-in-role is never a cut signal and never an exemption — JD alignment decides first, readability second, tenure/recency only as tiebreakers (Steps 2, 8) |
| Treating a proficiencies/Tools line as permanent ATS-host real estate | The machine keeps a line whole only when it hosts JD evidence and cuts a line with no ask whole (Step 2, never a partial value list); hosting comes from purpose-written bullet text, not preserved lines |
| Overriding a prune cut without theme rationale, or hand-editing the emitted cuts | Step 3's theme review is the sanctioned override: restore as a fresh, purpose-written host, or fix the evidence families and re-run `auto_prune.py`; record the rationale in the script. Never hand-edit the machine's output cuts — the machine prune stays the only master consumer and there is no `# kept:` negotiation |
| Inflating verbs to match the JD ("designed from scratch" for a refactor) | Keep verbs truthful — see Accuracy |
| Editing the master from a tailoring session | Never — the master is user-owned and read-only to this workflow; make any master update directly, then re-run Phase 1 |
| Storing the JD in /tmp | Persist it as `jd_<target>.txt` in the skill root (Step 1) — every tool and the re-run instructions reference that path across sessions |
| Inserting a Core Strengths/Top Skills section between Summary and Technical Proficiencies | Don't — weave skills into role bullets (Step 7) |
| Headline still says "Staff" against a less-senior JD title | Rewrite the top title to the JD's exact title (Step 5); the Summary stays untouched — the first line is what the screener compares |
| Appending bullets when content overlaps an existing one | Merge (`merge_into`) — appending blows the page budget (Step 7) |
| Overwriting the master resume | Write to `<userName> Resume - <Target>.docx` — never the master filename (Step 10) |
| Keeping Education when the degree isn't evidence for the JD | Evaluate the drop/keep predicates (Step 4.4) — a BA vs an engineering JD is a 3-line drop |
| Reading a clean render (no `--jd`) as education-clause clearance | The education gate runs only with `--jd`; the seniority gate always — render_pdf.sh NOTEs when the education gate did not run (Step 11) |
| Relying on spellcheck for proper nouns | Grep the text for `GitHub`, `HIPAA`, etc. (Step 9) |
| Trusting the internal JD matchers as the ATS score | Internal matching is term/concept-based; ATS tools match literal phrases — run `ats_audit.py` on the rendered PDF before declaring done (Step 11) |
| Cutting the last host of a JD-named hard skill | The machine protects any JD-named/concept SENTENCE or LINE whole through every trim (Step 2 never edits a survivor's words); a hosting rewrite can still kill one — `ats_audit.py --jd` catches it post-build (Step 11) |
| Widening the contact block or rewriting link text for ATS parsers | IGNORED by rule — the compact hyperlinked contact block is deliberate design; `contactEmail` searchability findings are noise (Step 11) |
| Reformatting typography to clear the scan's Special Characters finding | IGNORED by rule — Wingdings bullets, en-dash dates, curly quotes are the user's deliberate formatting; never reformat to satisfy a text parser (Step 11) |
| Restoring Education because the scan wants an Education section | IGNORED by rule when Education was dropped per Step 4.4 — the render gate sanctioned the drop; the scan's generic advice does not re-open it (Step 11) |
| Treating "no literal host" as "no evidence" and declaring honest gaps, or re-asking the user about evidence-backed terms | Follow the INFERENCE MAP's verdicts (Step 8): AUTO-HOST terms are hosted without asking — debugging/UI/data-management asks are usually demonstrated, just lexically invisible; the user's checklist contains exactly the RAISE terms |
| Treating the external report's wordCount as the cap | The service's PDF parser inflates counts — the cap is `ats_audit.py`'s own count; the report's number is a cross-check only (Step 11) |
| Storing scan-service credentials in the repo | They live in the skill root's `.ats-check/` dot-directory (user's saved cURL exports; gitignored, 0600, invisible to `git add *`); refresh from a logged-in browser when scans 401 (Step 11) |
| Punctuation in prose (em dash, semicolon, colon, ellipsis) | Periods and commas ONLY — no em dashes, double hyphens, semicolons, colons, or ellipses (`...`); split into a new sentence or use a comma. The Tools line's `Label: values` colon is the one exempt structural colon (Step 9) |
| JD asks for fewer years than the candidate has | Offer Step 4 seniority alignment up front and record approval (`--seniority-approved`) — the render blocks without it. The token needs the user's authority: their chat reply or pre-authorization in the request; never pass it on your own |
