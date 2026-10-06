"""Stage runner: the skill's deterministic pipeline entry points.

`run.py search` — fetch -> judge -> record -> report -> save candidates
`run.py approve <ids...|all> [--except id...]` — dispatch tailoring

The interactive approval gate lives BETWEEN the two commands: the agent
prints search's report, the user approves, then approve runs. Candidates
persist to state/candidates.json so the two invocations share run data.
"""

import json
import sys
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import dispatch
import fetch as fetch_mod
import judge as judge_mod
import ledger
import profile_dump
import report as report_mod
from config import criteria_hash, load_config
from postings import Posting

WORKFLOW_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = "candidates.json"


class RunError(Exception):
    """Raised on CLI misuse (unknown ids, missing files)."""


def cmd_search(config_path: str, sites_path: str, state_dir,
               _fetch=None, _judge=None, _resume=None) -> int:
    """Fetch, judge, record, and report; persist candidates for approve."""
    state_dir = Path(state_dir)
    cfg = load_config(config_path)
    fetch_all = _fetch or fetch_mod.fetch_all
    run_judgment = _judge or judge_mod.run_judgment
    resume_of = _resume or profile_dump.dump_text

    fetch_report = fetch_all(fetch_mod.load_sites(sites_path), cfg,
                             state_dir)
    run_id = uuid.uuid4().hex[:8]
    if fetch_report.candidates:
        judgments = run_judgment(cfg, fetch_report.candidates,
                                 resume_of(cfg.relevance_profile_path))
        judge_mod.record_judgments(judgments, fetch_report.candidates,
                                   state_dir, cfg, run_id)
    else:
        judgments = []
    _save_candidates(state_dir, run_id, {
        posting.posting_id: (posting, posting.jd_text or "")
        for posting in fetch_report.candidates})

    run_info = _run_info(fetch_report, run_id, cfg)
    state = ledger.current_state(state_dir)
    console = report_mod.render_console(state, run_info, cfg)
    report_mod.write_decisions_md(state, run_info, cfg,
                                  state_dir / "decisions.md")
    print(console)
    if judgments:
        print("Approve tailoring with: python3 scripts/run.py approve "
              "<posting_id...|all> [--except <posting_id>...]")
    else:
        print("no candidates judged this run")
    return 0


def cmd_approve(config_path: str, state_dir, refs: list[str],
                except_refs: list[str], _queue=None) -> int:
    """Dispatch tailoring sessions for the approved posting ids."""
    state_dir = Path(state_dir)
    cfg = load_config(config_path)
    queue = _queue or dispatch.run_queue
    resolved = _resolve_refs(state_dir, refs, except_refs)
    candidates = _load_candidates(state_dir)
    approved = [candidates[posting_id] for posting_id in resolved]
    outcomes = queue(approved, cfg, state_dir)
    for outcome in outcomes:
        print(f"{outcome['posting_id']}: {outcome['status']} "
              f"(exit {outcome['returncode']})")
    return 0


def _run_info(fetch_report, run_id: str, cfg) -> dict:
    """FetchReport + run identity as the report's plain-dict run_info."""
    return {
        "run_id": run_id,
        "criteria_version": criteria_hash(cfg),
        "site_results": [
            {"name": result.site.name, "ok": result.ok,
             "error": result.error}
            for result in fetch_report.site_results
        ],
        "queue": {"running": 0, "queued": len(fetch_report.candidates),
                  "outcomes": []},
    }


def _save_candidates(state_dir, run_id: str, candidates: dict) -> None:
    """Persist (posting, jd_text) pairs for the approve invocation."""
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "candidates": {
            posting_id: {**_jsonable(posting), "jd_text": jd_text}
            for posting_id, (posting, jd_text) in candidates.items()
        },
    }
    _atomic_write(state_dir / CANDIDATES_FILE, payload)


def _jsonable(posting: Posting) -> dict:
    """Posting fields with datetimes as ISO strings for JSON."""
    fields = asdict(posting)
    for key in ("posted_at", "fetched_at"):
        if fields.get(key) is not None:
            fields[key] = fields[key].isoformat()
    return fields


def _load_candidates(state_dir) -> dict:
    """Rebuild Posting objects (with jd_text) from the saved candidates."""
    path = Path(state_dir) / CANDIDATES_FILE
    if not path.exists():
        raise RunError(f"no candidates file at {path} — run search first")
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = {}
    for posting_id, fields in payload["candidates"].items():
        fields = dict(fields)
        jd_text = fields.pop("jd_text", None)
        fields["posted_at"] = _parse_time(fields.get("posted_at"))
        fields["fetched_at"] = _parse_time(fields.get("fetched_at"))
        candidates[posting_id] = (Posting(**fields), jd_text)
    return candidates


def _resolve_refs(state_dir, refs: list[str],
                  except_refs: list[str]) -> list[str]:
    """'all' expands to every saved candidate id (minus excepts)."""
    candidates = _load_candidates(state_dir)
    if refs == ["all"]:
        resolved = list(candidates)
    else:
        resolved = list(refs)
    unknown = [ref for ref in resolved if ref not in candidates]
    if unknown:
        raise RunError(f"unknown posting ids: {', '.join(unknown)}")
    return [ref for ref in resolved if ref not in set(except_refs)]


def _parse_time(raw):
    """ISO string back to aware datetime; None stays None."""
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def _atomic_write(path: Path, payload: dict) -> None:
    """Write the candidates JSON (candidates are regenerable, not ledger
    data — a torn write costs one re-run of search, not history)."""
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    """CLI: search | approve."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("search", "approve"):
        print(__doc__)
        return 2
    config_path = str(WORKFLOW_ROOT / "config.toml")
    state_dir = WORKFLOW_ROOT / "state"
    if argv[0] == "search":
        sites_path = str(WORKFLOW_ROOT / "sites.toml")
        return cmd_search(config_path, sites_path, state_dir)
    refs, except_refs = [], []
    remaining = list(argv[1:])
    while remaining:
        token = remaining.pop(0)
        if token == "--except":
            while remaining and not remaining[0].startswith("--"):
                except_refs.append(remaining.pop(0))
        else:
            refs.append(token)
    if not refs:
        print("approve needs posting ids or 'all'")
        return 2
    return cmd_approve(config_path, state_dir, refs, except_refs)


if __name__ == "__main__":
    sys.exit(main())
