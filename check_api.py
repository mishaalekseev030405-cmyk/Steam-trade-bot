
"""Read-only Market.CSGO balance check."""

import asyncio
import os
from decimal import Decimal, InvalidOperation

import httpx

BASE = "https://market.csgo.com/api/v2"


async def main():
    key = os.getenv("MARKET_CSGO_API_KEY", "").strip()

    if not key:
        raise RuntimeError("API key missing")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{BASE}/get-money",
            params={"key": key}
        )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError("Invalid API response")

    if data.get("success") is not True:
        raise RuntimeError("Market API rejected request")

    if data.get("currency") != "RUB":
        raise RuntimeError("Expected RUB account")

    try:
        balance = Decimal(str(data["money"]))
    except (InvalidOperation, KeyError, TypeError):
        raise RuntimeError("Invalid balance")

    if not balance.is_finite() or balance < 0:
        raise RuntimeError("Invalid balance")

    print("MARKET API: OK")
    print("CURRENCY: RUB")
    print(f"AVAILABLE BALANCE: {balance:.2f} RUB")
    print("PURCHASES: DISABLED")


if __name__ == "__main__":
    asyncio.run(main())
