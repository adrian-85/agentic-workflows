"""Report rendering: console summary + rewritten decisions.md (spec §7).

decisions.md is the superset of the console report: every console line
appears verbatim, plus a per-posting DETAILS section carrying the full
rationale, URL, and criteria_version. Both derive from the same line
builders so they cannot drift.
"""

from pathlib import Path

from config import Config

MARK_APPLIED_HINT = ("apply manually, then: python3 scripts/ledger.py "
                     "mark-applied <posting_id>")
AUTH_REEXPORT_HINT = ("  auth expired: re-export cURL from a logged-in "
                      "session into auth/<site name>/curl.txt")


def render_console(state: dict, run_info: dict, cfg: Config) -> str:
    """The run's console summary (spec §7 section order)."""
    del cfg
    return "\n".join(_summary_lines(state, run_info))


def write_decisions_md(state: dict, run_info: dict, cfg: Config,
                       path: Path) -> str:
    """Write decisions.md (console superset + details); returns content."""
    del cfg
    lines = _summary_lines(state, run_info)
    lines.append("")
    lines.append("== DETAILS ==")
    for event in _visible(state):
        lines.append(f"- {event.get('posting_id')}: "
                     f"{event.get('company')} — {event.get('title')}")
        lines.append(f"  url: {event.get('url')}")
        lines.append(f"  event: {event.get('event')} | "
                     f"decision: {event.get('decision')} | "
                     f"reason: {event.get('reason')}")
        lines.append(f"  rationale: {event.get('rationale_short')}")
        lines.append(f"  criteria_version: {event.get('criteria_version')}")
    content = "\n".join(lines) + "\n"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")
    return content


def _summary_lines(state: dict, run_info: dict) -> list[str]:
    """Shared section builders so console and md cannot drift."""
    site_results = run_info.get("site_results", [])
    ok_count = sum(1 for site in site_results if site.get("ok"))
    failed = [site for site in site_results if not site.get("ok")]
    queue = run_info.get("queue", {})

    lines = [
        f"JOB SEARCH RUN {run_info.get('run_id')} — "
        f"criteria {run_info.get('criteria_version')}",
        f"Sites: {ok_count} ok, {len(failed)} failed",
    ]
    ok_names = [site.get("name") for site in site_results if site.get("ok")]
    if ok_names:
        lines.append(f"  ok: {', '.join(str(name) for name in ok_names)}")
    lines.append("")
    visible = _visible(state)
    lines.extend(_tier("PREFERRED", MARK_APPLIED_HINT,
                       _by_decision(visible, "preferred")))
    lines.extend(_tier("ACCEPTABLE — proposed for auto-tailoring "
                       "(approval gate: nothing starts until you approve)",
                       "", _by_decision(visible, "acceptable")))
    lines.extend(_tier("REVIEW (needs your judgment)", "",
                       _by_decision(visible, "review")))
    lines.extend(_reason_group("EXCLUDED", "not_relevant", visible))
    lines.extend(_reason_group("EXCLUDED", "ethics", visible))
    lines.extend(_reason_group("UNACCEPTABLE", "pay_below_threshold",
                               visible))
    lines.append("== FAILED SITES ==")
    if failed:
        for site in failed:
            lines.append(f"- {site.get('name')}: {site.get('error')}")
            if "authexpired" in str(site.get("error", "")).lower().replace(
                    " ", ""):
                lines.append(AUTH_REEXPORT_HINT)
    else:
        lines.append("- none")
    lines.append("")
    lines.append("== TAILORING QUEUE ==")
    lines.append(f"running {queue.get('running', 0)} / "
                 f"queued {queue.get('queued', 0)}")
    for outcome in queue.get("outcomes", []):
        lines.append(f"- {outcome}")
    return lines


def _visible(state: dict) -> list[dict]:
    """Latest events that are not marked-applied (applied never appears)."""
    return [event for event in state.values()
            if event.get("event") != "marked-applied"]


def _by_decision(events: list[dict], decision: str) -> list[dict]:
    """Events with a given decision, stable by posting_id."""
    return sorted((event for event in events
                   if event.get("decision") == decision),
                  key=lambda event: event.get("posting_id", ""))


def _by_reason(events: list[dict], reason: str) -> list[dict]:
    """Excluded/unacceptable events carrying a given reason."""
    return sorted((event for event in events
                   if event.get("reason") == reason),
                  key=lambda event: event.get("posting_id", ""))


def _tier(title: str, hint: str, events: list[dict]) -> list[str]:
    """One titled section of posting lines."""
    lines = [f"== {title} =="]
    if hint:
        lines.append(hint)
    if events:
        lines.extend(_posting_line(event) for event in events)
    else:
        lines.append("- none")
    lines.append("")
    return lines


def _reason_group(title: str, reason: str, events: list[dict]) -> list[str]:
    """A titled section listing events carrying one reason."""
    return _tier(f"{title} — {reason}", "", _by_reason(events, reason))


def _posting_line(event: dict) -> str:
    """The one-line posting summary shared by console and decisions.md."""
    return (f"- [{event.get('company')}] {event.get('title')} "
            f"({event.get('posting_id')}) — {event.get('rationale_short')}")
