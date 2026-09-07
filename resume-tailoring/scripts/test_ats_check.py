"""Unit tests for ats_check.py — the external scan chain (offline: no
network; subprocess is exercised in the live validated run).

Run from the scripts directory:

    cd ~/.pi/agent/skills/resume-tailoring/scripts && python3 -m unittest test_ats_check
"""

import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import ats_check as ac  # noqa: E402

# Synthetic saved exports: same shapes as real "Copy as cURL" output, no
# real service, no credentials.
SAMPLE_CURLS = """
curl --url 'https://ats.example/api/v4/resumes' \\
  -H 'accept: application/json, text/plain, */*' \\
  -H 'content-type: multipart/form-data; boundary=----WebKitFormBoundaryX' \\
  -b 'session_cookie=abc123; csrf_token=DEF456%3D; logged_in=1' \\
  -H 'origin: https://app.example.com' \\
  -H 'user-agent: Mozilla/5.0 Test Browser' \\
  --data-raw $'------WebKitFormBoundaryX\\r\\nContent-Disposition: form-data; name="name"\\r\\n\\r\\nauto:resume.pdf\\r\\n------WebKitFormBoundaryX--\\r\\n'

curl --url 'https://ats.example/api/v4/jobs' \\
  -H 'accept: application/json, text/plain, */*' \\
  -H 'content-type: application/json' \\
  -b 'session_cookie=abc123; csrf_token=DEF456%3D' \\
  --data-raw '{"content":"Sample job description text"}'

curl --url 'https://ats.example/api/v4/opportunities' \\
  -H 'accept: application/json, text/plain, */*' \\
  -H 'content-type: application/json' \\
  -b 'session_cookie=abc123; csrf_token=DEF456%3D' \\
  --data-raw '{"job_description_id":83215311,"resume_id":28475091,"stage":"saved"}'

curl --url 'https://ats.example/api/v4/opportunities/12807851' \\
  -H 'accept: application/json, text/plain, */*' \\
  -b 'session_cookie=abc123; csrf_token=DEF456%3D'
"""


class ConfigParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(SAMPLE_CURLS)
        cls.reqs = ac.parse_curl_file(cls.path)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def test_four_requests_parsed(self):
        self.assertEqual(len(self.reqs), 4)

    def test_urls_extracted(self):
        self.assertEqual(self.reqs[0]["url"],
                         "https://ats.example/api/v4/resumes")

    def test_cookie_blob_separated_from_headers(self):
        self.assertEqual(self.reqs[0]["cookies"],
                         "session_cookie=abc123; csrf_token=DEF456%3D; "
                         "logged_in=1")
        # The -b blob must not leak into the -H header list.
        self.assertFalse(any("csrf_token" in h
                             for h in self.reqs[0]["headers"]))

    def test_methods_detected(self):
        self.assertEqual([r["method"] for r in self.reqs],
                         ["POST", "POST", "POST", "GET"])

    def test_multiline_body_parsed(self):
        self.assertIn("form-data", self.reqs[0]["body"])
        self.assertIn("Sample job description text", self.reqs[1]["body"])

    def test_missing_file_is_actionable(self):
        with self.assertRaises(SystemExit) as cm:
            ac.parse_curl_file("/nonexistent/curl.txt")
        self.assertIn("Copy as cURL", str(cm.exception))


class ClassifyTests(unittest.TestCase):
    QUERY_CURLS = SAMPLE_CURLS.replace(
        "curl --url 'https://ats.example/api/v4/opportunities/12807851' \\",
        "curl --url 'https://ats.example/api/v4/opportunities/12807851"
        "/match-report?advanced_parser_enabled=true' \\")

    def test_all_four_kinds_classified(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(SAMPLE_CURLS)
        try:
            kinds = ac.classify(ac.parse_curl_file(path))
        finally:
            os.unlink(path)
        self.assertEqual(set(kinds),
                         {"resume", "job", "opportunity", "report"})

    def test_report_url_templated_with_report_suffix(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(SAMPLE_CURLS)
        try:
            kinds = ac.classify(ac.parse_curl_file(path))
        finally:
            os.unlink(path)
        # The saved GET's numeric id becomes {id}; the report endpoint is
        # one path segment below the opportunity.
        self.assertEqual(kinds["report"]["url"],
                         "https://ats.example/api/v4/opportunities/{id}"
                         "/report")

    def test_report_query_string_survives_templating(self):
        # The ATS-verification export carries query flags and its own
        # report path segment — both must survive the templating.
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(self.QUERY_CURLS)
        try:
            kinds = ac.classify(ac.parse_curl_file(path))
        finally:
            os.unlink(path)
        self.assertEqual(
            kinds["report"]["url"],
            "https://ats.example/api/v4/opportunities/{id}/match-report"
            "?advanced_parser_enabled=true")

    def test_missing_kind_is_actionable(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(SAMPLE_CURLS.split("\ncurl --url "
                    "'https://ats.example/api/v4/jobs'", maxsplit=1)[0])
        try:
            with self.assertRaises(SystemExit) as cm:
                ac.classify(ac.parse_curl_file(path))
        finally:
            os.unlink(path)
        self.assertIn("job", str(cm.exception))


class ConfigLocationTests(unittest.TestCase):
    """The config lives in the SKILL ROOT (.ats-check/) — with the
    workflow's other personal assets, gitignored, and durable across
    session cleanup. No fallback: one path, one source of truth."""

    def test_config_dir_is_skill_root_dotdir(self):
        # scripts/ats_check.py -> skill root is its parent directory.
        expected = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(ac.__file__))),
            ".ats-check")
        self.assertEqual(ac.CONFIG_DIR, expected)

    def test_config_dir_not_under_home_config(self):
        # A ~/.config location was wiped by a sandbox session cleanup —
        # the whole point of the relocation. Never resolve there.
        self.assertFalse(
            ac.CONFIG_DIR.startswith(os.path.join(os.path.expanduser("~"),
                                                  ".config")))

    def test_write_private_enforces_0600(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            os.chmod(path, 0o644)
            ac._write_private(path, "secret content")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(open(path).read(), "secret content")
        finally:
            os.unlink(path)


class JarTests(unittest.TestCase):
    def setUp(self):
        fd, self.jar = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        os.unlink(self.jar)
        self._saved_jar = ac.JAR_FILE
        ac.JAR_FILE = self.jar  # never touch the real user jar in tests
        ac.seed_jar("session_cookie=abc123; XSRF-TOKEN=TOK%3D",
                    "https://ats.example/api/v4/resumes", jar=self.jar)

    def tearDown(self):
        os.unlink(self.jar)
        ac.JAR_FILE = self._saved_jar

    def test_jar_seeded_to_patched_path(self):
        self.assertTrue(os.path.exists(self.jar))

    def test_plain_cookie_value_read(self):
        self.assertEqual(ac.jar_value("session_cookie"), "abc123")

    def test_httponly_lines_not_treated_as_comments(self):
        # curl prefixes HttpOnly cookies with '#HttpOnly_' — the reader
        # must strip the prefix, not skip the line (the session cookie is
        # HttpOnly; skipping it breaks rotation).
        with open(ac.JAR_FILE, "a", encoding="utf-8") as f:
            f.write("#HttpOnly_.ats.example\tTRUE\t/\tTRUE\t9999999999\t"
                    "rotated_session\txyz789\n")
        self.assertEqual(ac.jar_value("rotated_session"), "xyz789")

    def test_csrf_header_is_url_decoded_cookie(self):
        header = ac.csrf_header()
        self.assertTrue(header.startswith("x-xsrf-token: "))
        # The exported cookie value is URL-encoded; the header is not.
        self.assertEqual(header.split(": ", 1)[1],
                         urllib.parse.unquote("TOK%3D"))


class ResponseTests(unittest.TestCase):
    def test_extract_id_top_level_object(self):
        # Resume upload: the object sits at top level AND carries its own
        # "data" field (docx parse metadata) — the top-level id wins.
        self.assertEqual(
            ac.extract_id({"id": 28495705, "name": " Resume_copy",
                           "data": {"meta": {}}}), 28495705)

    def test_extract_id_inside_data_wrapper(self):
        self.assertEqual(ac.extract_id({"data": {"id": 12807942}}),
                         12807942)
        self.assertEqual(ac.extract_id({"id": 5}), 5)
        self.assertIsNone(ac.extract_id({"data": {"name": "x"}}))

    def test_extract_id_from_409_dedupe_body(self):
        self.assertEqual(
            ac.extract_id({"message": "already saved",
                           "errors": {"duplicate_opportunity": {
                               "opportunity": {"id": 12807942}}}}),
            12807942)

    def test_report_ready_checks_wrapped_object(self):
        self.assertTrue(ac.report_ready(
            {"data": {"matchRate": {"score": 93}}}))
        self.assertTrue(ac.report_ready({"data": {"findings": [1]}}))
        self.assertFalse(ac.report_ready({"data": {"stage": "saved"}}))
        self.assertFalse(ac.report_ready({"error": "x"}))


class BrowserHeaderTests(unittest.TestCase):
    def test_per_request_headers_dropped(self):
        saved = [
            "accept: application/json",
            "content-type: multipart/form-data; boundary=X",
            "x-xsrf-token: stale",
            "cookie: k=v",
            "origin: https://app.example.com",
        ]
        out = ac._browser_headers(saved)
        # Rebuilt per request: multipart boundary, CSRF, cookie.
        self.assertNotIn("content-type: multipart/form-data; boundary=X",
                         out)
        self.assertNotIn("x-xsrf-token: stale", out)
        self.assertNotIn("cookie: k=v", out)
        self.assertIn("accept: application/json", out)
        self.assertIn("origin: https://app.example.com", out)


class MimeTests(unittest.TestCase):
    def test_pdf_and_docx(self):
        self.assertEqual(ac.MIME_BY_EXT[".pdf"], "application/pdf")
        self.assertIn("wordprocessingml", ac.MIME_BY_EXT[".docx"])


class ScanArgumentTests(unittest.TestCase):
    def test_missing_resume_file_fails(self):
        with self.assertRaises(SystemExit) as cm:
            ac.scan("/nonexistent.pdf", "/nonexistent.txt")
        self.assertIn("resume file not found", str(cm.exception))

    def test_unsupported_extension_fails(self):
        rfd, resume = tempfile.mkstemp(suffix=".rtf")
        os.close(rfd)
        jfd, jd = tempfile.mkstemp(suffix=".txt")
        os.close(jfd)
        try:
            with self.assertRaises(SystemExit) as cm:
                ac.scan(resume, jd)
        finally:
            os.unlink(resume)
            os.unlink(jd)
        self.assertIn(".pdf or .docx", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
