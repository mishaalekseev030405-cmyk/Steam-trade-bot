"""Market.CSGO v2 adapter with explicit price units and no write retries."""
from __future__ import annotations

import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

BASE = 'https://market.csgo.com/api/v2'


class MarketError(RuntimeError):
    pass


def to_decimal(raw: Any) -> Decimal:
    if raw is None or isinstance(raw, bool):
        raise ValueError('Missing/non-numeric price')
    try:
        num = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('Non-numeric price') from exc
    if not num.is_finite() or num < 0:
        raise ValueError('Invalid price')
    return num


def kopecks_to_rub(raw: Any) -> Decimal:
    value = to_decimal(raw)
    if value != value.to_integral_value():
        raise ValueError('Expected integer kopecks')
    return value / 100


def rub_to_kopecks(raw: Any) -> int:
    value = to_decimal(raw) * 100
    if value != value.to_integral_value():
        raise ValueError('RUB price must be precise to a kopeck')
    return int(value)


class Market:
    """Synchronous client. Shared rate limiting across scanner and purchases."""

    def __init__(self, api_key: str, request_delay_s: float = .5,
                 transport: httpx.BaseTransport | None = None):
        self.key = api_key
        self.delay = max(request_delay_s, .35)
        self.client = httpx.Client(timeout=httpx.Timeout(20, connect=10), transport=transport,
                                   headers={'User-Agent': 'CS2TradeOne/1.0'})
        self.lock = threading.Lock()
        self.last_request = 0.0

    def close(self) -> None:
        self.client.close()

    def _get(self, route: str, params: dict | list[tuple] | None = None,
             *, keyed: bool = False, mutating: bool = False) -> dict:
        if keyed and not self.key:
            raise MarketError('MARKET_CSGO_API_KEY не задан')
        pairs = list(params.items()) if isinstance(params, dict) else list(params or [])
        if keyed:
            pairs.append(('key', self.key))
        # Serialize all queries. Crucially, a trading request must NEVER be auto-retried.
        with self.lock:
            wait = self.delay - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            try:
                result = self.client.get(BASE + route, params=pairs)
                result.raise_for_status()
                data = result.json()
            except (httpx.HTTPError, ValueError) as exc:
                kind = 'Неизвестный результат операции' if mutating else 'Ошибка API'
                raise MarketError(f'{kind}: {type(exc).__name__}') from None
        if not isinstance(data, dict):
            raise MarketError('API вернул объект неизвестного формата')
        if data.get('success') is False:
            raise MarketError(f"Market API отклонил запрос: {str(data.get('error', 'unknown'))[:100]}")
        return data

    def balance(self) -> Decimal:
        body = self._get('/get-money', keyed=True)
        if body.get('success') is not True or body.get('currency') != 'RUB':
            raise MarketError('Баланс не подтверждён в RUB')
        return to_decimal(body.get('money'))

    def all_history_ids(self) -> dict[str, Any]:
        body = self._get('/full-history/all.json')
        names = body.get('history')
        if not isinstance(names, dict):
            raise MarketError('Некорректный каталог истории')
        return names

    def history(self, history_id: Any) -> dict:
        if not str(history_id).isdigit():
            raise ValueError('Invalid history id')
        body = self._get(f'/full-history/{history_id}.json')
        if not isinstance(body.get('data'), dict):
            raise MarketError('Нет статистики продаж')
        return body

    def buy_order_quotes(self) -> dict[str, Decimal]:
        """ONLY documented major RUB fields in prices/class_instance; conservative min for aliases."""
        data = self._get('/prices/class_instance/RUB.json')
        if data.get('currency') != 'RUB':
            raise MarketError('Котировки не в RUB')
        stamp = data.get('time')
        if not isinstance(stamp, (int, float)) or not 0 <= time.time() - stamp <= 3600:
            raise MarketError('Котировки слишком старые или без времени обновления')
        items = data.get('items')
        if not isinstance(items, dict):
            raise MarketError('Неподдерживаемый формат котировок — торговля запрещена')
        quotes = {}
        for item in items.values():
            if not isinstance(item, dict):
                continue
            name = item.get('market_hash_name')
            if not isinstance(name, str) or not name:
                continue
            try:
                bid = to_decimal(item.get('buy_order'))
            except ValueError:
                continue
            if bid <= 0:
                continue
            # Treat duplicate hash names conservatively. Unique phase/float is unpriced.
            quotes[name] = min(quotes[name], bid) if name in quotes else bid
        return quotes

    def offers(self, names: list[str]) -> dict[str, list[dict]]:
        if not 1 <= len(names) <= 50:
            raise ValueError('Batch must include 1-50 names')
        params = [('list_hash_name[]', name) for name in names]
        data = self._get('/search-list-items-by-hash-name-all', params, keyed=True)
        if data.get('success') is not True or data.get('currency') != 'RUB':
            raise MarketError('Невозможно проверить текущие лоты в RUB')
        groups = data.get('data')
        if not isinstance(groups, dict):
            raise MarketError('Неверный формат лотов')
        return {name: groups.get(name, []) if isinstance(groups.get(name), list) else []
                for name in names}

    def buy_by_id(self, item_id: str, max_kopecks: int, custom_id: str) -> dict:
        if not item_id.isdigit() or not 1 <= max_kopecks <= 1000000:
            raise ValueError('Invalid item id or price')
        if not (1 <= len(custom_id) <= 50 and custom_id.isascii()):
            raise ValueError('Invalid custom id')
        return self._get('/buy', {'id': item_id, 'price': max_kopecks,
                                   'custom_id': custom_id, 'buy_alfaskin': 0},
                         keyed=True, mutating=True)

    def buy_status(self, custom_id: str) -> dict:
        return self._get('/get-buy-info-by-custom-id',
                         {'custom_id': custom_id}, keyed=True)

    def inventory(self) -> dict:
        return self._get('/my-inventory', keyed=True)

    # Listing APIs are provided as isolated building blocks but deliberately NOT
    # called automatically. Sale requires separate inventory and custody validation.
    def list_owned_item(self, owned_inventory_id: str, price_kopecks: int) -> dict:
        if not owned_inventory_id.isdigit() or price_kopecks <= 0:
            raise ValueError('Invalid inventory item or price')
        return self._get('/add-to-sale', {'id': owned_inventory_id,
                                          'price': price_kopecks, 'cur': 'RUB'},
                         keyed=True, mutating=True)
