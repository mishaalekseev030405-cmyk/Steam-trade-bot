"""Offline Telegram panel tests; no Telegram API calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import purchase_ledger
import telegram_bot


class PanelTests(unittest.TestCase):
    def test_budget_uses_purchase_ledger_not_legacy_purchases(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "purchase_ledger.json").write_text(
                '{"version":1,"operations":[{"item_id":"test-1",'
                '"name":"Test","price_rub":"150","status":"CONFIRMED",'
                '"created_at":"2026-01-01T00:00:00+00:00"}]}',
                encoding="utf-8",
            )
            (state / "purchases.json").write_text(
                '[{"price":2900}]', encoding="utf-8"
            )
            with patch.object(purchase_ledger, "LEDGER", state / "purchase_ledger.json"), patch.object(telegram_bot, "STATE_DIR", state):
                page = telegram_bot.screen("budget")
                self.assertIn("2 850.00", page)
                self.assertNotIn("100.00", page)
                self.assertIn("1", telegram_bot.screen("history"))
                self.assertIn("CONFIRMED", telegram_bot.screen("history"))


if __name__ == "__main__":
    unittest.main()
