import asyncio
import httpx

BASE = "https://market.csgo.com/api/v2/prices/"
MIN_PRICE = 50
MAX_PRICE = 5000
MIN_VOLUME = 20
MAX_SPREAD = 30
FEE = 0.10  # Предполагаемая комиссия

async def get_items(client, url):
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()

    if data.get("success") is not True:
        raise ValueError("API returned an error")

    if not isinstance(data.get("items"), list):
        raise ValueError("Invalid items format")

    return data["items"]

async def scan():
    async with httpx.AsyncClient(timeout=30) as client:
        sales = await get_items(
            client, BASE + "RUB.json"
        )
        orders = await get_items(
            client,
            "https://market.csgo.com/api/v2/prices/orders/RUB.json"
        )

    order_map = {
        x["market_hash_name"]: x
        for x in orders
        if x.get("market_hash_name")
    }

    results = []

    for item in sales:
        name = item.get("market_hash_name")
        order = order_map.get(name)

        if not order:
            continue

        try:
            sell = float(item["price"])
            bid = float(order["price"])
            volume = int(item.get("volume", 0))
        except (KeyError, ValueError, TypeError):
            continue

        if not MIN_PRICE <= sell <= MAX_PRICE:
            continue

        if volume < MIN_VOLUME or bid <= 0:
            continue

        spread = (sell - bid) / sell * 100

        if not 0 < spread <= MAX_SPREAD:
            continue

        net_sell = sell * (1 - FEE)
        margin = net_sell - bid

        results.append({
            "name": name,
            "sell_reference": round(sell, 2),
            "buy_order": round(bid, 2),
            "spread": round(spread, 2),
            "reference_margin": round(margin, 2),
            "volume": volume
        })

    return sorted(
        results,
        key=lambda x: x["reference_margin"],
        reverse=True
    )

if __name__ == "__main__":
    found = asyncio.run(scan())
    print("Найдено:", len(found))
    for item in found[:10]:
        print(item)

