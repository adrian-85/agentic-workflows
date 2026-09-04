"""CLI: `python -m p2p_qa run|demo`.

run  – run explorer + adversarial (baseline + hacker) + judge against any
       reachable API URL, write the spec report (atomic), print a narrative.
demo – boot the mock API, then run against it, then tear down.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from p2p_qa.client import P2PClient, StepLogger
from p2p_qa import config, judge


def _fresh_report_dir() -> Path:
    base = Path("reports")
    base.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return base / stamp


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, default=str)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def narrate(report: dict) -> str:
    lines = []
    hp = report["happy_path"]
    lines.append("=== EXPLORER (happy path) ===")
    lines.append(f"status: {hp['status']}  | steps: {len(hp['steps'])}")
    for s in hp["steps"]:
        lines.append(f"  {s['name']:<18s} {s.get('status_code')} verified={s.get('verified')} "
                     f":: {(s.get('interpretation') or '')[:90]}")
    lines.append("")
    lines.append("=== ADVERSARIAL (verdicts) ===")
    for a in report["adversarial"]:
        ev = a.get("evidence") or {}
        lines.append(f"  [{a['status']:9s}] {a['rule']:26s} :: {(a.get('note') or '')[:110]}")
    if report.get("integration_issues"):
        lines.append("")
        lines.append("=== INTEGRATION ISSUES (schema drift) ===")
        for it in report["integration_issues"]:
            lines.append(f"  [{it.get('severity')}] {it.get('endpoint')} {it.get('field')} "
                         f":: {it.get('detail')}")
    lines.append("")
    lines.append("=== SUMMARY ===")
    lines.append(report.get("summary", ""))
    return "\n".join(lines)


def cmd_run(args) -> int:
    run_dir = _fresh_report_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "steps.jsonl"
    logger = StepLogger(str(log_path))
    client = P2PClient(args.api, token=args.token or os.environ.get("P2P_API_TOKEN"))

    happy_status = "INCOMPLETE"
    if not args.skip_explorer:
        from p2p_qa.explorer import run_explorer
        print("[1/4] explorer: discovering + constructing happy path...", flush=True)
        summary = run_explorer(client, logger, progress=_cli_progress("explorer"))
        happy_status = summary["status"]
        print(f"  -> happy path {happy_status} ({summary['steps_count']} stages)\n", flush=True)

    from p2p_qa.adversarial import run_baseline, run_hacker
    # Adversarial evidence lives in ProbeResults, not the happy-path log; they
    # run against the same client but do NOT append to the explorer's logger.
    print("[2/4] adversarial baseline: 12 deterministic probes...", flush=True)
    baseline = run_baseline(client)
    print(f"  -> {len(baseline)} verdicts\n", flush=True)
    hacker = []
    if not args.prepass_only:
        print(f"[3/4] adversarial hacker: open-ended LLM probes (up to {config.MAX_HACKER_PROBES})...", flush=True)
        hacker = run_hacker(client, max_probes=config.MAX_HACKER_PROBES,
                            progress=_cli_progress("hacker"))
        print(f"  -> {len(hacker)} verdicts\n", flush=True)
    probes = baseline + hacker

    print("[4/4] judge: replaying step log + writing report...", flush=True)
    findings = judge.run_prepass(logger.iter_steps(), probes)
    integration = list(client.integration_issues)

    if args.prepass_only:
        summary_text = judge.llm_summary(findings, happy_status)
    else:
        summary_text = judge.llm_summary(findings, happy_status)

    report = judge.build_report(args.api, logger.iter_steps(), findings,
                                integration, summary_text, happy_status=happy_status)
    report_path = Path(args.report) if args.report else (run_dir / "report.json")
    _write_atomic(report_path, report)
    print(narrate(report))
    print(f"\nReport: {report_path}")
    return 0


def _cli_progress(tag: str):
    """Returns a progress callback printing one line per step (flush=True)."""
    def progress(step):
        name = getattr(step, "name", None)
        if name:
            print(f"  [{tag}] {name}", flush=True)
    return progress


def _wait_ready(base_url: str, timeout: float = 20.0) -> bool:
    import httpx
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(base_url + "/vendors").status_code in (200, 401):
                return True
        except Exception:
            time.sleep(0.2)
    return False


def cmd_demo(args) -> int:
    env = dict(os.environ)
    env["P2P_BUG_PROFILE"] = args.bug_profile
    if args.require_auth:
        env["P2P_REQUIRE_AUTH"] = "1"
    port = args.port
    proc = subprocess.Popen(
        [sys.executable, "-m", "p2p_qa.mock_api", "--host", "127.0.0.1",
         "--port", str(port), "--bug-profile", args.bug_profile]
        + (["--require-auth"] if args.require_auth else []),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        if not _wait_ready(base):
            print("mock failed to start", file=sys.stderr)
            return 1
        return cmd_run(argparse.Namespace(
            api=base, token=config.SEED_TOKEN if args.require_auth else None,
            skip_explorer=args.skip_explorer, prepass_only=args.prepass_only,
            report=args.report))
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def cmd_stress(args) -> int:
    from p2p_qa import stress
    res = stress.run_stress(seed=args.seed, bug_profile=args.bug_profile, n=args.n)
    print("=== 50-PO STRESS TEST ===")
    print(f"profile: {res['bug_profile']}  | total POs: {res['total']}  | seed: {res['seed']}")
    for rule, rate in sorted(res["failure_rate"].items()):
        bar = "#" * int(rate * 30)
        print(f"  {rule:28s} failure_rate={rate:5.1%} {bar}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="p2p_qa", description="P2P QA lab")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run agents against a live API")
    p_run.add_argument("--api", required=True, help="base URL")
    p_run.add_argument("--token", default=None, help="Bearer token")
    p_run.add_argument("--report", default=None, help="output report path (default: reports/<ts>/report.json)")
    p_run.add_argument("--skip-explorer", action="store_true")
    p_run.add_argument("--prepass-only", action="store_true")
    p_run.set_defaults(fn=cmd_run)

    p_demo = sub.add_parser("demo", help="boot mock + run against it")
    p_demo.add_argument("--bug-profile", default="clean", choices=list(config.BUG_PROFILES))
    p_demo.add_argument("--port", type=int, default=8000)
    p_demo.add_argument("--require-auth", action="store_true")
    p_demo.add_argument("--skip-explorer", action="store_true")
    p_demo.add_argument("--prepass-only", action="store_true")
    p_demo.add_argument("--report", default=None, help="output report path")
    p_demo.set_defaults(fn=cmd_demo)

    p_stress = sub.add_parser("stress", help="50-PO synthetic stress test (failure rate)")
    p_stress.add_argument("--seed", type=int, default=0)
    p_stress.add_argument("--n", type=int, default=50)
    p_stress.add_argument("--bug-profile", default="clean",
                          choices=list(config.BUG_PROFILES))
    p_stress.set_defaults(fn=cmd_stress)

    args = parser.parse_args(argv)
    return args.fn(args)