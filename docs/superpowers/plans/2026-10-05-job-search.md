# Job Search Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. (pi has no subagent dispatch; native execution is the supported path.) Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A skill-driven workflow that searches configured job sites, classifies postings by pay/relevance/ethics, records every disposition in an append-only ledger, and dispatches approved resume-tailoring runs headlessly.

**Architecture:** Deterministic Python pipeline (fetch adapters → dedup/date/applied filters → JD fetch) feeds one headless `pi` judgment session per run; validated judgments append to a ledger that drives the console report, the rewritten `decisions.md`, and — behind a hard interactive approval gate — a bounded-parallelism dispatcher that spawns resume-tailoring sessions with `RESUME_UNATTENDED=1`.

**Tech Stack:** Python 3.13 stdlib only (`tomllib`, `urllib.request`, `zipfile`), `pi -p` headless sessions, repo unittest conventions.

**Spec:** `docs/superpowers/specs/2026-10-05-job-search-design.md` — read it first; this plan argues from it.

## Global Constraints

- Python stdlib only — no third-party packages (spec: repo convention; Python 3.13.5 confirmed).
- `tomllib` for TOML parsing (stdlib, ≥3.11).
- Tests: `python3 -m unittest`, offline, no network. Every test/module lives in `job-search/scripts/`, run from that directory.
- **No personal data in any committed file** — no real companies, titles, dates, resume text, site URLs, thresholds, or captured live pages. Fixtures are synthetic with self-describing names; test names state what they verify.
- Committed example files (`config.example.toml`, `sites.example.toml`) use illustrative placeholder values only.
- pylint: max-line-length 100, fail-on any C/W/R/E/F message (repo `pyproject.toml`). Every task's commit must pass `python3 -m pylint --disable=all --enable=E,W,C,R <files>` — simplest: run repo pylint as CI does.
- Commit style: `job-search: <lowercase description>` (repo convention: `area: description`).
- Polite fetch delays: default 1–2s between requests to the same site (`request_delay_seconds`, default 1.5).
- Date gate: strict `< 24h`. Remote/US: trusted from site URL filters; never re-judged.
- Adapter HTTP goes through an injected `http_get` callable so all parser tests are offline.

## Review Focus

Five input classes the spec implies but task tests might miss — each pinned by a test in the owning task:

1. **Corrupt trailing ledger line** (crash mid-append) → `current_state` skips the partial line, run proceeds. → Task 4 `test_current_state_skips_trailing_partial_line`
2. **Non-USD pay text** (`£50k–£60k`, `€60,000`) → never tiered as USD; `parse_pay` reports `currency != USD`. → Task 3 `test_non_usd_currency_detected_not_tiered`
3. **Judgment JSON with unknown decision value or missing field** → validation rejects, one retry, loud failure. → Task 11 `test_validate_rejects_unknown_decision`, `test_run_judgment_retries_once_then_fails_loudly`
4. **Site URL lacking remote/US filter** → run-start guard flags that site's postings `review`. → Task 5 `test_site_without_remote_filter_flags_review`
5. **Same posting under two URLs** (query-param variants, or two sources) → canonical id dedups. → Task 2 `test_canonical_id_strips_query_params`, `test_dedup_across_sources`

---

### Task 1: Scaffold + config loader

**Files:**
- Create: `job-search/config.example.toml`, `job-search/sites.example.toml`, `job-search/scripts/config.py`, `job-search/scripts/test_config.py`
- Modify: root `.gitignore` (add `job-search/config.toml`, `job-search/sites.toml`, `job-search/state/`, `job-search/auth/`)

**Interfaces:**
- Produces: `load_config(path: str) -> Config` and `criteria_hash(cfg: Config) -> str`; `Config` dataclass with fields `preferred_min: int`, `acceptable_min: int`, `hours_per_year: int = 2080`, `currency: str = "USD"`, `relevance_profile_path: str`, `linkedin_export_path: str | None`, `relevance_domains: str`, `ethics_rule: str`, `max_parallel_tailoring: int = 3`, `request_delay_seconds: float = 1.5`. Later tasks import `Config` from `config`.

- [ ] **Step 1: Write failing tests** in `test_config.py`: `test_example_config_loads` (asserts every Config field populated from `config.example.toml`), `test_missing_required_field_raises` (`relevance_domains` absent → `ConfigError`), `test_criteria_hash_is_deterministic_and_order_insensitive` (same criteria via two equal dicts → same hash; changed `ethics_rule` → different hash), `test_default_values_applied` (hours_per_year 2080, max_parallel_tailoring 3).
- [ ] **Step 2: Run** `python3 -m unittest test_config -v` from `job-search/scripts/` — expect FAIL (module missing).
- [ ] **Step 3: Implement** `config.py`: `@dataclass(frozen=True) Config`, `load_config` via `tomllib`, `ConfigError(Exception)`; `criteria_hash` = sha256 over a canonical `json.dumps(..., sort_keys=True)` of the criteria block (`preferred_min`, `acceptable_min`, `hours_per_year`, `relevance_domains`, `ethics_rule`). Write `config.example.toml` with placeholder values (e.g. `preferred_min = 150000`, `acceptable_min = 90000`, placeholder `relevance_domains`/`ethics_rule` text marked as examples) and `sites.example.toml` with two fictional entries (one `adapter = "greenhouse"`, one `adapter = "indeed-curlfeed"` with `auth = "curl-feed"`) showing remote+US filter params in comments.
- [ ] **Step 4: Run tests** — PASS. Run pylint on new files.
- [ ] **Step 5: Commit** `job-search: scaffold + config loader with criteria hash` (include `.gitignore` change).

### Task 2: Posting model — canonical id, dedup, 24h gate

**Files:**
- Create: `job-search/scripts/postings.py`, `job-search/scripts/test_postings.py`

**Interfaces:**
- Produces: `@dataclass Posting` with schema fields exactly per spec §3 (`posting_id, source, url, jd_url, company, title, location, posted_at, date_confidence, pay_raw, fetched_at`) plus runtime fields `jd_text: str | None = None` and `review_flags: list[str] = field(default_factory=list)`; `canonical_id(source: str, url_or_ext_id: str) -> str`; `dedup(postings: list[Posting]) -> list[Posting]`; `is_within_24h(posted_at: datetime | None, now: datetime) -> bool`.

- [ ] **Step 1: Write failing tests**: `test_canonical_id_strips_query_params`, `test_dedup_across_sources` (same external id from two sources → first wins, second dropped), `test_is_within_24h_boundaries` (23h59m → True; 24h01m → False; None → False), `test_posting_id_format` (`"example-source:12345"`).
- [ ] **Step 2: Run** — FAIL (`postings` missing).
- [ ] **Step 3: Implement** `postings.py`. Canonicalization: `urlsplit` → strip query/fragment → path + optional external id when the adapter supplies one (`linkedin:4476100529` style) — one rule: if `url_or_ext_id` starts with `http`, use scheme://netloc/path; else use as-is.
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: posting model with canonical ids and 24h gate`.

### Task 3: Pay parsing and tiering

**Files:**
- Create: `job-search/scripts/pay.py`, `job-search/scripts/test_pay.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) PayInfo` (`seen: bool`, `currency: str = "USD"`, `top: int | None`, `annualized: int | None`, `basis: str` ∈ `range_top | point | hourly_x2080 | none`); `parse_pay(raw: str | None) -> PayInfo`; `tier(annualized: int | None, cfg: Config) -> str` returning `preferred | acceptable | unacceptable` (spec §4 table: range→top; point; hourly→×`hours_per_year`; "up to"→max; missing→`seen=False` and caller treats as acceptable).

- [ ] **Step 1: Write failing table-driven tests**: `test_range_uses_top` (`"$160,000 - $190,000/yr"` → top 190000, basis range_top), `test_point_figure`, `test_hourly_annualizes` (`"$70/hr"` × 2080 = 145600), `test_up_to_uses_max` (`"up to $120,000"` → 120000), `test_missing_pay_seen_false` (`None`, `""`, `"DOE"`), `test_non_usd_currency_detected_not_tiered` (`"£50,000 - £60,000"` → currency GBP, seen True), `test_k_suffix_expands` (`"$120k - $150k"`), `test_tier_boundaries` (at `preferred_min` → preferred; `preferred_min - 1` → acceptable; `acceptable_min - 1` → unacceptable).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `pay.py`: regex number extraction with `$`/`€`/`£`/USD/EUR/GBP detection, `/hr|/hour|hourly` period detection, k-suffix expansion. No third-party libs.
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: pay parsing with top-of-range tiering`.

### Task 4: Ledger — append-only events, current state, CLI

**Files:**
- Create: `job-search/scripts/ledger.py`, `job-search/scripts/test_ledger.py`

**Interfaces:**
- Produces: `append_event(state_dir: Path, event: dict) -> None` (json line, `ts` + `run_id` auto-filled if absent); `current_state(state_dir: Path) -> dict[str, dict]` (latest event per `posting_id`); `applied_ids(state: dict) -> set[str]`; CLI: `python3 ledger.py mark-applied <id-or-url> | retry-tailor <posting_id> | show <posting_id>` operating on `state/` under the workflow root. Event `event` values per spec §5 (`judged | corrected | marked-applied | tailoring-queued | tailoring-succeeded | tailoring-failed`).

- [ ] **Step 1: Write failing tests**: `test_append_and_current_state_latest_wins`, `test_current_state_skips_trailing_partial_line`, `test_applied_ids_excludes_from_results`, `test_mark_applied_cli_appends_event` (URL input canonicalized to posting_id via `postings.canonical_id`), `test_show_prints_latest_event`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `ledger.py`. Partial-line tolerance: skip a final line that fails `json.loads`.
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: append-only ledger with current-state derivation and cli`.

### Task 5: Fetch framework — sites loader, registry, guards, isolation

**Files:**
- Create: `job-search/scripts/fetch.py`, `job-search/scripts/test_fetch.py`, `job-search/scripts/fixtures/README.md`

**Interfaces:**
- Produces: `@dataclass Site` (`name, url, adapter, auth, notes`); `@dataclass SiteResult` (`site, ok, postings, error`); `@dataclass FetchReport` (`site_results: list[SiteResult]`); `load_sites(path: str) -> list[Site]`; adapter registry `register(name)` decorator, `get_adapter(name)`; adapter contract: `list_postings(site: Site, http_get: Callable) -> list[Posting]`, `fetch_jd(site: Site, posting: Posting, http_get: Callable) -> str`, and `REMOTE_FILTER_PARAMS: tuple[str, ...]` per adapter module; `site_has_remote_filter(site: Site) -> bool`; `default_http_get(url, headers=None, data=None) -> HttpResponse(status:int, body:str)` via `urllib.request`; `fetch_all(sites, cfg, ledger_state, http_get=default_http_get, sleep=time.sleep) -> FetchReport` applying: applied-exclusion (`ledger.applied_ids`), strict-24h gate (`is_within_24h` for `date_confidence="timestamp"`; pass for `"url-filter"`; flag `review` for `"none"`), remote-guard (`site_has_remote_filter` False → all that site's postings get `review_flags` entry), JD fetch for survivors, per-site isolation, inter-request `cfg.request_delay_seconds`.

- [ ] **Step 1: Write failing tests** with a **mock adapter** defined inside the test file (registered as `"mock"`): `test_fetch_all_applies_applied_exclusion`, `test_site_without_remote_filter_flags_review`, `test_url_filter_confidence_passes_without_timestamp` (`date_confidence="url-filter"`, `posted_at=None` → kept), `test_none_date_confidence_flags_review`, `test_site_error_isolates` (mock adapter raises → SiteResult ok=False, other site's postings present), `test_jd_fetched_for_survivors_only`, `test_delay_between_requests` (injected sleep recorded ≥1 call).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `fetch.py` + `fixtures/README.md` stating the synthetic-fixtures-only rule.
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: fetch framework with guards, isolation, and adapter registry`.

### Task 6: Adapters — greenhouse, ashby

**Files:**
- Create: `job-search/scripts/adapters/__init__.py` (re-exports registry from fetch), `job-search/scripts/adapters/greenhouse.py`, `job-search/scripts/adapters/ashby.py`, `job-search/scripts/fixtures/greenhouse_sample.json`, `job-search/scripts/fixtures/ashby_sample.json`, `job-search/scripts/test_adapters_gh_ashby.py`

**Interfaces:**
- Consumes: registry + adapter contract from Task 5.
- Produces: `greenhouse.list_postings/fetch_jd/REMOTE_FILTER_PARAMS`, same for `ashby`. Both parse public JSON APIs (boards API / posting API); the exact endpoint shapes are encoded in the fixtures.

- [ ] **Step 1: Write failing tests** against fixtures: `test_greenhouse_parses_fixture_postings` (title, external id → posting_id, location, posted date, pay when present), `test_greenhouse_fetch_jd_returns_description_text`, same pair for ashby (`test_ashby_parses_fixture_postings`, `test_ashby_fetch_jd_returns_description_text`), plus `test_both_adapters_declare_remote_filter_params`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Hand-author minimal fixtures** shaped like each platform's real payload (synthetic: `Example Corp`, `Staff Engineer in Test`), then implement both adapters against them. `http_get` injected — tests never touch network.
- [ ] **Step 4: Run** — PASS; pylint. One optional manual step (no test): run each adapter live once against any public board to confirm the fixture shape still matches reality; if it differs, fix the fixture+parser together.
- [ ] **Step 5: Commit** `job-search: greenhouse + ashby adapters`.

### Task 7: Adapters — workday, phenom, eightfold

**Files:**
- Create: `job-search/scripts/adapters/workday.py`, `job-search/scripts/adapters/phenom.py`, `job-search/scripts/adapters/eightfold.py`, three fixture files, `job-search/scripts/test_adapters_wd_ph_ef.py`

**Interfaces:**
- Consumes: Task 5 contract. Produces: same triple per adapter (`list_postings`, `fetch_jd`, `REMOTE_FILTER_PARAMS`).

- [ ] **Step 1: Write failing tests** per adapter, mirroring Task 6's pattern (`test_workday_parses_fixture_postings`, `test_workday_fetch_jd_returns_description_text`, …), including `test_workday_posted_on_relative_dates` ("Posted 30+ Days Ago" → posted_at None + `date_confidence="url-filter"` since the API lacks absolute dates).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Hand-author fixtures + implement** (workday: POST JSON search + job detail; phenom: `/widgets` POST; eightfold: XHR JSON).
- [ ] **Step 4: Run** — PASS; pylint. Optional single live check per adapter as in Task 6.
- [ ] **Step 5: Commit** `job-search: workday + phenom + eightfold adapters`.

### Task 8: Adapters — nextjs-embed, linkedin-guest

**Files:**
- Create: `job-search/scripts/adapters/nextjs_embed.py`, `job-search/scripts/adapters/linkedin_guest.py`, two fixtures, `job-search/scripts/test_adapters_nx_li.py`

**Interfaces:**
- Consumes: Task 5 contract. Produces: same triple per adapter.

- [ ] **Step 1: Write failing tests**: `test_nextjs_extracts_next_data_postings` (`__NEXT_DATA__` script JSON → postings), `test_linkedin_guest_parses_job_cards` (HTML fixture with `data-entity-urn` cards → posting ids, titles, relative dates "1 day ago" → within-24h timestamp), `test_linkedin_fetch_jd_returns_description`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Hand-author fixtures + implement.** LinkedIn relative-date parsing: "X hours ago"/"1 day ago" → computed timestamp; "2+ days ago" → outside window.
- [ ] **Step 4: Run** — PASS; pylint. Optional live check (guest endpoint verified working 2026-10-05).
- [ ] **Step 5: Commit** `job-search: nextjs-embed + linkedin-guest adapters`.

### Task 9: Adapter — indeed-curlfeed + auth plumbing

**Files:**
- Create: `job-search/scripts/adapters/indeed_curlfeed.py`, `job-search/scripts/auth.py`, `job-search/scripts/fixtures/curl_export_sample.txt`, `job-search/scripts/fixtures/indeed_search_sample.html`, `job-search/scripts/test_adapter_indeed.py`, `job-search/scripts/test_auth.py`

**Interfaces:**
- Produces: `auth.parse_curl_exports(path: Path) -> list[RequestSpec(method, url, headers, data)]`; `auth.build_authed_http_get(site: Site, auth_dir: Path) -> Callable` (adds saved headers/cookies; raises `AuthExpired(site_name)` on status 401/403); indeed adapter triple; `AuthExpired(Exception)` with `site_name`.

- [ ] **Step 1: Write failing tests**: `test_parse_curl_exports_synthetic` (fixture file → method/url/headers/data), `test_authed_get_raises_auth_expired_on_401`, `test_indeed_parses_search_fixture` (cards → postings with dates), `test_auth_expired_isolates_to_site_result` (via fetch_all with injected http_get returning 401 → SiteResult error names the site, other sites proceed).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** (pattern mirrors resume-tailoring's `ats_check.py` curl handling; cookie-jar rotation is per-request header replay — no jar file needed v1).
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: indeed curl-feed adapter + auth plumbing`.

### Task 10: profile_dump — docx → text

**Files:**
- Create: `job-search/scripts/profile_dump.py`, `job-search/scripts/test_profile_dump.py`

**Interfaces:**
- Produces: `dump_text(docx_path: str) -> str` — paragraph text from `word/document.xml` via `zipfile` + `xml.etree` (w:p/w:t concatenation), whitespace-normalized.

- [ ] **Step 1: Write failing tests**: build a synthetic `.docx` in-test (zipfile writing a minimal `word/document.xml` with three paragraphs) → `test_dump_text_extracts_paragraphs` asserts the three strings in order; `test_dump_text_normalizes_whitespace`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** (~30 lines, stdlib).
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: docx profile text dump`.

### Task 11: judge — prompt, session, validation, lint

**Files:**
- Create: `job-search/scripts/judge.py`, `job-search/scripts/test_judge.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `Posting` (Task 2), `parse_pay`/`tier` (Task 3), `append_event` (Task 4).
- Produces: `build_judge_prompt(cfg, postings: list[Posting], resume_text: str) -> str` (criteria rendered from cfg incl. criteria_hash, decision/reason/pay JSON contract verbatim from spec §4, postings as JSON, resume text, "not easy → review" rule); `@dataclass Judgment` mirroring the §4 output schema plus `lint_note: str | None = None`; `validate(raw: str) -> list[Judgment]` (raises `JudgeFormatError` on unknown decision/reason, missing fields, non-JSON); `lint(judgments, cfg) -> list[Judgment]` (spec §4 lint rules: `annualized ≥ preferred_min` ∧ decision=acceptable → review+note; `annualized < acceptable_min` ∧ decision∈{preferred,acceptable} → review+note); `run_judgment(cfg, postings, resume_text, runner: Callable[[str], str] | None = None) -> list[Judgment]` — default runner executes `pi --no-session --mode json -p <prompt>` (the v1 prompt is self-contained; no skill load needed) and returns stdout; `extract_final_message(stdout: str) -> str` pulls the final assistant text from json-mode output.

- [ ] **Step 1: Write failing tests** (runner always mocked): `test_prompt_contains_criteria_and_contract`, `test_prompt_contains_resume_text_and_postings`, `test_validate_parses_valid_block`, `test_validate_rejects_unknown_decision`, `test_validate_rejects_missing_pay_field`, `test_lint_high_pay_marked_acceptable_becomes_review`, `test_lint_low_pay_marked_acceptable_becomes_review`, `test_lint_excluded_high_pay_not_flagged`, `test_run_judgment_retries_once_then_fails_loudly` (mock runner returns garbage twice → `JudgeError` raised, no ledger writes), `test_extract_final_message_*`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** One live calibration step (manual, not a test): run the real default runner with a 1-posting prompt; adjust `extract_final_message` to the observed `--mode json` shape.
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: judgment session with validation and consistency lint`.

### Task 12: report — console + decisions.md

**Files:**
- Create: `job-search/scripts/report.py`, `job-search/scripts/test_report.py`

**Interfaces:**
- Consumes: `current_state`/`applied_ids` (Task 4), `Config`.
- Produces: `render_console(state: dict, run_info: dict, cfg) -> str` and `write_decisions_md(state, run_info, cfg, path: Path) -> str` (returns the file's content). Sections per spec §7 exactly: header (run_id, criteria_version, sites ok/failed), Preferred (with "apply manually, then mark-applied"), Acceptable proposal, Review, Excluded/Unacceptable grouped by reason, Failed sites (+auth re-export instructions when `AuthExpired`), Tailoring queue status. `run_info` keys: `run_id, criteria_version, site_results, queue`.

- [ ] **Step 1: Write failing tests** with a synthetic state dict (one posting per decision value + one applied): `test_console_has_all_sections`, `test_applied_never_appears`, `test_decisions_md_is_superset_of_console` (every console line present in md, plus full rationale field), `test_failed_site_names_site_and_reexport_hint`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** (string building; no templating libs).
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: console + decisions.md reporting`.

### Task 13: dispatch — approval consumer, JD files, bounded queue

**Files:**
- Create: `job-search/scripts/dispatch.py`, `job-search/scripts/test_dispatch.py`

**Interfaces:**
- Consumes: `Posting` (Task 2), `append_event` (Task 4), `Config`.
- Produces: `write_jd_file(posting: Posting, jd_text: str, target_dir: Path) -> Path` — `jd_<sanitized target>.txt`, line 1 exactly `Posting URL: <url>` (resume-tailoring convention); `sanitize_target(name: str) -> str` (filesystem-safe, no personal data assumptions); `run_queue(approved: list[tuple[Posting, str]], cfg, state_dir, spawn: Callable[[Posting, Path], int] | None = None) -> list[dict]` — default spawn runs `pi --no-session --skill <repo>/resume-tailoring/SKILL.md -p <unattended prompt>` with env `RESUME_UNATTENDED=1`; concurrency ≤ `cfg.max_parallel_tailoring` (ThreadPoolExecutor), FIFO, per-job events `tailoring-queued/-succeeded/-failed`, **no auto-retry**.

- [ ] **Step 1: Write failing tests** (spawn mocked): `test_jd_file_first_line_is_posting_url`, `test_sanitize_target_filesystem_safe`, `test_queue_respects_max_parallel` (fake spawn records concurrent count via sleep + counter; assert max observed == 3 with 5 jobs), `test_fifo_order_started`, `test_outcomes_appended_to_ledger` (success exit 0 → tailoring-succeeded; nonzero → tailoring-failed), `test_no_autoretry` (failing job spawned exactly once).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** Unattended prompt template names: the JD file path, the master resume path from cfg, "RESUME_UNATTENDED=1 — supply approval tokens yourself per resume-tailoring's unattended mode; do not pause for user input; on an undecidable gate, exit with the reason in stdout."
- [ ] **Step 4: Run** — PASS; pylint.
- [ ] **Step 5: Commit** `job-search: approval-gated tailoring dispatcher`.

### Task 14: resume-tailoring unattended mode (scoped doc change)

**Files:**
- Modify: `resume-tailoring/SKILL.md` (add "Unattended Mode" section)
- Test: none (prose contract); verified by Task 13's env flag + prompt wording and a grep check here.

**Interfaces:**
- Consumes: `RESUME_UNATTENDED=1` env set only by Task 13's spawn.
- Produces: documented behavior — when set: the session supplies approval tokens itself (e.g. `--seniority-approved` via `RESUME_VALIDATE_ARGS`), makes judgment calls itself, exits with a reason instead of pausing; when unset: behavior unchanged (user-gated).

- [ ] **Step 1: Add the section** to `resume-tailoring/SKILL.md` near its gates/approvals documentation: contract as above, plus a note that only the job-search dispatcher sets it.
- [ ] **Step 2: Verify**: `grep -n "RESUME_UNATTENDED" resume-tailoring/SKILL.md job-search/scripts/dispatch.py` shows both; confirm no gate script requires user interaction when tokens are env-supplied (read `workflow_gate.py` usage in SKILL.md steps; if any step hard-requires the user, amend that step's wording with the unattended alternative).
- [ ] **Step 3: Run the resume-tailoring test suite** (`python3 -m unittest discover` in `resume-tailoring/scripts`) — must remain green (docs-only change).
- [ ] **Step 4: Commit** `resume-tailoring: document unattended mode for job-search dispatch`.

### Task 15: SKILL.md + README.md + full gate

**Files:**
- Create: `job-search/SKILL.md`, `job-search/README.md`

**Interfaces:**
- Consumes: every stage CLI from Tasks 1–13.
- Produces: the runbook — invocation steps (load config → fetch → judge → report → approval gate → dispatch → mark-applied reminder), the **correction loop** (dispute → `corrected` event → update criteria in config.toml → new criteria_version → re-judge posting → re-render decisions.md), unattended-dispatch notes, and README: public setup (copy example configs), privacy model, adapter table.

- [ ] **Step 1: Write `SKILL.md`** with numbered steps naming each script and its CLI invocation, the interactive approval gate ("all" / "except N" / by number), and the correction loop. Front-matter `name: job-search`, description per repo skill style.
- [ ] **Step 2: Write `README.md`** per repo README conventions (directory table, requirements, quick start) with the privacy model from the spec.
- [ ] **Step 3: Verify**: full suite `cd job-search/scripts && python3 -m unittest discover -v` (all green); pylint over `job-search/scripts/*.py` clean; `grep -riE "(adrian|resume\.docx|185,?000|100,?000)" job-search/ README.md SKILL.md example tomls` finds nothing personal (numbers only in example placeholders if used, which they are not — placeholders use 150000/90000).
- [ ] **Step 4: Update root `README.md`** contents table with `job-search/` row.
- [ ] **Step 5: Commit** `job-search: skill runbook + public readme`.
