
"""Persistent CS2 purchase ledger. No trading requests."""

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "purchase_ledger.json"

BUDGET = Decimal("3000")
MAX_ITEM = Decimal("500")
MAX_POSITIONS = 3


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid monetary value")

    if not result.is_finite() or result < 0:
        raise ValueError("Invalid monetary value")

    return result


def load_ledger():
    if not LEDGER.exists():
        return {"version": 1, "operations": []}

    data = json.loads(LEDGER.read_text(encoding="utf-8"))

    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("operations"), list)
    ):
        raise RuntimeError("Invalid purchase ledger")

    return data


def save_ledger(data):
    temp = LEDGER.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(LEDGER)


def check_capacity(data):
    operations = data["operations"]
    reserved = Decimal("0")
    active = 0
    seen = set()

    for operation in operations:
        if not isinstance(operation, dict):
            raise RuntimeError("Invalid operation")

        item_id = str(operation.get("item_id", "")).strip()
        status = operation.get("status")

        if not item_id or item_id in seen:
            raise RuntimeError("Missing or duplicate item ID")

        seen.add(item_id)

        if status not in (
            "PENDING",
            "UNKNOWN",
            "CONFIRMED",
            "FAILED",
        ):
            raise RuntimeError("Unknown operation status")

        if status in ("PENDING", "UNKNOWN", "CONFIRMED"):
            reserved += money(operation["price_rub"])
            active += 1

    if reserved > BUDGET or active > MAX_POSITIONS:
        raise RuntimeError("Ledger limits exceeded")

    return {
        "reserved_rub": reserved,
        "remaining_rub": BUDGET - reserved,
        "active_positions": active,
        "remaining_positions": MAX_POSITIONS - active,
        "known_item_ids": seen,
        "has_unresolved": any(
            op["status"] in ("PENDING", "UNKNOWN")
            for op in operations
        ),
    }


def reserve_candidate(item):
    data = load_ledger()
    capacity = check_capacity(data)

    if capacity["has_unresolved"]:
        raise RuntimeError(
            "Unresolved operation: purchases blocked"
        )

    item_id = str(item.get("item_id", "")).strip()
    name = str(item.get("name", "")).strip()
    price = money(item.get("buy_price_rub"))

    if not item_id or not name:
        raise ValueError("Missing item identity")

    if item_id in capacity["known_item_ids"]:
        raise RuntimeError("Item already recorded")

    if price <= 0 or price > MAX_ITEM:
        raise RuntimeError("Item price limit exceeded")

    if capacity["remaining_positions"] < 1:
        raise RuntimeError("Position limit reached")

    if price > capacity["remaining_rub"]:
        raise RuntimeError("Budget exceeded")

    operation = {
        "item_id": item_id,
        "name": name,
        "price_rub": str(price),
        "status": "PENDING",
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "custom_id": None,
    }

    data["operations"].append(operation)
    save_ledger(data)

    return operation


def main():
    data = load_ledger()
    capacity = check_capacity(data)

    print("PURCHASE LEDGER: OK")
    print("Budget:", BUDGET, "RUB")
    print("Reserved:", capacity["reserved_rub"], "RUB")
    print("Remaining:", capacity["remaining_rub"], "RUB")
    print("Active positions:", capacity["active_positions"])
    print("Remaining positions:", capacity["remaining_positions"])
    print("Unresolved operations:", capacity["has_unresolved"])
    print("REAL PURCHASES: DISABLED")


if __name__ == "__main__":
    main()
