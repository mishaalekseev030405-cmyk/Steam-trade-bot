
import math
import os
import time

import httpx


# ===== MARKET.CSGO API =====

BASE_URL = "https://market.csgo.com/api/v2/"

PRICES_URL = (
    BASE_URL + "prices/class_instance/RUB.json"
)

LOTS_URL = (
    BASE_URL + "search-list-items-by-hash-name-all"
)


# ===== НАСТРОЙКИ =====

MIN_PRICE = 50.0
MAX_PRICE = 500.0

MIN_POPULARITY_7D = 20
MIN_MARGIN = 50.0
MIN_PROFIT_PERCENT = 10.0

SELL_FEE = 0.10
MAX_DATA_AGE = 7200

MAX_CANDIDATES = 10


# ===== ПРОВЕРКА ЧИСЕЛ =====

def number(value):
    try:
        result = float(value)

        if math.isfinite(result):
            return result

    except (TypeError, ValueError, OverflowError):
        pass

    return None


# ===== ОБЩИЙ ПРАЙС-ЛИСТ =====

async def get_market_prices(client):
    response = await client.get(PRICES_URL)
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Invalid prices response")

    if data.get("success") is not True:
        raise ValueError("Market prices API error")

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

    return items


# ===== РЕАЛЬНЫЕ ЛОТЫ =====

async def get_live_lots(client, api_key, name):
    response = await client.get(
        LOTS_URL,
        params={
            "key": api_key,
            "list_hash_name[]": name,
        },
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Invalid lots response")

    if data.get("success") is not True:
        raise ValueError("Market lots API error")

    if data.get("currency") != "RUB":
        raise ValueError("Unexpected lots currency")

    items = data.get("data")

    if not isinstance(items, dict):
        raise ValueError("Invalid lots data")

    offers = items.get(name, [])

    if not isinstance(offers, list):
        raise ValueError("Invalid offers list")

    valid_lots = []

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        lot_id = offer.get("id")
        raw_price = number(offer.get("price"))

        if (
            not isinstance(lot_id, int)
            or isinstance(lot_id, bool)
            or lot_id <= 0
            or raw_price is None
            or raw_price <= 0
        ):
            continue

        price_rub = raw_price / 100

        if not MIN_PRICE <= price_rub <= MAX_PRICE:
            continue

        valid_lots.append({
            "item_id": lot_id,
            "price": price_rub,
        })

    valid_lots.sort(
        key=lambda lot: lot["price"]
    )

    return valid_lots


# ===== ОСНОВНОЙ СКАНЕР =====

async def scan():
    api_key = os.environ.get(
        "MARKET_CSGO_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "MARKET_CSGO_API_KEY is missing"
        )

    print("MARKET LIVE SCANNER STARTED")

    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        market_items = await get_market_prices(
            client
        )

        candidates = {}

        # ===== ПЕРВИЧНЫЙ ОТБОР =====

        for item in market_items.values():
            if not isinstance(item, dict):
                continue

            name = item.get("market_hash_name")

            if not isinstance(name, str) or not name:
                continue

            price = number(item.get("price"))
            avg_price = number(
                item.get("avg_price")
            )
            bid = number(
                item.get("buy_order")
            )
            popularity = number(
                item.get("popularity_7d")
            )

            if any(
                value is None
                for value in (
                    price,
                    avg_price,
                    bid,
                    popularity,
                )
            ):
                continue

            if not MIN_PRICE <= price <= MAX_PRICE:
                continue

            if avg_price <= 0 or bid <= 0:
                continue

            if popularity < MIN_POPULARITY_7D:
                continue

            preliminary_profit = (
                bid * (1 - SELL_FEE) - price
            )

            if preliminary_profit < MIN_MARGIN:
                continue

            preliminary_percent = (
                preliminary_profit / price * 100
            )

            if (
                preliminary_percent
                < MIN_PROFIT_PERCENT
            ):
                continue

            candidate = {
                "name": name,
                "avg_price": avg_price,
                "bid": bid,
                "popularity": popularity,
                "preliminary_profit": (
                    preliminary_profit
                ),
            }

            previous = candidates.get(name)

            if (
                previous is None
                or preliminary_profit
                > previous["preliminary_profit"]
            ):
                candidates[name] = candidate

        ranked = sorted(
            candidates.values(),
            key=lambda x: x["preliminary_profit"],
            reverse=True,
        )

        print(
            "Preliminary candidates:",
            len(ranked)
        )

        # ===== ПРОВЕРКА РЕАЛЬНЫХ ЛОТОВ =====

        opportunities = []

        for candidate in ranked[:MAX_CANDIDATES]:
            name = candidate["name"]

            try:
                lots = await get_live_lots(
                    client,
                    api_key,
                    name,
                )

            except (
                httpx.HTTPError,
                ValueError,
            ) as error:
                print(
                    "Lot check failed:",
                    name,
                    type(error).__name__,
                )
                continue

            if not lots:
                continue

            best_lot = lots[0]

            buy_price = best_lot["price"]
            bid = candidate["bid"]

            estimated_sale = (
                bid * (1 - SELL_FEE)
            )

            profit = (
                estimated_sale - buy_price
            )

            if profit < MIN_MARGIN:
                continue

            profit_percent = (
                profit / buy_price * 100
            )

            if (
                profit_percent
                < MIN_PROFIT_PERCENT
            ):
                continue

            avg_price = candidate["avg_price"]

            discount = (
                (avg_price - buy_price)
                / avg_price * 100
            )

            opportunity = {
                "name": name,
                "buy_price": round(
                    buy_price, 2
                ),
                "sell_reference": round(
                    bid, 2
                ),
                "buy_order": round(
                    bid, 2
                ),
                "spread": round(
                    discount, 2
                ),
                "reference_margin": round(
                    profit, 2
                ),
                "volume": int(
                    candidate["popularity"]
                ),
                "profit_percent": round(
                    profit_percent, 2
                ),
                "item_id": best_lot["item_id"],
                "live_lots_count": len(lots),
                "price_source": "LIVE_LOT",
            }

            opportunities.append(opportunity)

            print(
                "LIVE SIGNAL:",
                name,
                "Lot ID:",
                best_lot["item_id"],
                "Buy:",
                round(buy_price, 2),
                "Estimated profit:",
                round(profit, 2),
            )

        opportunities.sort(
            key=lambda item: (
                item["reference_margin"]
            ),
            reverse=True,
        )

        print(
            "Подходящих сигналов:",
            len(opportunities)
        )

        print("MARKET LIVE SCAN COMPLETED")

        return opportunities
