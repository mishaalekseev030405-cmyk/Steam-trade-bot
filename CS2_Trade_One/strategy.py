"""Find liquid discounts vs live buy-order quotes; these are NOT guaranteed profits."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from config import Settings
from market import kopecks_to_rub, to_decimal


@dataclass(frozen=True)
class Candidate:
    item_id: str
    name: str
    ask_kopecks: int
    bid_rub: str
    profit_rub: str
    roi_percent: str
    sales_7d: int

    @property
    def ask_rub(self) -> Decimal:
        return Decimal(self.ask_kopecks) / 100

    def serialize(self) -> dict:
        return asdict(self)


def sales7d(data: dict[str, Any]) -> int:
    raw = data.get('sales7d')
    if isinstance(raw, dict):
        raw = raw.get('RUB')
    val = to_decimal(raw)
    if val != val.to_integral_value():
        raise ValueError('Invalid sales count')
    return int(val)


def qualify(name: str, offer: dict, history: dict, bid_rub: Decimal,
            cfg: Settings) -> Candidate | None:
    """Safety: phase/pattern-specific premiums not priced; no arbitrary substitution."""
    if any(token in name.lower() for token in (
            'doppler', 'gamma doppler', 'case hardened', 'heat treated', 'fade')):
        return None
    try:
        cnt = sales7d(history)
        offer_id = str(offer.get('id', ''))
        if not offer_id.isdigit():
            return None
        price_kopecks = to_decimal(offer['price'])
        if price_kopecks != price_kopecks.to_integral_value():
            return None
        ask_kopecks = int(price_kopecks)
        ask = kopecks_to_rub(ask_kopecks)
        if not cfg.min_item_rub <= ask <= cfg.max_item_rub or cnt < cfg.min_sales_7d:
            return None
        if bid_rub <= ask or bid_rub / ask < cfg.price_min_bid_ask_ratio:
            return None
        net_sell = bid_rub * (Decimal(1) - cfg.sell_fee)
        profit = net_sell - ask
        roi = profit / ask * 100
        if profit < cfg.min_profit_rub or roi < cfg.min_roi_percent:
            return None
        return Candidate(offer_id, name, ask_kopecks, str(bid_rub),
                         str(profit.quantize(Decimal('0.01'))),
                         str(roi.quantize(Decimal('0.01'))), cnt)
    except (ValueError, TypeError, ZeroDivisionError):
        return None
