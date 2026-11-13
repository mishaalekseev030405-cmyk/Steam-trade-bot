
import os
import json
import time
import math
import httpx

BASE_URL = "https://market.csgo.com/api/v2"
PROGRESS_FILE = "scan_progress.json"

MIN_PRICE = 50.0
MAX_PRICE = 500.0
MIN_PROFIT = 50.0
MIN_PROFIT_PERCENT = 10.0
MIN_SALES_7D = 20

SELL_FEE = 0.10

BATCH_SIZE = 20
MAX_LIVE_CHECKS = 5
REQUEST_DELAY = 2.0


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


def load_cursor():
    try:
        with open(PROGRESS_FILE, "r") as file:
            data = json.load(file)
        return max(0, int(data.get("cursor", 0)))
    except (OSError, ValueError, TypeError):
        return 0


def save_cursor(cursor):
    temporary = PROGRESS_FILE + ".tmp"

    with open(temporary, "w") as file:
        json.dump({"cursor": cursor}, file)

    os.replace(temporary, PROGRESS_FILE)


def fetch(client, path, params=None):
    response = client.get(
        f"{BASE_URL}/{path}",
        params=params,
    )
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Invalid API response")

    if data.get("success") is False:
        raise RuntimeError("Market API rejected request")

    return data


def error_status(name, error):
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        print("HTTP ERROR:", name, "Status:", status)
        return status

    print("API ERROR:", name, type(error).__name__)
    return None


def scan():
    print("BATCH MARKET SCANNER STARTED")

    api_key = os.getenv("MARKET_CSGO_API_KEY", "").strip()

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

        index = fetch(
            client,
            "full-history/all.json",
        )

        history_ids = index.get("history", {})

        if not isinstance(items, dict):
            raise RuntimeError("Invalid catalog")

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

            if not MIN_PRICE <= price <= MAX_PRICE:
                continue

            history_id = history_ids.get(name)

            if history_id is None:
                continue

            seen.add(name)

            candidates.append({
                "name": name,
                "price": price,
                "history_id": history_id,
            })

        candidates.sort(key=lambda x: x["name"])

        total = len(candidates)
        print("Total candidates:", total)

        if total == 0:
            print("No candidates")
            return []

        cursor = load_cursor() % total

        batch = [
            candidates[(cursor + i) % total]
            for i in range(min(BATCH_SIZE, total))
        ]

        print("Starting cursor:", cursor)
        print("Batch size:", len(batch))

        profitable = []
        processed = 0
        rate_limited = False

        for candidate in batch:
            name = candidate["name"]

            try:
                time.sleep(REQUEST_DELAY)

                history = fetch(
                    client,
                    f"full-history/{candidate['history_id']}.json",
                )

                data = history.get("data", {})

                if not isinstance(data, dict):
                    processed += 1
                    continue

                average_7d = rub(data.get("average7d"))
                average_30d = rub(data.get("average30d"))
                sales_7d = rub(data.get("sales7d"))

                if average_7d <= 0 or sales_7d < MIN_SALES_7D:
                    processed += 1
                    continue

                sell_reference = (
                    min(average_7d, average_30d)
                    if average_30d > 0
                    else average_7d
                )

                preliminary_profit = (
                    sell_reference * (1 - SELL_FEE)
                    - candidate["price"]
                )

                preliminary_percent = (
                    preliminary_profit / candidate["price"] * 100
                )

                print(
                    "HISTORY:",
                    name,
                    "Profit:",
                    round(preliminary_profit, 2),
                )

                if (
                    preliminary_profit >= MIN_PROFIT
                    and preliminary_percent >= MIN_PROFIT_PERCENT
                ):
                    profitable.append({
                        **candidate,
                        "sell_reference": sell_reference,
                        "sales_7d": sales_7d,
                        "preliminary_profit": preliminary_profit,
                    })

                processed += 1

            except (httpx.HTTPError, ValueError, RuntimeError) as error:
                status = error_status(name, error)

                if status == 429:
                    rate_limited = True
                    break

                processed += 1

        new_cursor = (cursor + processed) % total
        save_cursor(new_cursor)

        print("Processed:", processed)
        print("Next cursor:", new_cursor)

        if rate_limited:
            print("RATE LIMIT: live checks skipped")
            print("BATCH MARKET SCAN COMPLETED")
            return []

        profitable.sort(
            key=lambda x: x["preliminary_profit"],
            reverse=True,
        )

        for candidate in profitable[:MAX_LIVE_CHECKS]:
            name = candidate["name"]

            try:
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
                    kopeks = number(lot.get("price"))

                    if not item_id or kopeks <= 0:
                        continue

                    valid_lots.append({
                        "item_id": str(item_id),
                        "price": kopeks / 100,
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

                sell_reference = candidate["sell_reference"]

                profit = (
                    sell_reference * (1 - SELL_FEE)
                    - buy_price
                )

                profit_percent = profit / buy_price * 100

                if (
                    profit < MIN_PROFIT
                    or profit_percent < MIN_PROFIT_PERCENT
                ):
                    continue

                opportunities.append({
                    "name": name,
                    "buy_price": round(buy_price, 2),
                    "sell_reference": round(sell_reference, 2),
                    "buy_order": round(sell_reference, 2),
                    "spread": round(
                        sell_reference - buy_price, 2
                    ),
                    "reference_margin": round(profit, 2),
                    "profit_percent": round(profit_percent, 2),
                    "volume": int(candidate["sales_7d"]),
                    "item_id": cheapest["item_id"],
                    "live_lots_count": len(valid_lots),
                    "price_source": "sales_history",
                })

                print(
                    "SIGNAL:",
                    name,
                    "Estimated profit:",
                    round(profit, 2),
                )

            except (httpx.HTTPError, ValueError, RuntimeError) as error:
                status = error_status(name, error)

                if status == 429:
                    print("RATE LIMIT: stopping live checks")
                    break

    opportunities.sort(
        key=lambda x: x["reference_margin"],
        reverse=True,
    )

    print("Подходящих сигналов:", len(opportunities))
    print("BATCH MARKET SCAN COMPLETED")

    return opportunities


if __name__ == "__main__":
    results = scan()
    print("Scanner results:", len(results))
