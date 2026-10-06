# Job Search Workflow — Design

**Date:** 2026-10-05
**Status:** Approved design (pending user spec review)
**Type:** New workflow (`job-search/`) + scoped change to `resume-tailoring/` (unattended mode)

## Overview

A skill-driven workflow that searches configured job sites for postings meeting
configured criteria, classifies each posting into pay tiers, records every
disposition in a reviewable ledger, and dispatches resume-tailoring runs for
approved mid-tier postings via headless pi sessions.

Each invocation: fetch → deterministic filter → one judgment session →
report → interactive approval → tailoring dispatch. The user corrects
dispositions in session; corrections update the criteria and are recorded.

## Goals

- Search an editable, user-private list of job-board and company-portal URLs
- Classify postings into tiers by pay, gated by relevance and a role-based
  ethics rule
- Report preferred-tier postings for manual application; propose acceptable-tier
  postings for automated resume tailoring behind a hard interactive approval gate
- Keep an append-only ledger of every disposition (eval surface) and a
  rewritten human-readable decision file (review surface)
- Exclude postings already marked applied
- Run resume-tailoring headlessly with agent gates (no user pauses) when
  dispatched from this workflow, without changing direct-invocation behavior
- Keep the committed repo fully generic: no personal thresholds, criteria text,
  site lists, dispositions, or credentials in versioned files

## Non-goals (explicitly out of scope)

- Scheduling/cron — manual invocation only
- Notifications (email/desktop) — console + files only
- Decision caching — early mode re-judges every fetched posting every run
  (criteria expected to be tuned; cache added later only if cost demands it)
- Schedule/timezone violation checks — dropped (US-remote site filters make
  overnight testing roles rare to none; YAGNI)
- State-residency restriction filtering
- Browser automation for auth — cURL-export + cookie-jar only
- Agent-extract fallback for unparseable sites — schema slot reserved,
  implemented only when a real site needs it
- "Since last successful run" date window — strict literal 24 hours only
  (option may be added later without restructuring)

## Privacy model (public/private split)

| Committed (generic) | Gitignored (personal) |
|---|---|
| `config.example.toml` — every knob as a placeholder with example values | `config.toml` — real thresholds, ethics-rule text, resume paths |
| `sites.example.toml` — fictional example entries per adapter type | `sites.toml` — the user's real site URLs and adapter assignments |
| `scripts/` + synthetic `scripts/fixtures/` | `state/` — `ledger.jsonl`, `decisions.md`, run logs |
| `SKILL.md`, `README.md` | `auth/<site>/curl.txt`, `auth/<site>/cookies.txt` (mode 600) |

Example values in committed files are illustrative only. The root `.gitignore`
gains patterns for `job-search/config.toml`, `job-search/sites.toml`,
`job-search/state/`, and `job-search/auth/`.

**Testing rule:** no personal data anywhere in committed test code or fixtures —
no real company names, titles, employment dates, resume content, or captured
live pages. Fixtures are purpose-built synthetic samples with self-describing
names; test names state what they verify.

## Architecture & data flow

```
sites.toml ──> fetch.py (per-site adapters, sequential, polite delays)
                 │  normalized postings (schema below)
                 ▼
              dedup + strict-24h + applied-exclusion      (deterministic)
                 ▼
              JD text fetch for surviving candidates      (deterministic)
                 ▼
              judge.py builds prompt (criteria from config.toml
                + resume text dumped once per run + postings + JD text)
                 ▼
              one headless `pi --mode json -p ...` judgment session
                 ▼
              JSON validation + consistency lint ──> append events to ledger
                 ▼
              report.py: console report + rewritten decisions.md
                 ▼
              ┌─ preferred ──> listed only ("apply manually, then mark-applied")
              ├─ acceptable ─> proposed auto-tailor list
              │                  HARD GATE: interactive user approval
              │                  → dispatcher: ≤ MAX_PARALLEL_TAILORING sessions,
              │                    FIFO queue, outcomes appended to ledger
              └─ unacceptable / excluded / review ─> listed with rationale
```

The run is agent-driven via `SKILL.md` inside an interactive pi session (the
approval gate and correction loop require the user).

## Components

### 1. Configuration (`config.toml` / `config.example.toml`)

- `preferred_min` (int, USD/year) — example: `150000`
- `acceptable_min` (int, USD/year) — example: `90000`
- `hours_per_year` (int) — default `2080`; hourly pay × this = annualized
- `currency` — `USD` only (non-USD postings excluded)
- `relevance_profile` — path to the master resume `.docx` (plus optional
  LinkedIn export path); dumped to text once per run for the judgment prompt
- `relevance_domains` — text: core (testing/QA) and adjacent domains
  (CI/CD, DevOps, AI, release engineering, developer advocacy/enablement)
  and the strong-resume-match rule
- `ethics_rule` — text: the role-based exclusion rule the agent applies
  (example placeholder: "exclude roles that directly contribute to [category],
  as configured"; the real rule text is personal and lives in config only)
- `max_parallel_tailoring` (int) — default `3`
- `criteria_version` is not stored; it is computed as a hash of the criteria
  block (thresholds + relevance + ethics) and stamped on every ledger event,
  so decision diffs across criteria tweaks are attributable

### 2. Sites & adapters (`sites.toml` / `sites.example.toml`)

Per-site entry: `name`, `url`, `adapter`, `auth` (`none` | `curl-feed`),
optional `notes`. Site URLs are expected to carry the site's own:

- **US-remote filter** — anything returned is trusted as remote and workable
  from the user's US location; the agent performs zero remote re-derivation
- **24h date filter** where the site supports one (e.g. last-24h params)

Adapter classes (platform-level, reusable across companies):

| Adapter | Access | Auth |
|---|---|---|
| `workday` | public JSON jobs API | none |
| `phenom` | `/widgets` JSON API | none |
| `ashby` | public posting API | none |
| `greenhouse` | public boards API | none |
| `eightfold` | public XHR JSON | none |
| `nextjs-embed` | `__NEXT_DATA__` embedded JSON | none |
| `linkedin-guest` | guest search endpoint (works unauthenticated today) | none; fallback `curl-feed` |
| `indeed-curlfeed` | reconstructed from saved cURL exports | `curl-feed` |
| `html-generic` | reserved slot for agent-extract fallback | n/a until implemented |

Each adapter: (a) lists postings with dates and pay-when-available;
(b) fetches JD detail text. Adapters run sequentially with polite delays (default 1–2 seconds between
requests to the same site, configurable);
per-site failures isolate (reported; other sites proceed).

Deterministic guards at run start:

- A `sites.toml` entry whose URL lacks a remote+US filter → warning; that
  site's postings are flagged `review`, not silently trusted
- Date confidence: `timestamp` (payload date, strict `<24h` evaluated),
  `url-filter` (24h filter baked into the URL, trusted), or `none`
  (→ postings flagged `review`)

### 3. Posting schema (normalization contract)

```json
{
  "posting_id": "<source>:<external-id>",
  "source": "linkedin",
  "url": "https://...",
  "jd_url": "https://...",
  "company": "Example Corp",
  "title": "Staff Software Engineer in Test",
  "location": "US Remote",
  "posted_at": "ISO8601 or null",
  "date_confidence": "timestamp | url-filter | none",
  "pay_raw": "$160,000 - $190,000/yr",
  "fetched_at": "ISO8601"
}
```

`posting_id` is the canonical dedup key (URL query params stripped from the
id source). Remote is not a field — it is trusted from the site filter.

### 4. Judgment layer (one headless session per run)

**Input:** criteria rendered from `config.toml`, resume text (deterministic
docx→text dump once per run), candidate postings with JD text.

**Per-posting output:**

```json
{
  "posting_id": "linkedin:4476100529",
  "decision": "preferred | acceptable | unacceptable | excluded | review",
  "reason": "none | pay_below_threshold | not_relevant | ethics",
  "pay": {"seen": true, "top": 190000, "annualized": 190000,
           "basis": "range_top | point | hourly_x2080 | none"},
  "rationale_short": "one line for the report"
}
```

**Pay rules** (deterministic where numeric, agent-parsed where text):

| Posting says | Tiering basis |
|---|---|
| Range `$A - $B` | top of range (`$B`) |
| Single figure | that figure |
| Hourly rate | rate × `hours_per_year` |
| "Up to `$X`" | max = `$X` |
| No pay listed | **acceptable** (tailoring candidate) |
| Non-USD | excluded |

**Relevance** is a hard gate that outranks pay: an irrelevant posting is
`excluded` regardless of salary. The agent judges fit freely (non-determinism
accepted); anything not easy is `review`.

**Ethics** is role-based, from the configured rule text: the agent judges
whether the role *directly contributes* to the excluded categories;
employer type is evidence, not verdict.

**Consistency lint** (deterministic, post-session; only fires when pay and
the decision genuinely conflict):

- `annualized ≥ preferred_min` and `decision = acceptable` → contradiction
- `annualized < acceptable_min` and `decision ∈ {preferred, acceptable}` →
  contradiction

(An `excluded` posting with high pay is *not* a contradiction — relevance
and ethics legitimately outrank pay.) Contradictions are marked `review`
with a lint note and surfaced in the report. Malformed session JSON → one
retry → the run fails loudly (deterministic fetch results are not corrupted;
the user re-invokes).

### 5. Ledger & decision files

`state/ledger.jsonl` — append-only, one event per judgment, correction,
status change, or tailoring outcome:

```json
{"ts": "...", "run_id": "...", "posting_id": "...", "url": "...",
 "company": "...", "title": "...", "event": "judged | corrected | marked-applied | tailoring-queued | tailoring-succeeded | tailoring-failed",
 "decision": "...", "reason": "...", "rationale_short": "...",
 "criteria_version": "..."}
```

Current state per posting = latest event. Applied-exclusion: a posting whose
latest status is applied never appears in results again.

- `state/decisions.md` — rewritten each run (and on corrections); mirrors the
  console report with fuller rationale. The review/eval surface.
- `scripts/ledger.py` CLI: `mark-applied <posting_id|url>`,
  `retry-tailor <posting_id>`, `show <posting_id>`
- Early mode: every fetched posting is re-judged every run (no cache
  suppression); the schema supports adding a cache later without migration

**Correction loop (in session):** the user disputes a disposition → the agent
appends a `corrected` event → updates the criteria text in `config.toml`
(new `criteria_version`; skill file if the change is structural) → re-judges
just that posting → re-renders `decisions.md`. The ledger retains old→new.

### 6. Dispatch: approval gate + tailoring

1. Judgment produces the acceptable-tier proposal list
2. **Hard gate:** the user approves interactively ("all" / "except N" /
   by number). No tailoring session starts before approval
3. Per approved job: write `resume-tailoring/jd_<target>.txt` with
   `Posting URL: <url>` as line one (resume-tailoring's established
   convention; `<target>` sanitized), then spawn
   `pi --skill ./resume-tailoring/SKILL.md -p <prompt>` with
   `RESUME_UNATTENDED=1`
4. Dispatcher: at most `max_parallel_tailoring` concurrent sessions (default
   3; older hardware), FIFO queue for the rest, per-session outcomes appended
   to the ledger
5. Failure → job listed `tailoring-failed`, re-runnable via
   `retry-tailor <posting_id>`; never auto-retried
6. Outputs land in `resume-tailoring/` under its existing naming and
   gitignore conventions

**Scoped change to `resume-tailoring`:** an unattended mode keyed on the
`RESUME_UNATTENDED` environment variable. Set (only ever set by this
workflow's dispatcher): the session supplies approval tokens itself
(e.g. `--seniority-approved` via `RESUME_VALIDATE_ARGS`), makes judgment
calls itself, and routes anything it cannot decide back to the job's
`review` state in this workflow's ledger instead of pausing. Unset:
resume-tailoring behaves exactly as today (user-gated). Direct invocation
is unchanged.

### 7. Report (console)

Run header (run_id, `criteria_version`, sites ok/failed), then:

- **Preferred** — title, company, pay, URL, rationale, "apply manually, then
  `mark-applied`"
- **Acceptable (proposed for auto-tailor)** — the approval-gate list
- **Review** — postings the agent couldn't call, with what's unclear
- **Excluded / Unacceptable** — grouped one-liners with reasons
- **Failed sites** — with per-site auth re-export instructions when 401/403
- **Tailoring queue status** — running/queued/outcomes

`decisions.md` is the superset of the console report.

### 8. Auth (cURL-export + cookie-jar only)

The `ats_check.py` pattern, generalized: per-site `auth/<site>/curl.txt`
(saved cURL exports from a logged-in browser session), cookie jar rotation,
CSRF re-derivation from the jar where needed. On 401/403 the report names
the site whose exports need re-creation. Files are mode 600 and gitignored.
LinkedIn uses the guest endpoint while it works; the curl-feed is its
fallback and Indeed's required path.

## Error handling

- Per-site isolation: fetch/parse/auth failure on one site never aborts the run
- 401/403 → site marked failed with re-export instructions
- Judgment session failure → retry once → loud run failure; nothing partial
  written to the ledger
- Tailoring session failure → `tailoring-failed` event; manual `retry-tailor`
- All state transitions append-only; a corrupted run never rewrites history

## Testing

Offline unittest suite (repo standard; no network):

- Pay tiering — table-driven: range top, point, hourly×`hours_per_year`,
  "up to", missing→acceptable, non-USD excluded
- Ledger — dedup, applied-exclusion, current-state derivation, correction
  events, criteria_version stamping
- `decisions.md` rendering — mirrors report content, full rationale
- Consistency lint — both contradiction classes
- Dispatcher — parallel cap, FIFO order, failure handling (mock sessions)
- Adapter parsers — pinned against hand-authored synthetic samples shaped
  like each platform's payload; never captured live pages
- Config guard — sites lacking remote/US filters flagged
- Fixtures: `scripts/fixtures/` (synthetic, self-describing) plus a synthetic
  `sample_profile.txt`; the real resume path exists only in gitignored config

## File map

```
job-search/
├── SKILL.md                  # runbook: steps, approval gate, correction loop
├── README.md                 # public setup, placeholder model, privacy
├── config.example.toml       # committed placeholders
├── sites.example.toml        # committed fictional entries per adapter
├── scripts/
│   ├── fetch.py              # adapters + normalization + run-start guards
│   ├── judge.py              # prompt build, session spawn, lint, validation
│   ├── report.py             # console + decisions.md
│   ├── dispatch.py           # approval-gate consumer, queue, sessions
│   ├── ledger.py             # append/query CLI (mark-applied, retry-tailor)
│   ├── profile_dump.py       # docx → text once per run
│   └── test_*.py             # offline suite
└── (gitignored) config.toml, sites.toml, state/, auth/
```
