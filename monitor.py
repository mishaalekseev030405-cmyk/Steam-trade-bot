
"""CS2 Market Monitor — read-only scanner with Telegram alerts."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from scanner import scan

ROOT = Path(__file__).resolve().parent

RESULTS_FILE = ROOT / "latest_results.json"
HISTORY_FILE = ROOT / "candidate_history.json"

MAX_HISTORY = 1000
MAX_ALERT_ITEMS = 5


def load_json(path, default):
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


def send_telegram(client, token, chat_id, message):
    response = client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message
        }
    )

    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict) or not data.get("ok"):
        raise ValueError("Telegram rejected message")


def format_candidate(item, index):
    return (
        f"{index}. {item['name']}\n"
        f"Покупка: {item['buy_price_rub']:.2f} ₽\n"
        f"Историческая цена: "
        f"{item['historical_sell_price_rub']:.2f} ₽\n"
        f"Оценочная прибыль: "
        f"{item['estimated_profit_rub']:.2f} ₽\n"
        f"Доходность: "
        f"{item['estimated_roi_percent']:.1f}%"
    )


def main():
    print(
        "CS2 MARKET MONITOR - READ ONLY",
        flush=True
    )

    if os.getenv("DRY_RUN", "true").strip().lower() != "true":
        raise RuntimeError(
            "Safety stop: DRY_RUN must be true"
        )

    results = scan()

    save_json(RESULTS_FILE, results)

    previous = load_json(HISTORY_FILE, [])

    if not isinstance(previous, list):
        previous = []

    seen = {
        str(item.get("item_id"))
        for item in previous
        if isinstance(item, dict) and item.get("item_id")
    }

    new_items = []
    now = datetime.now(timezone.utc).isoformat()

    for item in results:
        if not isinstance(item, dict):
            continue

        if item.get("profit_verified") is not False:
            continue

        if item.get("status") != "ESTIMATE_REVIEW_REQUIRED":
            continue

        item_id = str(item.get("item_id", "")).strip()

        if not item_id or item_id in seen:
            continue

        new_item = dict(item)
        new_item["first_seen_utc"] = now

        new_items.append(new_item)
        seen.add(item_id)

    print(
        f"Candidates this batch: {len(results)}",
        flush=True
    )

    print(
        f"New candidates: {len(new_items)}",
        flush=True
    )

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN", ""
    ).strip()

    chat_id = os.getenv(
        "TELEGRAM_OWNER_ID", ""
    ).strip()

    if not new_items:
        print(
            "No new candidates. No alert.",
            flush=True
        )

    elif not token or not chat_id:
        print(
            "Telegram credentials missing.",
            flush=True
        )

    else:
        lines = [
            "CS2 MARKET MONITOR",
            "",
            f"New candidates: {len(new_items)}",
            "Mode: READ ONLY",
            ""
        ]

        for index, item in enumerate(
            new_items[:MAX_ALERT_ITEMS], 1
        ):
            lines.append(
                format_candidate(item, index)
            )
            lines.append("")

        lines.append(
            "Внимание: прибыль расчётная. "
            "Требуется ручная проверка."
        )

        try:
            with httpx.Client(timeout=15) as client:
                send_telegram(
                    client,
                    token,
                    chat_id,
                    "\n".join(lines)
                )

            print(
                "Telegram alert sent",
                flush=True
            )

        except (httpx.HTTPError, ValueError) as exc:
            print(
                "Telegram delivery failed:",
                type(exc).__name__,
                flush=True
            )

    combined = previous + new_items

    save_json(
        HISTORY_FILE,
        combined[-MAX_HISTORY:]
    )

    print("Real purchases: 0", flush=True)
    print("MONITOR COMPLETE", flush=True)


if __name__ == "__main__":
    main()
