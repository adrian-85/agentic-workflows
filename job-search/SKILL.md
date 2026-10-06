---
name: job-search
description: Search configured job sites for last-24h US-remote postings, classify them by pay/relevance/ethics, keep an append-only disposition ledger, and dispatch headless resume-tailoring runs for approved mid-tier jobs. Use when the user asks to run the job search, review dispositions, correct filtering, or mark applications.
---

# Job Search

Deterministic fetch + one judgment session per run. Personal values
(thresholds, criteria text, sites, ledgers, credentials) live ONLY in
gitignored files — never commit them or echo them into committed files.

## Step 1 — Verify configuration

`job-search/config.toml` and `job-search/sites.toml` must exist (copy from
`config.example.toml` / `sites.example.toml` if missing and stop: the user
fills them in). Each sites.toml URL must carry the site's own remote+US
filter (and its 24h date filter where supported) — the run warns and flags
postings `review` when a URL lacks a remote filter.

## Step 2 — Run the search

From `job-search/`:

```bash
python3 scripts/run.py search
```

This fetches every site (failures isolate), gates (applied-exclusion,
strict 24h, remote guard), judges every candidate in one headless session,
records judged events, and prints the console report. `state/decisions.md`
is rewritten with the full detail (the review surface). If the session
output is invalid twice the run fails loudly — re-invoke; nothing partial
reaches the ledger.

## Step 3 — Present the approval gate (HARD GATE)

Show the report's ACCEPTABLE section and ask the user to approve tailoring:
"all", "except <ids>", or explicit ids. **Do not start any tailoring
session before an explicit user reply.** REVIEW-section postings are the
user's to inspect and rule on — see the correction loop below.

## Step 4 — Dispatch approved tailoring

```bash
python3 scripts/run.py approve <posting_id...|all> [--except <posting_id>...]
```

Runs headless resume-tailoring sessions (`RESUME_UNATTENDED=1`, agent-gate
mode) — at most `max_parallel_tailoring` concurrent (default 3), FIFO
queue, no auto-retry. Report the per-job outcomes; failures are re-runnable
with `python3 scripts/ledger.py retry-tailor <posting_id>`.

## Step 5 — Preferred-tier reminder

For PREFERRED postings remind the user: apply manually, then
`python3 scripts/ledger.py mark-applied <posting_id-or-url>`. Applied
postings never resurface.

## Correction loop (when the user disputes a disposition)

1. Append a correction event so the eval trail keeps old→new:

```bash
python3 -c "import sys; sys.path.insert(0, 'scripts'); import ledger; \
ledger.append_event('state', {'posting_id': '<id>', 'event': 'corrected', \
'decision': '<new decision>', 'reason': '<reason>', \
'rationale_short': '<why>'})"
```

2. Fix the criteria: edit the relevant text in `config.toml`
   (`[criteria]` or `[pay]`). This changes `criteria_version` — every
   later judgment is attributable to the new criteria.
3. Re-judge just that posting (fetch already ran; reuse state/candidates):

```bash
python3 -c "import sys; sys.path.insert(0, 'scripts'); import json, run, \
judge, config; from pathlib import Path; cfg = config.load_config(\
'config.toml'); c = run._load_candidates(Path('state')); posting, jd = \
c['<id>']; posting.jd_text = jd; js = judge.run_judgment(cfg, [posting], \
'<resume text via scripts/profile_dump.py>'); judge.record_judgments(js, \
[posting], Path('state'), cfg, 'correction')"
```

4. Re-render `state/decisions.md` (rerun `run.py search` next invocation
   re-renders it from the ledger; or rebuild via `report.py`).

Early mode re-judges every fetched posting every run — criteria tweaks
take effect on the next search with no extra machinery.

## Privacy (non-negotiable)

`config.toml`, `sites.toml`, `state/`, `auth/` are gitignored. Never quote
their contents into committed files, tests, or docs. Example files carry
placeholders only.
