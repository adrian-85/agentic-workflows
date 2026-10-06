"""Tailoring dispatch: JD files, bounded-parallelism session queue.

Behind the interactive approval gate (spec §6): each approved job gets a
resume-tailoring jd file (Posting URL as line one — its SKILL Step 1
convention), then a headless pi session running with RESUME_UNATTENDED=1
(agent-gate mode). At most cfg.max_parallel_tailoring sessions run at
once; the rest queue FIFO. Failures never auto-retry (retry-tailor is
the manual path).
"""

import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ledger
from config import Config, load_config
from postings import Posting

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TARGET_DIR = REPO_ROOT / "resume-tailoring"
RESUME_SKILL = REPO_ROOT / "resume-tailoring" / "SKILL.md"
SESSION_TIMEOUT_SECONDS = 3600

UNATTENDED_PROMPT = """Run the resume-tailoring workflow for one target.

- Job description file: {jd_path} (line one is the Posting URL).
- Master resume: {master_resume}
- RESUME_UNATTENDED=1 is set: per the skill's Unattended Mode section,
  supply approval tokens yourself (e.g. --seniority-approved via
  RESUME_VALIDATE_ARGS), make every judgment call yourself, and do NOT
  pause for user input. If a gate is genuinely undecidable, exit
  non-zero with the reason in your final message.
- Target: {company} — {title}
"""


def sanitize_target(name: str) -> str:
    """Filesystem-safe target token for jd_<target>.txt names."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", name)
    return cleaned or "target"


def write_jd_file(posting: Posting, jd_text: str,
                  target_dir: Path = DEFAULT_TARGET_DIR) -> Path:
    """Write resume-tailoring's jd_<target>.txt (Posting URL line one)."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"jd_{sanitize_target(posting.company)}.txt"
    body = f"Posting URL: {posting.url}\n{jd_text}\n"
    path.write_text(body, encoding="utf-8")
    return path


def run_queue(approved: list[tuple[Posting, str]], cfg: Config,
              state_dir, target_dir: Path = DEFAULT_TARGET_DIR,
              spawn=None) -> list[dict]:
    """Run tailoring sessions for approved jobs: bounded, FIFO, no retry.

    approved is (posting, jd_text) tuples in approval order. Returns one
    outcome dict per job: {posting_id, status, returncode}.
    """
    if spawn is None:
        spawn = _default_spawn
    state_dir = Path(state_dir)
    jobs = []
    for posting, jd_text in approved:
        jd_path = write_jd_file(posting, jd_text, target_dir)
        jobs.append((posting, jd_path))
        ledger.append_event(state_dir, {
            "posting_id": posting.posting_id,
            "url": posting.url,
            "company": posting.company,
            "title": posting.title,
            "event": "tailoring-queued",
        })

    outcomes = [None] * len(jobs)

    def _run(index):
        posting, jd_path = jobs[index]
        returncode = spawn(posting, jd_path)
        status = ("tailoring-succeeded" if returncode == 0
                  else "tailoring-failed")
        ledger.append_event(state_dir, {
            "posting_id": posting.posting_id,
            "event": status,
            "returncode": returncode,
        })
        return {"posting_id": posting.posting_id, "status": status,
                "returncode": returncode}

    with ThreadPoolExecutor(max_workers=cfg.max_parallel_tailoring) as pool:
        futures = [pool.submit(_run, index) for index in range(len(jobs))]
        for index, future in enumerate(futures):
            outcomes[index] = future.result()
    return outcomes


def _default_spawn(posting: Posting, jd_path: Path) -> int:
    """Headless resume-tailoring session in agent-gate mode."""
    env = dict(os.environ)
    env["RESUME_UNATTENDED"] = "1"
    prompt = UNATTENDED_PROMPT.format(
        jd_path=jd_path,
        master_resume=_master_resume_hint(),
        company=posting.company,
        title=posting.title,
    )
    result = subprocess.run(
        ["pi", "--no-session", "--skill", str(RESUME_SKILL), "-p", prompt],
        capture_output=True, text=True, env=env,
        timeout=SESSION_TIMEOUT_SECONDS, check=False)
    if result.returncode != 0:
        _log_session_failure(posting, result)
    return result.returncode


def _master_resume_hint() -> str:
    """Master resume path from config.toml (fail-safe to a placeholder)."""
    try:
        workflow_root = Path(__file__).resolve().parent.parent
        cfg = load_config(str(workflow_root / "config.toml"))
        return cfg.relevance_profile_path
    except Exception:  # pylint: disable=broad-exception-caught  # boundary: prompt hint falls back when config unreadable
        return "<master resume path from config.toml>"


def _log_session_failure(posting: Posting, result) -> None:
    """Emit the session tail so failures are diagnosable in the console."""
    tail = (result.stdout or result.stderr or "").strip().splitlines()[-5:]
    print(f"tailoring session failed for {posting.posting_id} "
          f"(exit {result.returncode}):")
    for line in tail:
        print(f"  {line}")


def outcomes_json(outcomes: list[dict]) -> str:
    """Outcomes as JSON for report consumption."""
    return json.dumps(outcomes)
