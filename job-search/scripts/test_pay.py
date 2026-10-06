"""Pay parsing tests: spec §4 pay rules, table-driven.

All strings are synthetic examples — no real posting text.
"""

import unittest

from pay import parse_pay, tier
from test_helpers import make_config


def _cfg(preferred_min: int = 185000, acceptable_min: int = 100000):
    """Pay-test config with explicit thresholds."""
    return make_config(preferred_min=preferred_min,
                       acceptable_min=acceptable_min)


class ParsePayTest(unittest.TestCase):
    """parse_pay extracts top-of-range, points, hourly, 'up to', currency."""

    def test_range_uses_top(self):
        """A range tiers by its TOP figure (user decision B4)."""
        info = parse_pay("$160,000 - $190,000/yr")
        self.assertTrue(info.seen)
        self.assertEqual(info.currency, "USD")
        self.assertEqual(info.top, 190000)
        self.assertEqual(info.annualized, 190000)
        self.assertEqual(info.basis, "range_top")

    def test_point_figure(self):
        """A single yearly figure is itself."""
        info = parse_pay("$150,000 per year")
        self.assertEqual(info.top, 150000)
        self.assertEqual(info.annualized, 150000)
        self.assertEqual(info.basis, "point")

    def test_hourly_annualizes(self):
        """Hourly rates annualize as rate x hours_per_year (default 2080)."""
        info = parse_pay("$70/hr")
        self.assertEqual(info.top, 70)
        self.assertEqual(info.annualized, 70 * 2080)
        self.assertEqual(info.basis, "hourly_x2080")

    def test_up_to_uses_max(self):
        """'Up to $X' means max = X."""
        info = parse_pay("up to $120,000")
        self.assertEqual(info.top, 120000)
        self.assertEqual(info.annualized, 120000)

    def test_missing_pay_seen_false(self):
        """None, empty, and 'DOE' carry no pay signal."""
        for raw in (None, "", "   ", "DOE", "Competitive"):
            info = parse_pay(raw)
            self.assertFalse(info.seen, msg=f"raw={raw!r}")
            self.assertIsNone(info.top)
            self.assertIsNone(info.annualized)
            self.assertEqual(info.basis, "none")

    def test_non_usd_currency_detected_not_tiered(self):
        """Non-USD figures report their currency; callers exclude them."""
        for raw, code in (
            ("£50,000 - £60,000", "GBP"),
            ("€60,000", "EUR"),
            ("CAD 90k - 110k", "CAD"),
        ):
            info = parse_pay(raw)
            self.assertTrue(info.seen, msg=raw)
            self.assertEqual(info.currency, code, msg=raw)

    def test_k_suffix_expands(self):
        """'$120k - $150k' expands k-suffixed figures."""
        info = parse_pay("$120k - $150k")
        self.assertEqual(info.top, 150000)
        self.assertEqual(info.annualized, 150000)


class TierTest(unittest.TestCase):
    """tier applies the configured thresholds, inclusive at the minimums."""

    def test_tier_boundaries(self):
        """preferred at/above preferred_min; acceptable at acceptable_min."""
        cfg = _cfg(preferred_min=185000, acceptable_min=100000)
        self.assertEqual(tier(185000, cfg), "preferred")
        self.assertEqual(tier(250000, cfg), "preferred")
        self.assertEqual(tier(184999, cfg), "acceptable")
        self.assertEqual(tier(100000, cfg), "acceptable")
        self.assertEqual(tier(99999, cfg), "unacceptable")


if __name__ == "__main__":
    unittest.main()
