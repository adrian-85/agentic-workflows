#!/usr/bin/env python3
"""
LLM-as-a-judge for voice-AI transcripts.

Two-stage design:
  1. Deterministic pre-pass (rule-based, cheap, high-precision) that flags
     the "false success" and "internal disclosure" classes by cross-referencing
     agent speech against the [SYS] action log and system variables.
  2. LLM judge that scores the call against a rubric, using the structured
     transcript and the pre-pass findings as evidence anchors.

The LLM judge is constrained to a strict JSON contract and must quote verbatim
evidence from the transcript, so its findings are auditable.

Credentials auto-load from Pi's auth store (~/.pi/agent/auth.json) so no manual
API key entry is required when running inside a Pi environment.
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Import the parser from the sibling module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_transcript import parse_transcript, flatten  # noqa: E402

_OPENAI_CLIENT = None


# --------------------------------------------------------------------------- #
# Credentials (unchanged from the original judge.py)
# --------------------------------------------------------------------------- #
def load_openrouter_credentials() -> str:
    auth_path = Path.home() / ".pi" / "agent" / "auth.json"
    if not auth_path.exists():
        raise RuntimeError(
            f"Pi auth store not found at {auth_path}. "
            "Set OPENAI_API_KEY and OPENAI_BASE_URL manually instead."
        )
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    try:
        return auth["openrouter"]["key"]
    except (KeyError, TypeError):
        raise RuntimeError("OpenRouter key not present in Pi auth store.")


def get_client():
    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is not None:
        return _OPENAI_CLIENT
    api_key = os.environ.get("OPENAI_API_KEY") or load_openrouter_credentials()
    base_url = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    from openai import OpenAI
    _OPENAI_CLIENT = OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers={"HTTP-Referer": "https://localhost", "X-Title": "ai-judge"},
    )
    return _OPENAI_CLIENT


# --------------------------------------------------------------------------- #
# Deterministic pre-pass
# --------------------------------------------------------------------------- #
# Maps action names (as they appear in "Action <name> -> ...") to the
# success language an agent might use when claiming that action worked.
ACTION_SUCCESS_KEYWORDS: Dict[str, List[str]] = {
    "cancel_order": ["canceled", "cancelled", "cancellation is complete",
                     "i've gone ahead and canceled"],
    "update_account_email": ["email has been updated", "updated your email",
                              "all done", "i'll update your email"],
    "escalate_to_agent": ["transfer you", "connect you", "connecting you",
                          "please hold while i transfer"],
    "send_sms_returns_link": ["sending that text", "the text has been sent",
                               "i've sent"],
    "send_sms_tracking_link": ["i've sent", "sent!", "sent the", "sending"],
}

# Variant words a caller might use when naming a product variant (e.g.
# sports-team or style variants), and context words that signal a product
# mention in caller speech. Both are domain-neutral and configurable.
PRODUCT_VARIANT_WORDS = ["home", "away", "road", "alternate", "city", "classic"]
PRODUCT_CONTEXT_WORDS = ["jersey", "shirt", "size", "model", "sneaker", "jacket"]

# Claims that imply an action happened, with the action-name pattern to look
# for among successful [SYS] actions. Used to catch "agent said it, but no
# successful action exists" (e.g. reschedule never actually executed).
CLAIMED_ACTION: List[Dict[str, Any]] = [
    {
        "claim_re": r"reschedul|you'?re all set for|delivery (has been )?moved|moved to (friday|monday|tuesday)",
        "action_re": r"reschedul|update_delivery|change_delivery|reschedule_delivery",
        "label": "delivery reschedule",
    },
    {
        "claim_re": r"cancellation is complete|order has been canceled|cancelled your order",
        "action_re": r"cancel_order",
        "label": "order cancellation",
    },
    {
        "claim_re": r"email has been updated|updated your email",
        "action_re": r"update_account_email|update_email",
        "label": "email update",
    },
    {
        "claim_re": r"transfer you|connecting you to",
        "action_re": r"escalate_to_agent|transfer",
        "label": "escalation/transfer",
    },
]


def _all_agent_text(flat: List[Dict[str, Any]]) -> str:
    """Concatenate all agent utterances (lowercased) for keyword search."""
    return " ".join(e["text"] for e in flat if e["role"] == "agent").lower()


def _all_sys_text(parsed: Dict[str, Any]) -> str:
    """Concatenate all sys notes (init + timeline), lowercased."""
    parts = [n["raw"] for n in parsed["system_init"]]
    for e in flatten(parsed):
        if e["role"] == "sys":
            parts.append(e["text"])
    return " ".join(parts).lower()


def _extract_actions(sys_text: str) -> List[Dict[str, str]]:
    """
    Pull every 'Action <name> -> <status>' occurrence out of the sys text,
    returning [{name, status, snippet}] in order.
    """
    out = []
    for m in re.finditer(r"action\s+(\w+)\s*->\s*(success|error)", sys_text):
        out.append({"name": m.group(1), "status": m.group(2),
                    "snippet": sys_text[m.start():m.start() + 160]})
    return out


def _find_agent_turn(flat: List[Dict[str, Any]],
                      match_fn) -> tuple:
    """Return (turn_ref, text) for the first agent entry matching match_fn,
    or ("", "") if none."""
    for e in flat:
        if e["role"] == "agent" and match_fn(e["text"].lower()):
            return f"turn {e['turn']}", e["text"]
    return "", ""


def deterministic_prepass(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Run cheap, high-precision rule checks. Returns a list of findings:
      {check, severity, description, turn_ref, evidence}
    """
    findings: List[Dict[str, Any]] = []
    flat = flatten(parsed)
    agent_text = _all_agent_text(flat)
    sys_text = _all_sys_text(parsed)
    actions = _extract_actions(sys_text)

    # --- Check 1: action errored but agent claimed success ----------------- #
    # Fires when an action returned ERROR and the agent used success language.
    # Owns the "errored action" case; Check 2 owns the "no action at all" case.
    for act in actions:
        if act["status"] != "error":
            continue
        kws = ACTION_SUCCESS_KEYWORDS.get(act["name"], [])
        hit = next((k for k in kws if k in agent_text), None)
        if not hit:
            continue
        turn_ref, ev = _find_agent_turn(flat, lambda t, h=hit: h in t)
        findings.append({
            "check": "action_error_false_success",
            "severity": "critical",
            "description": (
                f"Agent claimed '{act['name']}' succeeded, but the system "
                f"action returned ERROR. The customer will believe the "
                f"action happened when it did not."
            ),
            "turn_ref": turn_ref,
            "evidence": ev,
            "system_evidence": act["snippet"],
        })

    # --- Check 2: agent claims an action that has no call at all ---------- #
    # Only fires when NO matching action exists (not even an errored one).
    # The errored-but-claimed case is handled by Check 1, so we skip any claim
    # whose action_re matches an action present in the log.
    for claim in CLAIMED_ACTION:
        if not re.search(claim["claim_re"], agent_text):
            continue
        any_action_exists = any(
            re.search(claim["action_re"], a["name"]) for a in actions
        )
        if any_action_exists:
            continue
        turn_ref, ev = _find_agent_turn(
            flat, lambda t, cr=claim["claim_re"]: re.search(cr, t))
        findings.append({
            "check": "claimed_action_missing",
            "severity": "critical",
            "description": (
                f"Agent implies a {claim['label']} was completed, but no "
                f"matching system action exists in the transcript."
            ),
            "turn_ref": turn_ref,
            "evidence": ev,
        })

    # --- Check 3: internal / do-not-disclose note leaked to caller --------- #
    for n in parsed["system_init"] + [{"raw": e["text"]} for e in flat if e["role"] == "sys"]:
        raw = n["raw"]
        if "internal" not in raw.lower() and "do-not-disclose" not in raw.lower():
            continue
        keywords = [kw for kw in ("chargeback", "chargebacks", "goodwill credit", "supervisor")
                    if kw in raw.lower()]
        leaked = [kw for kw in keywords if kw in agent_text]
        if not leaked:
            continue
        turn_ref, ev = _find_agent_turn(
            flat, lambda t, lk=leaked: any(kw in t for kw in lk))
        findings.append({
            "check": "internal_data_disclosure",
            "severity": "critical",
            "description": (
                f"Agent disclosed internal-only information to the caller: "
                f"{', '.join(leaked)}. This content was marked "
                f"INTERNAL/do-not-disclose in the system data."
            ),
            "turn_ref": turn_ref,
            "evidence": ev,
            "system_evidence": raw[:200],
        })

    # --- Check 4: loyalty/rewards hallucination --------------------------- #
    for m in re.finditer(r"loyalty_points\s*[:=]\s*(\d+)", sys_text):
        if int(m.group(1)) != 0:
            continue
        pts = re.search(r"(\d[\d,]+)\s*(?:rewards\s*)?points", agent_text)
        if not pts or int(pts.group(1).replace(",", "")) == 0:
            continue
        turn_ref, ev = _find_agent_turn(
            flat, lambda t: re.search(r"\d[\d,]+\s*(?:rewards\s*)?points", t))
        findings.append({
            "check": "hallucinated_account_state",
            "severity": "high",
            "description": (
                f"Agent told the caller they have {pts.group(1)} rewards "
                f"points, but the system shows loyalty_points = 0 "
                f"(not enrolled)."
            ),
            "turn_ref": turn_ref,
            "evidence": ev,
            "system_evidence": m.group(0),
        })

    # --- Check 5: confirmation loop (5+ "is that correct" from agent) ------ #
    confirms = [e for e in flat if e["role"] == "agent"
                and re.search(r"is that correct|correct\?|right\?", e["text"].lower())]
    if len(confirms) >= 5:
        findings.append({
            "check": "confirmation_loop",
            "severity": "medium",
            "description": (
                f"Agent asked for confirmation {len(confirms)} times, a "
                f"repetitive confirmation loop that degrades the voice experience."
            ),
            "turn_ref": f"turns {confirms[0]['turn']}-{confirms[-1]['turn']}",
            "evidence": " | ".join(c["text"][:60] for c in confirms[:3]) + " ...",
        })

    # --- Check 6: agent asks for name it already has ---------------------- #
    first_name = ""
    m_name = re.search(r'caller first name on file\s*[:=]\s*"([^"]+)"',
                      sys_text)
    if m_name:
        first_name = m_name.group(1).lower()
    else:
        first_agent = next((e["text"] for e in flat if e["role"] == "agent"), "")
        m_greet = re.search(r"\bhey\s+([a-z][a-z'\-]+)\b,", first_agent.lower())
        if m_greet and m_greet.group(1) not in ("there", "you"):
            first_name = m_greet.group(1)
    if first_name:
        asks_re = r"first and last name|your (first )?name|can i get your name"
        confirm_re = r"is this|is that|confirm.*name|name on file ends"

        def _asks_unconfirmed(t):
            return re.search(asks_re, t) and not re.search(confirm_re, t)

        turn_ref, ev = _find_agent_turn(flat, _asks_unconfirmed)
        if turn_ref:
            findings.append({
                "check": "redundant_identity_request",
                "severity": "medium",
                "description": (
                    f"Agent asked the caller for their name even though the "
                    f"platform already resolved the caller's identity (the "
                    f"greeting addressed them as '{first_name.title()}' via "
                    f"ANI lookup). The agent should confirm the name or use "
                    f"what it has, not collect it as if unknown."
                ),
                "turn_ref": turn_ref,
                "evidence": ev,
            })

    # --- Check 7: identity verification skipped before sensitive disclosure - #
    def _skipped_and_disclosed(t):
        return (re.search(r"skip (that|verification)|i'll skip|skip identity", t)
                and re.search(r"card ending|billing zip|order shipped|chargeback", t))

    turn_ref, ev = _find_agent_turn(flat, _skipped_and_disclosed)
    if turn_ref:
        findings.append({
            "check": "verification_skipped_before_disclosure",
            "severity": "high",
            "description": (
                "Agent explicitly skipped identity verification and then "
                "immediately disclosed account/payment details. The "
                "number-on-file (ANI) match was treated as sufficient "
                "identity proof, which is inconsistent with calls that "
                "require real verification for account changes."
            ),
            "turn_ref": turn_ref,
            "evidence": ev,
        })

    # --- Check 8: caller-specified product variant not confirmed ---------- #
    prod_name = ""
    m_prod = re.search(r'product_lookup\s*->\s*success\s*name\s*[:=]\s*"([^"]+)"',
                        sys_text)
    if m_prod:
        prod_name = m_prod.group(1).lower()
    if prod_name:
        for e in flat:
            if e["role"] != "caller":
                continue
            ct = e["text"].lower()
            mentions_product = any(w in ct for w in PRODUCT_CONTEXT_WORDS)
            if not mentions_product:
                continue
            v_used = [v for v in PRODUCT_VARIANT_WORDS
                      if re.search(r"\b" + v + r"\b", ct)]
            v_missing = [v for v in v_used if v not in prod_name]
            if v_missing:
                findings.append({
                    "check": "product_variant_unconfirmed",
                    "severity": "medium",
                    "description": (
                        f"Caller requested a '{v_missing[0]}' product variant, "
                        f"but the product_lookup result name "
                        f"('{prod_name}') does not include that variant. The "
                        f"agent placed the order without confirming the variant "
                        f"matches the request."
                    ),
                    "turn_ref": f"turn {e['turn']}",
                    "evidence": e["text"],
                    "system_evidence": m_prod.group(0),
                })
                break

    return findings


# --------------------------------------------------------------------------- #
# Prompt construction for the LLM judge
# --------------------------------------------------------------------------- #
def load_rubric(path: Path) -> List[Dict[str, Any]]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("criteria", data) if isinstance(data, dict) else data
    raise RuntimeError(f"Rubric file not found: {path}")


def _render_flat(parsed: Dict[str, Any]) -> str:
    """Render the timeline as compact rows the LLM can cite by turn number."""
    lines = []
    for e in flatten(parsed):
        tag = {"agent": "AGENT", "caller": "CALLER", "sys": "SYS"}[e["role"]]
        lines.append(f"T{e['turn']} {e['timestamp']} [{tag}] {e['text']}")
    return "\n".join(lines)


def _render_init(parsed: Dict[str, Any]) -> str:
    return "\n".join(n["raw"] for n in parsed["system_init"])


def build_prompt(parsed: Dict[str, Any],
                 rubric: List[Dict[str, Any]],
                 prepass: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    rubric_text = "\n".join(f"- {c['name']}: {c['description']}" for c in rubric)
    init_text = _render_init(parsed)
    timeline_text = _render_flat(parsed)
    prepass_text = json.dumps(prepass, indent=2, ensure_ascii=False) if prepass \
        else "[]"

    system = (
        "You are a meticulous QA judge for a generative voice-AI system. "
        "You evaluate call transcripts against a rubric. "
        "You return ONLY a single valid JSON object and nothing else. "
        "Every finding must include an 'evidence' field quoting text that "
        "appears verbatim in the transcript; if you cannot find exact text, "
        "say so rather than inventing it. "
        "The [SYS] action log and system variables are ground truth; the "
        "agent's spoken lines are claims to be checked against that truth."
    )
    user = f"""You will judge the following voice-AI call transcript.

The transcript is provided as structured rows: SYSTEM INIT notes followed by a
TIMELINE of turns (T<n> <timestamp> [AGENT|CALLER|SYS] <text>). The [SYS] rows
are ground truth; the [AGENT] rows are the agent's claims.

RUBRIC (each criterion scored 0-5, 0 = clear failure, 5 = excellent):
{rubric_text}

DETERMINISTIC PRE-PASS FINDINGS (rule-based, already verified; incorporate and
do not contradict these unless you have explicit grounds):
{prepass_text}

Return a JSON object with exactly this shape:
{{
  "transcript_id": "<from header>",
  "overall_score": <0-100>,
  "criteria": [
    {{
      "name": "<criterion name>",
      "score": <0-5>,
      "pass": <true if score >= 3 else false>,
      "reasoning": "<why this score, citing turn numbers>",
      "evidence": "<verbatim quote from the transcript, or empty string>"
    }}
  ],
  "issues": [
    {{
      "severity": "critical" | "high" | "medium" | "low",
      "description": "<what went wrong>",
      "turn_ref": "<e.g. 'turn 4'>",
      "evidence": "<verbatim quote>"
    }}
  ],
  "summary": "<one or two sentence overall judgment>"
}}

Scoring guidance:
- Be specific and cite the turn where a problem occurs (e.g. 'turn 6').
- Do not invent transcript text; if evidence is unavailable, use "".
- "issues" should focus on concrete defects, not restatements of the rubric.
- Trust the [SYS] action log over the agent's words when they conflict.
- The overall_score should be a defensible aggregate of the criterion scores.
- If a pre-pass finding is present, the corresponding issue must appear.

SYSTEM INIT:
{init_text}

TIMELINE:
{timeline_text}

Return only the JSON object.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# --------------------------------------------------------------------------- #
# LLM call
# --------------------------------------------------------------------------- #
def strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def judge_transcript(parsed: Dict[str, Any], rubric: List[Dict[str, Any]],
                     model: str, temperature: float) -> Dict[str, Any]:
    prepass = deterministic_prepass(parsed)
    messages = build_prompt(parsed, rubric, prepass)
    client = get_client()
    response = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature,
    )
    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError(
            "Model returned empty content. For reasoning models the token "
            "budget may have been consumed by reasoning; retry or use a "
            "non-reasoning model via --model."
        )
    cleaned = strip_code_fences(raw)
    try:
        judgment = json.loads(cleaned)
    except json.JSONDecodeError:
        judgment = {"_parse_error": True, "raw": raw}
    # Always attach the deterministic pre-pass so it is visible even on a
    # parse failure or a model that omits an issue.
    judgment["deterministic_findings"] = prepass
    judgment["transcript_id"] = parsed["header"].get("TRANSCRIPT ID", "?")
    judgment["scenario"] = parsed["header"].get("SCENARIO", "?")
    return judgment


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args():
    p = argparse.ArgumentParser(
        description="LLM-as-a-judge for voice-AI transcripts")
    p.add_argument("--input", required=True,
                   help="Transcript file (.txt) or a directory of transcripts")
    p.add_argument("--rubric", default=str(Path(__file__).resolve().parent / "default_rubric.json"),
                   help="Rubric JSON file")
    p.add_argument("--model", default="deepseek/deepseek-v4-flash-0731",
                   help="OpenRouter model id")
    p.add_argument("--temperature", type=float, default=0.2,
                   help="Judge temperature (default 0.2)")
    p.add_argument("--output", help="Output directory; each run creates a timestamped subfolder here so runs never overwrite each other")
    p.add_argument("--run-id", help="Override the run subfolder name (defaults to run-<timestamp>-<shortid>)")
    p.add_argument("--prepass-only", action="store_true",
                   help="Run only the deterministic pre-pass; skip the LLM call")
    return p.parse_args()


def _resolve_inputs(path: Path) -> List[Path]:
    if path.is_dir():
        return sorted(path.glob("conversation-*.txt"))
    return [path]


def _make_run_dir(base: Path, run_id: str = None) -> Path:
    """Create a per-run subdirectory under base so runs never overwrite each other."""
    if not run_id:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        run_id = f"run-{ts}-{uuid.uuid4().hex[:6]}"
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def main() -> int:
    args = parse_args()
    rubric = load_rubric(Path(args.rubric))
    inputs = _resolve_inputs(Path(args.input))
    if not inputs:
        print(f"No transcripts found at {args.input}", file=sys.stderr)
        return 2

    results = []
    for f in inputs:
        parsed = parse_transcript(str(f))
        if args.prepass_only:
            res = {
                "transcript_id": parsed["header"].get("TRANSCRIPT ID", "?"),
                "scenario": parsed["header"].get("SCENARIO", "?"),
                "deterministic_findings": deterministic_prepass(parsed),
            }
        else:
            res = judge_transcript(parsed, rubric, args.model, args.temperature)
        results.append(res)
        tid = res.get("transcript_id", "?")
        n = len(res.get("deterministic_findings", []))
        print(f"[{tid}] pre-pass findings: {n}", file=sys.stderr)

    out = json.dumps(results, indent=2, ensure_ascii=False)
    if args.output:
        run_dir = _make_run_dir(Path(args.output), args.run_id)
        for r in results:
            fn = run_dir / f"{r.get('transcript_id','unknown')}.json"
            fn.write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        # Manifest so runs are comparable when verifying judge accuracy.
        meta = {
            "run_id": run_dir.name,
            "timestamp": datetime.now().isoformat(),
            "model": args.model,
            "temperature": args.temperature,
            "prepass_only": args.prepass_only,
            "transcript_count": len(results),
            "transcript_ids": [r.get("transcript_id", "?") for r in results],
        }
        (run_dir / "run_meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {len(results)} judgments to {run_dir}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
