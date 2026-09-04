# P2P QA Lab — Narrating the Report

The report is the deliverable. Here's how to read it like an auditor.

## Report shape

```json
{
  "api_url": "...",
  "happy_path": { "status": "PASS|FAIL|INCOMPLETE", "steps": [...] },
  "adversarial": [
    { "rule": "overpayment_protection", "status": "HELD|BREACHED|NOT_TESTED",
      "evidence": {"request": "...", "status": 400, "response": "..."}, "note": "..." }
  ],
  "integration_issues": [],
  "summary": "..."
}
```

## Reading the fields in `happy_path.steps`

Each step carries three fields that are easy to skim past:

- **`interpretation`** — the explorer's own evaluation of whether that step's
  *outcome was correct*, not the raw status. On LLM-driven steps this is the
  model's `INTERPRET:` line ("partial receipt recorded — 6/10 units; flag
  should be partial=true"); on create steps there may also be a
  deterministic fallback ("invoice created; amount must not exceed received
  value"). This is the evidence that the agent is *reasoning about results*,
  not just issuing HTTP calls.
- **`verified`** — applies **only to create steps** (`create_vendor`,
  `create_po`, `create_invoice`). `true` means the double-verification GET
  succeeded and the persisted record echoed the sent values. `false` on a
  create is a **critical flag** (phantom write / POST lied). On every
  non-create step `verified` and `verify_note` are **absent entirely** —
  verification is not applicable to reads/transitions.
- **`verifies`** — on a **GET step only**: the name of the create step it
  is the double-verify proof for (e.g. `get_vendor` with
  `verifies="create_vendor"`). The GET is the verification itself; it
  carries the proof marker, but is never marked `verified` in its own
  right (that would be circular).

## The three hard rules of reading it

1. **Status codes are not the truth; business recomputation is.** The judge's
   pre-pass replays the step log and re-derives every invariant from raw
   payloads (exact integer-cent math). A 200 that overpaid is a BREACH even
   if the API said "OK"; a 400 on a legit flow is FAIL even if the API was
   "polite". Point at the recomputed numbers (received_value_cents vs
   invoice_amount_cents; debits vs credits) as the evidence.

2. **BREACHED is a finding, not a test failure — but read it hard.** On the
   clean mock, `authorization`, `pii_exposure`, and `injection` are BREACHED
   *by design* — the mock is a realistic messy legacy API: it ships **authless**
   (so `GET /vendors` exposes vendor contact email + bank_account_last4 to any
   caller, and injection payloads like `x' OR '1'='1` / `<script>` are accepted
   and stored verbatim rather than sanitized). These are the same findings
   you'd expect an auditor to flag on a real legacy API. Every other rule
   should be HELD on a correct API. If a *financial* rule is BREACHED (e.g.
   overpayment leaked), that's the headline: double payment risk.

3. **NOT_TESTED is intellectual honesty, not a gap.** The pre-pass won't
   claim a verdict with no evidence. If `partial_receipt_flag` is
   NOT_TESTED because the happy path never ran a partial receipt, say so and
   run the adversarial partial probe.

## Per-rule financial risk (what an auditor cares about)

| Rule | If BREACHED, the real-world harm |
|---|---|
| overpayment_protection | Paying more than goods received → direct cash loss |
| match_gate | Approving unblessed invoices → fraud / wrong obligation |
| partial_receipt_flag | Silent under-receipt → overpayment that looks matched |
| inactive_vendor_gate | New obligation to a blocked vendor |
| gl_balance | Books don't balance → audit failure, hidden theft |
| duplicate_detection | Double payment on one invoice |
| authorization | Anyone reads/mutates financial records |
| pii_exposure | Tenant/payment data leak → regulatory exposure |
| mis_credit | Refund to a party who never paid → fraud payout |
| injection | Data exfiltration / tampering |
| destructive_ops | Silent data destruction |
| data_integrity | POST lies about what was saved → unreconcilable books |

## The two-stage judge (why it's trustworthy)

- **Deterministic pre-pass**: exact, cheap, stable across runs. It's the
  anchor. It catches the "false success" class — claiming a guardrail held
  when the math says it leaked.
- **LLM summary**: narrative, constrained to not contradict the anchors.
  The LLM adds interpretation (which breach is *operationally* worst);
  the pre-pass keeps it honest.
- If you re-run and the LLM summary varies but the verdicts don't, that's
  the design working — the variance lives in prose, not in the verdicts.

## Where the judge's own evaluation lives

The judge is itself an agent, so its *work product* is in two places:

- **`reports/<ts>/steps.jsonl`** — the full, raw step log both agents wrote
  (every request client sent, every status + response, plus each step's
  `interpretation`/`verified`/`verify_note`). The judge's pre-pass replays
  this log to recompute each invariant — that replay *is* its evidence base.
- **`reports/<ts>/report.json`** — the judge's verdicts (`adversarial[]`,
  each with concrete `evidence`), plus its synthesis in `summary`.
  `integration_issues[]` is the judge surfacing client-detected schema
  drift the agents adapted to.

The `evidence` object on every verdict is the output of the *deterministic*
judge (raw request/status/response or recomputed numbers). The `summary` is
the output of the *LLM* judge, written under the constraint that it must not
contradict the deterministic evidence.

## Demo narrative script (60 seconds)

> "The explorer walked vendor→PO→submit→partial-receive→invoice→match→approve,
> double-verified every create with a GET, and interpreted each step. The
> adversarial layer probed 12 guardrails — six financial invariants plus
> authorization, PII, mis-credit fraud, injection, destructive ops, and
> data-integrity. The judge recomputed each invariant from the raw step log —
> not from status codes — and only the things verified with byte-level
> evidence got verdicts. Net: all financial guardrails held;
> authorization, PII exposure and input-sanitization gaps surface on the
> legacy mock (authless + no sanitization), each with the request trace as
> evidence. The report is at reports/<ts>/report.json."