
"""CS2 trade engine: safe simulation only."""

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT_FILE = ROOT / "latest_results.json"
OUTPUT_FILE = ROOT / "trade_simulation.json"

BUDGET = Decimal("3000")
MAX_PRICE = Decimal("500")
MIN_PROFIT = Decimal("50")
MIN_ROI = Decimal("10")
MIN_SALES_7D = 20


def decimal_value(value):
    try:
        number = Decimal(str(value))
        if number.is_finite():
            return number
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def evaluate(items):
    spent = Decimal("0")
    seen = set()
    simulated = []
    rejected = []

    for item in items:
        if not isinstance(item, dict):
            rejected.append({
                "reason": "invalid_item"
            })
            continue

        item_id = str(item.get("item_id") or "").strip()
        name = str(item.get("name") or "")

        price = decimal_value(item.get("buy_price_rub"))
        profit = decimal_value(
            item.get("estimated_profit_rub")
        )
        roi = decimal_value(
            item.get("estimated_roi_percent")
        )
        sales = decimal_value(
            item.get("sales7d_reported")
        )

        reason = None

        if not item_id:
            reason = "missing_item_id"
        elif item_id in seen:
            reason = "duplicate_item"
        elif price is None or price <= 0:
            reason = "invalid_price"
        elif price > MAX_PRICE:
            reason = "price_above_limit"
        elif profit is None or roi is None:
            reason = "profit_not_calculated"
        elif profit < MIN_PROFIT or roi < MIN_ROI:
            reason = "insufficient_profit"
        elif sales is None or sales < MIN_SALES_7D:
            reason = "insufficient_sales"
        elif spent + price > BUDGET:
            reason = "budget_exceeded"

        if item_id:
            seen.add(item_id)

        if reason:
            rejected.append({
                "item_id": item_id,
                "name": name,
                "reason": reason
            })
            continue

        spent += price

        simulated.append({
            "item_id": item_id,
            "name": name,
            "price_rub": str(price),
            "estimated_profit_rub": str(profit),
            "estimated_roi_percent": str(roi),
            "profit_verified": (
                item.get("profit_verified") is True
            ),
            "status": "SIMULATED_ONLY"
        })

    return {
        "mode": "DRY_RUN",
        "budget_rub": str(BUDGET),
        "simulated_spend_rub": str(spent),
        "remaining_rub": str(BUDGET - spent),
        "simulated_buys": simulated,
        "rejected": rejected,
        "real_purchases": 0,
        "warning": (
            "Simulation only. "
            "Profit estimates are unverified."
        )
    }


def main():
    if os.getenv("DRY_RUN", "").lower() != "true":
        raise RuntimeError(
            "DRY_RUN must remain true"
        )

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            "latest_results.json missing"
        )

    items = json.loads(
        INPUT_FILE.read_text(encoding="utf-8")
    )

    if not isinstance(items, list):
        raise ValueError(
            "Expected a list of candidates"
        )

    report = evaluate(items)

    OUTPUT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print("Trade simulation: OK", flush=True)
    print("Candidates:", len(items), flush=True)
    print(
        "Simulated buys:",
        len(report["simulated_buys"]),
        flush=True
    )
    print(
        "Simulated spend:",
        report["simulated_spend_rub"],
        "RUB",
        flush=True
    )
    print(
        "Rejected:",
        len(report["rejected"]),
        flush=True
    )
    print("Real purchases: 0", flush=True)


if __name__ == "__main__":
    main()
