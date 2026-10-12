"""Engine unit tests — no network, no token, pure logic."""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcd_expiry_ledger.demo import DemoClient
from mcd_expiry_ledger.ledger import LedgerEngine, parse_when, urgency_of
from mcd_expiry_ledger.report import render_html, render_markdown


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
        self.engine = LedgerEngine(DemoClient())
        self.bundle = self.engine.scan(address="北京朝阳区建国路")

    def test_scan_collects_all_kinds(self):
        kinds = set(self.bundle.by_kind())
        self.assertEqual(
            kinds, {"coupon", "point", "lottery", "prize", "mall_product", "campaign"}
        )

    def test_no_tool_failures(self):
        self.assertEqual(self.bundle.tools_failed, {})

    def test_order_profile_derived(self):
        snap = self.bundle.account_snapshot
        self.assertEqual(snap["orders_count"], 7)
        self.assertIn("orders_top_slot", snap)
        self.assertGreater(snap["orders_total_spend"], 0)

    def test_stores_scan_is_additive(self):
        without = LedgerEngine(DemoClient()).scan()
        self.assertEqual(without.stores, [])
        self.assertNotIn("query-nearby-stores", without.tools_ok)
        self.assertEqual(len(self.bundle.stores), 3)
        self.assertIn("query-nearby-stores", self.bundle.tools_ok)

    def test_plan_ends_with_strategy_entries(self):
        plan = self.engine.build_plan(self.bundle)
        kinds = [item["kind"] for item in plan]
        self.assertIn("历史复盘", kinds)
        self.assertIn("门店", kinds)
    def test_plan_has_claimable_first(self):
        plan = self.engine.build_plan(self.bundle)
        self.assertIn("待领券", plan[0]["asset"])
        self.assertGreater(plan[0]["value"], 0)

    def test_priority_ordering_is_value_x_weight(self):
        assets = self.bundle.sorted_assets()
        priorities = [a.priority for a in assets]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_expiring_coupon_detected(self):
        dead = [a for a in self.bundle.assets if a.days_left is not None and a.days_left < 0]
        self.assertTrue(any("过期" in a.title for a in dead))

    def test_report_renders_standalone_html(self):
        plan = self.engine.build_plan(self.bundle)
        html = render_html(self.bundle, plan)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("麦麦到期清单", html)
        self.assertIn("历史复盘", html)
        self.assertNotIn("http://cdn", html)
        self.assertNotIn('src="https://', html)

    def test_markdown_report_is_pasteable(self):
        plan = self.engine.build_plan(self.bundle)
        md = render_markdown(self.bundle, plan)
        self.assertIn("| # | 资产 | 估值 | 紧迫度 | 动作 |", md)
        self.assertIn("历史复盘", md)
        self.assertIn("order-list", md)


if __name__ == "__main__":
    unittest.main()
