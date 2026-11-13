
import os
import time
import math

import httpx


BASE_URL = "https://market.csgo.com/api/v2"

MIN_PRICE = 50.0
MAX_PRICE = 500.0

MIN_PROFIT = 50.0
MIN_PROFIT_PERCENT = 10.0

MIN_SALES_7D = 20
SELL_FEE = 0.10

MAX_HISTORY_CHECKS = 60
MAX_LIVE_CHECKS = 5

REQUEST_DELAY = 2.0


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def rub(value):
    if isinstance(value, dict):
        return number(value.get("RUB"))
    return 0.0


def fetch(client, path, params=None):
    response = client.get(
        f"{BASE_URL}/{path}",
        params=params,
    )

    response.raise_for_status()

    result = response.json()

    if not isinstance(result, dict):
        raise ValueError("Invalid API response")

    if result.get("success") is False:
        raise RuntimeError("Market API rejected request")

    return result


def log_error(name, error):
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        print("HTTP ERROR:", name, "Status:", status)
        return status

    print("API ERROR:", name, type(error).__name__)
    return None


def scan():
    print("SMART MARKET SCANNER STARTED")

    api_key = os.getenv(
        "MARKET_CSGO_API_KEY", ""
    ).strip()

    if not api_key:
        raise RuntimeError("Market API key missing")

    opportunities = []

    with httpx.Client(timeout=40) as client:

        catalog = fetch(
            client,
            "prices/class_instance/RUB.json",
        )

        if catalog.get("currency") != "RUB":
            raise RuntimeError("Invalid catalog currency")

        items = catalog.get("items", {})

        history_index = fetch(
            client,
            "full-history/all.json",
        )

        history_ids = history_index.get("history", {})

        if not isinstance(items, dict):
            raise RuntimeError("Invalid catalog items")

        if not isinstance(history_ids, dict):
            raise RuntimeError("Invalid history index")

        candidates = []
        seen = set()

        for item in items.values():
            if not isinstance(item, dict):
                continue

            name = item.get("market_hash_name")

            if not name or name in seen:
                continue

            price = number(item.get("price"))
            popularity = number(
                item.get("popularity_7d")
            )

            if not MIN_PRICE <= price <= MAX_PRICE:
                continue

            if popularity < MIN_SALES_7D:
                continue

            history_id = history_ids.get(name)

            if history_id is None:
                continue

            seen.add(name)

            candidates.append({
                "name": name,
                "price": price,
                "history_id": history_id,
                "popularity": popularity,
            })

        candidates.sort(
            key=lambda x: x["popularity"],
            reverse=True,
        )

        candidates = candidates[:MAX_HISTORY_CHECKS]

        print("History candidates:", len(candidates))

        profitable = []

        for candidate in candidates:
            time.sleep(REQUEST_DELAY)

            name = candidate["name"]

            try:
                history = fetch(
                    client,
                    (
                        "full-history/"
                        f"{candidate['history_id']}.json"
                    ),
                )

                data = history.get("data", {})

                if not isinstance(data, dict):
                    continue

                average_7d = rub(data.get("average7d"))
                average_30d = rub(data.get("average30d"))
                sales_7d = rub(data.get("sales7d"))

                if sales_7d < MIN_SALES_7D:
                    continue

                if average_7d <= 0:
                    continue

                sell_reference = average_7d

                if average_30d > 0:
                    sell_reference = min(
                        average_7d,
                        average_30d,
                    )

                catalog_price = candidate["price"]

                preliminary_profit = (
                    sell_reference * (1 - SELL_FEE)
                    - catalog_price
                )

                preliminary_percent = (
                    preliminary_profit
                    / catalog_price * 100
                )

                if preliminary_profit < MIN_PROFIT:
                    continue

                if preliminary_percent < MIN_PROFIT_PERCENT:
                    continue

                profitable.append({
                    **candidate,
                    "sell_reference": sell_reference,
                    "sales_7d": sales_7d,
                    "preliminary_profit": preliminary_profit,
                })

                print(
                    "HISTORY CANDIDATE:",
                    name,
                    "Profit:",
                    round(preliminary_profit, 2),
                )

            except (
                httpx.HTTPError,
                ValueError,
                RuntimeError,
            ) as error:
                status = log_error(name, error)

                if status == 429:
                    print("RATE LIMIT: stopping scan")
                    break

        profitable.sort(
            key=lambda x: x["preliminary_profit"],
            reverse=True,
        )

        profitable = profitable[:MAX_LIVE_CHECKS]

        print("Candidates for live check:", len(profitable))

        for candidate in profitable:
            time.sleep(REQUEST_DELAY)

            name = candidate["name"]

            try:
                live = fetch(
                    client,
                    "search-list-items-by-hash-name-all",
                    params={
                        "key": api_key,
                        "list_hash_name[]": name,
                    },
                )

                if live.get("currency") != "RUB":
                    continue

                data = live.get("data", {})

                if not isinstance(data, dict):
                    continue

                lots = data.get(name, [])

                if not isinstance(lots, list):
                    continue

                valid_lots = []

                for lot in lots:
                    if not isinstance(lot, dict):
                        continue

                    item_id = lot.get("id")
                    price_kopeks = number(
                        lot.get("price")
                    )

                    if not item_id or price_kopeks <= 0:
                        continue

                    valid_lots.append({
                        "item_id": str(item_id),
                        "price": price_kopeks / 100,
                    })

                if not valid_lots:
                    continue

                cheapest = min(
                    valid_lots,
                    key=lambda x: x["price"],
                )

                buy_price = cheapest["price"]
                sell_reference = candidate["sell_reference"]

                if not MIN_PRICE <= buy_price <= MAX_PRICE:
                    continue

                profit = (
                    sell_reference * (1 - SELL_FEE)
                    - buy_price
                )

                profit_percent = (
                    profit / buy_price * 100
                )

                if profit < MIN_PROFIT:
                    continue

                if profit_percent < MIN_PROFIT_PERCENT:
                    continue

                opportunities.append({
                    "name": name,
                    "buy_price": round(buy_price, 2),
                    "sell_reference": round(
                        sell_reference, 2
                    ),
                    "buy_order": round(
                        sell_reference, 2
                    ),
                    "spread": round(
                        sell_reference - buy_price, 2
                    ),
                    "reference_margin": round(
                        profit, 2
                    ),
                    "profit_percent": round(
                        profit_percent, 2
                    ),
                    "volume": int(candidate["sales_7d"]),
                    "item_id": cheapest["item_id"],
                    "live_lots_count": len(valid_lots),
                    "price_source": "sales_history",
                })

                print(
                    "VERIFIED HISTORY SIGNAL:",
                    name,
                    "Profit:",
                    round(profit, 2),
                )

            except (
                httpx.HTTPError,
                ValueError,
                RuntimeError,
            ) as error:
                status = log_error(name, error)

                if status == 429:
                    print("RATE LIMIT: stopping live checks")
                    break

    opportunities.sort(
        key=lambda x: x["reference_margin"],
        reverse=True,
    )

    print("Подходящих сигналов:", len(opportunities))
    print("SMART MARKET SCAN COMPLETED")

    return opportunities


if __name__ == "__main__":
    results = scan()
    print("Scanner results:", len(results))
