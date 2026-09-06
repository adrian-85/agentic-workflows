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
subtractive and JD-driven: **every role is pruned to its JD-relevant bullets,
including the most recent**, under a hard per-role bullet cap of 8 kept
bullets (Step 8).
JD alignment is king, readability second; time-in-role and recency are only
tiebreakers, never a cut signal and never an exemption.

## When to Use

- User provides a job description and wants their resume tailored to it
- User forwards a recruiter's screening message (e.g. "top 3 skills in
  bullets") and wants the resume aligned to it
- User has a master `.docx` resume and needs a per-target customized copy
- User needs a submission-ready PDF from an existing `.docx` resume

## Quick Reference

| Step | Action | Tool |
|---|---|---|
| 1 | Read inputs (JD — persist to skill root, master, LinkedIn) | `read_profile.sh` |
| 2 | Extract employer selling points | — |
| 3 | Decide length + seniority alignment | `measure_resume.py` (TIMELINE) |
| 4 | Align top title to JD title (less senior); rewrite Summary to lead with JD value | `set_text` |
| 5 | No sections between Summary & Proficiencies | — |
| 6 | Re-anchor senior role (merge, don't append) | `set_text`, `merge_into` |
| 7 | Expand role adjacent to JD industry/stage | `set_text` |
| 8 | Compress any section, any role (measure first): every role's off-JD bullets under the per-role cap, then off-JD proficiencies/certs | `measure_resume.py` `--jd` (DROP PLAN + weak-match listing + TOP-BLOCK CANDIDATES); `squeeze_resume.py` for the residual gap |
| 9 | Fix grammar, typos, punctuation | grep + `validate_resume.py` |
| 10 | Save tailored copy (never overwrite master) | `save()` |
| 11 | Render + verify PDF | `render_pdf.sh` |
| 12 | Fold user-confirmed experience into the master (additive, AFTER the tailor script is final) | `clone_after`, `--set-text`/`--append-after` |

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

## Helper library & reference template

`docx_edit.py` helpers (`set_text`, `set_labeled`, `find_p`, `drop`, `drop_role`, `drop_section`, `save`, `clone_after`, `merge_into`), the CLI reference, and the `tailor_resume.py` template are documented in [docs/api.md](docs/api.md). Read the api reference before authoring a tailor script; import only the helpers the planned edits use.

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
   evidence automatically (see Step 8), so the plan doesn't fight the JD. **The plan's
   WHICH transfers; its HOW MANY does not** — per-role budgets are derived from the state
   you measured, and your content edits change the math, so don't carry "drop N per role"
   forward; re-run measure on the build to confirm the gap closed and read its JD-FIT AUDIT.
   **The build's own measure run is also the term-coverage drift check**: its **JD terms
   with NO host** list catches an ask whose only host died with a cut role or trimmed Tools
   line — the master-measure said "covered", the deliverable doesn't have the word.
3. **Before reusing a tailor script after the user edited the .docx, run `diff_resume.py --tailor`**
   first — one command surfaces manual edits a blind re-run would wipe. (The drift sidecar
   is the tripwire; diff_resume is the review.)
4. **Over-cut by 1–2 bullets per batch; if still over, drop a whole oldest role.** Never
   hand-shorten sentences to chase a page break — it's the lowest-leverage, highest-cycle
   edit. When only a few lines over, run `squeeze_resume.py` (Step 8) to close the residual
   gap automatically instead of trimming by hand.
5. **Slice files, not re-runs.** Output you will read in sections — measure's DROP PLAN /
   page-fill table, a full `--prefixes` dump — goes to a file once (`measure_resume.py … >
   /tmp/measure.txt 2>&1`), then read the file with grep/sed. Never pipe a dump you will
   author from through `head`: the tail is silently lost and the missing paragraphs resurface
   as skipped edits.
6. **Syntax-check a tailor script the moment it is written.** Run
   `python3 -c "import ast; ast.parse(open('scripts/tailor_<target>.py').read())"`
   immediately after authoring. On corruption, do not repair incrementally
   with `edit` — rewrite the whole file in one bash heredoc and re-check.
7. **Before each `edit` of a script, view only the target region**
   (`sed -n 'A,Bp'`, or `grep -n` to find it) — not a full re-read. A
   session re-read its 300-line tailor script seventeen times across edit
   rounds; targeted views keep the edit anchors exact at a fraction of
   the tokens. Full re-read only when paragraph/script indices shifted
   and the anchor's position is genuinely unknown.

Tool-enforced (no instruction needed): `render_pdf.sh` refuses broken or unapproved-elimination
docs (validator, Step 11); `measure_resume.py` prints the BATCH RECLAIM PLAN, its JD-aware DROP PLAN
with copy-pasteable `find_p` cut lines, the per-role **JD-FIT AUDIT** (off-JD/weak bullets in every
role, even on target), **JD REQUIREMENT COVERAGE** (each qualification line → its kept hosts;
[weak] = proficiencies/Tools-line host only, [UNCOVERED] = demonstrate it or raise the gap), **JD
terms with NO host in the resume** (the never-fabricate flags), and flags page widows /
underfilled pages + **SPACER OPPORTUNITIES** (Step 8); `validate_resume.py` re-reports the
JD-FIT count at render/save time (the render gate is not skippable); `squeeze_resume.py` closes
the residual page gap automatically.

## Workflow

### 1. Read inputs
- Read the **job description** (JD) **or the recruiter's message**. A
  recruiter's "top skills" list or screening email is a lighter-weight input
  than a full JD — treat the named skills/tools as the alignment target just
  the same.
- **Persist the JD in the skill root, not /tmp.** Save it as
  `jd_<target>.txt` (e.g. `jd_optum.txt`) before anything else. Every
  downstream tool (tailor, measure, render, the `RESUME_VALIDATE_ARGS`
  tokens) references that path for the whole session, and the re-run
  instructions quoted at the end of a session outlive it — a JD left in
  `/tmp` was wiped mid-session once and crashed the deliverable gate.
  The tailor script's docstring records the path it was authored with.
- Read the **master resume**. If it is a `.docx`, use `docx_edit.py` to edit. If
  only a PDF is available, ask for the `.docx` source — PDFs can be read but
  not edited precisely.
- **Read the LinkedIn source before editing — the WHOLE export, via the
  script.** The resume is a compressed view; the LinkedIn data export has
  the richer detail that lets you enrich and merge bullets. Run the dump
  ONCE and read the file — never hand-`cat` individual CSVs (a session
  read only Skills + Profile, missing Positions' role detail and
  Certifications/Recommendations evidence, and judged regulated-industry
  strength from skill keywords alone):

  ```bash
  ./scripts/read_profile.sh > /tmp/profile.txt   # the whole export, one stream
  ```

  What each section of the dump is for:
  - `Positions.csv` — the full role history with description bullets: the
    richest source for restoring sub-roles and extra bullets the resume
    compressed away.
  - `Profile.csv` — headline and career summary.
  - `Skills.csv` — the candidate-tech vocabulary; keyword evidence only —
    never a substitute for the role detail above it.
  - `Certifications.csv` / `Education.csv` — certs and degrees (the
    validator's education gate needs the degree line).
  - `Recommendations_Received.csv` / `Endorsement_Received_Info.csv` —
    third-party evidence for themes the resume claims (quotable support
    for regulated/leadership claims a JD emphasizes).

### 2. Extract the employer's selling points
Ask the user (or infer from the JD) the handful of themes to sell on; these
themes drive every later edit. **If the input is a recruiter's named-skills
list rather than a JD, those skills/tools ARE the selling points** — every
later edit shows where each was used. Cross-check measure's **JD terms with
NO host in the resume** list (authoring-time measure, Step 8): those are the
mechanical never-fabricate flags — raise each to the user instead of
inventing evidence, and note where 'similar' tooling truthfully answers the
ask (Postman/Karate for "SoapUI or REST API testing tools").

**Soft-skill asks are inferred from action-verb evidence, not keyword-matched.**
A qual line like "Excellent communication, stakeholder management, and
technical leadership skills" is demonstrated by the master's structural
evidence — bullets about presenting, demoing, leading, mentoring, and
training (the master is full of them). Treat such a line as covered when
kept bullets carry that action evidence; one user confirmation ("my
communication was excellent at every position") covers every role at once —
do not re-ask per company. Never chase the literal adjective as a keyword:
a self-assessment adjective is the user's word to stand behind, so inject
it into a bullet only when the user states it or asks for the literal term
(and then host it in a bullet where the action evidence lives). The
never-fabricate rule is for tools and employers (Appium, LoadRunner) —
not for judging the user's own confirmed abilities.

### 3. Decide length up front
- **Target 2 pages; accept 3 for senior/Staff; 4 is too long.** "Senior"
  is mechanical, not a judgment call: the JD's stated title is
  Senior/Staff/Principal, OR the candidate's visible background is
  Staff-level — EITHER condition targets 3. A JD asking "7-10 years" (a
  range starting at 7) is itself a seniority signal favoring 3. When in
  doubt, default to 3 and let the measure's page-fill table decide (an
  underfilled last page below 50% full means re-target one page lower
  BEFORE cutting JD-matched bullets).
- **Present only a feasibility-measured target.** Before recommending a
  page count to the user, run the what-if (`measure --simulate` with the
  candidate whole-role drops at the candidate target) and check the
  projected page count. The user's approval is only as good as the
  numbers it is based on; simulate first, present the measured target,
  then ask.
- **Don't waffle between page targets.** If the LAST page renders under
  50% full, re-target one page lower BEFORE cutting any JD-matched bullet
  (measure emits `TARGET NOTE`). Once chosen, don't revisit the target
  mid-compression unless the note fires. (This prevents the 8-cycle
  waffle a 3-page senior build triggered when a 43% last page went
  unaddressed.)
- Length is reclaimed by **pruning every role to its JD-relevant bullets**
  (Step 8), then by whole-role drops at the bottom when seniority alignment
  calls for them. Recency and time-in-role are tiebreakers only — they decide
  which of two otherwise-equal bullets survives, never whether the
  most-recent role is exempt from pruning.
- Don't bloat the top to "add content" — instead *reallocate*: expand the
  senior role with JD-aligned content AND prune every role (including that
  one) under the per-role cap, then trim off-JD proficiencies, Tools lines,
  and spacers to make room. Done right, the resume gets
  *shorter* while the important part gets stronger. Decide the target page
  count now (Step 8 measures it before cutting).

**Seniority alignment — when the JD specifies fewer years than the candidate
has** (this session's case: a mid-level "Software Test Engineer" JD asking
"5+ years" against a 15-year Staff-engineer background). This is a distinct
decision, presented **up front and to the user** — not discovered mid-
compression when the page budget forces it:

1. **Compare the candidate's total years to the JD's ask.** `measure_resume.py`
   prints the resume's visible TIMELINE span; that — not the candidate's full
   history — is what a recruiter/screener compares against the JD line.
2. **Eliminate older work experience in contiguous blocks — but only roles
   that carry no JD evidence.** Age is the tiebreaker, JD evidence is the
   rule: a whole-role drop must not remove the resume's strongest evidence
   for a JD-named requirement. Run the what-if WITH `--jd` — measure prints
   each dropped role's JD-matched bullets (`JD EVIDENCE LOST:`). A role
   flagged with evidence is **trimmed to its JD-relevant bullets**, not
   dropped whole; pick whole-role drops from roles reported as clean.
   Remove *entire* roles (header, job title, bullets, Tools line) so the
   visible timeline stays gapless and lands at roughly the JD's ask plus
   a buffer (e.g. "5+ years" → show ~7–8 years). Deleting a few bullets
   from a 15-year span does not align the resume — the *years shown* are
   what a screener sees. The structural validator catches any orphaned
   title/bullets after each whole-role removal.

   **Compute the resulting span BEFORE editing.** Pass each whole-role drop
   to measure as a what-if — it drops the roles in a temp copy, renders
   THAT, and prints the resulting TIMELINE, so the year math is the tool's,
   not hand-derived in chat. See [docs/api.md](docs/api.md) for the full
   simulation command, `--jd-years`, `JD EVIDENCE LOST` interpretation,
   and `drop_role`/`drop_section` usage.
3. **Reduce number-of-years statements** to match the visible span ("15 years"
   → "7+ years" in the Summary; any other "N years" claim). The validator
   enforces this mechanically for the Summary and every paragraph.
4. **Check the JD for a degree/education substitution clause.** See
   [docs/api.md](docs/api.md) for the full Education drop/keep predicates
   and the validator's enforcement. The short version: DROP when the JD
   states no degree requirement and the degree doesn't evidence the role;
   KEEP when the JD requires a degree, has a substitution clause the
   visible span doesn't satisfy, or the field is credential-sensitive.
   The validator blocks the render when Education is dropped against a
   degree-requiring JD; `--education-approved` records the override.
5. **Raise it to the user before acting — the DROP LIST, not just the span,
   as ONE question, before authoring the tailor script.** Whole-role
   elimination changes the narrative materially; a plan the user corrects
   piecemeal mid-build ("target 3 pages", then "keep Company X") costs a
   re-simulation and a re-plan of every downstream cut. Present in ONE
   message: the measured target page count, each proposed whole-role drop
   BY NAME with its years, and the resulting visible span — then wait for
   the reply before writing the tailor script. Steering replies (a page
   target, "keep X") are NOT seniority approval — EXCEPT when the steering
   reply itself names the complete revised drop set (e.g. "drop Illumina
   and Epic, keep Rakuten and Trove"): naming every role to drop IS
   approval of that set, so re-present the measured numbers and proceed
   without a second approval round-trip.
   **Enforced, not a habit:** `validate_resume.py` detects whole-role elimination
   (visible span ≥2 years shorter than the master) and `render_pdf.sh` blocks the
   PDF until the approval is recorded with `--seniority-approved` (Step 11) — you
   cannot ship a PDF from a shortened timeline without the approval token.
   See [docs/api.md](docs/api.md) for the full approval-token rules and
   single-turn session behavior.

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
The `--prefixes` dump marks it for you (`# HEADLINE (positioning title,
not the name)`) — the name line shares the Title style, so the mark, not
the index, tells you which Title is the headline.

Level the title's echo in the Summary's first sentence so the pair reads
consistently ("Results-driven Staff engineer…" → "Results-driven Software Test
Engineer…"). `measure_resume.py --jd` and `validate_resume.py --jd` print a
`JD TITLE vs HEADLINE` WARNING when the headline is more senior — act on it.

Then rewrite the Summary so its first sentence hits the JD's core ask (e.g.
"owns quality end-to-end", "builds QA frameworks from scratch rather than
working within established ones"). Mirror the user's selling points explicitly.
**Cap every prose paragraph — the Summary included — at 40 words (a ceiling,
never a target: shorter is always fine). Individual bullets carry the same
40-word cap.** Word count,
not sentence count: a 3-sentence Summary measured ~84 words in a real
session and still read as a wall. `validate_resume.py` warns over the cap
in its GUIDANCE section (Tools lines exempt — they are keyword lists
governed by the wrap budget; master input exempt). The Summary is the
intro a human reviewer reads first — an overlong intro risks the reviewer
never reaching the bullets. Every Summary claim must be re-evidenced by a
kept bullet below; cut Summary content that duplicates what a role block
already says and let that block speak for itself.

### 5. Don't insert sections between the Summary and Technical Proficiencies

The Summary is the intro paragraph; Technical Proficiencies follows directly.
**Do not insert a Core Strengths, Top Skills, or keyword-mirror section between
them.** A separate keyword list duplicates the proficiencies below it and
competes with the role bullets for the reader's attention. ATS keyword
matching is already carried by the Summary's mirror of JD language plus the
Technical Proficiencies section — a third keyword surface between them adds
noise, not signal. `validate_resume.py`'s GUIDANCE section warns when a
SectionHeading appears between Summary and Technical Proficiencies.

When a recruiter or JD names required skills/tools, weave each into the role
bullet where it was actually used (see Step 6) so the skill appears as in-role
evidence, not a bare list.

### 6. Re-anchor the most recent / senior role
That role carries the most weight. Rewrite its intro to emphasize
**ownership** and the JD's selling points.

**The most-recent role is NOT exempt from JD-fit pruning.** Weight is not
immunity: recency protects a role from whole-role elimination, never from
bullet selection. A 1-year Staff role with heavy AI leverage can genuinely
accomplish more than a 3-year one — time served is never a cut signal, and
volume of accomplishment never justifies keeping a bullet. Prune its off-JD
bullets under the same hard cap and priority order as every other role
(Step 8).

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
**Cuts can come from ANY section, not just job bullets — and from ANY role,
including the most recent.** Technical Proficiencies lines, Certifications,
Tools lines, blank spacers, and role bullets are all first-class cuts — the
same rendered line cost. Priority order for every cut/keep decision:
(1) **JD alignment** — a bullet that does not serve THIS JD is cut wherever
it sits; (2) **readability** — concise, spaced, within the per-role bullet
cap below; only then (3) time-in-role and recency as tiebreakers between
otherwise-equal bullets. Compression order: (1) JD-fit pruning of EVERY
role via DROP PLAN, (2) TOP-BLOCK CANDIDATES lines (off-JD
proficiencies/certs), (3) Tools line trims, (4) blank spacers. Go in that
order; don't hand-pick.

**Hard bullet cap per role: never more than 8 kept bullets.** Enforced by
count, not by judgment, and independent of page target, tenure, or
accomplishment — the master keeps everything, the tailored resume
re-selects. The cap is a ceiling, not a quota: measure's page math and JD
alignment decide actual counts below it. The most-recent role competes
under the same cap — a 1-year role whose master block carries 20+ bullets
selects its strongest JD-aligned ones like everyone else. A role at the
cap while others sit far below it still crowds the page; a reviewer who
hits a wall of text skips bullets they needed to read.

**Reconcile the arithmetic before running the tailor script.** Per role:
intended keep + number of `drop()` entries must equal the role's master
bullet count (measure's table shows it as `b/cap`; intros are not bullets
and not cap fillers). A real failure: 23 master bullets, "keep the 8
strongest", 16 drops — 7 kept, one bullet more cut than intended, and the
post-build table that showed 7 got rationalized as "the intro" instead of
flagged as a miss. When a built role's count differs from the intent,
fix the drop list.

**Below the cap, pruning is JD-driven, not page-driven.** The DROP PLAN
fires only when the page math demands cuts — which is how an under-cap
role keeps every bullet, including ones no JD term names, after other
roles close the gap (a 5-bullet role kept 5/5; two matched nothing the JD
asks for). measure's **JD-FIT AUDIT** (printed for every role with
`--jd`, whether or not the resume is on target) closes the hole: cut its
OFF-JD bullets (no JD term, no practice phrase) and its weak-match
bullets even when the page target is already met, and re-read the audit
AFTER the build — a clean render is not a JD-tight resume. Irrelevant
bullets fail the JD-match goal twice over: they are noise for the
screener and lines the JD-relevant content paid for. The validator now
carries the same check into the render path, so the deliverable gate
re-reports the count — act on it or give each kept bullet a one-line JD
reason.

**Prove each qualification, don't just avoid fabricating it.** The
**JD REQUIREMENT COVERAGE** section maps every qualification line to its
kept host bullets. `[weak]` — the ask is hosted only on a
proficiencies/Tools line: weave it into the bullet where it was used
(Step 5), that is the evidence recruiters ask for. `[UNCOVERED]` — no
kept bullet demonstrates the ask: restore the evidence from the master
if it exists, or raise the gap to the user; never fabricate. A resume
that cannot show a required qual reads as unqualified for it, however
clean the rest.

**"Covered" means a literal-phrase host.** The coverage matcher matches
the JD's extracted terms as literal phrases — concept evidence does not
flip a line to covered ("event-driven architecture" wording covers that
phrase; "Kafka and MSMQ in a Tools line" does not cover "event-driven").
When a qual you KNOW is demonstrated still prints UNCOVERED, the fix is
to host the JD's literal phrase in a truthful bullet at authoring time —
not to debug the matcher. Read the UNCOVERED list at authoring-time
measure (before writing the script) and plan those hosts then.

**Soft-skill qual lines are judged on action-verb evidence.** "Excellent
communication, stakeholder management, technical leadership" and the
like extract no skill terms — measure reports them `by hand` with the
inference rule. Cover them with the kept bullets that show the behavior
(presented, demoed, led, mentored, trained, coordinated); inject the
literal adjective only with the user's stated authority (Step 2), hosted
in a bullet where the action evidence lives.

**Mostly-irrelevant role: cut to a stub, don't carry it whole.** When
most of a role's bullets are off-JD (the audit prints STUB CANDIDATE),
cut them; if the role then carries no JD evidence at all, keep a
1-bullet stub (header/title + strongest bullet) ONLY to prevent an
employment gap — timeline gaplessness is the one reason to keep
irrelevant content. An interior role dropped to nothing is a `drop_role`
(Step 3), not a stub.

**Never lengthen the resume unless it improves JD alignment.** Every kept
bullet, kept line, and added spacer must trace to a JD requirement or to
the readability spacing below; when content needs room, spacers go
first.

**The plan is a sum of REMOVALS, and measure emits it.** Every line in
the plan's math is a paragraph the tailor script deletes. When the
oldest-first plan cannot close the gap, measure emits a TOP-ROLE TRIM
BATCH (the most-recent role's weakest unprotected bullets, sized to the
residual gap) and, when even that cannot close it, a NOTE saying so —
paste its `find_p` lines into the script's first pass and take the NOTE
back to the user (whole-role drops / JD-matched tradeoffs). Kept
bullets' text is final FOR PAGE MATH: hand-shortening a kept bullet from
two rendered lines to one is not a cut and never closes a measured gap.
Shortening IS a legitimate JD-fit edit — trimming a kept bullet's
irrelevant clauses (40 words is a ceiling, never a target; less is always
fine) — it just never substitutes for a measured removal.

**Measure before cutting.** After the content edits (steps 4–7), run
`measure_resume.py` with the agreed Step-3 target — it renders once and
reports the exact reclaim gap, the BATCH RECLAIM PLAN (oldest roles first),
and the DROP PLAN (which bullets to cut, ranked weakest-first). See
[docs/api.md](docs/api.md) for the full command reference, `--jd`/`--protect`
flags, squeeze harvesting (`--plan-only`), and spacing procedures.

**Apply the DROP PLAN, not your own instinct.** The plan names *which*
bullets; page math says *how many*. DEAD-END PLANS and weak-match
`(cuttable)` listings are in the measure output — read them; don't guess.

**Check DEAD-END PLANS before cutting anything.** A role whose DROP PLAN
budget exceeds its unprotected bullets cannot meet the budget without
cutting JD-matched content — the honest fix is TOP-BLOCK candidates, a
Tools-line trim, or a whole-role drop — NOT slicing kept bullets.

**"No unprotected bullet to give" is not "no bullet to cut."** JD-matching
has false positives on generic terms. A term hitting MORE THAN HALF a
role's own bullets is weak evidence and does NOT protect. Specific
technology nouns (API, SQL, Playwright, ...) are exempt.

**Also check the TOP-BLOCK RECLAIM CANDIDATES** — off-JD proficiencies/cert
lines, copy-pasteable `find_p` cuts. Cut those before touching any
JD-matched bullet.

**Human rule still applies on top:** keep (or protect) the 2–3 bullets with hard
numbers or framework-ownership signal; drop generic process bullets
("established meetings", "enhanced documentation", "coordinated across teams")
before quantified ones. The scorer only ranks — you confirm against the JD.
And JD alignment outranks recency: when a most-recent-role bullet and an
older-role bullet are equally JD-aligned, the hard cap and readability
decide — not which role is newer.

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

Still a few lines over? Trim the oldest roles' Tools lines and drop blank
spacers — see [docs/api.md](docs/api.md) for TOOLS LINES THAT WRAP
budgets, `squeeze_resume.py`, and the `render_pdf.sh` verification render.

**Readability spacing — lowest priority, only when there is room.** After
every cut is placed and the measure shows the last page at/below target
with slack, add one blank spacer paragraph between roles — measure prints
**SPACER OPPORTUNITIES** with the boundaries that lack the pause. Fixed
priority order: (1) JD-aligned work experience, (2) the page target,
(3) this spacing — when content or pages need room, the spacers go first.

### 9. Fix grammar and typos in the same pass
Common catches: `to improving` → `improving` (infinitive),
`companies goal` → `company's goal`, `HIPPA` → `HIPAA`, `evangalist` →
`evangelist`, `testzing` → `testing`, `Github` → `GitHub` (official casing).
Don't rely on spellcheck for these — grep the text.

**Re-read every paragraph you generated — the Summary first.** Before
declaring the build done, dump each `set_text`-rewritten paragraph with
`docx_edit.py "<docx>" <idx> --full` and verify it reads clean. The Summary
is the highest-visibility text; read it twice. The validator's TEXT
INTEGRITY section (non-ASCII mangling, doubled punctuation, doubled
words) catches the mechanical classes; the re-read catches everything
else — awkward phrasing, missing words, wrong tense.

**Punctuation rule — periods and commas only.** In the Summary and
job-history prose, never use em dashes (`—`), double hyphens (`--`),
semicolons (`;`), colons (`:`), or ellipses (`...` or the `…` character).
Rejoin with a period (split into a new
sentence) or a comma instead. **Single hyphens are fine** — they appear in
compound words (`test-automation`, `end-to-end`, `CI/CD`) and are never
flagged by the validator. En dashes are only allowed in date ranges
(`01/2023 – 12/2024`); in prose, treat them like em dashes (replace with a
period or comma). Exempt from the rule: structural lines (company headers,
job titles), non-role sections (Technical Proficiencies, Certifications,
Education), and the Tools line's `Label: values` colon — the colon there
separates a bold label from a value list, it is not prose punctuation.

### 10. Save the tailored copy (as .docx, the working format)
Write to `<userName> Resume - <Target>.docx` (drop "Master" from the
master's name). Never overwrite the master.
**The deliverable gate runs at save time.** A tailor script's `save(..., src=SRC)`
validates BEFORE writing: a state that would fail validation is never
written, and the stale master copy is removed — nothing to convert by hand.
Approval tokens go in `RESUME_VALIDATE_ARGS` (same env the render gate
reads). Tool-internal saves and master writes are exempt.
The `.docx` is the working file for the session — iterate on it while tuning
the rendered PDF, then delete both after the resume is submitted. The master
is the permanent artifact; tailored copies are temp files scoped to the
session that created them.

### 11. Render the final PDF and verify
The `.docx` is the editing format; **the `.pdf` is the deliverable** — render and
verify with `render_pdf.sh`. See [docs/api.md](docs/api.md) for the full
render command, `--target-pages`, `RESUME_VALIDATE_ARGS`, and approval-token
rules.

`render_pdf.sh` **validates first** (runs `validate_resume.py`): it refuses to
render on blocking errors — orphan content, unapproved whole-role elimination,
or Education dropped against a degree-requiring JD. Fix the errors, then render.
The seniority gate runs unconditionally; the education gate runs only with
`--jd`.

**Fix tool bugs in the session that finds them.** If a script misbehaves or
contradicts its documented behavior, do not route around it: fix the script and
add a regression test in the same session (then continue the tailoring run on
the fixed tool). A workaround leaves the bug armed for the next session.

**Verification is TEXT-ONLY — never render pages to images.** This harness
reads no images; the text path covers what a visual check would:
`render_pdf.sh --verbose` prints the page-boundary map and last-page tail,
and `measure_resume.py` prints the page-fill table with widow/underfill
detection.

**Final human review (what the tools can't judge).** After the last render,
re-read the full `--prefixes` dump top-to-bottom once: every kept bullet still
serves the JD, whole-role removals still read as a coherent timeline, the top
title's level matches the JD's title (Step 4), and the Summary's claims still
match what the reader sees. Years-vs-timeline is
automated (`validate_resume.py`); JD-fit judgment of kept bullets is not — that
stays human. The post-build measure run's **JD-FIT AUDIT** narrows where to
look: any OFF-JD or weak-match bullet it lists gets cut or shortened even
when the page target is met, or kept with a one-line reason tied to the JD.

If it overshoots the target, **compress one more older-role bullet** and
re-render until the last page is full (the `.pdf` is the deliverable; the `.docx` is
session-temp source — see Step 10).

### 12. Fold user-confirmed experience into the master
The session is NOT done when the PDF renders. Any fact the user confirmed
that landed in the deliverable — a tool with no prior host (BrowserStack),
an experience the resume compressed away (LLM prompt testing, contract
testing), a theme they stated ("event-driven at every position") — goes
back into the master so every future target inherits it. The master is
the data pool; a fact that lives only in a per-target script is lost to
the next run. **Do not wait for the user to remember this step** — one
session ended the deliverable summary and the user had to prompt the
fold themselves.

The fold is strictly ADDITIVE: new bullets (`clone_after`), proficiency
line additions, and in-place appends (`--set-text`/`--append-after`) —
never removals or replacements of master text. Run it AFTER the per-target
script is final (a fold rewrites master text and invalidates the script's
`find_p` prefixes); the next tailor re-run detects the changed master
(`MASTER CHANGED:` auto-strict) and must come up green — new master
bullets whose evidence already lives in kept, rewritten bullets join that
role's drop list. See the Assets section above for the full ordering and
the user-edit precedence rule.

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

**Soft-skill claims are the user's word, evidenced by their history.** The
never-fabricate rule governs tools and employers. Communication,
leadership, and stakeholder management are different: the master's
presented/demoed/led/mentored/trained bullets ARE the evidence (Step 2's
inference rule), and the user's explicit statement ("my communication was
excellent at every position") is the authority for the literal adjective.
Declining to state a skill the user has confirmed — or re-asking after
they confirmed it — is over-caution that costs round-trips and leaves JD
lines flagged for no reason.

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
| Reading "no unprotected bullet to give" as a dead end while the most-recent role carries off-JD content | JD-matching false-positives on generic terms — read the TOP-ROLE PROTECTED BULLETS list (matched term per bullet) and override weak matches deliberately; that is the sanctioned top-role trim, not hand-picking (Step 8) |
| Running squeeze in apply mode on the tailored .docx and then folding cuts back into the script by hand | Harvest with `--plan-only` BEFORE the script's first run — same loop, same fold-back block, file untouched (Step 8) |
| Cutting only job bullets — leaving off-JD proficiencies/certs while JD-matched bullets die | Cuts span the WHOLE resume: check measure's TOP-BLOCK RECLAIM CANDIDATES and the Tools lines before cutting another JD-matched bullet (Step 8) |
| Pruning only the oldest roles while the most-recent role keeps 15+ bullets | The hard per-role cap (8) applies to EVERY role — check the DROP PLAN's weak-match (cuttable) listing for the top role (Steps 6, 8) |
| Leaving an under-cap role unpruned because the page math closed | Below the cap, pruning is JD-driven, not page-driven: the JD-FIT AUDIT lists OFF-JD/weak bullets per role — cut or shorten them even on target, stub a mostly-irrelevant role at 1 bullet (Step 8) |
| Treating a proficiencies/Tools-line host as proof of a JD ask | JD REQUIREMENT COVERAGE prints [weak] for non-bullet hosts — weave the skill into the bullet where it was used (Step 5); [UNCOVERED] means demonstrate it or raise the gap, never fabricate |
| "Keep N" with a drop list that doesn't add up | intended keep + len(drop list) == the role's master bullet count (23 − 16 = 7, not 8); a built role whose count differs from intent is a MISS to fix, not a counting convention (Step 8) |
| Carrying the master measure's per-role budgets into the build | The plan's WHICH transfers; its HOW MANY is derived from the measured state and changes with your content edits — re-run measure on the build (Step 8, practice #2) |
| Cutting a bullet because the role is short, or keeping one because it is recent | Time-in-role is never a cut signal and never an exemption — JD alignment decides first, readability second, tenure/recency only as tiebreakers (Steps 3, 8) |
| Trusting a JD-matched (kept) listing that protected everything | A term matching half a role's bullets is shown as `[weak: term]` and protects nothing; specific tech nouns stay strong — read the weak-match (cuttable) listing before calling a role a dead end (Step 8) |
| Dropping an interior role and leaving a timeline gap | Check the plan's gap warning; cut from the oldest role instead, or restore a lean stub (header/title + strongest bullet) of the dropped role (Step 8) |
| Passing `find_p(ps, ...)` results into `drop()`/`drop_role()` | Works now — the element's own text is derived as the prefix (`save()` prints one summary line if element-form was used). Still prefer pasting the DROP PLAN's `find_p` lines verbatim: the string is the documented form (Helper library) |
| Iterating Tools-line trims because a trimmed line still wraps | Rare now: TOOLS LINES THAT WRAP reports the MEASURED budget per line ("value is N chars, wraps after ~M — cut ~N-M chars"), so the first trim lands. Trim to the reported budget, not a tool count — the proportional font makes "~8 tools" unreliable (Step 8) |
| Inflating verbs to match the JD ("designed from scratch" for a refactor) | Keep verbs truthful — see Accuracy |
| Re-asking for communication/leadership evidence the user already confirmed, or refusing to state a soft skill their bullets demonstrate | Soft-skill asks are covered by action-verb evidence (presented/demoed/led/mentored/trained); one user confirmation covers every role; the literal adjective only with their stated authority (Steps 2, 8; Accuracy) |
| Ending the session at the rendered PDF without folding confirmed experience back into the master | Step 12 is part of the workflow — every user-confirmed fact lands in the master (additively) before the session closes |
| Storing the JD in /tmp | Persist it as `jd_<target>.txt` in the skill root (Step 1) — every tool and the re-run instructions reference that path across sessions |
| Inserting a Core Strengths/Top Skills section between Summary and Technical Proficiencies | Don't — weave skills into role bullets (Step 5) |
| Headline still says "Staff" against a less-senior JD title | Rewrite the top title to the JD's title and level its summary echo (Step 4) — the first line is what the screener compares |
| Appending bullets when content overlaps an existing one | Merge (`merge_into`) — appending blows the page budget (Step 6) |
| Overwriting the master resume | Write to `<userName> Resume - <Target>.docx` — never the master filename (Step 10) |
| Keeping Education when the degree isn't evidence for the JD | Evaluate the drop/keep predicates (Step 3.4) — a BA vs an engineering JD is a 3-line drop |
| Reading a clean render (no `--jd`) as education-clause clearance | The education gate runs only with `--jd`; the seniority gate always — render_pdf.sh NOTEs when the education gate did not run (Step 11) |
| Relying on spellcheck for proper nouns | Grep the text for `GitHub`, `HIPAA`, etc. (Step 9) |
| Punctuation in prose (em dash, semicolon, colon, ellipsis) | Periods and commas ONLY — no em dashes, double hyphens, semicolons, colons, or ellipses (`...`); split into a new sentence or use a comma. The Tools line's `Label: values` colon is the one exempt structural colon (Step 9) |
| JD asks for fewer years than the candidate has | Offer Step 3 seniority alignment up front and record approval (`--seniority-approved`) — the render blocks without it. The token needs the user's authority: their chat reply or pre-authorization in the request; never pass it on your own |
