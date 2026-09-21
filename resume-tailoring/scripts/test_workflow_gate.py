"""Tests for the ordered resume-tailoring workflow gates."""

# Test method names are self-documenting; class and method docstrings are not
# part of this small state-machine test's contract.
# pylint: disable=missing-function-docstring,missing-class-docstring

import contextlib
import io
import json
import os
import tempfile
import unittest

import workflow_gate as wg


class StateTransitionTests(unittest.TestCase):
    """Workflow phases advance once and in the required order."""

    def test_transitions_follow_theme_first_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "company theme")
            wg.advance(path, "prune-theme-reviewed")
            wg.advance(path, "ats-audited")
            wg.advance(path, "ats-theme-reviewed")
            self.assertEqual(wg.load_state(path)["phase"], "ats-theme-reviewed")

    def test_rejects_skipping_or_repeating_a_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            with self.assertRaises(wg.GateError):
                wg.advance(path, "ats-audited")
            with self.assertRaises(wg.GateError):
                wg.advance(path, "pruned")


    def test_record_audit_is_idempotent_on_re_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            wg.advance(path, "prune-theme-reviewed")
            wg.record_audit(path, ["gemini", "consulting"])
            self.assertEqual(wg.load_state(path)["phase"], "ats-audited")
            # Post-host re-audit after later reviews: accepted, no rewind.
            wg.advance(path, "ats-theme-reviewed")
            wg.record_audit(path, ["gemini"])
            self.assertEqual(wg.load_state(path)["phase"], "ats-theme-reviewed")

    def test_record_audit_rejects_early_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            with self.assertRaises(wg.GateError):
                wg.record_audit(path, ["gemini"])


class ReviewTemplateTests(unittest.TestCase):
    """`template` prints a fill-and-record skeleton that passes validation."""

    def _state_with_baseline(self, tmp, phrases):
        path = os.path.join(tmp, "target.workflow.json")
        wg.create_state(path, "Target", "jd_target.txt", "theme")
        wg.advance(path, "prune-theme-reviewed")
        wg.record_audit(path, phrases)
        return path

    def test_ats_template_prefills_every_baseline_phrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._state_with_baseline(tmp, ["Gen AI", "observability", "Gen AI"])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                wg.print_review_template("ats", path)
            skeleton = json.loads(out.getvalue())
            # normalized (lowercased, deduped, sorted) by record_audit
            self.assertEqual([f["phrase"] for f in skeleton["findings"]],
                             ["gen ai", "observability"])
            self.assertTrue(all(f["decision"] == "" and f["rationale"] == ""
                                for f in skeleton["findings"]))

    def test_filled_ats_template_passes_the_exact_set_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._state_with_baseline(tmp, ["Gen AI", "observability"])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                wg.print_review_template("ats", path)
            skeleton = json.loads(out.getvalue())
            skeleton["findings"][0].update(decision="host", rationale="evidenced")
            skeleton["findings"][1].update(decision="raise", rationale="no evidence")
            review = os.path.join(tmp, "review.json")
            with open(review, "w", encoding="utf-8") as stream:
                json.dump(skeleton, stream)
            wg.record_review(path, review)  # must not raise
            self.assertEqual(wg.load_state(path)["phase"], "ats-theme-reviewed")

    def test_prune_template_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                wg.print_review_template("prune", path)
            skeleton = json.loads(out.getvalue())
            self.assertEqual(skeleton["kind"], "prune")
            self.assertEqual(skeleton["theme_anchors"], [""])
            self.assertEqual(skeleton["dispositions"],
                             [{"item": "", "decision": "", "rationale": ""}])

    def test_ats_template_requires_recorded_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            with self.assertRaises(wg.GateError):
                wg.print_review_template("ats", path)


class RequireAtLeastTests(unittest.TestCase):
    """require_at_least accepts later phases (post-host baseline re-render)."""

    def test_require_at_least_passes_on_later_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            wg.advance(path, "prune-theme-reviewed")
            wg.advance(path, "ats-audited")
            wg.advance(path, "ats-theme-reviewed")
            # Baseline re-render after Theme Review B: phase has moved past
            # prune-theme-reviewed; the gate must still accept it.
            wg.require_at_least(path, "prune-theme-reviewed")

    def test_require_at_least_rejects_earlier_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            with self.assertRaises(wg.GateError):
                wg.require_at_least(path, "prune-theme-reviewed")


class ReviewValidationTests(unittest.TestCase):
    """Review records contain explicit, non-empty judgment evidence."""

    def test_prune_review_requires_theme_anchors_and_dispositions(self):
        review = {
            "kind": "prune",
            "theme_anchors": ["regulated healthcare quality"],
            "dispositions": [{
                "item": "cut bullet",
                "decision": "restore",
                "rationale": "unique domain evidence",
            }],
        }
        self.assertEqual(wg.validate_review(review), "prune")

    def test_ats_review_requires_a_disposition_for_each_finding(self):
        review = {
            "kind": "ats",
            "findings": [{
                "phrase": "risk-based testing",
                "decision": "raise",
                "rationale": "not evidenced in either source",
            }],
        }
        self.assertEqual(wg.validate_review(review), "ats")

    def test_rejects_empty_review_fields(self):
        with self.assertRaises(wg.ReviewError):
            wg.validate_review({"kind": "prune", "theme_anchors": []})

    def test_review_decisions_match_review_kind(self):
        with self.assertRaises(wg.ReviewError) as caught:
            wg.validate_review({
                "kind": "prune",
                "theme_anchors": ["quality"],
                "dispositions": [{
                    "item": "cut bullet",
                    "decision": "host",
                    "rationale": "wrong review vocabulary",
                }],
            })
        message = str(caught.exception)
        self.assertIn("entry 1", message)
        self.assertIn("allowed decisions", message)

    def test_reports_all_invalid_review_decisions(self):
        review = {
            "kind": "ats",
            "findings": [
                {"phrase": "python", "decision": "keep",
                 "rationale": "invalid for ATS reviews"},
                {"phrase": "sql", "decision": "restore",
                 "rationale": "invalid for ATS reviews"},
            ],
        }
        with self.assertRaises(wg.ReviewError) as caught:
            wg.validate_review(review)
        message = str(caught.exception)
        self.assertIn("entry 1", message)
        self.assertIn("entry 2", message)

    def test_ats_review_must_cover_every_baseline_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            review_path = os.path.join(tmp, "ats.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            prune_path = os.path.join(tmp, "prune.json")
            with open(prune_path, "w", encoding="utf-8") as stream:
                json.dump(self._prune_review(), stream)
            wg.record_review(path, prune_path)
            wg.record_audit(path, ["python", "sql"])
            incomplete = {"kind": "ats", "findings": []}
            with open(review_path, "w", encoding="utf-8") as stream:
                json.dump(incomplete, stream)
            with self.assertRaises(wg.ReviewError):
                wg.record_review(path, review_path)

    @staticmethod
    def _prune_review():
        return {
            "kind": "prune",
            "theme_anchors": ["quality"],
            "dispositions": [{
                "item": "cut bullet",
                "decision": "keep",
                "rationale": "supports quality",
            }],
        }


class BudgetRuleTests(unittest.TestCase):
    """Only small rendered spills qualify for page-removal trimming."""

    def test_page_removal_allowed_at_five_lines(self):
        self.assertTrue(wg.page_removal_allowed(5))
        self.assertFalse(wg.page_removal_allowed(6))
        self.assertFalse(wg.page_removal_allowed(0))

    def test_budget_close_enforces_word_cap_and_page_spill_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            wg.advance(path, "prune-theme-reviewed")
            wg.advance(path, "ats-audited")
            wg.advance(path, "ats-theme-reviewed")
            wg.advance(path, "seniority-approved")
            with self.assertRaises(wg.GateError):
                wg.close_budgets(path, 1001, 2, True)
            wg.close_budgets(path, 990, 5, True)
            self.assertEqual(wg.load_state(path)["phase"], "budgets-closed")

    def test_spacer_close_rejects_a_new_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            for phase in ("prune-theme-reviewed", "ats-audited",
                          "ats-theme-reviewed", "seniority-approved",
                          "budgets-closed"):
                wg.advance(path, phase)
            with self.assertRaises(wg.GateError):
                wg.close_spacers(path, True)
            wg.close_spacers(path, False)
            self.assertEqual(wg.load_state(path)["phase"], "spacers-closed")
            self.assertEqual(wg.load_state(path)["spacers_omitted"], [])

    def test_spacer_close_records_omitted_boundaries(self):
        # SKILL Step 9: a spacer that would create a new page is omitted —
        # but the omission must be RECORDED so final validation can exempt
        # exactly those boundaries instead of blocking the deliverable.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            for phase in ("prune-theme-reviewed", "ats-audited",
                          "ats-theme-reviewed", "seniority-approved",
                          "budgets-closed"):
                wg.advance(path, phase)
            wg.close_spacers(path, False, omitted=["Globex, CA (Remote)"])
            state = wg.load_state(path)
            self.assertEqual(state["spacers_omitted"], ["Globex, CA (Remote)"])
            self.assertEqual(state["history"][-1]["spacers_omitted"],
                             ["Globex, CA (Remote)"])

    def test_spacer_close_rerecords_omissions_after_close(self):
        # Render feedback can reveal an omitted-header string that never
        # matched (e.g. a full header recorded without its dates). Re-closing
        # must update the omissions without rewinding the phase.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            for phase in ("prune-theme-reviewed", "ats-audited",
                          "ats-theme-reviewed", "seniority-approved",
                          "budgets-closed"):
                wg.advance(path, phase)
            wg.close_spacers(path, False, omitted=["Symbols"])
            wg.close_spacers(path, False,
                             omitted=["Symbols, Tbilisi, Georgia (Remote)02/2025"])
            state = wg.load_state(path)
            self.assertEqual(state["phase"], "spacers-closed")
            self.assertEqual(state["spacers_omitted"],
                             ["Symbols, Tbilisi, Georgia (Remote)02/2025"])

    def test_spacers_cli_splits_the_omitted_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            for phase in ("prune-theme-reviewed", "ats-audited",
                          "ats-theme-reviewed", "seniority-approved",
                          "budgets-closed"):
                wg.advance(path, phase)
            # No ';' present: legacy comma split for header-free names.
            wg._main(["spacers", path, "--omitted", "Alpha, Beta"])
            self.assertEqual(wg.load_state(path)["spacers_omitted"],
                             ["Alpha", "Beta"]
                             )

    def test_spacers_cli_semicolon_keeps_commas_inside_headers(self):
        # Regression: real role headers contain commas ("GEICO, Chevy Chase,
        # MD (Remote)06/2025 – 07/2026"), so the CLI separator is ';' — a
        # comma split garbled every recorded header into fragments that
        # never matched, and final validation blocked the deliverable.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.workflow.json")
            wg.create_state(path, "Target", "jd_target.txt", "theme")
            for phase in ("prune-theme-reviewed", "ats-audited",
                          "ats-theme-reviewed", "seniority-approved",
                          "budgets-closed"):
                wg.advance(path, phase)
            headers = ["GEICO, Chevy Chase, MD (Remote)06/2025 – 07/2026",
                       "Symbols, Tbilisi, Georgia (Remote)02/2025 – 06/2025"]
            wg._main(["spacers", path, "--omitted", ";".join(headers)])
            self.assertEqual(wg.load_state(path)["spacers_omitted"], headers)


if __name__ == "__main__":
    unittest.main()
