
"""Market.CSGO scanner v2 — READ ONLY.

Scans historical prices and current offers.
Never buys or sells items.
"""

import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
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
MAX_RETRIES = 3

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

    except (TypeError, ValueError, OverflowError):
        pass

    return None


def numeric_field(value, currency=None):
    if isinstance(value, dict):
        return positive(value.get("RUB"))

    return positive(value)


def rub_value(value, currency):
    if isinstance(value, dict):
        return positive(value.get("RUB"))

    if currency == "RUB":
        return positive(value)

    return None


def convert_price(value, unit):
    number = positive(value)

    if number is None:
        return None

    if unit == "kopecks":
        return number / 100.0

    if unit == "rubles":
        return number

    return None


def read_json(path, default):
    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return default


def save_json(path, data):
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    temporary.replace(path)


def fetch(client, endpoint, params=None):
    for attempt in range(MAX_RETRIES):
        try:
            response = client.get(
                BASE + endpoint,
                params=params
            )

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise ValueError(
                    "Invalid API response"
                )

            if data.get("success") is False:
                raise ValueError(
                    "API rejected request"
                )

            return data

        except (
            httpx.HTTPError,
            ValueError
        ):
            if attempt == MAX_RETRIES - 1:
                raise

            time.sleep(2 ** attempt)


def calculate_profit(buy, sell):
    net_sale = sell * (1.0 - SELL_FEE)
    profit = net_sale - buy
    roi = (profit / buy) * 100.0

    return profit, roi


def load_cursor(total):
    state = read_json(PROGRESS, {})

    if not isinstance(state, dict):
        return 0

    try:
        cursor = int(state.get("cursor", 0))
    except (
        TypeError,
        ValueError,
        OverflowError
    ):
        return 0

    return max(0, cursor) % total


def scan():
    # Hard safety stop.
    if os.getenv(
        "DRY_RUN", "true"
    ).strip().lower() != "true":
        raise RuntimeError(
            "DRY_RUN must remain true"
        )

    key = os.getenv(
        "MARKET_CSGO_API_KEY", ""
    ).strip()

    if not key:
        raise RuntimeError(
            "MARKET_CSGO_API_KEY missing"
        )

    if OFFER_UNIT not in (
        "kopecks", "rubles"
    ):
        raise RuntimeError(
            "Offer price unit not configured"
        )

    if HISTORY_UNIT not in (
        "kopecks", "rubles"
    ):
        raise RuntimeError(
            "History price unit not configured"
        )

    counts = Counter()
    candidates = []
    samples = []

    with httpx.Client(
        timeout=30,
        follow_redirects=False
    ) as client:

        catalog = fetch(
            client,
            "/full-history/all.json"
        ).get("history")

        if not isinstance(catalog, dict):
            raise ValueError(
                "History catalog unavailable"
            )

        names = sorted(
            name
            for name in catalog
            if isinstance(name, str)
            and name.strip()
        )

        if not names:
            raise ValueError("Empty catalog")

        total = len(names)
        cursor = load_cursor(total)

        batch_size = min(
            BATCH_SIZE,
            total
        )

        selected = [
            names[(cursor + index) % total]
            for index in range(batch_size)
        ]

        print(
            f"CATALOG: {total}",
            flush=True
        )
        print(
            f"CURSOR: {cursor}",
            flush=True
        )
        print(
            f"BATCH: {batch_size}",
            flush=True
        )

        for name in selected:
            counts["items_scanned"] += 1

            try:
                history_id = catalog[name]

                if history_id is None:
                    counts["missing_history_id"] += 1
                    continue

                history_response = fetch(
                    client,
                    f"/full-history/{history_id}.json"
                )

                hist = history_response.get(
                    "data", {}
                )

                if not isinstance(hist, dict):
                    counts["invalid_history"] += 1
                    continue

                currency = hist.get("currency")

                # sales7d is a count, not a price.
                sales = numeric_field(
                    hist.get("sales7d")
                )

                if sales is None:
                    counts["missing_sales"] += 1
                    continue

                if sales < MIN_SALES_7D:
                    counts["low_liquidity"] += 1
                    continue

                average_raw = rub_value(
                    hist.get("average7d"),
                    currency
                )

                if average_raw is None:
                    counts["missing_average"] += 1
                    continue

                sell = convert_price(
                    average_raw,
                    HISTORY_UNIT
                )

                if sell is None:
                    counts["invalid_sell_price"] += 1
                    continue

                # If selling at the historical average
                # cannot produce 50 RUB profit even with
                # the cheapest permitted purchase,
                # there is no reason to fetch offers.
                max_possible_profit = (
                    sell * (1.0 - SELL_FEE)
                    - MIN_PRICE
                )

                if max_possible_profit < MIN_PROFIT:
                    counts[
                        "history_profit_ceiling"
                    ] += 1
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
                    counts[
                        "invalid_offer_currency"
                    ] += 1
                    continue

                groups = payload.get("data", {})

                if not isinstance(groups, dict):
                    counts["invalid_offers"] += 1
                    continue

                offers = groups.get(name, [])

                if not isinstance(offers, list):
                    counts["invalid_offers"] += 1
                    continue

                counts["items_with_offers"] += 1

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

                    if (
                        item_id is None
                        or not str(item_id).strip()
                    ):
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
                        raw_price,
                        OFFER_UNIT
                    )

                    if buy is None:
                        counts["invalid_buy_price"] += 1
                        continue

                    if buy < MIN_PRICE:
                        counts["below_min_price"] += 1
                        continue

                    if buy > MAX_PRICE:
                        counts["above_max_price"] += 1
                        continue

                    counts["offers_in_budget"] += 1

                    profit, roi = calculate_profit(
                        buy, sell
                    )

                    if profit < MIN_PROFIT:
                        counts["low_profit"] += 1
                        continue

                    if roi < MIN_ROI:
                        counts["low_roi"] += 1
                        continue

                    candidates.append({
                        "name": name,
                        "item_id": str(item_id),
                        "buy_price_rub": round(
                            buy, 2
                        ),
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
                        "status": (
                            "ESTIMATE_REVIEW_REQUIRED"
                        )
                    })

                    counts[
                        "estimated_candidates"
                    ] += 1

            except (
                httpx.HTTPError,
                ValueError,
                TypeError,
                KeyError
            ) as exc:

                counts["item_failures"] += 1

                print(
                    f"ERROR: {name}: "
                    f"{type(exc).__name__}",
                    flush=True
                )

            finally:
                time.sleep(REQUEST_DELAY)

    next_cursor = (
        cursor + batch_size
    ) % total

    candidates.sort(
        key=lambda item: (
            item["estimated_profit_rub"],
            item["estimated_roi_percent"]
        ),
        reverse=True
    )

    save_json(
        PROGRESS,
        {
            "cursor": next_cursor,
            "catalog_size": total
        }
    )

    save_json(
        RESULTS,
        candidates
    )

    report = {
        "mode": "READ_ONLY",
        "timestamp_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "catalog_size": total,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "batch_size": batch_size,
        "counts": dict(counts),
        "estimated_candidates": len(
            candidates
        ),
        "verified_profitable_candidates": 0,
        "real_purchases": 0,
        "offer_price_unit": OFFER_UNIT,
        "history_price_unit": HISTORY_UNIT,
        "assumed_sell_fee_percent": (
            SELL_FEE * 100
        ),
        "price_samples": samples,
        "note": (
            "Historical average is not a "
            "guaranteed selling price. "
            "API price units, sales fields "
            "and actual fees require verification. "
            "No purchases performed."
        )
    }

    save_json(
        DIAGNOSTICS,
        report
    )

    print(
        "\nSCAN SUMMARY",
        flush=True
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        flush=True
    )

    print(
        f"\nCANDIDATES: {len(candidates)}",
        flush=True
    )

    print(
        "REAL PURCHASES: 0",
        flush=True
    )

    return candidates[:30]


if __name__ == "__main__":
    scan()
