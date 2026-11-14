
"""Market.CSGO scanner — read-only, safe price diagnostics."""

import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BASE = "https://market.csgo.com/api/v2"

BATCH_SIZE = 100
MIN_PRICE = 50.0
MAX_PRICE = 500.0
MIN_SALES_7D = 20

MIN_PROFIT = 50.0
MIN_ROI = 10.0
SELL_FEE = 0.10

REQUEST_DELAY = 0.3

PROGRESS = ROOT / "scan_progress.json"
DIAGNOSTICS = ROOT / "scan_diagnostics.json"
RESULTS = ROOT / "profitable_candidates.json"

OFFER_UNIT = os.getenv(
    "MARKET_OFFER_PRICE_UNIT", "unknown"
).strip().lower()

HISTORY_UNIT = os.getenv(
    "MARKET_HISTORY_PRICE_UNIT", "unknown"
).strip().lower()


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


def rub_value(value, currency):
    if isinstance(value, dict):
        return positive(value.get("RUB"))

    if currency == "RUB":
        return positive(value)

    return None


def convert_price(value, unit):
    value = positive(value)

    if value is None:
        return None

    if unit == "kopecks":
        return value / 100

    if unit == "rubles":
        return value

    return None


def read_json(path, default):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return default


def save_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")

    temp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ) + "\n",
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


def calculate_profit(buy, sell):
    net_sale = sell * (1 - SELL_FEE)
    profit = net_sale - buy
    roi = profit / buy * 100
    return profit, roi


def scan():
    key = os.getenv("MARKET_CSGO_API_KEY", "").strip()

    if not key:
        raise RuntimeError("MARKET_CSGO_API_KEY missing")

    state = read_json(PROGRESS, {})

    if not isinstance(state, dict):
        state = {}

    counts = Counter()
    results = []
    samples = []

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
            cursor = int(state.get("cursor", 0))
        except (ValueError, TypeError, OverflowError):
            cursor = 0

        cursor = max(0, cursor) % len(names)

        selected = [
            names[(cursor + i) % len(names)]
            for i in range(min(BATCH_SIZE, len(names)))
        ]

        print(
            f"Catalog: {len(names)} | "
            f"Cursor: {cursor} | "
            f"Batch: {len(selected)}",
            flush=True
        )

        for name in selected:
            counts["items_scanned"] += 1

            try:
                history_id = catalog[name]

                hist = fetch(
                    client,
                    f"/full-history/{history_id}.json"
                ).get("data", {})

                if not isinstance(hist, dict):
                    counts["invalid_history"] += 1
                    continue

                sales = rub_value(
                    hist.get("sales7d"),
                    hist.get("currency")
                )

                if sales is None:
                    counts["missing_sales"] += 1
                    continue

                if sales < MIN_SALES_7D:
                    counts["low_liquidity"] += 1
                    continue

                average_raw = rub_value(
                    hist.get("average7d"),
                    hist.get("currency")
                )

                if average_raw is None:
                    counts["missing_average"] += 1
                    continue

                payload = fetch(
                    client,
                    "/search-list-items-by-hash-name-all",
                    {
                        "key": key,
                        "list_hash_name[]": name
                    }
                )

                if payload.get("currency") != "RUB":
                    counts["invalid_offer_currency"] += 1
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
                        counts["invalid_offer"] += 1
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
                        counts["missing_id"] += 1
                        continue

                    if len(samples) < 5:
                        samples.append({
                            "name": name,
                            "average7d_raw": average_raw,
                            "offer_price_raw": raw_price,
                            "offer_price_div_100": (
                                raw_price / 100
                            )
                        })

                    buy = convert_price(
                        raw_price, OFFER_UNIT
                    )

                    sell = convert_price(
                        average_raw, HISTORY_UNIT
                    )

                    if buy is None or sell is None:
                        counts["price_units_unverified"] += 1
                        continue

                    if not MIN_PRICE <= buy <= MAX_PRICE:
                        counts["outside_price_range"] += 1
                        continue

                    profit, roi = calculate_profit(
                        buy, sell
                    )

                    if profit < MIN_PROFIT:
                        counts["low_profit"] += 1
                        continue

                    if roi < MIN_ROI:
                        counts["low_roi"] += 1
                        continue

                    results.append({
                        "name": name,
                        "item_id": str(item_id),
                        "buy_price_rub": round(buy, 2),
                        "historical_sell_price_rub": round(
                            sell, 2
                        ),
                        "estimated_profit_rub": round(
                            profit, 2
                        ),
                        "estimated_roi_percent": round(
                            roi, 2
                        ),
                        "sales7d_reported": sales,
                        "profit_verified": False,
                        "status": "ESTIMATE_REVIEW_REQUIRED"
                    })

                    counts["estimated_candidates"] += 1

            except (
                httpx.HTTPError,
                ValueError,
                TypeError,
                KeyError
            ) as exc:
                counts["item_failures"] += 1

                print(
                    f"ERROR: {name}: {type(exc).__name__}",
                    flush=True
                )

            time.sleep(REQUEST_DELAY)

    next_cursor = (
        cursor + len(selected)
    ) % len(names)

    results.sort(
        key=lambda item: item["estimated_profit_rub"],
        reverse=True
    )

    save_json(
        PROGRESS,
        {
            "cursor": next_cursor,
            "catalog_size": len(names)
        }
    )

    save_json(RESULTS, results)

    report = {
        "mode": "READ_ONLY",
        "catalog_size": len(names),
        "cursor": cursor,
        "next_cursor": next_cursor,
        "batch_size": len(selected),
        "counts": dict(counts),
        "estimated_candidates": len(results),
        "verified_profitable_candidates": 0,
        "real_purchases": 0,
        "offer_price_unit": OFFER_UNIT,
        "history_price_unit": HISTORY_UNIT,
        "price_samples": samples,
        "note": (
            "Price units and fees must be verified. "
            "Historical average is not a guaranteed "
            "selling price. No purchases performed."
        )
    }

    save_json(DIAGNOSTICS, report)

    print("\nPRICE DIAGNOSTICS", flush=True)
    print(
        json.dumps(
            samples,
            ensure_ascii=False,
            indent=2
        ),
        flush=True
    )

    print("\nSCAN COMPLETE", flush=True)
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        flush=True
    )

    return results[:30]


if __name__ == "__main__":
    scan()
