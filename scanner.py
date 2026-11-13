
import os
import time
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
MAX_HISTORY_AGE_HOURS = 6

REQUEST_DELAY = 0.35


def number(value, default=0.0):
    try:
        result = float(value)
        if not (result >= 0 and result < float("inf")):
            return default
        return result
    except (TypeError, ValueError):
        return default


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
        raise RuntimeError("Market API error")

    return result


def rub(value):
    if isinstance(value, dict):
        return number(value.get("RUB"))
    return 0.0


def scan():
    print("HISTORY VERIFIED SCANNER STARTED")

    api_key = os.getenv(
        "MARKET_CSGO_API_KEY", ""
    ).strip()

    if not api_key:
        raise RuntimeError("Market API key missing")

    opportunities = []

    with httpx.Client(
        timeout=40,
        follow_redirects=True,
    ) as client:

        catalog = fetch(
            client,
            "prices/class_instance/RUB.json",
        )

        if catalog.get("currency") != "RUB":
            raise RuntimeError("Catalog currency mismatch")

        items = catalog.get("items", {})

        if not isinstance(items, dict):
            raise RuntimeError("Invalid catalog")

        history_index = fetch(
            client,
            "full-history/all.json",
        )

        history_ids = history_index.get("history", {})

        if not isinstance(history_ids, dict):
            raise RuntimeError("Invalid history index")

        candidates = []

        for item in items.values():
            if not isinstance(item, dict):
                continue

            name = item.get("market_hash_name")

            if not name:
                continue

            ask = number(item.get("price"))

            if not MIN_PRICE <= ask <= MAX_PRICE:
                continue

            history_id = history_ids.get(name)

            if history_id is None:
                continue

            candidates.append({
                "name": name,
                "catalog_ask": ask,
                "history_id": history_id,
            })

        candidates.sort(
            key=lambda x: x["catalog_ask"]
        )

        # Limit requests for each scan.
        candidates = candidates[:MAX_CANDIDATES]

        print(
            "Candidates for history check:",
            len(candidates),
        )

        for candidate in candidates:
            name = candidate["name"]

            try:
                time.sleep(REQUEST_DELAY)

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

                updated_at = number(
                    history.get("time")
                )

                age_hours = (
                    datetime.now(timezone.utc).timestamp()
                    - updated_at
                ) / 3600

                if (
                    updated_at <= 0
                    or age_hours < 0
                    or age_hours > MAX_HISTORY_AGE_HOURS
                ):
                    print("STALE HISTORY:", name)
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

                if average_7d <= 0:
                    continue

                if sales_7d < MIN_SALES_7D:
                    continue

                # Conservative historical reference.
                if average_30d > 0:
                    sell_reference = min(
                        average_7d,
                        average_30d,
                    )
                else:
                    sell_reference = average_7d

                # A cheap catalog listing is not
                # sufficient. Verify a real lot.
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
                    print("Live currency mismatch:", name)
                    continue

                live_data = live.get("data", {})

                if not isinstance(live_data, dict):
                    continue

                lots = live_data.get(name, [])

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
                    "Average 7d:",
                    round(average_7d, 2),
                    "Profit:",
                    round(profit, 2),
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
                    "volume": int(sales_7d),
                    "item_id": cheapest["item_id"],
                    "live_lots_count": len(valid_lots),
                    "price_source": "sales_history",
                })

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
                print(
                    "Check failed:",
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

    print("HISTORY VERIFIED SCAN COMPLETED")

    return opportunities


if __name__ == "__main__":
    results = scan()
    print("Scanner results:", len(results))
