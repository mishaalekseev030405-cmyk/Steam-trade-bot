
import os
import time
import math
from datetime import datetime, timezone

import httpx


BASE_URL = "https://market.csgo.com/api/v2"

MIN_PRICE = 50.0
MAX_PRICE = 500.0

MIN_PROFIT = 50.0
MIN_PROFIT_PERCENT = 10.0

MIN_SALES_7D = 20
SELL_FEE = 0.10

MAX_CANDIDATES = 30
REQUEST_DELAY = 0.5


def number(value, default=0.0):
    try:
        result = float(value)

        if not math.isfinite(result):
            return default

        return result

    except (TypeError, ValueError):
        return default


def rub(value):
    if isinstance(value, dict):
        return number(value.get("RUB"))

    return 0.0


def fetch(client, path, params=None):
    url = f"{BASE_URL}/{path}"

    response = client.get(
        url,
        params=params,
    )

    response.raise_for_status()

    result = response.json()

    if not isinstance(result, dict):
        raise ValueError(
            "Invalid Market API response"
        )

    if result.get("success") is False:
        raise RuntimeError(
            "Market API returned success=false"
        )

    return result


def print_error(name, error):
    print(
        "Check failed:",
        name,
        repr(error),
    )

    if isinstance(error, httpx.HTTPStatusError):
        print(
            "HTTP STATUS:",
            error.response.status_code,
        )

        # Do not expose API keys or query parameters.
        print(
            "REQUEST URL:",
            str(error.request.url).split("?")[0],
        )

        if error.response.status_code == 429:
            print(
                "RATE LIMIT: too many requests"
            )


def scan():
    print("HISTORY VERIFIED SCANNER STARTED")

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

        print("Loading market catalog")

        catalog = fetch(
            client,
            "prices/class_instance/RUB.json",
        )

        if catalog.get("currency") != "RUB":
            raise RuntimeError(
                "Catalog currency mismatch"
            )

        items = catalog.get("items", {})

        if not isinstance(items, dict):
            raise RuntimeError(
                "Invalid catalog format"
            )

        print(
            "Catalog entries:",
            len(items),
        )

        print("Loading history index")

        history_index = fetch(
            client,
            "full-history/all.json",
        )

        history_ids = history_index.get(
            "history", {}
        )

        if not isinstance(history_ids, dict):
            raise RuntimeError(
                "Invalid history index"
            )

        print(
            "History entries:",
            len(history_ids),
        )

        candidates = []
        seen_names = set()

        for item in items.values():
            if not isinstance(item, dict):
                continue

            name = item.get(
                "market_hash_name"
            )

            if not name:
                continue

            if name in seen_names:
                continue

            ask = number(
                item.get("price")
            )

            if not MIN_PRICE <= ask <= MAX_PRICE:
                continue

            history_id = history_ids.get(name)

            if history_id is None:
                continue

            seen_names.add(name)

            candidates.append({
                "name": name,
                "catalog_ask": ask,
                "history_id": history_id,
            })

        candidates.sort(
            key=lambda item: item["catalog_ask"]
        )

        candidates = candidates[:MAX_CANDIDATES]

        print(
            "Candidates for history check:",
            len(candidates),
        )

        for candidate in candidates:
            name = candidate["name"]

            try:
                time.sleep(REQUEST_DELAY)

                history_path = (
                    "full-history/"
                    f"{candidate['history_id']}.json"
                )

                history = fetch(
                    client,
                    history_path,
                )

                data = history.get(
                    "data", {}
                )

                if not isinstance(data, dict):
                    print(
                        "Invalid history data:",
                        name,
                    )
                    continue

                average_7d = rub(
                    data.get("average7d")
                )

                average_30d = rub(
                    data.get("average30d")
                )

                sales_7d = rub(
                    data.get("sales7d")
                )

                print(
                    "HISTORY DATA:",
                    name,
                    "Average 7d:",
                    round(average_7d, 2),
                    "Sales 7d:",
                    int(sales_7d),
                )

                if average_7d <= 0:
                    continue

                if sales_7d < MIN_SALES_7D:
                    continue

                if average_30d > 0:
                    sell_reference = min(
                        average_7d,
                        average_30d,
                    )
                else:
                    sell_reference = average_7d

                time.sleep(REQUEST_DELAY)

                live = fetch(
                    client,
                    "search-list-items-by-hash-name-all",
                    params={
                        "key": api_key,
                        "list_hash_name[]": name,
                    },
                )

                if live.get("currency") != "RUB":
                    print(
                        "Live currency mismatch:",
                        name,
                    )
                    continue

                live_data = live.get(
                    "data", {}
                )

                if not isinstance(live_data, dict):
                    continue

                lots = live_data.get(
                    name, []
                )

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

                    if (
                        item_id is None
                        or price_kopeks <= 0
                    ):
                        continue

                    valid_lots.append({
                        "item_id": str(item_id),
                        "price": price_kopeks / 100,
                    })

                if not valid_lots:
                    continue

                cheapest = min(
                    valid_lots,
                    key=lambda item: item["price"],
                )

                buy_price = cheapest["price"]

                if not MIN_PRICE <= buy_price <= MAX_PRICE:
                    continue

                profit = (
                    sell_reference * (1 - SELL_FEE)
                    - buy_price
                )

                profit_percent = (
                    profit / buy_price * 100
                )

                print(
                    "HISTORY CHECK:",
                    name,
                    "Buy:",
                    round(buy_price, 2),
                    "Sell reference:",
                    round(sell_reference, 2),
                    "Profit:",
                    round(profit, 2),
                )

                if profit < MIN_PROFIT:
                    continue

                if profit_percent < MIN_PROFIT_PERCENT:
                    continue

                opportunity = {
                    "name": name,
                    "buy_price": round(
                        buy_price, 2
                    ),
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
                    "volume": int(sales_7d),
                    "item_id": cheapest["item_id"],
                    "live_lots_count": len(valid_lots),
                    "price_source": "sales_history",
                }

                opportunities.append(
                    opportunity
                )

                print(
                    "HISTORY VERIFIED SIGNAL:",
                    name,
                    "Estimated profit:",
                    round(profit, 2),
                )

            except (
                httpx.HTTPError,
                ValueError,
                RuntimeError,
            ) as error:
                print_error(name, error)

    opportunities.sort(
        key=lambda item: item["reference_margin"],
        reverse=True,
    )

    print(
        "Подходящих сигналов:",
        len(opportunities),
    )

    print(
        "HISTORY VERIFIED SCAN COMPLETED"
    )

    return opportunities


if __name__ == "__main__":
    results = scan()

    print(
        "Scanner results:",
        len(results),
    )
