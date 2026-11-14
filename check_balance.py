
"""Read-only Market.CSGO balance check."""

import os
from decimal import Decimal, InvalidOperation

import httpx

API_URL = "https://market.csgo.com/api/v2/get-money"
BUDGET_RUB = Decimal("3000")
MAX_ITEM_RUB = Decimal("500")


def main():
    key = os.getenv("MARKET_CSGO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("MARKET_CSGO_API_KEY missing")

    with httpx.Client(timeout=20) as client:
        response = client.get(API_URL, params={"key": key})
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict) or data.get("success") is not True:
        raise RuntimeError("Balance API rejected request")

    if data.get("currency") != "RUB":
        raise RuntimeError("Account currency is not RUB")

    try:
        balance = Decimal(str(data["money"]))
    except (KeyError, InvalidOperation, TypeError):
        raise RuntimeError("Invalid balance response")

    if not balance.is_finite() or balance < 0:
        raise RuntimeError("Invalid balance amount")

    available = min(balance, BUDGET_RUB)

    print("Balance check: OK")
    print("Account currency: RUB")
    print("Account balance:", balance, "RUB")
    print("Trading budget cap:", BUDGET_RUB, "RUB")
    print("Available within budget:", available, "RUB")
    print("Maximum item price:", MAX_ITEM_RUB, "RUB")
    print("Can afford one max-price item:", available >= MAX_ITEM_RUB)
    print("Real purchases: DISABLED")


if __name__ == "__main__":
    main()
