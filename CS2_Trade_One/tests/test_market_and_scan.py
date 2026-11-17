import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

import httpx

from config import Settings
from market import Market, MarketError
from scanner import run_scan
from store import Store


class MarketApiTests(unittest.TestCase):
    def setUp(self):
        self.paths = []
        def handler(request):
            self.paths.append((request.url.path, str(request.url.query)))
            route = request.url.path
            if route.endswith('/get-money'):
                return httpx.Response(200, json={'success': True, 'money': 300.25, 'currency': 'RUB'})
            if route.endswith('/buy'):
                return httpx.Response(200, json={'success': True, 'id': '123456'})
            if route.endswith('/prices/class_instance/RUB.json'):
                return httpx.Response(200, json={'success': True, 'currency': 'RUB',
                    'time': int(time.time()), 'items': {
                        '13_0': {'market_hash_name': 'Test Skin', 'buy_order': '200.00'},
                        '14_0': {'market_hash_name': 'Test Skin', 'buy_order': '190.00'},
                    }})
            if route.endswith('/full-history/all.json'):
                return httpx.Response(200, json={'history': {'Test Skin': 123}})
            if route.endswith('/full-history/123.json'):
                return httpx.Response(200, json={'time': int(time.time()),
                    'data': {'sales7d': {'RUB': 34}, 'average7d': {'RUB': 234}}})
            if route.endswith('/search-list-items-by-hash-name-all'):
                return httpx.Response(200, json={'success': True, 'currency': 'RUB',
                    'data': {'Test Skin': [{'id': 123456, 'price': '10000'}]}})
            return httpx.Response(404)
        self.market = Market('fake_api_key', .35, transport=httpx.MockTransport(handler))
        self.addCleanup(self.market.close)

    def test_api_units_and_exact_buy_params(self):
        self.assertEqual(self.market.balance(), Decimal('300.25'))
        self.assertEqual(self.market.buy_order_quotes()['Test Skin'], Decimal('190.00'))
        result = self.market.buy_by_id('123456', 10000, 'operation00001')
        self.assertTrue(result['success'])
        route, query = self.paths[-1]
        self.assertTrue(route.endswith('/buy'))
        self.assertIn('id=123456', query)
        self.assertIn('price=10000', query)
        self.assertIn('custom_id=operation00001', query)
        self.assertIn('key=fake_api_key', query)

    def test_scanner_end_to_end_with_fake_network(self):
        with tempfile.TemporaryDirectory() as path:
            db = Store(Path(path) / 'state.sqlite3')
            cfg = Settings(market_key='fake_api_key', telegram_token='fake', owner_id=1,
                          db_path=Path(path) / 'state.sqlite3', scope='catalog')
            found = run_scan(cfg, self.market, db)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]['item_id'], '123456')
            self.assertEqual(found[0]['profit_rub'], '71.00')
            self.assertEqual(db.get('last_scan_count'), '1')
            db.mark_alerted(['123456'])
            self.assertEqual(run_scan(cfg, self.market, db), [])

    def test_incorrect_quote_schema_fails_closed(self):
        self.market.client.close()
        self.market.client = httpx.Client(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json={'currency': 'RUB', 'items': []})))
        with self.assertRaises(MarketError):
            self.market.buy_order_quotes()

    def test_buy_never_implicitly_retried(self):
        seen = []
        def error(request):
            seen.append(request)
            return httpx.Response(502)
        self.market.client.close()
        self.market.client = httpx.Client(transport=httpx.MockTransport(error))
        with self.assertRaises(MarketError):
            self.market.buy_by_id('123456', 10000, 'one')
        self.assertEqual(len(seen), 1)


if __name__ == '__main__':
    unittest.main()
