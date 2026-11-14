"""Read-only Market.CSGO scanner. Prices require explicit RUB verification."""
import json
import math
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BASE = "https://market.csgo.com/api/v2"
BATCH_SIZE = 20


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fetch(client, endpoint, params=None):
    for attempt in range(3):
        try:
            response = client.get(BASE + endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("success") is False:
                raise ValueError("Unexpected API response")
            return data
        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def rub_history_value(value):
    """Return explicit RUB value only; do not guess currency or minor units."""
    if not isinstance(value, dict):
        return None
    return positive(value.get("RUB"))


def scan():
    key = os.environ.get("MARKET_CSGO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("MARKET_CSGO_API_KEY missing")

    progress = ROOT / "scan_progress.json"
    state = read(progress, {})
    if not isinstance(state, dict):
        state = {}

    with httpx.Client(timeout=30) as client:
        index = fetch(client, "/full-history/all.json").get("history")
        if not isinstance(index, dict):
            raise ValueError("History catalog unavailable")
        names = sorted(k for k in index if isinstance(k, str) and k.strip())
        if not names:
            raise ValueError("Empty catalog")
        try:
            cursor = max(0, int(state.get("cursor", 0))) % len(names)
        except (TypeError, ValueError, OverflowError):
            cursor = 0
        selected = [names[(cursor + i) % len(names)] for i in range(min(BATCH_SIZE, len(names)))]
        print("Catalog:", len(names), "Cursor:", cursor, "Batch:", len(selected), flush=True)

        results = []
        checked_offers = 0
        failures = 0
        skipped_currency = 0
        for name in selected:
            try:
                hist = fetch(client, "/full-history/" + str(index[name]) + ".json").get("data", {})
                if not isinstance(hist, dict):
                    hist = {}
                sales = positive(hist.get("sales7d"))
                if sales is None:
                    sales = rub_history_value(hist.get("sales7d"))
                average_rub_raw = rub_history_value(hist.get("average7d"))
                if average_rub_raw is None and hist.get("currency") == "RUB":
                    average_rub_raw = positive(hist.get("average7d"))

                # Historical data is informational only: its price units are not yet verified.
                payload = fetch(client, "/search-list-items-by-hash-name-all", {
                    "key": key,
                    "list_hash_name[]": name,
                })
                if payload.get("currency") != "RUB":
                    skipped_currency += 1
                    print("SKIP offer currency not confirmed RUB:", name, flush=True)
                    continue
                groups = payload.get("data", {})
                offers = groups.get(name, []) if isinstance(groups, dict) else []
                if not isinstance(offers, list):
                    continue
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    checked_offers += 1
                    raw = positive(offer.get("price"))
                    item_id = offer.get("id")
                    if raw is None or item_id is None or not str(item_id).strip():
                        continue
                    # Market.CSGO listing price is assumed to be RUB kopecks;
                    # verify this against current official API documentation before trading.
                    buy = raw / 100
                    if not 50 <= buy <= 500:
                        continue
                    results.append({
                        "name": name,
                        "item_id": str(item_id),
                        "buy_price_rub": round(buy, 2),
                        "historical_average_rub_raw": average_rub_raw,
                        "sales7d_reported": sales,
                        "status": "manual_review_required",
                        "profit_verified": False,
                    })
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                failures += 1
                print("Item error:", name, type(exc).__name__, flush=True)
            time.sleep(0.25)

    write(progress, {"cursor": (cursor + len(selected)) % len(names), "catalog_size": len(names)})
    print("Offers checked:", checked_offers, "Failures:", failures,
          "Unverified offer currency:", skipped_currency,
          "Review candidates:", len(results), flush=True)
    return results[:30]
