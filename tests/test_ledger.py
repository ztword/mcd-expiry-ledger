"""Engine unit tests — no network, no token, pure logic."""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcd_expiry_ledger.demo import DemoClient
from mcd_expiry_ledger.ledger import LedgerEngine, parse_when, urgency_of
from mcd_expiry_ledger.report import render_html


class TestParsers(unittest.TestCase):
    def test_parse_when_shapes(self):
        cases = [
            ("2026-10-25 23:59:59", datetime(2026, 10, 25, 23, 59, 59)),
            ("2026-10-25", datetime(2026, 10, 25)),
            ("2026/10/25", datetime(2026, 10, 25)),
            ("2026年10月25日", datetime(2026, 10, 25)),
            (1761446400, datetime.fromtimestamp(1761446400)),
            (1761446400000, datetime.fromtimestamp(1761446400)),
            ("", None),
            (None, None),
            ("not a date", None),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                got = parse_when(raw)
                if expected is None:
                    self.assertIsNone(got)
                else:
                    self.assertEqual(got.replace(microsecond=0), expected)

    def test_urgency_bands(self):
        self.assertEqual(urgency_of(0.5)[0], "今天到期")
        self.assertEqual(urgency_of(2.9)[0], "72小时")
        self.assertEqual(urgency_of(6.0)[0], "本周")
        self.assertEqual(urgency_of(-1.0)[0], "已过期")
        self.assertEqual(urgency_of(None)[0], "未知")


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.bundle = LedgerEngine(DemoClient()).scan()

    def test_scan_collects_all_kinds(self):
        kinds = set(self.bundle.by_kind())
        self.assertEqual(
            kinds, {"coupon", "point", "lottery", "prize", "mall_product", "campaign"}
        )

    def test_no_tool_failures(self):
        self.assertEqual(self.bundle.tools_failed, {})

    def test_expiring_coupon_detected(self):
        dead = [a for a in self.bundle.assets if a.days_left is not None and a.days_left < 0]
        self.assertTrue(any("过期" in a.title for a in dead))

    def test_priority_ordering_is_value_x_weight(self):
        assets = self.bundle.sorted_assets()
        priorities = [a.priority for a in assets]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_plan_has_claimable_first(self):
        plan = LedgerEngine(DemoClient()).build_plan(self.bundle)
        self.assertIn("待领券", plan[0]["asset"])

    def test_report_renders_standalone_html(self):
        plan = LedgerEngine(DemoClient()).build_plan(self.bundle)
        html = render_html(self.bundle, plan)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("麦麦到期清单", html)
        # no external resources allowed
        self.assertNotIn("http://cdn", html)
        self.assertNotIn('src="https://', html)


if __name__ == "__main__":
    unittest.main()
