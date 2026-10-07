# Job Search

A skill-driven workflow that searches configured job sites for fresh
(<24h) US-remote postings, classifies each by pay tier behind relevance
and role-based ethics gates, records every disposition in an append-only
ledger, and — behind a hard interactive approval gate — dispatches
headless [resume-tailoring](../resume-tailoring/) runs for approved
mid-tier postings.

The committed repo is fully generic: every personal value (pay
thresholds, criteria text, site list, dispositions, credentials) lives in
gitignored local files. A clone ships placeholders only.

## How it works

```
sites.toml → fetch (per-site adapters, polite delays, per-site isolation)
          → deterministic gates (applied-exclusion, strict 24h, remote guard)
          → one headless pi judgment session (pay / relevance / ethics)
          → console report + rewritten state/decisions.md
          → HARD GATE: user approves the auto-tailor list
          → dispatcher: ≤ max_parallel_tailoring headless sessions, FIFO queue
```

- **Pay tiers** (values from your `config.toml`): a range tiers by its
  TOP figure; hourly annualizes as rate × `hours_per_year` (default 2,080);
  "up to $X" means max = $X; **no pay listed → the acceptable tier**;
  non-USD excluded.
- **Relevance outranks pay** — an irrelevant posting is excluded at any
  salary. Not-easy judgments surface as `review` for the user, never
  silent cuts.
- **Every disposition is a ledger event** (append-only `state/ledger.jsonl`)
  with a `criteria_version` hash, so filtering decisions are auditable and
  criteria tweaks are attributable. `state/decisions.md` is the rewritten
  human-readable view.
- **Strict literal 24-hour window**; skip a day and that day's postings
  are gone (a deliberate trade; a "since last run" option can be added
  later without restructuring).

## Directory layout

| File | Purpose |
|---|---|
| `SKILL.md` | The runbook: search → approval gate → dispatch → correction loop |
| `config.example.toml` | Placeholder configuration (copy to `config.toml`) |
| `sites.example.toml` | Placeholder site entries per adapter (copy to `sites.toml`) |
| `scripts/run.py` | Stage runner: `search` and `approve` commands |
| `scripts/fetch.py` | Sites loader, adapter registry dispatch, gates, isolation |
| `scripts/adapters/` | Platform adapters (see table below) |
| `scripts/judge.py` | Judgment prompt, headless session, validation, consistency lint |
| `scripts/pay.py` | Deterministic pay parsing + tiering |
| `scripts/ledger.py` | Append-only ledger + CLI (`mark-applied`, `retry-tailor`, `show`) |
| `scripts/report.py` | Console report + `decisions.md` rendering |
| `scripts/dispatch.py` | JD files, bounded-parallelism tailoring queue |
| `scripts/profile_dump.py` | Master `.docx` → text for the judgment prompt |
| `scripts/auth.py` | Saved-cURL session replay (curl-feed sites) |
| `scripts/test_*.py` | Offline unittest suite (synthetic fixtures only) |

## Adapters

| Adapter | Platform | Access | Auth |
|---|---|---|---|
| `greenhouse` | Greenhouse boards | `boards-api.greenhouse.io/v1` public API | none |
| `ashby` | Ashby boards | `api.ashbyhq.com` posting API | none |
| `workday` | Workday tenants | `wday/cxs` search API; relative dates gate the 24h window in-adapter | none |
| `epam` | EPAM careers | `__NEXT_DATA__` embedded jobs | none |
| `linkedin-guest` | LinkedIn | guest search endpoint; UI URL converted automatically | none (curl-feed fallback) |
| `indeed-curlfeed` | Indeed | saved-cURL session replay | `curl-feed` |
| `shopify` | Shopify careers | careers sitemap + turbo-stream detail pages; lastmod gates the 24h window in-adapter | none |
| `phenom` | Phenom CareerConnect | `/widgets` refineSearch API + embedded jobDetail DDO; URL query params become selected_fields (facet names vary by tenant, e.g. `remote`, `flexibilityStatus`) | none |
| `pcsx` | pcsx career sites | `/api/pcsx/search` JSON + schema.org JobPosting detail; URL carries the remote filter | none |
| `html-generic` | *(reserved)* | agent-extract fallback for unparseable sites | TBD |

Deferred platforms (no verifiable plain-HTTP contract as of 2026-10-05):
widget-gated career portals and client-rendered JS shells with no public
JSON. Sites on those surface as isolated per-site failures until the
`html-generic` slot ships.

Sites whose URL lacks a remote+US filter get their postings flagged
`review` — the fetch layer never silently trusts an unfiltered site.

## Quick start

1. Copy `config.example.toml` → `config.toml`; fill in thresholds,
   resume path, relevance domains, ethics rule, parallelism.
2. Copy `sites.example.toml` → `sites.toml`; list your sites with their
   adapter and their search URL **including the site's remote+US filter
   and (where supported) last-24h params**.
3. Run the skill: "run the job search" in a pi session, or directly:

```bash
cd job-search
python3 scripts/run.py search
python3 scripts/run.py approve all --except <posting_id>
```

For curl-feed sites (e.g. Indeed): from a logged-in browser session,
"Copy as cURL" the search request into `auth/<site name>/curl.txt`
(mode 600; gitignored). On 401/403 the report names the site to re-export.

## Requirements

- Python 3.11+ (stdlib only)
- `pi` on PATH (judgment + tailoring sessions)
- `libreoffice`, `pdftotext` (only for the resume-tailoring stage)

## Privacy model

| Committed (generic) | Gitignored (personal) |
|---|---|
| `config.example.toml`, `sites.example.toml` | `config.toml`, `sites.toml` |
| `scripts/` + synthetic `scripts/fixtures/` | `state/` (ledger, decisions, candidates) |
| `SKILL.md`, `README.md` | `auth/<site>/curl.txt` |

Run the suite from `job-search/scripts/`:

```bash
python3 -m unittest discover
```
