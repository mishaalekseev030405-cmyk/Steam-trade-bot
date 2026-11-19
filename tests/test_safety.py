"""Offline safety regression tests. No network or real trades."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import purchase_ledger
from scanner import calculate_profit
from trade_guard import prepare_purchase, validate_candidate, purchase_allowed


def candidate(**overrides):
    item = {
        "item_id": "test-lot-1",
        "name": "Test item",
        "buy_price_rub": 100,
        "estimated_profit_rub": 60,
        "estimated_roi_percent": 60,
        "profit_verified": True,
    }
    item.update(overrides)
    return item


class SafetyTests(unittest.TestCase):
    def test_live_purchases_always_blocked(self):
        self.assertFalse(purchase_allowed())
        self.assertFalse(prepare_purchase(candidate(), 0, 3000)["allowed"])

    def test_unverified_profit_rejected(self):
        ok, _ = validate_candidate(candidate(profit_verified=False), 0, 3000)
        self.assertFalse(ok)

    def test_budget_and_balance_limits(self):
        self.assertFalse(validate_candidate(candidate(), 2950, 3000)[0])
        self.assertFalse(validate_candidate(candidate(), 0, 50)[0])
        self.assertFalse(validate_candidate(candidate(buy_price_rub=501), 0, 3000)[0])

    def test_invalid_numbers_rejected(self):
        for value in ["NaN", "Infinity", -1, 0]:
            self.assertFalse(validate_candidate(candidate(buy_price_rub=value), 0, 3000)[0])

    def test_profit_includes_fee(self):
        profit, roi = calculate_profit(100, 200)
        self.assertAlmostEqual(profit, 80)
        self.assertAlmostEqual(roi, 80)

    def test_ledger_reservations_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(purchase_ledger, "LEDGER", Path(folder) / "ledger.json"):
                purchase_ledger.reserve_candidate(candidate())
                with self.assertRaises(RuntimeError):
                    purchase_ledger.reserve_candidate(candidate())
                with self.assertRaises(RuntimeError):
                    purchase_ledger.reserve_candidate(candidate(item_id="test-lot-2"))
                capacity = purchase_ledger.check_capacity(purchase_ledger.load_ledger())
                self.assertTrue(capacity["has_unresolved"])
                self.assertEqual(capacity["reserved_rub"], 100)


if __name__ == "__main__":
    unittest.main()
