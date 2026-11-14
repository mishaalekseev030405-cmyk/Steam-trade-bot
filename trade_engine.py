"""CS2 trading simulation only. No network requests or real purchases."""
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'latest_results.json'
REPORT = ROOT / 'trade_simulation.json'
BUDGET = Decimal('3000')
MAX_ITEM = Decimal('500')
MIN_PROFIT = Decimal('50')
MIN_ROI = Decimal('10')


def amount(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def simulate(items):
    spent = Decimal('0')
    seen = set()
    approved, rejected = [], []
    for item in items:
        if not isinstance(item, dict):
            rejected.append({'reason': 'invalid_item'})
            continue
        name = str(item.get('name', ''))
        item_id = str(item.get('item_id', '')).strip()
        price = amount(item.get('buy_price_rub'))
        profit = amount(item.get('estimated_profit_rub'))
        roi = amount(item.get('estimated_roi_percent'))
        reason = None
        if not item_id or item_id in seen:
            reason = 'missing_or_duplicate_id'
        elif price is None or profit is None or roi is None:
            reason = 'missing_or_invalid_numbers'
        elif price <= 0 or price > MAX_ITEM:
            reason = 'item_price_limit'
        elif profit < MIN_PROFIT or roi < MIN_ROI:
            reason = 'profit_filter'
        elif spent + price > BUDGET:
            reason = 'budget_limit'
        if item_id:
            seen.add(item_id)
        if reason:
            rejected.append({'item_id': item_id, 'name': name, 'reason': reason})
            continue
        spent += price
        approved.append({'item_id': item_id, 'name': name,
                         'price_rub': str(price),
                         'estimated_profit_rub': str(profit),
                         'estimated_roi_percent': str(roi),
                         'profit_verified': item.get('profit_verified') is True,
                         'status': 'SIMULATED_ONLY'})
    return {'mode': 'SIMULATION_ONLY', 'real_purchases': 0,
            'simulated_spend_rub': str(spent),
            'budget_rub': str(BUDGET),
            'simulated_remaining_rub': str(BUDGET - spent),
            'approved_simulations': approved,
            'rejected': rejected,
            'warning': 'Estimates are not executable prices; no trading API is called.'}


def main():
    if os.getenv('DRY_RUN', '').strip().lower() != 'true':
        raise RuntimeError('Safety lock: DRY_RUN must be true')
    if not RESULTS.is_file():
        raise RuntimeError('latest_results.json missing: run monitor.py first')
    items = json.loads(RESULTS.read_text(encoding='utf-8'))
    if not isinstance(items, list):
        raise ValueError('latest_results.json must contain a list')
    report = simulate(items)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Trade simulation: OK')
    print('Candidates:', len(items))
    print('Simulated buys:', len(report['approved_simulations']))
    print('Simulated spend:', report['simulated_spend_rub'], 'RUB')
    print('Real purchases: 0')


if __name__ == '__main__':
    main()
