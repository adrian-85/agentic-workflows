"""Unit tests for squeeze_resume.py's pure, decidable helpers.

The end-to-end loop (render -> plan -> apply -> re-render) needs LibreOffice
and a full .docx, and is exercised by running the tool on a real tailored
resume (integration check, not a unit test). What IS unit-testable without a
render: the drop-applier against a synthetic document body, and the batch
selection that reuses measure_resume's JD-aware DROP PLAN machinery.

Run from the scripts directory:

    python3 -m unittest test_squeeze_resume
"""

import sys
import unittest
from xml.etree import ElementTree as ET

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402
import squeeze_resume as sq  # noqa: E402

W = de.W


def _para(text, style=None, numId=None):
    p = ET.Element(W + "p")
    if style is not None or numId is not None:
        pPr = ET.SubElement(p, W + "pPr")
        if style is not None:
            st = ET.SubElement(pPr, W + "pStyle")
            st.set(W + "val", style)
        if numId is not None:
            np = ET.SubElement(pPr, W + "numPr")
            ni = ET.SubElement(np, W + "numId")
            ni.set(W + "val", str(numId))
    r = ET.SubElement(p, W + "r")
    t = ET.SubElement(r, W + "t")
    t.text = text
    return p


def _body(ps):
    body = ET.Element(W + "body")
    for p in ps:
        body.append(p)
    return body


class ApplyDropsTests(unittest.TestCase):
    """_apply_drops removes exactly the paragraphs the plan named, and
    skips (never silently mis-edits) a prefix that no longer resolves."""

    def _three_bullet_body(self):
        return _body([
            _para("Bullet one", numId=2),
            _para("Bullet two", numId=2),
            _para("Bullet three", numId=2),
        ])

    def _prefixes(self, body):
        return [de.text_of(p)[:8] for p in de.paras(body)]

    def test_removes_only_the_named_paragraphs(self):
        body = self._three_bullet_body()
        applied, skipped = sq._apply_drops(body, [
            ("Bullet two", "Bullet two"),  # (find_p prefix, full text)
            ("Bullet one", "Bullet one"),
        ])
        self.assertEqual(applied, 2)
        self.assertEqual(skipped, [])
        remaining = [de.text_of(p) for p in de.paras(body)]
        self.assertEqual(remaining, ["Bullet three"])

    def test_missing_prefix_is_skipped_not_fatal(self):
        body = self._three_bullet_body()
        applied, skipped = sq._apply_drops(body, [
            ("Bullet two", "Bullet two"),
            ("No such bullet", "No such bullet"),
        ])
        self.assertEqual(applied, 1)
        self.assertEqual(skipped, ["No such bullet"])

    def test_empty_suggestions_apply_nothing(self):
        body = self._three_bullet_body()
        applied, skipped = sq._apply_drops(body, [])
        self.assertEqual((applied, skipped), (0, []))

    def test_drop_preserves_sibling_bullets(self):
        body = self._three_bullet_body()
        sq._apply_drops(body, [("Bullet two", "Bullet two")])
        remaining = [de.text_of(p) for p in de.paras(body)]
        self.assertEqual(remaining, ["Bullet one", "Bullet three"])


class NextBatchTests(unittest.TestCase):
    """The squeeze loop's per-iteration batch selection comes straight from
    measure_resume's JD-aware DROP PLAN machinery; this pins that the two
    compose (bullets are dropped oldest-role-first, weakest-first, and a
    JD-matched bullet is never in the batch)."""

    def _roles_plan(self):
        roles = [
            {"key": "GEICO", "bullet_texts": [
                "Led AI adoption across the department",
                "Refactored the Go integration framework",
                "Estimated weekly process meetings",
            ]},
            {"key": "Oldest, City", "bullet_texts": [
                "Championed the adoption of Cypress",
                "Established weekly cross-team meetings",
            ]},
        ]
        plan = [
            ("Oldest, City", "drop 1 bullet(s) (saves ~2 lines)", 2.0),
            ("GEICO", "drop 2 bullet(s) (saves ~5 lines)", 5.0),
        ]
        return roles, plan

    def test_batch_oldest_first_and_jd_aware(self):
        roles, plan = self._roles_plan()
        batch = sq._next_batch(
            roles, plan,
            all_texts=[b for r in roles for b in r["bullet_texts"]],
            protect=(), jd_terms={"cypress"},
        )
        texts = [t for _prefix, t in batch]
        # Oldest role first; its JD-matched Cypress bullet must not appear.
        # Within a role, weakest-first by the deterministic scorer (ties
        # toward longer text: Refactored Go framework is 39 chars, Led AI
        # adoption is 37).
        self.assertEqual(texts, ["Established weekly cross-team meetings",
                                 "Refactored the Go integration framework",
                                 "Led AI adoption across the department"])

    def test_batch_respects_protect(self):
        roles, plan = self._roles_plan()
        batch = sq._next_batch(
            roles, plan,
            all_texts=[b for r in roles for b in r["bullet_texts"]],
            protect=("process meetings",), jd_terms=(),
        )
        texts = [t for _prefix, t in batch]
        self.assertNotIn("Estimated weekly process meetings", texts)

    def test_batch_empty_when_budget_unmet_all_jd(self):
        # Budget demands a cut but every bullet is JD-matched: the batch is
        # empty (signals the loop to stop and call for a whole-role
        # seniority decision rather than cutting JD-critical content).
        roles = [{"key": "Only, City", "bullet_texts": [
            "Championed the adoption of Cypress",
            "Created performance tests using Gatling",
        ]}]
        plan = [("Only, City", "drop 2 bullet(s) (saves ~5 lines)", 5.0)]
        batch = sq._next_batch(
            roles, plan,
            all_texts=roles[0]["bullet_texts"],
            protect=(), jd_terms={"cypress", "gatling"},
        )
        self.assertEqual(batch, [])


if __name__ == "__main__":
    unittest.main()