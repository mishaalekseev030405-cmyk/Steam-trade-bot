
"""Read-only Market.CSGO scanner with diagnostics."""

import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BASE = "https://market.csgo.com/api/v2"

BATCH_SIZE = 20
MIN_PRICE = 50
MAX_PRICE = 500
MIN_SALES_7D = 20

PROGRESS = ROOT / "scan_progress.json"
DIAGNOSTICS = ROOT / "scan_diagnostics.json"


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        if math.isfinite(result) and result > 0:
            return result
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    temp.replace(path)


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
                raise ValueError("API rejected request")

            return data

        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def history_sales(value):
    return positive(value)


def history_average(value, currency):
    # Historical prices are informational only.
    # Currency and amount units must be verified.
    if isinstance(value, dict):
        return positive(value.get("RUB"))

    if currency == "RUB":
        return positive(value)

    return None


def scan():
    key = os.getenv("MARKET_CSGO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("MARKET_CSGO_API_KEY missing")

    state = read_json(PROGRESS, {})
    if not isinstance(state, dict):
        state = {}

    counts = Counter()
    results = []

    with httpx.Client(timeout=30) as client:
        catalog = fetch(
            client,
            "/full-history/all.json"
        ).get("history")

        if not isinstance(catalog, dict):
            raise ValueError("History catalog unavailable")

        names = sorted(
            name for name in catalog
            if isinstance(name, str) and name.strip()
        )

        if not names:
            raise ValueError("Empty catalog")

        try:
            cursor = int(state.get("cursor", 0))
        except (ValueError, TypeError, OverflowError):
            cursor = 0

        cursor = max(0, cursor) % len(names)

        selected = [
            names[(cursor + i) % len(names)]
            for i in range(min(BATCH_SIZE, len(names)))
        ]

        print(
            "Catalog:", len(names),
            "Cursor:", cursor,
            "Batch:", len(selected),
            flush=True
        )

        for name in selected:
            counts["items_scanned"] += 1

            try:
                hist = fetch(
                    client,
                    "/full-history/" +
                    str(catalog[name]) + ".json"
                ).get("data", {})

                if not isinstance(hist, dict):
                    counts["invalid_history"] += 1
                    continue

                sales = history_sales(
                    hist.get("sales7d")
                )

                if sales is None:
                    counts["missing_sales"] += 1
                    continue

                if sales < MIN_SALES_7D:
                    counts["low_liquidity"] += 1
                    continue

                counts["eligible_items"] += 1

                average = history_average(
                    hist.get("average7d"),
                    hist.get("currency")
                )

                if average is None:
                    counts["unverified_history_price"] += 1

                payload = fetch(
                    client,
                    "/search-list-items-by-hash-name-all",
                    {
                        "key": key,
                        "list_hash_name[]": name
                    }
                )

                if payload.get("currency") != "RUB":
                    counts["unverified_offer_currency"] += 1
                    continue

                groups = payload.get("data", {})
                offers = (
                    groups.get(name, [])
                    if isinstance(groups, dict)
                    else []
                )

                if not isinstance(offers, list):
                    counts["invalid_offers"] += 1
                    continue

                for offer in offers:
                    if not isinstance(offer, dict):
                        counts["invalid_offers"] += 1
                        continue

                    counts["offers_checked"] += 1

                    raw_price = positive(
                        offer.get("price")
                    )

                    item_id = offer.get("id")

                    if raw_price is None:
                        counts["invalid_price"] += 1
                        continue

                    if item_id is None or not str(item_id).strip():
                        counts["missing_item_id"] += 1
                        continue

                    # Assumption inherited from the current scanner:
                    # offer.price is expressed in kopecks.
                    # Verify against API documentation before live trading.
                    price = raw_price / 100

                    if price < MIN_PRICE:
                        counts["below_min_price"] += 1
                        continue

                    if price > MAX_PRICE:
                        counts["above_max_price"] += 1
                        continue

                    counts["price_eligible_offers"] += 1

                    # Do not invent an executable resale price.
                    # Historical average alone is insufficient.
                    counts["profit_not_verified"] += 1

                    results.append({
                        "name": name,
                        "item_id": str(item_id),
                        "buy_price_rub": round(price, 2),
                        "sales7d_reported": sales,
                        "historical_average_rub_raw": average,
                        "profit_verified": False,
                        "status": "manual_review_required"
                    })

            except (
                httpx.HTTPError,
                ValueError,
                TypeError,
                KeyError
            ) as exc:
                counts["item_failures"] += 1
                print(
                    "Item error:",
                    name,
                    type(exc).__name__,
                    flush=True
                )

            time.sleep(0.25)

    next_cursor = (
        cursor + len(selected)
    ) % len(names)

    save_json(PROGRESS, {
        "cursor": next_cursor,
        "catalog_size": len(names)
    })

    report = {
        "mode": "READ_ONLY",
        "catalog_size": len(names),
        "cursor": cursor,
        "next_cursor": next_cursor,
        "batch_size": len(selected),
        "counts": dict(counts),
        "manual_review_candidates": len(results),
        "verified_profitable_candidates": 0,
        "real_purchases": 0,
        "note": (
            "Prices and profitability require independent "
            "verification before live trading."
        )
    }

    save_json(DIAGNOSTICS, report)

    print("DIAGNOSTICS", flush=True)

    for key, value in sorted(counts.items()):
        print(f"{key}: {value}", flush=True)

    print(
        "Manual review candidates:",
        len(results),
        flush=True
    )
    print("Verified profitable candidates: 0", flush=True)
    print("Real purchases: 0", flush=True)

    return results[:30]
