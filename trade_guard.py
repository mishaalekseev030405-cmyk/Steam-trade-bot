
"""Safety limits for CS2 automated trading."""

import os
from decimal import Decimal, InvalidOperation

BUDGET_RUB = Decimal("3000")
MAX_ITEM_RUB = Decimal("500")
MIN_PROFIT_RUB = Decimal("50")
MIN_ROI_PERCENT = Decimal("10")


def validate_candidate(item, spent_rub, balance_rub):
    try:
        price = Decimal(str(item["buy_price_rub"]))
        profit = Decimal(str(item["estimated_profit_rub"]))
        roi = Decimal(str(item["estimated_roi_percent"]))
        spent = Decimal(str(spent_rub))
        balance = Decimal(str(balance_rub))
    except (KeyError, TypeError, InvalidOperation):
        return False, "Invalid candidate data"

    if not all(x.is_finite() for x in
               (price, profit, roi, spent, balance)):
        return False, "Non-finite value"

    if price <= 0 or spent < 0 or balance < 0:
        return False, "Invalid amount"

    if price > MAX_ITEM_RUB:
        return False, "Item price limit exceeded"

    if spent + price > BUDGET_RUB:
        return False, "Total budget exceeded"

    if price > balance:
        return False, "Insufficient balance"

    if profit < MIN_PROFIT_RUB or roi < MIN_ROI_PERCENT:
        return False, "Profit requirements not met"

    if item.get("profit_verified") is not True:
        return False, "Profit not independently verified"

    return True, "Candidate passed preliminary checks"


def purchase_allowed():
    # Hard lock: no live trading in this version.
    return False


def prepare_purchase(item, spent_rub, balance_rub):
    valid, reason = validate_candidate(
        item, spent_rub, balance_rub
    )

    if not valid:
        return {"allowed": False, "reason": reason}

    if not purchase_allowed():
        return {
            "allowed": False,
            "reason": "DRY RUN: real purchases disabled"
        }

    return {"allowed": False, "reason": "No verified trade adapter"}
