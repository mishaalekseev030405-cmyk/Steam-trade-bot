
import asyncio
import os
import httpx

API_URL = (
    "https://market.csgo.com/api/v2/"
    "search-list-items-by-hash-name-all"
)

ITEM_NAME = "Five-SeveN | Heat Treated (Field-Tested)"

async def main():
    key = os.environ.get("MARKET_CSGO_API_KEY")

    if not key:
        raise RuntimeError("API key is missing")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            API_URL,
            params={
                "key": key,
                "list_hash_name[]": ITEM_NAME,
            },
        )
        response.raise_for_status()
        data = response.json()

    if data.get("success") is not True:
        print("API error:", data.get("error"))
        return

    print("Currency:", data.get("currency"))

    offers = data.get("data", {}).get(ITEM_NAME, [])

    for offer in offers[:5]:
        print({
            "item_id": offer.get("id"),
            "price_rub": round(
                float(offer["price"]) / 100, 2
            ),
        })

    print("Offers found:", len(offers))

asyncio.run(main())
