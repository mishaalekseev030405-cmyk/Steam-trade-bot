
import asyncio
import os

import httpx


# ===== НАСТРОЙКИ =====

API_URL = (
    "https://market.csgo.com/api/v2/"
    "search-list-items-by-hash-name-all"
)

ITEM_NAME = "Five-SeveN | Heat Treated (Field-Tested)"

MAX_OFFERS_TO_SHOW = 5


# ===== ПРОВЕРКА РЕАЛЬНЫХ ЛОТОВ =====

async def main():
    print("CS2 LIVE LOTS CHECK STARTED")

    api_key = os.environ.get("MARKET_CSGO_API_KEY")

    if not api_key:
        raise RuntimeError(
            "MARKET_CSGO_API_KEY is missing"
        )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            API_URL,
            params={
                "key": api_key,
                "list_hash_name[]": ITEM_NAME,
            },
        )

        response.raise_for_status()
        data = response.json()

    # ===== ПРОВЕРКА ОТВЕТА =====

    if not isinstance(data, dict):
        raise ValueError("Invalid API response")

    if data.get("success") is not True:
        raise RuntimeError(
            f"Market API error: {data.get('error')}"
        )

    print("Currency:", data.get("currency"))
    print("Item:", ITEM_NAME)

    # ===== ПОЛУЧЕНИЕ ЛОТОВ =====

    items_data = data.get("data", {})

    if not isinstance(items_data, dict):
        raise ValueError("Invalid items data")

    offers = items_data.get(ITEM_NAME, [])

    if not isinstance(offers, list):
        raise ValueError("Invalid offers list")

    print("Offers found:", len(offers))

    # ===== ПРОВЕРКА ПОЛЕЙ API =====

    if offers and isinstance(offers[0], dict):
        print(
            "First offer fields:",
            list(offers[0].keys())
        )

    # ===== ВЫВОД ПРЕДЛОЖЕНИЙ =====

    valid_offers = []

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        try:
            price_rub = float(offer["price"]) / 100
        except (KeyError, TypeError, ValueError):
            continue

        if price_rub <= 0:
            continue

        valid_offers.append({
            "item_id": offer.get("id"),
            "price_rub": round(price_rub, 2),
        })

    valid_offers.sort(
        key=lambda item: item["price_rub"]
    )

    print("Valid offers:", len(valid_offers))

    for offer in valid_offers[:MAX_OFFERS_TO_SHOW]:
        print(offer)

    if valid_offers:
        print(
            "Lowest price:",
            valid_offers[0]["price_rub"],
            "RUB"
        )
    else:
        print("No valid offers found")

    print("CHECK COMPLETED")


if __name__ == "__main__":
    asyncio.run(main())
