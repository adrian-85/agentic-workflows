"""Tests for the ordered resume-tailoring workflow gates."""

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
        with self.assertRaises(wg.ReviewError):
            wg.validate_review({
                "kind": "prune",
                "theme_anchors": ["quality"],
                "dispositions": [{
                    "item": "cut bullet",
                    "decision": "host",
                    "rationale": "wrong review vocabulary",
                }],
            })

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


if __name__ == "__main__":
    unittest.main()
