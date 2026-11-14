
import json
import math
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BASE = "https://market.csgo.com/api/v2"

MIN_PRICE = 50.0
MAX_PRICE = 500.0
MIN_PROFIT = 50.0
MIN_ROI = 0.10
MIN_SALES = 20
SELL_FEE = 0.10
SAFETY_DISCOUNT = 0.15
BATCH_SIZE = 10


def number(value):
    if isinstance(value, dict):
        value = value.get("RUB")
    try:
        result = float(value)
        if math.isfinite(result) and result > 0:
            return result
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def fetch(client, endpoint, params=None):
    for attempt in range(3):
        try:
            response = client.get(
                BASE + endpoint,
                params=params
            )
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Invalid API response")

            if data.get("success") is False:
                raise ValueError(
                    "API rejected request: "
                    + str(data.get("error", "unknown"))
                )

            return data

        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def load_json(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    temporary.replace(path)


def scan():
    api_key = os.getenv("MARKET_CSGO_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("MARKET_CSGO_API_KEY missing")

    names = load_json(ROOT / "watchlist.json", [])

    if not isinstance(names, list):
        raise ValueError("watchlist.json must be a list")

    if not all(
        isinstance(name, str) and name.strip()
        for name in names
    ):
        raise ValueError("Invalid item names")

    names = list(dict.fromkeys(names))

    if not names:
        print("Watchlist is empty")
        return []

    progress_path = ROOT / "scan_progress.json"
    state = load_json(progress_path, {})

    cursor = int(state.get("cursor", 0)) % len(names)
    count = min(BATCH_SIZE, len(names))

    selected = [
        names[(cursor + i) % len(names)]
        for i in range(count)
    ]

    print("Total watchlist items:", len(names))
    print("Selected items:", len(selected))
    print("Starting cursor:", cursor)

    results = []
    checked = 0
    offers_checked = 0
    errors = 0

    with httpx.Client(timeout=25) as client:
        index_data = fetch(
            client,
            "/full-history/all.json"
        )

        index = index_data.get("history", {})

        if not isinstance(index, dict):
            raise ValueError("Invalid history index")

        for name in selected:
            checked += 1
            print("CHECKING:", name, flush=True)

            try:
                history_id = index.get(name)

                if history_id is None:
                    print("No history ID")
                    continue

                history_data = fetch(
                    client,
                    "/full-history/" + str(history_id) + ".json"
                )

                history = history_data.get("data", {})

                if not isinstance(history, dict):
                    print("Invalid history data")
                    continue

                sales = number(history.get("sales7d"))
                average = number(history.get("average7d"))

                if sales is None or average is None:
                    print("Missing sales or average")
                    continue

                if sales < MIN_SALES:
                    print("Insufficient sales:", sales)
                    continue

                payload = fetch(
                    client,
                    "/search-list-items-by-hash-name-all",
                    {
                        "key": api_key,
                        "list_hash_name[]": name
                    }
                )

                if payload.get("currency") != "RUB":
                    print("Currency not RUB")
                    continue

                groups = payload.get("data", {})

                if not isinstance(groups, dict):
                    continue

                offers = groups.get(name, [])

                if not isinstance(offers, list):
                    continue

                for offer in offers:
                    if not isinstance(offer, dict):
                        continue

                    offers_checked += 1

                    raw_price = number(offer.get("price"))
                    item_id = offer.get("id")

                    if raw_price is None or item_id is None:
                        continue

                    price = raw_price / 100.0

                    if not MIN_PRICE <= price <= MAX_PRICE:
                        continue

                    reference = average * (1 - SAFETY_DISCOUNT)
                    net_sale = reference * (1 - SELL_FEE)
                    profit = net_sale - price
                    roi = profit / price

                    if profit < MIN_PROFIT or roi < MIN_ROI:
                        continue

                    results.append({
                        "name": name,
                        "item_id": str(item_id),
                        "buy_price": round(price, 2),
                        "sell_reference": round(reference, 2),
                        "estimated_profit": round(profit, 2),
                        "roi_percent": round(roi * 100, 2),
                        "sales7d": int(sales),
                        "reference_type": "discounted_7d_average"
                    })

            except (
                httpx.HTTPError,
                ValueError,
                TypeError,
                KeyError
            ) as error:
                errors += 1
                print(
                    "ITEM ERROR:",
                    name,
                    type(error).__name__,
                    str(error)[:150],
                    flush=True
                )

            finally:
                time.sleep(0.3)

    next_cursor = (cursor + count) % len(names)

    save_json(
        progress_path,
        {"cursor": next_cursor}
    )

    results.sort(
        key=lambda item: item["estimated_profit"],
        reverse=True
    )

    print("SCAN COMPLETED")
    print("Items checked:", checked)
    print("Offers checked:", offers_checked)
    print("Errors:", errors)
    print("Candidates found:", len(results))
    print("Next cursor:", next_cursor)

    return results[:30]
