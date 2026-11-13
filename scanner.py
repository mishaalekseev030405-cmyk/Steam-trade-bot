
import math
import time

import httpx


# ===== MARKET.CSGO =====

API_URL = (
    "https://market.csgo.com/api/v2/"
    "prices/class_instance/RUB.json"
)


# ===== НАСТРОЙКИ =====

MIN_PRICE = 50
MAX_PRICE = 500

MIN_POPULARITY_7D = 20
MIN_MARGIN = 50

FEE = 0.10
MAX_DATA_AGE = 7200


def number(value):
    try:
        result = float(value)
        if math.isfinite(result):
            return result
    except (TypeError, ValueError, OverflowError):
        pass

    return None


async def scan():
    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.get(API_URL)
        response.raise_for_status()
        data = response.json()

    # ===== ПРОВЕРКА API =====

    if not isinstance(data, dict):
        raise ValueError("Invalid Market API response")

    if data.get("success") is not True:
        raise ValueError("Market API returned an error")

    if data.get("currency") != "RUB":
        raise ValueError("Unexpected currency")

    timestamp = number(data.get("time"))

    if timestamp is None:
        raise ValueError("Missing market timestamp")

    if abs(time.time() - timestamp) > MAX_DATA_AGE:
        raise ValueError("Market data is outdated")

    items = data.get("items")

    if not isinstance(items, dict):
        raise ValueError("Invalid market items")

    opportunities = {}

    # ===== АНАЛИЗ ПРЕДМЕТОВ =====

    for item in items.values():

        if not isinstance(item, dict):
            continue

        name = item.get("market_hash_name")

        if not isinstance(name, str) or not name:
            continue

        buy_price = number(item.get("price"))
        avg_price = number(item.get("avg_price"))
        bid = number(item.get("buy_order"))

        popularity = number(
            item.get("popularity_7d")
        )

        # ===== ПРОВЕРКА ДАННЫХ =====

        if (
            buy_price is None
            or avg_price is None
            or bid is None
            or popularity is None
        ):
            continue

        if not MIN_PRICE <= buy_price <= MAX_PRICE:
            continue

        if avg_price <= 0:
            continue

        if popularity < MIN_POPULARITY_7D:
            continue

        # ===== ПРОВЕРКА ЗАЯВКИ =====

        if bid <= 0:
            continue

        # ===== РАСЧЁТ ПРИБЫЛИ =====

        estimated_sale = bid * (1 - FEE)

        estimated_margin = (
            estimated_sale - buy_price
        )

        if estimated_margin <= 0:
            continue

        if estimated_margin < MIN_MARGIN:
            continue

        profit_percent = (
            estimated_margin / buy_price
        ) * 100

        discount = (
            (avg_price - buy_price)
            / avg_price
        ) * 100

        # ===== РЕЗУЛЬТАТ =====

        candidate = {
            "name": name,
            "buy_price": round(buy_price, 2),
            "sell_reference": round(bid, 2),
            "buy_order": round(bid, 2),
            "spread": round(discount, 2),
            "reference_margin": round(
                estimated_margin, 2
            ),
            "volume": int(popularity),
            "profit_percent": round(
                profit_percent, 2
            ),
        }

        previous = opportunities.get(name)

        if (
            previous is None
            or candidate["reference_margin"]
            > previous["reference_margin"]
        ):
            opportunities[name] = candidate

    # ===== СОРТИРОВКА =====

    results = sorted(
        opportunities.values(),
        key=lambda x: x["reference_margin"],
        reverse=True
    )

    print(
        f"Подходящих сигналов: {len(results)}"
    )

    return results
