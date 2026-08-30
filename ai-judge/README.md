# LLM-as-a-judge for voice-AI transcripts

A two-stage judge for evaluating call transcripts:

1. **Deterministic pre-pass** (rule-based, no API cost) cross-references agent
   speech against the `[SYS]` action log and system variables to catch the
   highest-severity defect class: the agent claiming an action succeeded when
   the system action errored or was never called.
2. **LLM judge** scores the call against a rubric using the structured
   transcript plus the pre-pass findings as evidence anchors, returning a
   strict JSON contract with verbatim-quoted evidence.

## Why two stages

The LLM judge alone is unreliable for the "false success" class because it has
to reason about whether a spoken claim matches a system action result across a
long transcript. The deterministic pre-pass makes that check cheap and exact.
The LLM is then free to handle the semantic defects (grounding, tone, leakage,
loops) where its judgment adds value, with the pre-pass findings as anchors it
must not contradict.

## Files

| File | Purpose |
|------|---------|
| `parse_transcript.py` | Parses a transcript `.txt` into structured JSON (header, metadata, system_init, timeline of turns). Also a CLI: `python3 parse_transcript.py <file>` |
| `default_rubric.json` | Generic 6-criterion rubric (grounding, interruption, confirmation, task completion, safety, tone/clarity). Default used by `judge.py` |
| `judge.py` | Deterministic pre-pass + LLM judge. Supports single file, directory, and `--prepass-only` mode |
| `run_all.sh` | Batch runner over a directory of transcripts |
| `run_judge.sh` | Single-file runner (thin wrapper around `judge.py`) |

## Input format

Transcripts are plain-text `.txt` files in the following layout. The parser
(`parse_transcript.py`) keys off the section labels in ALL CAPS. The example
below is **entirely fictional** (a clinic appointment call) and only shows the
file shape the parser expects.

```
================================================================================
TRANSCRIPT ID   : TRN-001
SCENARIO        : Appointment Reschedule
CALL DATE       : 2026-01-15
CALL OUTCOME    : Resolved
CALL REASON     : Reschedule Appointment

--------------------------------------------------------------------------------
 CALL METADATA
--------------------------------------------------------------------------------
Caller Phone Number        : +15550153421
Escalation Availability    : available
Caller On File             : Priya Raman
Email On File              : priya.raman@example.com

--------------------------------------------------------------------------------
 SYSTEM INITIALIZATION  (Actions & Variables)
--------------------------------------------------------------------------------
[SYS] Set Agent Greeting = "Thanks for calling Sunrise Health. How can I help?"
[SYS] Action initialize_conversation -> success

--------------------------------------------------------------------------------
 CONVERSATION TIMELINE
--------------------------------------------------------------------------------
[09:15:02 AM]
AI AGENT > Thanks for calling Sunrise Health. How can I help?
CALLER > I need to move my appointment to next Tuesday.
[09:15:11 AM]
AI AGENT > I've rescheduled you to Tuesday at 2pm.
```

The example above is crafted to trip the `claimed_action_missing` check: the
agent claims a reschedule was completed, but no `[SYS]` reschedule action
exists anywhere in the transcript — a fabricated outcome.

- Lines with `[SYS]` in the timeline are system action results / variables —
  the deterministic pre-pass cross-references speech against these.
- Speaker prefixes: `AI AGENT >`, `CALLER >`.
- The filename or `TRANSCRIPT ID` header identifies each call.

Run the parser on one file to confirm your format matches:

```bash
python3 parse_transcript.py path/to/conversation.txt | less
```

## Prerequisites

- Python 3.7+
- `openai` library (`pip install openai`)
- An OpenRouter API key (default base URL `https://openrouter.ai/api/v1`)

Credentials: set `OPENAI_API_KEY` (and `OPENAI_BASE_URL` if not OpenRouter).
`run_all.sh` / `run_judge.sh` also auto-load an OpenRouter key from Pi's auth
store (`~/.pi/agent/auth.json`) if `OPENAI_API_KEY` is not set.

## Quick start

```bash
# 1. Verify the parser on one transcript (no API cost)
python3 parse_transcript.py ./transcripts/conversation-01.txt | less

# 2. Run only the deterministic pre-pass over a directory (no API cost, no key needed)
./run_all.sh ./transcripts ./findings --prepass-only

# 3. Run the full judge (deterministic + LLM) over a directory
./run_all.sh ./transcripts ./judgments

# 4. Single transcript, full judge, output to stdout
./run_all.sh ./transcripts/conversation-01.txt -
```

`findings/` and `judgments/` are local output directories (gitignored) —
they hold per-run analysis of your conversations and are not versioned.

## judge.py arguments

| Argument | Purpose |
|----------|---------|
| `--input` | A transcript file, or a directory of transcripts. Required. |
| `--rubric` | Rubric JSON. Defaults to `default_rubric.json` next to this script. |
| `--model` | OpenRouter model id. Default `deepseek/deepseek-v4-flash-0731`. |
| `--temperature` | Judge temperature. Default 0.2 (low for consistency). |
| `--output` | Base output directory; each run creates a timestamped subfolder here so runs never overwrite each other |
| `--prepass-only` | Skip the LLM call; run only the deterministic checks. |
| `--run-id` | Override the run subfolder name (defaults to `run-<timestamp>-<shortid>`) |

## Deterministic pre-pass checks

| Check | What it catches | Severity |
|-------|-----------------|---------|
| `action_error_false_success` | Agent claims an action succeeded; system action returned ERROR | critical |
| `claimed_action_missing` | Agent implies an action was done; no matching action exists in the log at all (not even an errored one) | critical |
| `internal_data_disclosure` | Agent speaks content marked INTERNAL/do-not-disclose | critical |
| `hallucinated_account_state` | Agent reports account state (rewards points, etc.) that contradicts system variables | high |
| `confirmation_loop` | Agent asks for confirmation 5+ times | medium |
| `redundant_identity_request` | Agent asks for the caller's name the platform already resolved (greeting uses it via ANI) | medium |
| `verification_skipped_before_disclosure` | Agent skips identity verification then discloses account/payment details | high |
| `product_variant_unconfirmed` | Caller named a product variant the lookup result doesn't contain; order placed without confirming | medium |

## Per-run folders

Every execution with `--output` creates a new timestamped subfolder under the
base directory, so repeated runs (needed to verify judge accuracy on a
non-deterministic model) never overwrite each other. Each run folder contains:

- one `<transcript_id>.json` per transcript
- a `run_meta.json` manifest with the run id, timestamp, model, temperature,
  `--prepass-only` flag, and the list of transcript ids processed

To compare runs, diff or aggregate the per-transcript JSONs across run folders.

## Output schema

```json
{
  "transcript_id": "TRN-001",
  "scenario": "Appointment Reschedule",
  "overall_score": 0,
  "criteria": [
    { "name": "grounding", "score": 0, "pass": false,
      "reasoning": "...", "evidence": "..." }
  ],
  "issues": [
    { "severity": "critical", "description": "...",
      "turn_ref": "turn 2", "evidence": "..." }
  ],
  "summary": "...",
  "deterministic_findings": [ ... ]
}
```

The `deterministic_findings` array is always present, even if the LLM output
fails to parse, so the high-precision checks are never lost.

## Notes on non-determinism

The LLM judge is itself probabilistic. Run it several times over the same
transcript and track per-criterion score variance: a criterion that swings
between pass and fail across runs is itself a signal. The deterministic
pre-pass is stable across runs, which is why the most severe defects live there
rather than in the LLM's judgment.