#!/usr/bin/env python3
"""
Parser for QA transcript files.

Splits a transcript .txt into structured JSON:
  - header fields (transcript id, scenario, outcome, call reason, etc.)
  - metadata (caller on file, phone, email, escalation availability, ...)
  - system_init (list of [SYS] notes from the initialization block)
  - timeline (list of turns, each with a timestamp and ordered entries:
      {"role": "agent"|"caller"|"sys", "text": "..."} )

The structure is what judge.py uses for both its deterministic pre-pass and
the LLM-judge prompt, so the model reasons over rows rather than a raw blob.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _split_sections(text: str) -> Tuple[str, str, str, str]:
    """
    Return (header, metadata, system_init, timeline) as raw text blocks.
    Sections are delimited by full lines of dashes.
    """
    lines = text.splitlines()

    # The sections appear in a fixed order with labels between separators.
    # Locate the label lines to find section boundaries robustly.
    def find_label(prefix: str) -> int:
        for i, ln in enumerate(lines):
            if ln.strip().upper().startswith(prefix):
                return i
        return -1

    meta_i = find_label("CALL METADATA")
    init_i = find_label("SYSTEM INITIALIZATION")
    tl_i = find_label("CONVERSATION TIMELINE")

    header = "\n".join(lines[:meta_i]) if meta_i > 0 else ""
    # Each labeled section runs from the label line to the next label (or EOF).
    def block(start: int, end: int) -> str:
        if start < 0:
            return ""
        return "\n".join(lines[start:end])

    metadata = block(meta_i, init_i if init_i > meta_i else (tl_i if tl_i > meta_i else len(lines)))
    system_init = block(init_i, tl_i if tl_i > init_i else len(lines))
    timeline = block(tl_i, len(lines))
    return header, metadata, system_init, timeline


def _parse_kv_block(text: str) -> Dict[str, str]:
    """
    Parse lines of the form 'Key : Value' into a dict.
    Skips separator/label lines and blanks.
    """
    out: Dict[str, str] = {}
    for ln in text.splitlines():
        s = ln.strip()
        if not s or re.fullmatch(r"-{20,}", s):
            continue
        if s.upper() in ("CALL METADATA", "SYSTEM INITIALIZATION  (ACTIONS & VARIABLES)",
                         "SYSTEM INITIALIZATION", "CONVERSATION TIMELINE"):
            continue
        if ":" not in s:
            continue
        key, _, val = s.partition(":")
        out[key.strip()] = val.strip()
    return out


def _parse_sys_block(text: str) -> List[Dict[str, str]]:
    """
    Parse a block containing [SYS] notes into a list of
      {"raw": "..."} entries, with continuation lines folded in.
    """
    entries: List[Dict[str, str]] = []
    current: str = None  # type: ignore
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        # Skip separator lines (dashes or equals) and the file's trailing banner.
        if re.fullmatch(r"[-=]{20,}", s):
            continue
        if s.upper().startswith("SYSTEM INITIALIZATION") or s.upper().startswith("CONVERSATION TIMELINE"):
            continue
        m = re.match(r"^\[SYS\]\s*(.*)$", s)
        if m:
            if current is not None:
                entries.append({"raw": current})
            current = m.group(1)
        else:
            # continuation of the previous sys note
            if current is not None:
                current += " " + s
    if current is not None:
        entries.append({"raw": current})
    return entries


def _parse_timeline(text: str) -> List[Dict[str, Any]]:
    """
    Parse the CONVERSATION TIMELINE block into ordered turns.

    Each turn: {"timestamp": "11:04:25 PM", "entries": [ {role, text}, ... ]}
    roles: "agent", "caller", "sys".
    Multi-line speech is joined; sys-note continuation lines are folded in.
    """
    turns: List[Dict[str, Any]] = []
    current_turn: Dict[str, Any] = None
    current_speaker: str = None
    current_lines: List[str] = []

    def flush_speaker():
        nonlocal current_speaker, current_lines
        if current_speaker is not None and current_lines:
            joined = " ".join(l.strip() for l in current_lines)
            current_turn["entries"].append({"role": current_speaker, "text": joined})
        current_speaker = None
        current_lines = []

    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.fullmatch(r"[-=]{20,}", s):
            continue
        if s.upper().startswith("CONVERSATION TIMELINE"):
            continue

        # New timestamp -> new turn
        m_ts = re.match(r"^\[(\d{1,2}:\d{2}:\d{2}\s*[AP]M)\]$", s)
        if m_ts:
            flush_speaker()
            current_turn = {"timestamp": m_ts.group(1), "entries": []}
            turns.append(current_turn)
            continue

        if current_turn is None:
            continue

        m_agent = re.match(r"^AI AGENT >\s*(.*)$", s)
        m_caller = re.match(r"^CALLER\s*>\s*(.*)$", s)
        m_sys = re.match(r"^\[SYS\]\s*(.*)$", s)

        if m_agent:
            flush_speaker()
            current_speaker = "agent"
            current_lines = [m_agent.group(1)]
        elif m_caller:
            flush_speaker()
            current_speaker = "caller"
            current_lines = [m_caller.group(1)]
        elif m_sys:
            flush_speaker()
            current_turn["entries"].append({"role": "sys", "text": m_sys.group(1)})
        else:
            # continuation line
            if current_speaker is not None:
                current_lines.append(s)
            elif current_turn["entries"] and current_turn["entries"][-1]["role"] == "sys":
                current_turn["entries"][-1]["text"] += " " + s
            # else: stray line, ignore

    flush_speaker()
    return turns


def parse_transcript(path: str) -> Dict[str, Any]:
    """Parse a transcript file into a structured dict."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    header, metadata, system_init, timeline = _split_sections(text)

    header_kv = _parse_kv_block(header)
    meta_kv = _parse_kv_block(metadata)
    init_notes = _parse_sys_block(system_init)
    turns = _parse_timeline(timeline)

    return {
        "file": str(path),
        "header": header_kv,
        "metadata": meta_kv,
        "system_init": init_notes,
        "timeline": turns,
    }


# Convenience: flatten timeline into a single ordered list of events with turn numbers.
def flatten(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return timeline entries as a flat list with turn_index and timestamp."""
    flat: List[Dict[str, Any]] = []
    for i, turn in enumerate(parsed["timeline"], start=1):
        for entry in turn["entries"]:
            flat.append({
                "turn": i,
                "timestamp": turn["timestamp"],
                "role": entry["role"],
                "text": entry["text"],
            })
    return flat


if __name__ == "__main__":
    # CLI: parse a file and print JSON.
    if len(sys.argv) != 2:
        print("Usage: python3 parse_transcript.py <transcript.txt>", file=sys.stderr)
        sys.exit(2)
    data = parse_transcript(sys.argv[1])
    print(json.dumps(data, indent=2, ensure_ascii=False))
