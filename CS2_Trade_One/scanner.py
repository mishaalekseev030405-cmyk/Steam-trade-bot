"""Rotate across names, verify liquidity and inspect live lot IDs.

A buy-order quote is a snapshot, not a guaranteed executable exit.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from time import time

from config import Settings
from market import Market, MarketError
from store import Store, utcnow
from strategy import Candidate, qualify, sales7d

log = logging.getLogger(__name__)


def run_scan(cfg: Settings, market: Market, store: Store) -> list[dict]:
    """Only committed candidate data is shown. Returns new, unalerted candidates."""
    if cfg.scope == 'watchlist':
        names = json.loads((Path(__file__).resolve().parent / 'watchlist.json').read_text('utf-8'))
        if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
            raise ValueError('watchlist.json должен быть списком названий')
        names = sorted(set(names))
    else:
        names = sorted(market.all_history_ids().keys())
    if not names:
        raise RuntimeError('Нет предметов для поиска')
    cursor = int(store.get('cursor', '0')) % len(names)
    batch = [names[(cursor + i) % len(names)] for i in range(min(cfg.batch_size, len(names)))]
    # Read market bid snapshots first, then filter by 7-day liquidity.
    quotes = market.buy_order_quotes()
    possible = [n for n in batch if n in quotes]
    history_ids = market.all_history_ids()
    qualified = {}
    for name in possible:
        idx = history_ids.get(name)
        if idx is None:
            continue
        try:
            raw = market.history(idx)
            # Outdated history and missing volume must never trigger a trade.
            seen_time = raw.get('time')
            if not isinstance(seen_time, (int, float)) or not 0 <= time() - seen_time <= 10800:
                continue
            history = raw['data']
            if sales7d(history) >= cfg.min_sales_7d:
                qualified[name] = history
        except (MarketError, ValueError, KeyError) as exc:
            log.warning('History unavailable for %s: %s', name, type(exc).__name__)
            continue
    candidates: list[Candidate] = []
    for start in range(0, len(qualified), 50):
        group = list(qualified)[start:start + 50]
        offers = market.offers(group)
        for name in group:
            for offer in offers[name][:50]:
                if not isinstance(offer, dict):
                    continue
                result = qualify(name, offer, qualified[name], quotes[name], cfg)
                if result:
                    candidates.append(result)
    store.save_candidates(candidates)
    store.set('cursor', str((cursor + len(batch)) % len(names)))
    store.set('last_scan', utcnow())
    store.set('last_scan_count', str(len(batch)))
    store.set('last_scan_found', str(len(candidates)))
    return store.unalerted(limit=5)
