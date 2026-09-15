"""Normalize external ATS and internal no-host terms for source mining."""

import hashlib
import json
import re


def _key(term):
    return re.sub(r"\s+", " ", term.strip()).casefold()


def _add(queue, seen, term, source):
    if not isinstance(term, str) or not term.strip():
        return
    key = _key(term)
    if key not in seen:
        seen[key] = len(queue)
        queue.append({"term": term.strip(), "sources": [source]})
    elif source not in queue[seen[key]]["sources"]:
        queue[seen[key]]["sources"].append(source)


def missing_skills(report):
    """{"hard": [...], "soft": [...]} external skills with zero resume hits.

    The ONE parser for the scan report's keyword lists — shared by the
    scan's summary print (ats_check) and the normalized gap queue. Both
    categories are returned even when one is empty, so a soft-skill gap
    cannot be silently dropped.
    """
    result = {"hard": [], "soft": []}
    skills = report.get("skills") if isinstance(report, dict) else None
    if not isinstance(skills, dict):
        return result
    for category in result:
        entries = skills.get(category, [])
        if not isinstance(entries, list):
            continue
        result[category] = [entry["name"] for entry in entries
                            if isinstance(entry, dict)
                            and entry.get("name")
                            and entry.get("resumeCount") == 0]
    return result


def normalize_gaps(report, internal_terms=()):
    """Merge missing external hard/soft skills with internal no-host terms."""
    queue, seen = [], {}
    missing = missing_skills(report)
    for category, source in (("hard", "external-hard"),
                             ("soft", "external-soft")):
        for name in missing[category]:
            _add(queue, seen, name, source)
    for term in internal_terms:
        _add(queue, seen, term, "internal")
    return queue


def gap_fingerprint(gaps):
    """Stable digest for a normalized gap queue."""
    payload = json.dumps(gaps, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _file_fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_artifact(report_path, resume_path, internal_terms, output_path):
    """Write a normalized, freshness-bound external gap artifact."""
    with open(report_path, encoding="utf-8") as source:
        report = json.load(source)
    gaps = normalize_gaps(report, internal_terms)
    artifact = {
        "schema": 1,
        "reportPath": report_path,
        "resumePath": resume_path,
        "reportFingerprint": _file_fingerprint(report_path),
        "resumeFingerprint": _file_fingerprint(resume_path),
        "gapFingerprint": gap_fingerprint(gaps),
        "gaps": gaps,
    }
    with open(output_path, "w", encoding="utf-8") as output:
        json.dump(artifact, output, indent=2, ensure_ascii=False)
        output.write("\n")
    return artifact
