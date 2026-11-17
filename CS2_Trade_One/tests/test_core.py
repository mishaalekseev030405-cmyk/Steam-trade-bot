import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from config import Settings
from market import kopecks_to_rub, rub_to_kopecks, Market, MarketError
from store import Store
from strategy import Candidate, qualify, sales7d
from trade import TradeError, buy_candidate, reconcile


class BotTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.cfg = Settings(market_key='dummy', telegram_token='dummy', owner_id=123,
                            db_path=Path(self.folder.name) / 'state.sqlite3')
        self.db = Store(self.cfg.db_path)
        self.offer = {'id': 91842, 'price': '10000'}  # 100.00 RUB
        self.market = Mock()
        self.market.offers.return_value = {'Test Skin': [self.offer]}
        self.market.buy_order_quotes.return_value = {'Test Skin': Decimal('200')}
        self.market.balance.return_value = Decimal('3000')
        self.market.buy_by_id.return_value = {'success': True, 'id': '91842'}
        self.market.buy_status.return_value = {'success': True, 'data': {'item_id': '91842', 'stage': 2}}
        self.cand = Candidate('91842', 'Test Skin', 10000, '200', '80.00', '80.00', 200)
        self.db.save_candidates([self.cand])

    def test_money_units(self):
        self.assertEqual(kopecks_to_rub('18352'), Decimal('183.52'))
        self.assertEqual(rub_to_kopecks('183.52'), 18352)
        with self.assertRaises(ValueError):
            rub_to_kopecks('18.005')
        with self.assertRaises(ValueError):
            kopecks_to_rub('12.5')

    def test_thresholds(self):
        c = qualify('Test Skin', self.offer, {'sales7d': {'RUB': 20}},
                    Decimal('200'), self.cfg)
        self.assertIsNotNone(c)
        self.assertEqual(c.profit_rub, '80.00')
        self.assertEqual(c.roi_percent, '80.00')
        self.assertIsNone(qualify('Test Skin', self.offer,
                        {'sales7d': {'RUB': 19}}, Decimal('200'), self.cfg))
        self.assertIsNone(qualify('Test Skin', self.offer,
                        {'sales7d': {'RUB': 20}}, Decimal('155'), self.cfg))
        self.assertIsNone(qualify('AK-47 | Case Hardened (FT)', self.offer,
                        {'sales7d': {'RUB': 20}}, Decimal('250'), self.cfg))
        self.assertIsNone(qualify('Test Skin', {'id': 22, 'price': '10000.5'},
                        {'sales7d': {'RUB': 20}}, Decimal('250'), self.cfg))

    def test_simulation_never_calls_buy(self):
        result = buy_candidate('91842', self.cfg, self.market, self.db)
        self.assertIn('Симуляция', result)
        self.market.buy_by_id.assert_not_called()
        self.assertEqual(self.db.history()[0]['status'], 'SIMULATED')
        with self.assertRaisesRegex(RuntimeError, 'уже была операция'):
            buy_candidate('91842', self.cfg, self.market, self.db)

    def test_manual_live_one_write_then_sync(self):
        cfg = replace(self.cfg, dry_run=False, live_enabled=True,
                      live_ack='I_ACCEPT_REAL_MONEY_RISK')
        result = buy_candidate('91842', cfg, self.market, self.db)
        self.assertIn('принял запрос', result)
        self.assertEqual(self.market.buy_by_id.call_count, 1)
        self.assertEqual(self.db.history()[0]['status'], 'ACCEPTED')
        self.assertEqual(self.db.overview(cfg)['unresolved'], 1)
        self.assertIn('передано', reconcile(cfg, self.market, self.db))
        self.assertEqual(self.db.history()[0]['status'], 'CONFIRMED')
        self.assertEqual(self.db.overview(cfg)['confirmed'], 1)

    def test_timeout_is_unknown_and_never_retried(self):
        cfg = replace(self.cfg, dry_run=False, live_enabled=True,
                      live_ack='I_ACCEPT_REAL_MONEY_RISK')
        self.market.buy_by_id.side_effect = MarketError('Timeout')
        with self.assertRaisesRegex(TradeError, 'ПОВТОРНО НЕ ПОКУПАЙ'):
            buy_candidate('91842', cfg, self.market, self.db)
        self.assertEqual(self.market.buy_by_id.call_count, 1)
        self.assertEqual(self.db.history()[0]['status'], 'UNKNOWN')
        with self.assertRaisesRegex(RuntimeError, 'уже была операция'):
            buy_candidate('91842', cfg, self.market, self.db)
        self.assertEqual(self.market.buy_by_id.call_count, 1)

    def test_price_change_prevents_purchase(self):
        self.market.offers.return_value = {'Test Skin': [{'id': 91842, 'price': '12000'}]}
        with self.assertRaisesRegex(TradeError, 'Цена лота изменилась'):
            buy_candidate('91842', self.cfg, self.market, self.db)
        self.market.buy_by_id.assert_not_called()
        self.assertFalse(self.db.history())

    def test_budget(self):
        cfg = replace(self.cfg, budget_rub=Decimal('100'))
        self.db.reserve(self.cand.serialize(), cfg)
        next_one = Candidate('91843', 'Another Skin', 5000, '150', '85', '170', 30)
        self.db.save_candidates([next_one])
        with self.assertRaises(RuntimeError):
            self.db.reserve(next_one.serialize(), cfg)

    def test_auto_disabled_by_default(self):
        self.assertFalse(self.cfg.live_ready)
        cfg = replace(self.cfg, dry_run=False, live_enabled=True)
        self.assertFalse(cfg.live_ready)
        self.assertFalse(cfg.enable_auto_after_first)


if __name__ == '__main__':
    unittest.main()
