"""auto_prune (machine Phase A) tests.

The machine dispositions every prune candidate with no agent judgment:
bullet cuts, whole dead-sentence trims, whole-line proficiency/Tools keeps
or cuts, whole-category cuts, stub keeps, and the per-role cap — then emits
the first tailor script, which must pass run_tailor.sh's gates (ast + prefix
lint + prune coverage + strict exec).
"""

# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access
# unittest method names are self-documenting; tests white-box the plan
# dict (that IS the contract) and reuse the shared docx scaffolding.

import ast
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from test_helpers import _body, _para, _write_docx
import docx_edit as de  # noqa: E402
import docx_edit_cli  # noqa: E402
import measure_resume as mr  # noqa: E402
import measure_resume_drops as mrd  # noqa: E402
import auto_prune  # noqa: E402
import jd_asks  # noqa: E402

# Real-JD shape: a qualification section (the engine's ask source).
JD = ("required:\n"
      "Experience with Cypress, Jenkins, Gatling, Selenium, Playwright, "
      "Kubernetes, Docker, AWS, REST APIs, and Python scripting.\n"
      "CI/CD pipeline ownership and test automation depth.")


def _date():
    return mr._sample_date() if hasattr(mr, "_sample_date") else "01/2020"


def _master_paras():
    """A master-like fixture: proficiencies (JD + non-JD lines), a
    Certifications section, three roles (one JD-flagship, one mixed, one
    all-off-JD stub case), and Education."""
    return _body([
        _para("Adrian Alan", style="Title"),
        _para("Staff Engineer", style="Title"),
        _para("Summary of a career", style="SummaryBlock"),
        _para(mr.SECTION_PROFICIENCIES, style="SectionHeading"),
        _para("Programming Languages: Python, Java, COBOL"),
        _para("Automation Testing Frameworks: Cypress, Playwright, "
              "Karate"),
        _para("Certifications", style="SectionHeading"),
        _para("Rapid Software Testing, 2021"),
        _para(mr.SECTION_CAREER, style="SectionHeading"),
        _para("Company Alpha" + _date() + " – 08/2024",
              style=mr.COMPANY_STYLE),
        _para("Senior SDET", style="JobTitleBlock"),
        _para("Championed the adoption of Cypress, co-architecting the "
              "initial framework", numId=2),
        _para("Automated checkout flows with Cypress. Organized team "
              "offsites and holiday parties.", numId=2),
        _para("Created performance tests using Gatling and reported "
              "results", numId=2),
        _para("Organized team offsites and holiday parties", numId=2),
        _para("Tools & Technologies: Cypress, Jenkins, Kubernetes, "
              "COBOL"),
        _para("Company Beta" + _date() + " – 08/2022",
              style=mr.COMPANY_STYLE),
        _para("QA Engineer", style="JobTitleBlock"),
        _para("Automated regression suites with Selenium and Playwright",
              numId=2),
        _para("Wrote Python scripting utilities for test data",
              numId=2),
        _para("Attended weekly planning meetings", numId=2),
        _para("Company Gamma" + _date() + " – 08/2018",
              style=mr.COMPANY_STYLE),
        _para("Manual Tester", style="JobTitleBlock"),
        _para("Logged bugs in a spreadsheet and filed paperwork",
              numId=2),
        _para("Answered the office phone", numId=2),
        _para("Sole testing and quality engineering resource for the "
              "entire payments department, reporting to the director of "
              "payments, and partnered with the director to secure buy-in "
              "from a team of managers and an architect for process, "
              "release, and testing changes across five engineering teams "
              "building a new payments platform in a large monorepo."),
        _para(mr.SECTION_EDUCATION, style="SectionHeading"),
        _para("BA, General Studies"),
    ])


class _AutoPruneBase(unittest.TestCase):
    """Shared: compute candidates + plan for the fixture master."""

    def setUp(self):
        self.body = _master_paras()
        self.roles = mr._roles(self.body)
        self.jd_terms = mr._jd_terms(JD, self.body)
        self.candidates = mrd.prune_candidates(self.roles, self.jd_terms,
                                               self.body, protect=())
        self.candidates.extend(auto_prune._intro_candidates(
            self.body, self.roles, self.jd_terms,
            [de.text_of(p) for p in de.paras(self.body)]))
        self.plan = auto_prune.plan_phase_a(self.candidates, self.roles,
                                            self.jd_terms, self.body)

    def _cand(self, fragment, kind=None):
        for c in self.candidates:
            if fragment in c["text"] and (kind is None
                                          or c["kind"] == kind):
                return c
        return None


class TestJdEvidenceFamilies(unittest.TestCase):
    def test_component_testing_ask_protects_unit_testing_evidence(self):
        jd = ("required:\n"
              "Experience with component-level testing of isolated UI elements.\n")
        asks = {ask.phrase for ask in jd_asks.parse_asks(jd)}
        self.assertTrue(
            jd_asks.evidence_set(
                "Used a unit testing framework for isolated components.", asks))

    def test_alternative_scripting_terms_protect_source_evidence(self):
        jd = ("additional:\n"
              "Python scripting experience and scripting in Linux bash or "
              "Windows batch.\n")
        asks = {ask.phrase for ask in jd_asks.parse_asks(jd)}
        self.assertIn("linux bash", asks)
        text = "Wrote Python scripts and Linux WSL helpers for test data."
        evidence = jd_asks.evidence_set(text.lower(), asks)
        self.assertTrue(any(term in evidence for term in ("python scripting",
                                                           "python")))
        self.assertTrue(any(term in evidence for term in ("linux bash",
                                                           "linux")))

    def test_windows_batch_ask_requires_batch_evidence(self):
        jd = ("additional:\n"
              "Scripting experience in Linux bash or Windows batch.\n")
        asks = {ask.phrase for ask in jd_asks.parse_asks(jd)}
        # Bare 'windows' (e.g. Windows Server admin) is NOT batch-scripting
        # evidence — hosting the ask from it would fabricate a skill.
        evidence = jd_asks.evidence_set("administered windows servers", asks)
        self.assertNotIn("windows batch", evidence)

    def test_visual_regression_ask_protects_manual_visual_evidence(self):
        jd = ("required:\n"
              "Hands-on experience with visual regression testing tools.\n")
        asks = {ask.phrase for ask in jd_asks.parse_asks(jd)}
        evidence = jd_asks.evidence_set(
            "Performed manual visual checks on every release.", asks)
        self.assertIn("visual regression testing", evidence)


class TestIntroProseCap(_AutoPruneBase):
    """Over-cap role-intro prose paragraphs (non-bullets) are word-trim
    candidates — validate_resume caps every editable prose paragraph."""

    def test_over_cap_intro_is_a_word_trim_candidate(self):
        c = self._cand("Sole testing and quality", "word-trim")
        self.assertTrue(c, "over-cap intro prose must be a candidate")

    def test_under_cap_intro_is_never_a_candidate(self):
        self.assertFalse(self._cand("QA Engineer"))

    def test_intro_is_disposed_under_cap(self):
        # No JD-evidenced sentence in this fixture's intro → the machine
        # disposes it as a CUT (trim would be empty); with evidence it
        # word-trims to <= WORD_CAP (see the GEICO case on a real master).
        c = self._cand("Sole testing and quality", "word-trim")
        trims = [new for anchor, new in self.plan["trims"]
                 if anchor[1] == c["text"]]
        cuts = [t for _p, t in self.plan["drops"] if t == c["text"]]
        self.assertTrue(trims or cuts)
        for new in trims:
            self.assertLessEqual(len(new.split()), auto_prune.WORD_CAP)


class TestPlanDispositions(_AutoPruneBase):

    def test_off_jd_bullet_is_cut(self):
        c = self._cand("Organized team offsites", "bullet-cut")
        self.assertTrue(c)
        self.assertTrue(any(c["prefix"] == p
                            for p, _t in self.plan["drops"]))

    def test_role_losing_every_bullet_keeps_a_stub(self):
        # Company Gamma's both bullets are OFF-JD: one survives, and the
        # keep comment records it. Whole-role drops never appear.
        gamma = next(r for r in self.roles
                     if any("Logged bugs" in b
                            for b in r["bullet_texts"]))
        self.assertTrue(gamma["bullet_texts"])
        dropped = {t for _p, t in self.plan["drops"]}
        kept = [b for b in gamma["bullet_texts"] if b not in dropped]
        self.assertEqual(len(kept), 1)
        self.assertTrue(self.plan["keeps"])

    def test_no_whole_role_drops_anywhere(self):
        script = auto_prune.emit_script(
            self.plan, "m.docx", "out.docx",
            {"target": "T", "jd_name": "jd.txt",
             "script_name": "tailor_t.py"})
        self.assertNotIn("drop_role", script)

    def test_word_trim_removes_dead_sentence(self):
        c = self._cand("Automated checkout flows", "word-trim")
        self.assertTrue(c)
        trim = [(a, new) for a, new in self.plan["trims"]
                if a[1] == c["text"]]
        self.assertEqual(len(trim), 1)
        _anchor, new_text = trim[0]
        self.assertIn("Cypress", new_text)
        self.assertNotIn("offsites", new_text)  # dead sentence removed

    def test_trimmed_bullet_meets_word_cap(self):
        for _anchor, new in self.plan["trims"]:
            self.assertLessEqual(len(new.split()), auto_prune.WORD_CAP)

    def test_list_line_hosting_jd_evidence_is_kept_whole(self):
        # The Automation line hosts Cypress/Playwright (JD-evidenced) AND
        # Karate (not JD-named) — the whole line is kept UNCHANGED, never
        # reduced to a partial value list.
        c = self._cand("Automation Testing Frameworks:", "list-trim")
        self.assertTrue(c)
        self.assertNotIn(
            c["text"], {t for _p, t in self.plan["drops"]})
        self.assertTrue(any(head == c["prefix"] or c["text"][:24] in head
                            for head, _why in self.plan["keeps"]))
        self.assertFalse(
            any(a[1] == c["text"] for a, _new in self.plan["trims"]))

    def test_tools_line_without_jd_evidence_keeps_a_value_row(self):
        # Tools & Technologies is part of every retained role's presentation.
        # It may not host a JD term, but pruning it entirely leaves an
        # inconsistent role block and an empty heading cannot render as a
        # usable skills row.
        body = _master_paras()
        tools = next(p for p in de.paras(body)
                     if de.text_of(p).startswith("Tools & Technologies:"))
        de.set_text(tools, "Tools & Technologies: COBOL, Fortran")
        roles = mr._roles(body)
        terms = mr._jd_terms(JD, body)
        candidates = mrd.prune_candidates(roles, terms, body, protect=())
        candidates.extend(auto_prune._intro_candidates(
            body, roles, terms, [de.text_of(p) for p in de.paras(body)]))
        plan = auto_prune.plan_phase_a(candidates, roles, terms, body)
        dropped = {text for _prefix, text in plan["drops"]}
        self.assertNotIn(de.text_of(tools), dropped)
        self.assertTrue(any(head == "Tools "
                            for head, _why in plan["keeps"]))

    def test_languages_line_hosting_jd_evidence_is_kept_whole(self):
        # 'Python' (a capitalized mention) and 'python scripting' (the
        # cue-tail phrase) are BOTH asks under the engine; the Languages
        # line evidences 'python', so the WHOLE line (Java/COBOL included)
        # is kept unchanged — never reduced to just the JD-named item.
        c = self._cand("Programming Languages:", "list-trim")
        self.assertTrue(c)
        self.assertNotIn(
            c["text"], {t for _p, t in self.plan["drops"]})
        self.assertFalse(
            any(a[1] == c["text"] for a, _new in self.plan["trims"]))

    def test_emptied_cert_section_drops_whole(self):
        c = self._cand("Rapid Software Testing", "top-block")
        self.assertTrue(c)
        self.assertTrue(any("Certifications" in h
                            for _p, h in self.plan["section_drops"]))
        # the line cut moved into the section drop — not in drop list
        self.assertFalse(any(c["prefix"] == p
                             for p, _t in self.plan["drops"]))
        self.assertTrue(any("Certifications" in why or "emptied" in why
                            for _h, why in self.plan["section_keeps"]))

    def test_stats_summary(self):
        s = self.plan["stats"]
        self.assertGreater(s["cut"], 0)
        self.assertGreater(s["trim"], 0)
        self.assertGreaterEqual(s["stub"], 1)


class TestEmittedScript(_AutoPruneBase):
    # too-many-locals: the fixture-heavy test classes build the plan + script
# in setUp-adjacent helpers; splitting them harms the test narrative.

    """The emitted script must parse, cover every sidecar candidate, and
    never drop a whole role."""

    _META = {"target": "Target", "jd_name": "jd_x.txt",
             "script_name": "tailor_target.py"}

    def _script(self):
        return auto_prune.emit_script(
            self.plan, "master.docx", "out.docx", self._META)

    def test_parses(self):
        ast.parse(self._script())

    def test_no_drop_role(self):
        self.assertNotIn("drop_role", self._script())

    def test_emitted_imports_cover_only_machine_edits(self):
        # The machine never emits set_labeled (whole-line keeps/cuts only)
        # and never drop_role — Phase 2 extensions import their own helpers
        # (the authoring superset lives in the tailor_resume.py template).
        self.assertNotIn("set_labeled", self._script())

    def test_every_candidate_covered(self):
        # docx_edit_cli reads from a path — write the script to disk
        with tempfile.NamedTemporaryFile("w", suffix=".py",
                                         delete=False) as f:
            f.write(self._script())
            path = f.name
        try:
            literals, keeps, _dropped_roles = \
                docx_edit_cli._script_cover_strings(path)
        finally:
            os.unlink(path)
        for c in self.candidates:
            state = docx_edit_cli._prune_covered(c, literals, keeps, _dropped_roles)
            self.assertIsNotNone(
                state, f"uncovered candidate: {c['kind']} {c['text'][:60]}")


class TestEmittedScriptRuns(_AutoPruneBase):
    """End-to-end: the emitted script runs green under strict mode and
    writes the base build."""

    def test_script_runs_and_writes_build(self):
        # too-many-locals: the end-to-end fixture assembles master, JD,
        # plan, emitted script, and the subprocess env in one flow.
        # pylint: disable=too-many-locals
        with tempfile.TemporaryDirectory() as td:
            master = os.path.join(td, "Test User Master Resume.docx")
            _write_docx(master, _master_paras())
            dst = os.path.join(td, "Test User Resume - Target.docx")
            script = auto_prune.emit_script(
                self.plan, master, dst,
                {"target": "Target", "jd_name": "jd_x.txt",
                 "script_name": "tailor_target.py"})
            script_path = os.path.join(td, "tailor_target.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)
            src_dir = __file__.rsplit("/", 1)[0]
            env = dict(os.environ)
            env["DOCX_EDIT_STRICT"] = "1"
            env["PYTHONPATH"] = src_dir
            code = (f"import sys; sys.path.insert(0, {src_dir!r}); "
                    "import runpy; "
                    f"runpy.run_path({script_path!r}, run_name='__main__')")
            proc = subprocess.run([sys.executable, "-c", code], cwd=td,
                                  env=env, capture_output=True, text=True,
                                  check=False)
            self.assertEqual(
                proc.returncode, 0,
                "stdout:\n" + proc.stdout + "\nstderr:\n" + proc.stderr)
            self.assertTrue(os.path.exists(dst))
            _root, body, _n, _d, _w = de.load(dst)
            texts = [de.text_of(p) for p in de.paras(body)]
            self.assertNotIn(
                "Organized team offsites and holiday parties", texts)
            self.assertFalse(any("Certifications" == t for t in texts))
            self.assertNotIn("Rapid Software Testing, 2021", texts)
            # Gamma kept exactly one stub bullet
            gamma_bullets = ["Logged bugs in a spreadsheet and filed "
                             "paperwork", "Answered the office phone"]
            kept_gamma = [t for t in gamma_bullets if t in texts]
            self.assertEqual(len(kept_gamma), 1)


class TestTrimHelpers(unittest.TestCase):

    def test_trim_bullet_text_keeps_evidenced_sentence_verbatim(self):
        # Row/sentence granular only — a surviving sentence is NEVER
        # rewritten word-by-word, even when it also names a non-JD tool.
        text = "Built Selenium suites with Java."
        trimmed = auto_prune._trim_bullet_text(text, {"selenium"})
        self.assertEqual(trimmed, text)

    def test_trim_bullet_text_keeps_whole_sentence_with_mixed_chunks(self):
        text = "Built Selenium suites with Java, TestNG and Playwright."
        trimmed = auto_prune._trim_bullet_text(text, {"selenium", "java"})
        self.assertEqual(trimmed, text)

    def test_trim_bullet_text_keeps_parenthetical_verbatim(self):
        text = "Built Selenium suites with Java (TestNG and Playwright)."
        trimmed = auto_prune._trim_bullet_text(
            text, {"selenium", "java"})
        self.assertEqual(trimmed, text)

    def test_trim_bullet_text_drops_dead_sentences_and_caps_words(self):
        jd_terms = {"cypress"}
        text = ("Automated the regression suite with Cypress across "
                "browsers. Organized team offsites and holiday parties. "
                "Filed weekly status paperwork for managers. Coached "
                "interns on office tooling and onboarding paperwork. "
                "Maintained the snack inventory spreadsheet every week.")
        out = auto_prune._trim_bullet_text(text, jd_terms)
        self.assertIn("Cypress", out)
        self.assertNotIn("offsites", out)
        self.assertLessEqual(len(out.split()), auto_prune.WORD_CAP)

    def test_trim_bullet_text_drops_whole_sentence_not_words_when_over_cap(self):
        # A single evidenced sentence that survives whole is never chopped
        # mid-sentence to fit the cap — only whole SURVIVING sentences are
        # ever dropped to reach the cap.
        jd_terms = {"cypress"}
        long_sentence = ("Automated the regression suite with Cypress "
                         "across every supported browser and device "
                         "combination for the whole engineering "
                         "organization spanning multiple quarters of "
                         "continuous release cycles and audits.")
        out = auto_prune._trim_bullet_text(long_sentence, jd_terms)
        self.assertEqual(out, long_sentence)

    def test_surviving_chunks_boolean_signals_whole_line(self):
        # _hosts_jd_chunk is a whole-line boolean signal: True when ANY
        # chunk hosts JD evidence (line kept whole), False when none does.
        self.assertTrue(
            auto_prune._hosts_jd_chunk(
                "Languages: Python, COBOL, Rust", {"python"}))
        self.assertFalse(
            auto_prune._hosts_jd_chunk(
                "Languages: COBOL, Rust", {"python"}))


class TestJdContractAndEquivalences(unittest.TestCase):
    """The fixed JD contract enforced at the pipeline entry, the per-run
    --equivalence extension of the ask/evidence matcher, and the --theme
    traceability line in the emitted docstring."""

    def test_missing_headers_exit_2_with_names(self):
        jd = "required:\n5+ years QA\n"
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                auto_prune.validate_jd_contract(jd)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("title", err.getvalue())
        self.assertIn("expectations", err.getvalue())

    def test_unsectioned_jd_exit_2(self):
        jd = "Top 3 skills: Python, SQL, Selenium.\n"
        with contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                auto_prune.validate_jd_contract(jd)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("canonical section headers", err.getvalue())

    def test_complete_jd_passes_contract(self):
        sections = auto_prune.validate_jd_contract(_full_contract_jd())
        self.assertEqual(sections["title"], "Senior SDET")

    def test_equivalence_extends_matcher_for_this_run(self):
        auto_prune.apply_equivalences(["IV&V=testing,quality validation"])
        try:
            asks = {a.phrase for a in jd_asks.parse_asks(
                _full_contract_jd())}
            self.assertIn("iv&v", asks)
            self.assertTrue(jd_asks.evidence_set(
                "performed independent testing across the platform",
                asks))
        finally:
            jd_asks.EXTRA_EVIDENCE_FAMILIES.clear()

    def test_malformed_equivalence_exit_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                auto_prune.apply_equivalences(["no-equals-sign"])
        self.assertEqual(ctx.exception.code, 2)

    def test_theme_recorded_in_emitted_docstring(self):
        body = _master_paras()
        roles = mr._roles(body)
        jd_terms = mr._jd_terms(_full_contract_jd(), body)
        candidates = mrd.prune_candidates(roles, jd_terms, body,
                                          protect=())
        plan = auto_prune.plan_phase_a(candidates, roles, jd_terms, body)
        plan["candidates"] = candidates
        script = auto_prune.emit_script(
            plan, "Test User Master Resume.docx", "Test User Resume - X.docx",
            {"target": "X", "jd_name": "jd_x.txt",
             "script_name": "tailor_x.py", "theme": "AI-first QA startup"})
        self.assertIn("JD theme: AI-first QA startup", script)

    def test_no_theme_no_line(self):
        body = _master_paras()
        roles = mr._roles(body)
        jd_terms = mr._jd_terms(_full_contract_jd(), body)
        candidates = mrd.prune_candidates(roles, jd_terms, body,
                                          protect=())
        plan = auto_prune.plan_phase_a(candidates, roles, jd_terms, body)
        plan["candidates"] = candidates
        script = auto_prune.emit_script(
            plan, "Test User Master Resume.docx", "Test User Resume - X.docx",
            {"target": "X", "jd_name": "jd_x.txt",
             "script_name": "tailor_x.py"})
        self.assertNotIn("JD theme:", script)


def _full_contract_jd():
    return ("title:\n"
            "Senior SDET\n"
            "company:\n"
            "We build things.\n"
            "role:\n"
            "Own test automation for the platform.\n"
            "responsibilities:\n"
            "Own the automated test approach.\n"
            "required:\n"
            "Python, Selenium\n"
            "5+ years of test automation and IV&V experience\n"
            "additional:\n"
            "Docker\n"
            "education:\n"
            "Bachelor's degree\n"
            "expectations:\n")


if __name__ == "__main__":
    unittest.main()
