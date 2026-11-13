
import os
import time
import httpx

BASE_URL = "https://market.csgo.com/api/v2"

MAX_PRICE = 500.0
MIN_PRICE = 50.0
MIN_PROFIT = 50.0
MIN_PROFIT_PERCENT = 10.0
MIN_POPULARITY_7D = 20

SELL_FEE = 0.10
MAX_CANDIDATES = 10
REQUEST_DELAY = 0.3


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_json(client, url, params=None):
    response = client.get(
        url,
        params=params,
    )
    response.raise_for_status()

    result = response.json()

    if not isinstance(result, dict):
        raise ValueError("Invalid API response")

    if result.get("success") is False:
        raise RuntimeError(
            "Market API returned success=false"
        )

    return result


def scan():
    print("MARKET LIVE SCANNER STARTED")

    api_key = os.getenv(
        "MARKET_CSGO_API_KEY", ""
    ).strip()

    if not api_key:
        raise RuntimeError(
            "MARKET_CSGO_API_KEY is missing"
        )

    opportunities = []

    with httpx.Client(
        timeout=40,
        follow_redirects=True,
    ) as client:

        catalog = get_json(
            client,
            f"{BASE_URL}/prices/class_instance/RUB.json",
        )

        if catalog.get("currency") != "RUB":
            raise RuntimeError(
                "Catalog currency is not RUB"
            )

        items = catalog.get("items", {})

        if not isinstance(items, dict):
            raise RuntimeError(
                "Invalid catalog items"
            )

        candidates = []

        for item in items.values():
            if not isinstance(item, dict):
                continue

            name = item.get("market_hash_name")

            if not name:
                continue

            ask = number(item.get("price"))
            bid = number(item.get("buy_order"))
            popularity = number(
                item.get("popularity_7d")
            )

            if not MIN_PRICE <= ask <= MAX_PRICE:
                continue

            if popularity < MIN_POPULARITY_7D:
                continue

            if bid <= 0:
                continue

            # Only a buy order is treated as
            # a possible immediate sale price.
            profit = bid * (1 - SELL_FEE) - ask

            if profit < MIN_PROFIT:
                continue

            profit_percent = profit / ask * 100

            if profit_percent < MIN_PROFIT_PERCENT:
                continue

            candidates.append({
                "name": name,
                "catalog_ask": ask,
                "buy_order": bid,
                "volume": popularity,
                "preliminary_profit": profit,
            })

        candidates.sort(
            key=lambda x: x["preliminary_profit"],
            reverse=True,
        )

        candidates = candidates[:MAX_CANDIDATES]

        print(
            "Preliminary candidates:",
            len(candidates),
        )

        for candidate in candidates:
            time.sleep(REQUEST_DELAY)

            name = candidate["name"]

            try:
                live = get_json(
                    client,
                    (
                        f"{BASE_URL}/"
                        "search-list-items-by-hash-name-all"
                    ),
                    params={
                        "key": api_key,
                        "list_hash_name[]": name,
                    },
                )

                if live.get("currency") != "RUB":
                    print("Currency mismatch:", name)
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
                buy_order = candidate["buy_order"]

                # Conservative exit reference:
                # highest published buy order.
                sell_reference = buy_order

                profit = (
                    sell_reference * (1 - SELL_FEE)
                    - buy_price
                )

                profit_percent = (
                    profit / buy_price * 100
                    if buy_price > 0 else 0
                )

                if not MIN_PRICE <= buy_price <= MAX_PRICE:
                    continue

                if profit < MIN_PROFIT:
                    continue

                if profit_percent < MIN_PROFIT_PERCENT:
                    continue

                signal = {
                    "name": name,
                    "buy_price": round(buy_price, 2),
                    "sell_reference": round(
                        sell_reference, 2
                    ),
                    "buy_order": round(buy_order, 2),
                    "spread": round(
                        sell_reference - buy_price, 2
                    ),
                    "reference_margin": round(
                        profit, 2
                    ),
                    "profit_percent": round(
                        profit_percent, 2
                    ),
                    "volume": candidate["volume"],
                    "item_id": cheapest["item_id"],
                    "live_lots_count": len(valid_lots),
                    "price_source": "buy_order",
                }

                opportunities.append(signal)

                print(
                    "VERIFIED BID SIGNAL:",
                    name,
                    "Lot ID:",
                    signal["item_id"],
                    "Buy:",
                    buy_price,
                    "Bid:",
                    sell_reference,
                    "Estimated profit:",
                    round(profit, 2),
                )

            except (
                httpx.HTTPError,
                ValueError,
                RuntimeError,
            ) as error:
                print(
                    "Live lot check failed:",
                    name,
                    type(error).__name__,
                )

    opportunities.sort(
        key=lambda x: x["reference_margin"],
        reverse=True,
    )

    print(
        "Подходящих сигналов:",
        len(opportunities),
    )

    print("MARKET LIVE SCAN COMPLETED")

    return opportunities


if __name__ == "__main__":
    results = scan()
    print("Scanner test results:", len(results))
