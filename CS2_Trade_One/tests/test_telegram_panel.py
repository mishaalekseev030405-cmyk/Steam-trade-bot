"""Safe tests for the Russian Telegram control panel."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from config import Settings
from store import Store
from telegram_app import App


class TelegramPanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Settings(market_key='dummy', telegram_token='dummy',
                            owner_id=123,
                            db_path=Path(self.tmp.name) / 'bot.sqlite3')
        self.store = Store(self.cfg.db_path)
        self.market = Mock()
        self.market.balance.return_value = 250
        self.market.buy_order_quotes.return_value = {'Test skin': 200}
        self.app = App(self.cfg, self.market, self.store)
        self.addCleanup(lambda: asyncio.run(self.app.close()))

    def test_menu_has_all_panels(self):
        callbacks = [code for row in self.app.menu() for _, code in row]
        for name in ('home', 'finds', 'scan', 'toggle', 'budget', 'balance',
                     'history', 'sync', 'diagnostics', 'tests',
                     'notifications', 'security', 'settings', 'help'):
            self.assertIn(name, callbacks)
        self.assertEqual(len(callbacks), len(set(callbacks)))

    def test_panels_are_read_only(self):
        self.assertIn('SQLite', self.app.diagnostics_text())
        self.assertIn('БЮДЖЕТ', self.app.budget_text())
        self.assertIn('DRY_RUN', self.app.security_text())
        self.assertIn('САМОПРОВЕРКА', self.app.tests_text())
        self.market.buy_by_id.assert_not_called()
        self.market.list_owned_item.assert_not_called()

    def test_selfcheck_never_trades(self):
        result = asyncio.run(self.app.selftest())
        self.assertIn('Торговые запросы не отправлялись', result)
        self.assertIn('Котировки buy-ордеров', result)
        self.market.buy_by_id.assert_not_called()
        self.market.list_owned_item.assert_not_called()
        self.market.balance.assert_called_once()

    def test_notifications_toggle(self):
        self.app.show = AsyncMock()
        asyncio.run(self.app.handle('notifications'))
        self.assertEqual(self.store.get('notifications'), '0')
        asyncio.run(self.app.handle('notifications'))
        self.assertEqual(self.store.get('notifications'), '1')

    def test_selfcheck_errors_are_redacted(self):
        self.market.balance.side_effect = RuntimeError('SECRET_TOKEN')
        self.market.buy_order_quotes.side_effect = RuntimeError('SECRET_TOKEN')
        output = asyncio.run(self.app.selftest())
        self.assertNotIn('SECRET_TOKEN', output)
        self.assertIn('RuntimeError', output)


if __name__ == '__main__':
    unittest.main()
