"""Append-only disposition ledger (spec §5).

One JSON line per event; current state derives as the latest event per
posting. Applied is sticky: once marked-applied, a posting never
resurfaces even if a later judged event arrives (early mode re-judges).
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

LEDGER_FILENAME = "ledger.jsonl"


class LedgerError(Exception):
    """Raised on CLI misuse (unknown posting/URL)."""


def _ledger_path(state_dir: Path) -> Path:
    return Path(state_dir) / LEDGER_FILENAME


def append_event(state_dir: Path, event: dict) -> None:
    """Append one event line; ts and run_id auto-fill when absent."""
    path = _ledger_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if "ts" not in event:
        event["ts"] = datetime.now(timezone.utc).isoformat()
    if "run_id" not in event:
        event["run_id"] = uuid.uuid4().hex[:8]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _read_events(state_dir: Path) -> list[dict]:
    """All parseable events in file order; corrupt lines skipped."""
    path = _ledger_path(state_dir)
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def current_state(state_dir: Path) -> dict[str, dict]:
    """Latest event per posting_id."""
    state: dict[str, dict] = {}
    for event in _read_events(state_dir):
        posting_id = event.get("posting_id")
        if posting_id:
            state[posting_id] = event
    return state


def applied_ids(state_dir: Path) -> set[str]:
    """Postings ever marked applied — sticky by design (spec §5).

    Reads raw events, not current_state: in early mode every fetched
    posting is re-judged each run, so a later judged event must never
    resurrect a posting the user already applied to.
    """
    return {
        event["posting_id"]
        for event in _read_events(state_dir)
        if event.get("event") == "marked-applied" and event.get("posting_id")
    }


def mark_applied(state_dir: Path, ref: str) -> str:
    """Mark applied by posting_id or by URL (resolved against the ledger)."""
    posting_id = _resolve_ref(state_dir, ref)
    append_event(state_dir, {
        "posting_id": posting_id,
        "event": "marked-applied",
    })
    return posting_id


def retry_tailor(state_dir: Path, posting_id: str) -> None:
    """Re-queue a posting for tailoring (manual retry path)."""
    state = current_state(state_dir)
    if posting_id not in state:
        raise LedgerError(f"unknown posting_id: {posting_id}")
    append_event(state_dir, {
        "posting_id": posting_id,
        "event": "tailoring-queued",
    })


def show(state_dir: Path, posting_id: str) -> dict:
    """Latest event for a posting; errors loudly when unknown."""
    state = current_state(state_dir)
    if posting_id not in state:
        raise LedgerError(f"unknown posting_id: {posting_id}")
    return state[posting_id]


def _url_key(url: str) -> str | None:
    if not url.startswith("http"):
        return None
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}"


def _resolve_ref(state_dir: Path, ref: str) -> str:
    """Resolve a posting_id directly; a URL against recorded event urls."""
    events = _read_events(state_dir)
    for event in events:
        if event.get("posting_id") == ref:
            return ref
    url_key = _url_key(ref)
    if url_key is not None:
        for event in events:
            event_url = event.get("url")
            if event_url and _url_key(event_url) == url_key:
                return event["posting_id"]
    raise LedgerError(f"no ledger entry matches: {ref}")


def main(argv: list[str], state_dir: Path | None = None) -> int:
    """CLI: mark-applied <id|url> | retry-tailor <id> | show <id>."""
    if state_dir is None:
        state_dir = Path(__file__).resolve().parent.parent / "state"
    if len(argv) != 2:
        print("usage: ledger.py {mark-applied|retry-tailor|show} <arg>",
              file=sys.stderr)
        return 2
    command, ref = argv
    if command == "mark-applied":
        posting_id = mark_applied(state_dir, ref)
        print(f"marked applied: {posting_id}")
    elif command == "retry-tailor":
        retry_tailor(state_dir, ref)
        print(f"re-queued: {ref}")
    elif command == "show":
        print(json.dumps(show(state_dir, ref), indent=2, sort_keys=True))
    else:
        print(f"unknown command: {command}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
