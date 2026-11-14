
"""Market.CSGO scanner: read-only, estimated profit, no buying."""
import json
import math
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BASE = "https://market.csgo.com/api/v2"

BATCH_SIZE = 20
MIN_PRICE = 50.0
MAX_PRICE = 500.0
MIN_SALES_7D = 20
MIN_PROFIT = 50.0
MIN_ROI = 10.0

# Planning assumptions, NOT verified marketplace fees.
SELL_FEE = 0.10
PRICE_SAFETY_DISCOUNT = 0.15
REQUEST_DELAY = 0.5


def positive(value):
    try:
        result = float(value)
        if math.isfinite(result) and result > 0:
            return result
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def fetch(client, endpoint, params=None):
    for attempt in range(3):
        try:
            response = client.get(BASE + endpoint, params=params)
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Invalid API response")

            if data.get("success") is False:
                raise ValueError("API rejected request")

            return data

        except (httpx.HTTPError, ValueError) as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def scan():
    key = os.getenv("MARKET_CSGO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("MARKET_CSGO_API_KEY missing")

    progress = ROOT / "scan_progress.json"
    state = read(progress, {})
    if not isinstance(state, dict):
        state = {}

    results = []
    checked_offers = 0
    failures = 0
    skipped_currency = 0
    eligible_items = 0

    with httpx.Client(timeout=30) as client:
        catalog = fetch(
            client, "/full-history/all.json"
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
            cursor = max(
                0, int(state.get("cursor", 0))
            ) % len(names)
        except (TypeError, ValueError, OverflowError):
            cursor = 0

        selected = [
            names[(cursor + i) % len(names)]
            for i in range(min(BATCH_SIZE, len(names)))
        ]

        print(
            "Catalog:", len(names),
            "Cursor:", cursor,
            "Batch:", len(selected),
            flush=True,
        )

        for name in selected:
            try:
                history = fetch(
                    client,
                    "/full-history/" +
                    str(catalog[name]) + ".json"
                ).get("data", {})

                if not isinstance(history, dict):
                    continue

                avg_data = history.get("average7d")
                sales_data = history.get("sales7d")

                if not isinstance(avg_data, dict):
                    continue

                if not isinstance(sales_data, dict):
                    continue

                average = positive(avg_data.get("RUB"))
                sales = positive(sales_data.get("RUB"))

                if average is None or sales is None:
                    continue

                if sales < MIN_SALES_7D:
                    continue

                eligible_items += 1

                payload = fetch(
                    client,
                    "/search-list-items-by-hash-name-all",
                    {
                        "key": key,
                        "list_hash_name[]": name,
                    },
                )

                if payload.get("currency") != "RUB":
                    skipped_currency += 1
                    continue

                groups = payload.get("data", {})
                if not isinstance(groups, dict):
                    continue

                offers = groups.get(name, [])
                if not isinstance(offers, list):
                    continue

                # Discounted historical estimate.
                estimated_sell = (
                    average * (1 - PRICE_SAFETY_DISCOUNT)
                )
                estimated_net = (
                    estimated_sell * (1 - SELL_FEE)
                )

                for offer in offers:
                    if not isinstance(offer, dict):
                        continue

                    checked_offers += 1

                    raw_price = positive(offer.get("price"))
                    item_id = offer.get("id")

                    if raw_price is None or item_id is None:
                        continue

                    # Listing prices are in minor currency units.
                    buy_price = raw_price / 100.0

                    if not MIN_PRICE <= buy_price <= MAX_PRICE:
                        continue

                    profit = estimated_net - buy_price
                    roi = profit / buy_price * 100

                    if profit < MIN_PROFIT:
                        continue

                    if roi < MIN_ROI:
                        continue

                    results.append({
                        "name": name,
                        "item_id": str(item_id),
                        "buy_price_rub": round(buy_price, 2),
                        "historical_average_rub": round(
                            average, 2
                        ),
                        "estimated_sell_rub": round(
                            estimated_sell, 2
                        ),
                        "estimated_profit_rub": round(
                            profit, 2
                        ),
                        "estimated_roi_percent": round(
                            roi, 2
                        ),
                        "sales7d": int(sales),
                        "fee_assumption": SELL_FEE,
                        "status": "manual_review_required",
                        "profit_verified": False,
                    })

            except httpx.HTTPStatusError as exc:
                failures += 1
                print(
                    "HTTP error:",
                    exc.response.status_code,
                    name,
                    flush=True,
                )

            except (
                httpx.HTTPError,
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                failures += 1
                print(
                    "Item error:",
                    name,
                    type(exc).__name__,
                    flush=True,
                )

            time.sleep(REQUEST_DELAY)

    results.sort(
        key=lambda item: item["estimated_profit_rub"],
        reverse=True,
    )

    write(progress, {
        "cursor": (cursor + len(selected)) % len(names),
        "catalog_size": len(names),
    })

    print("Eligible items:", eligible_items, flush=True)
    print("Offers checked:", checked_offers, flush=True)
    print("Failures:", failures, flush=True)
    print("Unverified currency:", skipped_currency, flush=True)
    print("Estimated opportunities:", len(results), flush=True)
    print("Real purchases: 0", flush=True)

    return results[:30]
