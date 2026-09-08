# Resume Tailoring — Tool Reference

Mechanical procedures, commands, and API details extracted from SKILL.md.
SKILL.md contains the judgment (when to act, what to decide); this file
contains the execution (which command, what flag, how to read output).

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

## Reference template

`scripts/tailor_resume.py` is a **generic template** (placeholder content, no company or
recruiter detail) showing the subtractive pattern in order: summary → proficiencies →
role re-anchor → per-role compression → tools trims → spacers → PDF iteration (the
Workflow steps in SKILL.md cover the same pattern in detail). Import only the helpers the
planned edits use — the script is re-run after every revision, and pruning an unused
import mid-iteration costs a full edit-plus-rerun cycle for zero behavior change.

### Do you need a per-target script?

One-shot tailoring can be one-off commands — the `.docx`/`.pdf` are the only
deliverables. Write `scripts/tailor_<target>.py` when you'll **iterate**
(page-count tuning, accuracy fixes, user edits) or re-tailor later: it
re-runs from the untouched master and is a diff-able record of every edit.
**Caveat:** it pins to the master's bullet-text prefixes; when the master is
rewritten, `find_p` prefixes may drift (review warnings, or run with
`DOCX_EDIT_STRICT=1` to fail on any skip).

## Step 3 procedures — Seniority alignment

### Simulation (what-if whole-role drops)

Compute the resulting span BEFORE editing. Pass each whole-role drop
to measure as a what-if — it drops the roles in a temp copy, renders
THAT, and prints the resulting TIMELINE, so the year math is the tool's,
not hand-derived in chat (the file on disk is never modified):

```bash
python3 scripts/measure_resume.py "<Master>.docx" 3 --jd "<JD>.txt" \
    --jd-years <N> \
    --simulate "Acme Corp, Austin, TX" --simulate "Globex, Chicago, IL"
```

Pass `--jd-years <N>` here whenever the JD states a years ask (e.g.
"8+ years"): the TIMELINE is then compared against the real ask at
measure time, not first at render time — this is also what makes the
Education equivalent-experience check give a correct verdict.

With `--jd` the simulation also prints each drop's JD-evidence cost.
A `JD EVIDENCE LOST:` line means: restore that role trimmed to its
JD bullets instead of eliminating it — and expect the restored years
to keep the span above the JD's ask (that is fine; the years carry
the evidence).

### Applying whole-role drops

Apply the drops with `drop_role` — never a hand-rolled helper.
Whole-role removal is a library primitive (`docx_edit.drop_role`): it
owns the block grammar (company header → Tools line + trailing spacer,
boundary paragraph excluded) and handles duplicate job titles with no
anchor. Education goes with `drop_section`. See Common mistakes in
SKILL.md for the failure this replaces.

### Education drop predicates

**Establish mechanically whether the JD requires a degree at all before
applying the predicates below** — grep the JD text for degree language
(`degree`, `Master`, `Bachelor`, `will accept`, `H-1B`). Visa-attestation
boilerplate is easy to misread; the validator is the gate, this grep only
saves the cycle. Then decide by observable predicates, not habit:

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
- **"AND" is not "OR":** an AND construction ("degree AND N years",
  e.g. visa attestation) is a degree REQUIREMENT with no substitution
  path — Education is KEEP regardless of the span. Only an OR
  construction ("degree OR N years") opens the substitution path above.
- Removing Education is a structural change (the Education section heading
  and entries are removed together; `validate_resume.py` treats a resume
  ending at the last role's Tools line as clean). Remind yourself this is
  reversible: the master still has it, and a later JD that needs the degree
  just regenerates from the master.

### Approval tokens

`validate_resume.py` detects whole-role elimination
(visible span ≥2 years shorter than the master) and `render_pdf.sh` blocks the
PDF until the approval is recorded with `--seniority-approved` (Step 11) — you
cannot ship a PDF from a shortened timeline without the approval token.

**The token's authority comes from OUTSIDE you.** Approval is valid only from
(a) the user's reply in this chat, or (b) explicit pre-authorization in the
original request (e.g. "seniority alignment approved" or the user naming the
target span). Passing `--seniority-approved` on your own authority is not a
judgment call — it is a bypass that turns the gate into decoration. Same rule
for `--education-approved`. In a single-turn/autonomous session (the whole task
arrived in one message and no user turn is available): present the proposed span
with the numbers and STOP — the deliverable gate (Step 10) refuses to write the
.docx itself without the token, so there is no file to hand over and nothing to
convert by hand. After the user approves, re-run the tailor script with the
token in `RESUME_VALIDATE_ARGS` (it writes then), then render.

## Step 8 procedures — Compression tools

### Reading measure output

After the content edits (Steps 4–7), run `scripts/measure_resume.py <target.docx> [TARGET_PAGES]`
— it renders once and reports the per-role line cost and the **exact reclaim gap** to the target
page count, so you plan the oldest-role cuts as a batch instead of discovering them
through a cut-render loop. Pass the agreed Step-3 target positionally
(`measure_resume.py <target.docx> 3`) — measuring against the 2-page default
while over it prints a NOTE and over-reports the gap. Use its **BATCH RECLAIM PLAN** (measured
lines-per-bullet from the actual render, oldest roles first) rather than
estimating savings, and read its **page-fill table**: an underfilled page or a
role header stranded as the last line of a page ("WIDOW") will not be fixed by
a line-count budget alone — the WIDOW note names the block to reclaim from (the
content preceding the stranded header); trim those ~2 lines or merge
bullets so the next role starts cleanly at the top of a page.

### Applying the DROP PLAN

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

### Squeezing the residual gap

When only a few lines over after the planned old-role cuts, run
`squeeze_resume.py` (Step 8) to close the residual gap automatically instead
of trimming by hand.

**Harvest the plan with `--plan-only` BEFORE the tailor script's first run.**
Apply mode rewrites the .docx directly — running it on the tailored output
leaves the script unable to reproduce the state, and folding the cuts back
in by hand costs a repair cycle. `--plan-only` runs the identical loop
against a throwaway in-memory copy and prints the same fold-back block
WITHOUT touching the .docx (no backup, no log, no edit):

```bash
python3 scripts/squeeze_resume.py "<Target>.docx" 3 --jd "<JD>.txt" --plan-only
```

(Without `--plan-only`, it backs up to `<docx>.pre-squeeze.docx` and logs
every cut to `<docx>.squeeze.json`; reserve apply mode for a doc you will
NOT regenerate from the tailor script.)

Paste the printed fold-back block (or the DROP PLAN's `find_p` prefix strings)
straight into a `drop(body, [...])` call in the tailor script (never re-derive
them by hand), re-run the tailor script, re-measure once to confirm the gap
closed, then render to verify. This replaces the cut-render-cut guesswork.

### TOP-ROLE TRIM BATCH

When the oldest-first plan cannot close the gap, measure emits a
TOP-ROLE TRIM BATCH (the most-recent role's weakest unprotected bullets, sized
to the residual gap) and, when even that cannot close it, a NOTE saying so —
paste its `find_p` lines into the script's first pass and take the NOTE
back to the user (whole-role drops / JD-matched tradeoffs).

### JD REQUIREMENT COVERAGE

The coverage map matches the JD's extracted terms as **literal phrases**:
a qual line flips to covered only when a kept bullet (or, as `[weak]`, a
proficiencies/Tools line) contains the phrase itself. Concept evidence does
not flip it — "Kafka and MSMQ in a Tools line" does not cover
"event-driven architecture", and adjacent tooling does not cover a named
tool. So when a qual you know is demonstrated still prints `[UNCOVERED]`,
the fix is to host the JD's literal phrase in a truthful bullet — at
AUTHORING time, from the master-measure's list — not to debug the matcher. Self-assessment-adjective qual lines ("Excellent communication, ...")
extract no skill terms and print `[by hand]` with the soft-skill inference
rule — judge them on kept action-verb evidence (SKILL Step 8), never by
chasing the adjective.

### INFERENCE MAP — evidence for no-host JD terms

"No literal host" is not "no evidence": a real session reported six JD
skills as honest gaps (debugging, data management, aws services, UI, LLMs,
Solving Problems) that the user's experience clearly demonstrated — the terms
were lexically invisible, not absent. The INFERENCE MAP is the deterministic
half of the fix: it mechanically gathers candidate evidence so the agent can
judge, rather than declaring gaps prematurely.

**How it works.** For each term in the "JD terms with NO host" list,
`measure_resume.py` searches the master paragraphs (and an optional LinkedIn
dump) via two mechanisms:

1. **Morphological variants** — the term itself, its singular form (each word's
   trailing 's' stripped: `llms` → `llm`), and the hyphen-joined form for
   multiword terms (`customer facing` → `customer-facing`). Matched
   whole-word in the corpus.
2. **Skill-family roots** — an in-code table (`INFERENCE_FAMILIES`) mapping
   term families to related evidence roots. A no-host term matching a family
   key (whole-word) is searched for its family's roots as substrings in the
   corpus. The 7 families cover the session's actual failure modes:

| Family keys | Evidence roots |
|---|---|
| `debug` | debug, triage, root cause, diagnos, resolved, remediat, defect |
| `data management`, `data modeling`, `query tuning` | test data, sql, query, index, data model, etl |
| `aws`, `cloud` | aws, amazon web services, cloud, azure, gcp |
| `ui`, `frontend`, `front end` | web, user interface, frontend, browser, desktop |
| `customer facing` | customer, client, production, incident, stakeholder |
| `problem solving`, `solving problems`, `troubleshooting` | problem, troubleshoot, root cause, resolved, issue |
| `llm`, `genai`, `generative` | llm, prompt, copilot, gpt, claude, openai |

Roots are substring-matched (loose) — `sql` matches `SQL Server`, `index`
matches `indexed` — because these are evidence LEADS, not proof. The agent
judges each candidate's truthfulness before hosting.

**Per-source cap:** up to `_INFERENCE_MATCH_CAP` (2) evidence lines are
printed per source (master, LinkedIn) to keep output scannable.

**Output format:**
```
INFERENCE MAP for no-host terms (deterministic evidence search over the
  master + LinkedIn; judge each candidate against the user's real
  experience before hosting — never fabricate):
  - aws services: CANDIDATE
      master: "Cloud & Containers: AWS, GCP, Azure, Docker, Kubernetes"
      linkedin: "AWS"
  - ontology: NO deterministic evidence — a genuine gap: raise to the
    user, do not fabricate
    CANDIDATE = evidence exists; host the JD's literal phrase in the
    truthful bullet and present the whole map — candidates AND gaps — to
    the user in ONE message (SKILL Step 2).
```

**LinkedIn evidence.** Pass `--linkedin <profile-dump.txt>` (the
`read_profile.sh` output) so the map also searches the LinkedIn export —
the richer source for content the resume compressed away (a real session
justified the Elasticsearch fold from Skills.csv via this path):

```bash
python3 scripts/measure_resume.py "<Target>.docx" 3 --jd "<JD>.txt" \
    --linkedin /tmp/profile.txt
```

Without `--linkedin`, only the master is searched. The map still prints
terms with no evidence as genuine gaps — the flag adds a second evidence
source, it does not change the judgment.

### Readability spacing

After every cut is placed and the measure shows the last page at/below target
with slack (the render/measure Page fill lines), add one blank spacer
paragraph between roles:

```bash
# clone_after with empty text produces a blank line
clone_after(body, find_p(ps, "<a NON-bullet paragraph near the role
boundary, e.g. the Tools line>"), "")
```

Anchoring on a non-bullet paragraph keeps the clone from inheriting bullet
numbering. Then re-measure to confirm the resume still meets the target.
Fixed priority order: (1) JD-aligned work experience, (2) the page target,
(3) this spacing — when content or pages need room, the spacers go first.

Re-run `render_pdf.sh` (compact) to verify — measuring replaces iteration, it
does not replace the final verification render.

## Step 11 procedures — Render and verify

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

**The two gates have different trigger conditions.** The seniority gate runs
unconditionally; the education gate runs ONLY when `--jd` is passed (via
`RESUME_VALIDATE_ARGS`) — `render_pdf.sh` prints a NOTE whenever the
education gate did not run.

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
authority, the deliverable gate has already refused to write the .docx (Step
10) — present the plan, and after the user's reply re-run the tailor script
with the token in `RESUME_VALIDATE_ARGS`, then render.
The two flags are independent: `--jd-years` is an
optional advisory; the gate reads only the approval token.
`--jd-years` is ONLY for a JD that states a number of years. If the
posting names no years ask, do NOT pass it: every span comparison is then
measured against a fabricated ask, producing false *underqualified* verdicts
and a false load-bearing education warning. `validate_resume.py` warns when
`--jd-years` is passed but the JD text states no "N+ years" ask.

**Whole-resume word cap** (SKILL Steps 3/8): the validator counts every
paragraph's alphanumeric tokens and blocks over `MAX_WORDS` (1000) for
tailored resumes — the master input is exempt, like the bullet cap. Override
or disable the threshold with `--max-words <N>` (`--max-words 0` disables);
the same flag works in `RESUME_VALIDATE_ARGS` for the save-time gate. The
cap's authoritative measurement on the RENDERED text is `ats_audit.py`
(below), whose counting strips page furniture a text extractor emits.

## Step 11 procedures — ATS verification (literal phrases + external scan)

The internal matchers are term/concept-based; external ATS screeners match
literal phrases against the rendered text. A resume can pass every internal
gate and lose ATS points (a real session: 9 of 24 hard skills at zero literal
hits, external score DROPPED). Two tools close the gap:

### ats_audit.py — the local ground-truth audit (always run)

```bash
python3 scripts/ats_audit.py "<output>.pdf" --jd <JD.txt> \
    [--phrases-file <f>] [--report-json <report.json>] [--max-words N]
```

Checks, on the pdftotext output of the DELIVERABLE (what a screener parses,
not the .docx): (1) the whole-resume word cap (own count — see the calibration
note in its `_count_words` docstring); (2) with `--jd`, literal hosting of the
JD qualification lines' skill phrases (cue-tail mining: phrases are
extracted only from the text following skill-introducing cues like
"experience in" and "proficiency in", avoiding surrounding prose —
see `_jd_literal_terms` for the full precision rules); zero-host terms mean a
cut killed the last host (Step 8 cut-protection) or the phrase was never
mirrored — host the exact phrase truthfully or raise the gap, never fabricate;
(3) with `--phrases-file` (one phrase per line) or `--report-json` (an external
scan report, below), literal checks of externally supplied phrases — a
skill's `resumeCount` from the report is the authoritative host signal, the
literal check is the fallback. Exit 0 clean, 1 findings, 2 usage/IO error.

IGNORED by rule: the report's contactEmail searchability finding — the
compact hyperlinked contact block is a deliberate design (Step 11, SKILL.md);
never alter the contact block to satisfy a literal text parser.

### ats_check.py — the external scan (when configured)

```bash
python3 scripts/ats_check.py scan "<output>.pdf" <JD.txt> [--out <report.json>]
python3 scripts/ats_check.py check      # validate the saved config, no scan
```

Submits the deliverable (PDF preferred — it is the submitted format) to the
user's ATS scan service, waits for the match report, and saves its JSON next
to the resume (`<resume>.ats-check.json`); feed that back into
`ats_audit.py --report-json` for the authoritative cross-check. The chain is
reconstructed from the user's OWN saved cURL exports in
the skill root's `.ats-check/curl.txt` (four requests: resume upload, job
description, opportunity, report GET) — the tool classifies them by shape,
templates fresh ids, rotates the session cookies through a curl cookie jar,
and re-derives the CSRF header from the jar before every request. No service
specifics are hardcoded; when a scan returns 401/403 the credentials expired —
the user re-exports the four requests from a logged-in browser session and
deletes `.ats-check/cookies.txt` to re-seed. The service dedupes an
identical resume + JD pair (409) and the tool reuses the returned opportunity.
The scan output prints the match rate, the report's wordCount (cross-check
only — its PDF parser inflates counts), and the identified target ATS; the
latter requires the job posting URL persisted with the JD (Step 1).

**Fix tool bugs in the session that finds them.** If a script in this
skill misbehaves or contradicts its documented behavior, do not route
around it: fix the script and add a regression test in the same session
(then continue the tailoring run on the fixed tool). A workaround leaves
the bug armed for the next session.

**Verification is TEXT-ONLY — never render pages to images.** This harness
reads no images, so converting the PDF to PNGs and "viewing" them fails
every time (observed in two sessions). The text path already covers what a
visual check would: `render_pdf.sh --verbose` prints the page-boundary map
and last-page tail, and `measure_resume.py` prints the page-fill table with
widow/underfill detection. Read those, plus `pdftotext` per page if you need
to inspect content placement.
