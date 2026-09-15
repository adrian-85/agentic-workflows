"""Tests for the normalized external/internal ATS gap queue."""
# pylint: disable=missing-function-docstring,missing-class-docstring

import json
import os
import tempfile
import unittest

import gap_queue


class GapQueueTests(unittest.TestCase):
    def test_merges_external_hard_soft_and_internal_gaps(self):
        report = {
            "skills": {
                "hard": [
                    {"name": "Storybook", "resumeCount": 0},
                    {"name": "Python", "resumeCount": 2},
                ],
                "soft": [
                    {"name": "Stakeholder Management", "resumeCount": 0},
                ],
            }
        }
        gaps = gap_queue.normalize_gaps(report, ["storybook", "component testing"])
        self.assertEqual(
            gaps,
            [
                {"term": "Storybook", "sources": ["external-hard", "internal"]},
                {"term": "Stakeholder Management", "sources": ["external-soft"]},
                {"term": "component testing", "sources": ["internal"]},
            ],
        )

    def test_fingerprint_is_stable_for_normalized_gaps(self):
        gaps = [{"term": "Storybook", "sources": ["external-hard"]}]
        self.assertEqual(gap_queue.gap_fingerprint(gaps),
                         gap_queue.gap_fingerprint(list(gaps)))

    def test_write_artifact_records_source_fingerprints(self):
        with tempfile.TemporaryDirectory() as td:
            report = os.path.join(td, "scan.json")
            resume = os.path.join(td, "resume.docx")
            artifact = os.path.join(td, "gaps.json")
            with open(report, "w", encoding="utf-8") as f:
                json.dump({"skills": {"hard": [
                    {"name": "Storybook", "resumeCount": 0}],
                    "soft": []}}, f)
            with open(resume, "wb") as f:
                f.write(b"resume")
            result = gap_queue.write_artifact(
                report, resume, ["component testing"], artifact)
            self.assertEqual(result["gapFingerprint"],
                             gap_queue.gap_fingerprint(result["gaps"]))
            self.assertEqual(result["resumePath"], resume)
            self.assertTrue(os.path.exists(artifact))


if __name__ == "__main__":
    unittest.main()
