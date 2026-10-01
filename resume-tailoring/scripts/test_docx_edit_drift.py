"""Unit tests for DriftBook — the in-memory edit-accounting object.

DriftBook replaces docx_edit's module-level drift counters
(_APPLIED/_SKIPS/_ELEMENT_FORM_DROPS/_ORIG): mutators record into the
book between load() and save(), save() snapshots it for the end-of-run
report (then it resets), and tests rebind a fresh book instead of
resetting globals. These tests pin that contract in isolation.
"""

# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring
# unittest/pytest method names are self-documenting.

import sys
import unittest

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from docx_edit_drift import DriftBook


class FreshBook(unittest.TestCase):
    def test_starts_zeroed(self):
        book = DriftBook()
        self.assertEqual(book.applied, 0)
        self.assertEqual(book.skips, [])
        self.assertEqual(book.element_form_drops, 0)
        self.assertEqual(book.orig, {})


class Recording(unittest.TestCase):
    def test_record_applied_accumulates(self):
        book = DriftBook()
        book.record_applied()
        book.record_applied()
        book.record_applied()
        self.assertEqual(book.applied, 3)

    def test_record_skip_accumulates_in_order(self):
        book = DriftBook()
        book.record_skip("Acme")
        book.record_skip("Tools & Technologies")
        self.assertEqual(book.skips, ["Acme", "Tools & Technologies"])

    def test_record_element_form_drop_accumulates(self):
        book = DriftBook()
        book.record_element_form_drop()
        book.record_element_form_drop()
        self.assertEqual(book.element_form_drops, 2)


class OriginalText(unittest.TestCase):
    def test_begin_keys_orig_by_paragraph_identity(self):
        book = DriftBook()
        p1, p2 = object(), object()
        book.begin(p1, "original one")
        book.begin(p2, "original two")
        self.assertEqual(book.orig[id(p1)], (p1, "original one"))
        self.assertEqual(book.orig[id(p2)], (p2, "original two"))

    def test_register_keys_new_paragraph_like_begin(self):
        # clone_after registers a post-load paragraph the same way load()
        # registers the originals — find_p resolves both through orig.
        book = DriftBook()
        new = object()
        book.register(new, "cloned bullet")
        self.assertEqual(book.orig[id(new)], (new, "cloned bullet"))


class Snapshot(unittest.TestCase):
    def test_snapshot_returns_current_values_then_resets(self):
        book = DriftBook()
        book.record_applied()
        book.record_applied()
        book.record_skip("No Such Prefix")
        book.record_element_form_drop()
        applied, skips, element = book.snapshot()
        self.assertEqual((applied, skips, element), (2, ["No Such Prefix"], 1))
        # save() reads+resets atomically: the book is spent after a snapshot.
        self.assertEqual(book.applied, 0)
        self.assertEqual(book.skips, [])
        self.assertEqual(book.element_form_drops, 0)

    def test_snapshot_skips_is_a_copy(self):
        # save() prints from the returned list after the reset — mutating
        # it must not resurrect entries in the book.
        book = DriftBook()
        book.record_skip("gone")
        _, skips, _ = book.snapshot()
        skips.append("injected")
        self.assertEqual(book.skips, [])

    def test_orig_survives_snapshot(self):
        # snapshot spends the counters, not the original-text map: the
        # load()→save() window may still resolve prefixes through orig.
        book = DriftBook()
        p = object()
        book.begin(p, "original")
        book.snapshot()
        self.assertEqual(book.orig[id(p)], (p, "original"))


if __name__ == "__main__":
    unittest.main()
