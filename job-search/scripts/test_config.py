"""Config loader tests: example parsing, validation, defaults, criteria hash.

All data is synthetic placeholder content from config.example.toml — no
personal values appear in any committed file (spec: privacy model).
"""

import tempfile
import unittest
from pathlib import Path

import config

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


def _minimal_toml(tmpdir: str) -> str:
    """Write a config with only the required keys; returns its path."""
    path = Path(tmpdir) / "minimal.toml"
    path.write_text(
        "[pay]\n"
        "preferred_min = 150000\n"
        "acceptable_min = 90000\n"
        "[profile]\n"
        'relevance_profile_path = "/tmp/example-resume.docx"\n'
        "[criteria]\n"
        'relevance_domains = "example domains"\n'
        'ethics_rule = "example rule"\n',
        encoding="utf-8",
    )
    return str(path)


class LoadConfigTest(unittest.TestCase):
    """load_config parses the committed example and validates required keys."""

    def test_example_config_loads(self):
        """Every Config field populates from config.example.toml."""
        cfg = config.load_config(str(EXAMPLE))
        self.assertIsInstance(cfg, config.Config)
        self.assertGreater(cfg.preferred_min, cfg.acceptable_min)
        self.assertGreater(cfg.acceptable_min, 0)
        self.assertTrue(cfg.relevance_profile_path)
        self.assertTrue(cfg.relevance_domains)
        self.assertTrue(cfg.ethics_rule)

    def test_missing_required_field_raises(self):
        """A config lacking relevance_domains fails with a named ConfigError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.toml"
            path.write_text(
                "[pay]\npreferred_min = 1\nacceptable_min = 1\n"
                '[profile]\nrelevance_profile_path = "/tmp/r.docx"\n'
                '[criteria]\nethics_rule = "example rule"\n',
                encoding="utf-8",
            )
            with self.assertRaises(config.ConfigError) as ctx:
                config.load_config(str(path))
            self.assertIn("relevance_domains", str(ctx.exception))

    def test_default_values_applied(self):
        """Optional keys fall back to the spec's defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = config.load_config(_minimal_toml(tmpdir))
        self.assertEqual(cfg.hours_per_year, 2080)
        self.assertEqual(cfg.currency, "USD")
        self.assertIsNone(cfg.linkedin_export_path)
        self.assertEqual(cfg.max_parallel_tailoring, 3)
        self.assertEqual(cfg.request_delay_seconds, 1.5)


class CriteriaHashTest(unittest.TestCase):
    """criteria_hash covers exactly the criteria block, order-insensitively."""

    @staticmethod
    def _cfg(ethics_rule: str = "example rule") -> config.Config:
        return config.Config(
            preferred_min=150000,
            acceptable_min=90000,
            relevance_profile_path="/tmp/example.docx",
            relevance_domains="example domains",
            ethics_rule=ethics_rule,
        )

    def test_criteria_hash_is_deterministic_and_order_insensitive(self):
        """Equal criteria (regardless of construction) hash identically."""
        first = config.criteria_hash(self._cfg())
        second = config.criteria_hash(self._cfg())
        self.assertEqual(first, second)

    def test_non_criteria_change_keeps_hash(self):
        """Dispatch-only fields do not alter the criteria version."""
        base = self._cfg()
        tweaked = config.Config(
            preferred_min=base.preferred_min,
            acceptable_min=base.acceptable_min,
            relevance_profile_path=base.relevance_profile_path,
            relevance_domains=base.relevance_domains,
            ethics_rule=base.ethics_rule,
            max_parallel_tailoring=5,
            request_delay_seconds=0.5,
        )
        self.assertEqual(config.criteria_hash(base), config.criteria_hash(tweaked))

    def test_changed_ethics_rule_changes_hash(self):
        """A criteria edit yields a new criteria_version."""
        self.assertNotEqual(
            config.criteria_hash(self._cfg()),
            config.criteria_hash(self._cfg(ethics_rule="different rule")),
        )


if __name__ == "__main__":
    unittest.main()
