"""Single-item purchase execution, simulation, and idempotency ledger."""
from __future__ import annotations

from decimal import Decimal

from config import Settings
from market import Market, MarketError
from store import Store
from strategy import qualify


class TradeError(RuntimeError):
    pass


def buy_candidate(item_id: str, cfg: Settings, market: Market, store: Store) -> str:
    """Caller must have acquired the per-process trade lock.

    In DRY_RUN this only records simulation. Live requires a dedicated env gate
    AND the owner must press the second confirmation button in Telegram.
    """
    item = store.candidate(item_id)
    if item is None:
        raise TradeError('Лот не найден в результатах сканера')

    # Recheck the exact id, live bid, price and wallet immediately before reserve.
    offers = market.offers([item['name']])[item['name']]
    exact = next((o for o in offers if str(o.get('id')) == item_id), None)
    if exact is None:
        raise TradeError('Лот исчез из продажи')
    if str(exact.get('price')) != str(item['ask_kopecks']):
        raise TradeError('Цена лота изменилась; необходимо новое сканирование')
    quotes = market.buy_order_quotes()
    bid = quotes.get(item['name'])
    if bid is None:
        raise TradeError('Не удалось независимо подтвердить buy-ордер')
    market_history = {'sales7d': {'RUB': item['sales_7d']}}
    check = qualify(item['name'], exact, market_history, bid, cfg)
    if check is None:
        raise TradeError('При текущих котировках лот больше не подходит')

    if cfg.live_ready:
        account_balance = market.balance()
        if account_balance < check.ask_rub:
            raise TradeError('На Market.CSGO недостаточно RUB')

    # Durable reservation BEFORE any external request. Prevents double buys.
    reservation = store.reserve(item, cfg)
    if not cfg.live_ready:
        store.update_purchase(item_id, 'SIMULATED', 'DRY_RUN: no buy call')
        return f'🧪 Симуляция покупки: {item["name"]} за {check.ask_rub} ₽. Денег не потрачено.'

    try:
        response = market.buy_by_id(item_id, reservation['ask_kopecks'],
                                    reservation['custom_id'])
    except MarketError as exc:
        # Even a transport failure may have processed a real purchase.
        store.update_purchase(item_id, 'UNKNOWN', type(exc).__name__)
        raise TradeError('Статус покупки неизвестен. ПОВТОРНО НЕ ПОКУПАЙ. Проверь /sync.') from exc

    if response.get('success') is True and str(response.get('id', '')).strip():
        store.update_purchase(item_id, 'ACCEPTED', 'API accepted, needs reconciliation')
        return ('✅ Market.CSGO принял запрос на покупку. '\
                f'Лот {item_id}, максимум {check.ask_rub} ₽. '\
                'Это ещё НЕ подтверждение доставки. Нажми «Сверить покупки».')
    # Even explicit rejection can be ambiguous across API versions: keep it blocked.
    store.update_purchase(item_id, 'UNKNOWN', 'Unrecognized buy response')
    raise TradeError('Непонятный ответ торгового API; нужна ручная сверка')


def reconcile(cfg: Settings, market: Market, store: Store) -> str:
    if not cfg.live_ready:
        return '🧪 DRY_RUN: реальных покупок через этого бота нет.'
    ops = store.unresolved()
    if not ops:
        return 'Незавершённых сделок нет.'
    lines = []
    for op in ops:
        try:
            result = market.buy_status(op['custom_id'])
            detail = result.get('data')
            if result.get('success') is not True or not isinstance(detail, dict):
                lines.append(f"{op['item_id']}: неизвестный ответ, не повторять")
                continue
            reported_id = detail.get('item_id')
            if reported_id is not None and str(reported_id) != op['item_id']:
                lines.append(f"{op['item_id']}: ⚠️ API вернул другой item_id")
                continue
            status = str(detail.get('stage', ''))
            # Per documented market stages: 1 new, 2 given, 5 timed out.
            if status == '2':
                store.update_purchase(op['item_id'], 'CONFIRMED', 'stage=2 item given')
                lines.append(f"{op['item_id']}: ✅ передано (stage=2)")
            elif status == '1':
                store.update_purchase(op['item_id'], 'ACCEPTED', 'stage=1 waiting')
                lines.append(f"{op['item_id']}: ⏳ ожидает передачи")
            elif status == '5':
                # A timed-out trade can involve non-final refund; do not release budget.
                store.update_purchase(op['item_id'], 'UNKNOWN', 'stage=5; inspect refund')
                lines.append(f"{op['item_id']}: ⚠️ stage=5, проверь отмену и возврат вручную")
            else:
                store.update_purchase(op['item_id'], 'UNKNOWN', 'Unknown stage')
                lines.append(f"{op['item_id']}: ⚠️ неизвестная стадия")
        except (MarketError, ValueError):
            lines.append(f"{op['item_id']}: ⚠️ сверка не выполнена")
    return '\n'.join(lines)
