#!/usr/bin/env python3
"""ATS Check — run an external ATS scan on the rendered deliverable.

Submits the deliverable (PDF preferred — it is the submitted format) to
the user's ATS scan service, waits for the match report, and saves it as
JSON for `ats_audit.py --report-json`.

NO service specifics live in this file. The endpoints, headers, and
cookies come from the user's own "Copy as cURL" exports saved in
`<skill-root>/.ats-check/curl.txt` (never committed; the scan service
sees the resume text — assume nothing else in the repo does). See
"Setup".

Setup — save five cURL requests, captured from the scan service's web
app in the browser DevTools (Network tab, "Copy as cURL"), into
`<skill-root>/.ats-check/curl.txt`, separated by blank lines (the skill
root is this repo's resume-tailoring/ directory — the config lives with
the workflow's other personal assets, gitignored, and survives session
cleanup):

    1. the resume-upload POST (multipart, file upload)
    2. the job-description POST (JSON body with the JD text)
    3. the opportunity POST (JSON body linking resume + job description)
    4. the opportunity-update PUT (re-points an existing opportunity at
       the freshly uploaded resume — required so a re-scan of the same
       resume+JD pair reflects the NEW upload instead of the first one)
    5. the report GET (fetches the match report for one opportunity)

This tool classifies each request by its path/body/method, rebuilds the
chain for a NEW scan (fresh ids, the deliverable's file, this JD's text),
and chains the rotating session cookies itself: every response rotates the
session cookies, so requests run through a curl cookie jar (-b/-c) and
the CSRF header is re-derived from the jar before each request (the
header is the URL-decoded token cookie value).

usage:
    python3 scripts/ats_check.py scan <resume.pdf|docx> <jd.txt>
        [--out <report.json>] [--timeout 300] [--interval 6]
    python3 scripts/ats_check.py check

Exit codes: 0 report saved; 1 report not ready in time; 2 config/HTTP
error (401/403 -> credentials expired, re-save curl.txt).

Auth note: the jar is seeded once from curl.txt and then only rotated.
When the scan starts returning 401/403, re-export the requests from a
logged-in browser session — the cookie values are the only secret.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

# Config lives in the SKILL ROOT (this repo's resume-tailoring/), next
# to the master resume and JD files it belongs to — gitignored, durable
# across sessions (a ~/.config location was wiped by a sandbox cleanup
# once). A dot-directory: shell globs (`git add *`) skip dotfiles, so the
# credentials cannot be swept up by a blanket stage. Files are written
# 0600. No fallback location — one path, one source of truth.
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(SKILL_ROOT, ".ats-check")
CURL_FILE = os.path.join(CONFIG_DIR, "curl.txt")
JAR_FILE = os.path.join(CONFIG_DIR, "cookies.txt")
CSRF_COOKIE = "XSRF-TOKEN"
CSRF_HEADER = "x-xsrf-token"

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


# ---------------------------------------------------------------- config

def parse_curl_file(path=CURL_FILE):
    """Parse the saved cURL exports into request dicts.

    Returns a list of {"url", "method", "headers", "cookies", "body"}
    dicts, in file order. Headers keep their original casing in the
    values; the cookie (-b/--cookie) blob is separated out.
    """
    if not os.path.exists(path):
        raise SystemExit(
            f"error: {path} not found — save the four 'Copy as cURL' "
            "exports there (see the module docstring's Setup section)")
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    # One request per 'curl' line start; backslash continuations joined.
    raw_requests, cur = [], None
    for line in text.splitlines():
        if line.lstrip().startswith("curl "):
            if cur:
                raw_requests.append(cur)
            cur = [line]
        elif cur is not None and line.strip():
            cur.append(line)
    if cur:
        raw_requests.append(cur)
    if not raw_requests:
        raise SystemExit(f"error: no cURL requests parsed from {path}")

    requests = []
    for lines in raw_requests:
        joined = " ".join(l.rstrip("\\").strip() for l in lines)
        req = {"url": None, "method": "GET", "headers": [],
               "cookies": None, "body": None}
        # URL: the first quoted token after curl (or --url's value).
        m_url = (re.search(r"--url\s+'([^']+)'", joined)
                 or re.search(r"^curl\s+'([^']+)'", joined))
        if not m_url:
            continue
        req["url"] = m_url.group(1)
        m = re.search(r"\s(?:-b|--cookie)\s+'([^']*)'", joined)
        if m:
            req["cookies"] = m.group(1)
        for h in re.finditer(r"(?:^|\s)-H\s+'([^']*)'", joined):
            req["headers"].append(h.group(1))
        m = re.search(r"--data-raw\s+\$?'(.*)'\s*(?:--|$)", joined, re.S)
        if m:
            req["body"] = m.group(1)
            req["method"] = "POST"
        # Explicit verb (-X PUT, --request PUT) overrides the data-raw POST
        # default — the opportunity-update request is a PUT with a JSON body.
        m = re.search(r"(?:-X|--request)\s+'([^']+)'", joined)
        if m:
            req["method"] = m.group(1).upper()
        requests.append(req)
    return requests


def classify(reqs):
    """Identify the five chain requests from the saved exports.

    Returns {"resume", "job", "opportunity", "opportunity_update",
    "report"} request dicts. The report GET's and the opportunity PUT's
    numeric opportunity id are replaced with {id} so the templates serve
    future scans.
    """
    kinds = {}
    for r in reqs:
        path = urllib.parse.urlparse(r["url"]).path
        is_multipart = any(h.lower().startswith("content-type: multipart/")
                           for h in r["headers"])
        if r["method"] == "GET" and re.search(r"/opportunities/\d+", path):
            # Template for future scans: {id} placeholder, and the
            # match report lives one path segment below the opportunity.
            # A query string (parser/experiment flags from the saved
            # export) must survive the templating.
            url = re.sub(r"/opportunities/\d+", "/opportunities/{id}",
                         r["url"])
            base, _, query = url.partition("?")
            tail = base.rstrip("/").rsplit("/", 1)[-1]
            if tail not in ("report", "match-report"):
                base = base.rstrip("/") + "/report"
            url = base + (("?" + query) if query else "")
            kinds["report"] = dict(r, url=url)
        elif r["method"] == "POST" and is_multipart:
            kinds["resume"] = r
        elif r["method"] == "POST" and r.get("body", "") and \
                '"content"' in r["body"]:
            kinds["job"] = r
        elif r["method"] == "POST" and "opportunities" in path:
            kinds["opportunity"] = r
        elif r["method"] == "PUT" and re.search(r"/opportunities/\d+", path):
            # The re-scan update: bound to a freshly uploaded resume. The
            # saved export's literal id becomes {id}; the body's ids are
            # rebuilt at scan time (see _opportunity_update_body).
            url = re.sub(r"/opportunities/\d+", "/opportunities/{id}",
                         r["url"])
            kinds["opportunity_update"] = dict(r, url=url)
    missing = {"resume", "job", "opportunity", "opportunity_update",
               "report"} - set(kinds)
    if missing:
        raise SystemExit(
            "error: could not classify saved request(s) as "
            + ", ".join(sorted(missing))
            + " — re-export the requests (see Setup)")
    return kinds


# ------------------------------------------------------------------ jar

def _write_private(path, text):
    """Write a credential-bearing file owner-only (0600) — the jar and
    anything holding session cookies must not be group/world readable.
    os.open's mode only applies at creation, so chmod unconditionally."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


def seed_jar(cookies, url, jar=None):
    """Write the exported cookie blob into the Netscape jar (once)."""
    jar = jar or JAR_FILE
    host = urllib.parse.urlparse(url).netloc
    lines = ["# Netscape HTTP Cookie File",
             "# Seeded from curl.txt; rotated by curl -c afterwards."]
    for pair in cookies.split("; "):
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        lines.append(f".{host}\tTRUE\t/\tTRUE\t9999999999\t{name}\t{value}")
    _write_private(jar, "\n".join(lines) + "\n")


def jar_value(name, jar=None):
    """Current value of a cookie from the jar (HttpOnly lines included —
    curl prefixes them with '#HttpOnly_', which is not a comment)."""
    jar = jar or JAR_FILE
    with open(jar, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5] == name:
                return parts[6].strip()
    return None


def csrf_header():
    """The rotating CSRF header value: the URL-decoded token cookie."""
    value = jar_value(CSRF_COOKIE)
    return f"{CSRF_HEADER}: {urllib.parse.unquote(value)}" if value else None


# -------------------------------------------------------------- requests

def _browser_headers(saved_headers):
    """The saved request's headers minus the ones rebuilt per request:
    the cookie (jar), CSRF (rotates), and multipart content-type (curl
    sets its own boundary)."""
    skip = ("cookie:", "x-xsrf-token:")
    out = []
    for h in saved_headers:
        low = h.lower()
        if any(low.startswith(s) for s in skip):
            continue
        if low.startswith("content-type: multipart/"):
            continue
        out.append("-H")
        out.append(h)
    return out


def request(url, headers, *, method=None, json_body=None, multipart=None,
            timeout=90):
    cmd = ["curl", "-s", "-S", "--max-time", str(timeout),
           "-b", JAR_FILE, "-c", JAR_FILE, "-w", "\n%{http_code}"]
    if method and method != "GET":
        cmd += ["-X", method]
    csrf = csrf_header()
    if csrf:
        cmd += ["-H", csrf]
    cmd += headers
    if json_body is not None:
        cmd += ["-H", "content-type: application/json",
                "--data-raw", json.dumps(json_body)]
    if multipart is not None:
        path, mime = multipart
        cmd += ["-F", f"name=auto:{os.path.basename(path)}",
                "-F", f"original_file=@{path};type={mime}"]
    r = subprocess.run(cmd + [url], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise SystemExit(f"error: curl failed ({r.returncode}): "
                         f"{r.stderr[:300]}")
    body, _, code = r.stdout.rpartition("\n")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None
    return int(code), parsed, body


def extract_id(data):
    """The created object's id from a response. Three observed shapes,
    checked in order: top-level {"id": N, ...} (resume upload — whose
    "data" field is the docx parse metadata, NOT a wrapper), the
    {"data": {"id": N}} wrapper (job/opportunity), and the 409 dedupe
    body {"errors": {"duplicate_opportunity": {"opportunity":
    {"id": N}}}}. Direct paths only — no tree search, which could match
    unrelated nested ids."""
    if isinstance(data, dict):
        if isinstance(data.get("id"), int):
            return data["id"]
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("id"), int):
            return inner["id"]
        err = (data.get("errors") or {}).get("duplicate_opportunity") or {}
        opp = err.get("opportunity") if isinstance(err, dict) else None
        if isinstance(opp, dict) and isinstance(opp.get("id"), int):
            return opp["id"]
    return None


def report_ready(data):
    """A report GET is ready when the wrapped object carries the match
    rate or findings (otherwise the scan is still processing)."""
    obj = data.get("data") if isinstance(data, dict) else None
    obj = obj if isinstance(obj, dict) else data
    if not isinstance(obj, dict):
        return False
    return bool(obj.get("matchRate") or obj.get("findings"))


# ------------------------------------------------------------------ flow

def _posting_url(jd_text):
    """The job posting URL persisted with the JD (SKILL Step 1's
    'Posting URL: <url>' first line), or None.

    A line whose token is not an http(s) URL (a '(not provided)' or
    '(ask user)' placeholder) is treated as missing — a placeholder
    PATCHed to the service lands in the report as garbage ('url=(not)'
    in a real session). SKILL Step 1: line present means a real URL;
    when the URL is unknown, omit the line entirely."""
    for line in jd_text.splitlines():
        m = re.match(r"\s*posting url:\s*(\S+)", line, re.I)
        if m:
            url = m.group(1)
            if urllib.parse.urlparse(url).scheme in ("http", "https"):
                return url
            print(f"note: 'Posting URL: {url}' is not an http(s) URL — "
                  "treating as missing. Omit the line entirely when the "
                  "URL is unknown (SKILL Step 1); a placeholder PATCHed "
                  "to the service is garbage in the report.",
                  file=sys.stderr)
            return None
    return None


def _opportunity_update_body(saved_body, opp_id, resume_id, job_id):
    """Rebuild the saved opportunity-update body with the fresh ids.

    The saved export's ``--data-raw`` body is the per-scan shape
    ("{id, resume_id, job_description_id}" here). The numeric values are
    the first scan's ids and must be replaced with this run's uploads — a
    bare re-post of the template would silently re-point the opportunity
    at the STALE resume. Keys are recognized by name, so the body shape
    stays the service's; unknown keys keep their saved values. Returns
    None when the body is not JSON (caller aborts with an actionable
    error rather than sending a proxybag).
    """
    try:
        obj = json.loads(saved_body)
    except (TypeError, ValueError):
        return None
    mapping = {"id": opp_id, "opportunity_id": opp_id,
               "resume_id": resume_id, "job_description_id": job_id}

    def _sub(o):
        if isinstance(o, dict):
            return {k: (mapping.get(k, v) if k in mapping else _sub(v))
                    for k, v in o.items()}
        if isinstance(o, list):
            return [_sub(x) for x in o]
        return o

    return _sub(obj)


def scan(resume_path, jd_path, *, out=None, timeout=300, interval=6,
         config=CURL_FILE, company=None):
    if not os.path.exists(resume_path):
        raise SystemExit(f"error: resume file not found: {resume_path}")
    if not os.path.exists(jd_path):
        raise SystemExit(f"error: JD file not found: {jd_path}")
    mime = MIME_BY_EXT.get(os.path.splitext(resume_path)[1].lower())
    if mime is None:
        raise SystemExit("error: resume must be a .pdf or .docx — the "
                         "formats the deliverable is submitted in")
    if os.path.exists(config):
        os.chmod(config, 0o600)  # curl.txt holds session cookies

    kinds = classify(parse_curl_file(config))
    for r in kinds.values():
        if r.get("cookies") and not os.path.exists(JAR_FILE):
            os.makedirs(CONFIG_DIR, exist_ok=True)
            seed_jar(r["cookies"], r["url"])
    if not os.path.exists(JAR_FILE):
        raise SystemExit("error: no cookies in the saved requests")

    resume_headers = _browser_headers(kinds["resume"]["headers"])
    code, data, body = request(kinds["resume"]["url"], resume_headers,
                               method="POST", multipart=(resume_path, mime))
    resume_id = extract_id(data) if code in (200, 201) else None
    print(f"[1] resume upload -> {code}, resume_id={resume_id}")
    if not resume_id:
        _fail(code, body)

    with open(jd_path, encoding="utf-8", errors="replace") as f:
        jd_text = f.read()
    code, data, body = request(kinds["job"]["url"],
                               _browser_headers(kinds["job"]["headers"]),
                               method="POST", json_body={"content": jd_text})
    job_id = extract_id(data) if code in (200, 201) else None
    print(f"[2] job creation -> {code}, job_description_id={job_id}")
    if not job_id:
        _fail(code, body)

    code, data, body = request(
        kinds["opportunity"]["url"],
        _browser_headers(kinds["opportunity"]["headers"]), method="POST",
        json_body={"job_description_id": job_id, "resume_id": resume_id,
                   "stage": "saved"})
    opp_id = extract_id(data) if code in (200, 201) else None
    if code == 409 and not opp_id:
        # The service dedupes identical resume + JD pairs and returns the
        # existing opportunity — reuse it instead of failing.
        try:
            opp_id = extract_id(json.loads(body))
        except json.JSONDecodeError:
            opp_id = None
        if opp_id:
            print(f"[3] opportunity -> 409 duplicate, reusing "
                  f"opportunity_id={opp_id} (same resume + JD)")
    else:
        print(f"[3] opportunity -> {code}, opportunity_id={opp_id}")
    if not opp_id:
        _fail(code, body)

    # Re-point the opportunity at the freshly uploaded resume. The
    # service dedupes identical resume+JD pairs, so a re-scan can reuse
    # an existing opportunity created against an EARLIER upload — without
    # this PUT the report stays bound to the old resume's text and a
    # "score didn't move" is actually a stale parse (the bug fixed here).
    update = kinds.get("opportunity_update")
    if update:
        update_body = _opportunity_update_body(
            update.get("body"), opp_id, resume_id, job_id)
        if update_body is None:
            raise SystemExit(
                "error: could not parse the saved opportunity-update body "
                "(expected JSON --data-raw) — re-export the PUT request")
        update_url = update["url"].replace("{id}", str(opp_id))
        code, data, body = request(
            update_url, _browser_headers(update["headers"]),
            method="PUT", json_body=update_body)
        print(f"[3b] opportunity update -> {code} "
              f"(resume_id={resume_id}, job_description_id={job_id})")
        if code not in (200, 201, 204):
            _fail(code, body)

    # Attach the posting metadata the way the browser flow does — the
    # service's ATS-identification and several findings depend on the
    # posting URL (SKILL Step 1 persists it with the JD).
    posting_url = _posting_url(jd_text)
    if posting_url:
        patch = {"url": posting_url}
        if company:
            patch["company"] = company
        code, data, body = request(
            f"{kinds['opportunity']['url']}/{opp_id}",
            _browser_headers(kinds["opportunity"]["headers"]),
            method="PATCH", json_body=patch)
        print(f"[3c] opportunity metadata -> {code} "
              f"(url={posting_url}{', company=' + company if company else ''})")
    else:
        print("[3c] no Posting URL in the JD file — ATS cannot be "
              "identified (SKILL Step 1)")

    report_url = kinds["report"]["url"].replace("{id}", str(opp_id))
    report_headers = _browser_headers(kinds["report"]["headers"])
    deadline = time.time() + timeout
    report = None
    while time.time() < deadline:
        code, data, body = request(report_url, report_headers)
        if code == 200 and report_ready(data):
            report = data.get("data") if isinstance(data.get("data"),
                                                    dict) else data
            break
        time.sleep(interval)
    if report is None:
        print(f"error: report not ready after {timeout}s — the scan may "
              "still be processing; retry the GET later or raise "
              "--timeout")
        return 1

    out = out or os.path.splitext(resume_path)[0] + ".ats-check.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f)
    mr = report.get("matchRate") or {}
    fm = {f["key"]: f for f in report.get("findings", [])
          if isinstance(f, dict)}
    wc = (fm.get("wordCount") or {}).get("variables", {}).get("wordCount")
    ats = (fm.get("atsTip") or {}).get("variables", {}).get("ats")
    print(f"[4] report ready -> saved {out}")
    print(f"    matchRate: {mr.get('score')}")
    print(f"    wordCount: {wc} (cross-check only — the cap uses "
          "ats_audit's own count)")
    if ats:
        print(f"    target ATS: {ats}")
    elif posting_url:
        print("    target ATS: the service could not match this posting "
              "URL to a known ATS — ATS-specific findings are unavailable "
              "for this posting")
    else:
        print("    target ATS: NOT identified — the JD file has no "
              "'Posting URL:' line (SKILL Step 1); add it and re-scan")
    print(f"    next: ats_audit.py {resume_path} --jd {jd_path} "
          f"--report-json {out}")
    return 0


def _fail(code, body):
    if code in (401, 403):
        raise SystemExit(
            f"error: {code} — credentials expired. Re-export the four "
            f"requests from a logged-in browser session into "
            f"{CURL_FILE} (delete {JAR_FILE} to re-seed).")
    raise SystemExit(f"error: unexpected {code}: {body[:300]}")


def check(config=CURL_FILE):
    """Validate the saved config without scanning: classify the four
    requests, verify the jar/CSRF state."""
    kinds = classify(parse_curl_file(config))
    print("config ok — requests found:")
    for kind, r in sorted(kinds.items()):
        print(f"  {kind:12s} {r['method']:4s} {r['url']}")
    if os.path.exists(JAR_FILE):
        print(f"cookie jar: {JAR_FILE} (seeded; rotated on every request)")
        print("CSRF cookie in jar:", bool(jar_value(CSRF_COOKIE)))
    else:
        print("cookie jar: not yet seeded (first scan seeds it)")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]

    def _flag(name, cast=str, default=None):
        if name not in rest:
            return default
        i = rest.index(name)
        if i + 1 >= len(rest):
            raise SystemExit(f"error: {name} needs a value")
        return cast(rest[i + 1])

    if cmd == "check":
        return check(_flag("--config") or CURL_FILE)
    if cmd == "scan":
        # Flags may appear before or after the positionals.
        flag_names = ("--config", "--out", "--timeout", "--interval",
                      "--company")
        positional, skip_next = [], False
        for a in rest:
            if skip_next:
                skip_next = False
                continue
            if a in flag_names:
                skip_next = True
                continue
            positional.append(a)
        if len(positional) < 2:
            print(__doc__)
            return 2
        return scan(positional[0], positional[1],
                    out=_flag("--out"),
                    timeout=_flag("--timeout", cast=int, default=300),
                    interval=_flag("--interval", cast=int, default=6),
                    config=_flag("--config") or CURL_FILE,
                    company=_flag("--company"))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
