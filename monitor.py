
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scanner import scan


TOTAL_BUDGET = 3000.0
MAX_ITEM_PRICE = 500.0
MIN_MARGIN = 50.0
MIN_PROFIT_PERCENT = 10.0
SELL_FEE = 0.10

MAX_ALERTS = 5
COOLDOWN_HOURS = 1

DRY_RUN = True

ALERTS_FILE = Path("sent_alerts.json")
PURCHASES_FILE = Path("purchases.json")


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


def get_remaining_budget(purchases):
    spent = sum(
        float(item.get("price", 0))
        for item in purchases
    )
    return max(0.0, TOTAL_BUDGET - spent)


def recently_alerted(name, alerts, now):
    last_sent = alerts.get(name)

    if not last_sent:
        return False

    try:
        last_time = datetime.fromisoformat(last_sent)

        if last_time.tzinfo is None:
            last_time = last_time.replace(
                tzinfo=timezone.utc
            )

        return now - last_time < timedelta(
            hours=COOLDOWN_HOURS
        )

    except (ValueError, TypeError):
        return False


def already_purchased(item, purchases):
    item_id = item.get("item_id")

    if item_id is None or str(item_id).strip() == "":
        return True

    item_id = str(item_id)

    for purchase in purchases:
        if str(purchase.get("item_id")) == item_id:
            return True

    return False


async def send_telegram(message):
    token = os.getenv(
        "TELEGRAM_BOT_TOKEN", ""
    ).strip()

    owner_id = os.getenv(
        "TELEGRAM_OWNER_ID", ""
    ).strip()

    if not token or not owner_id:
        print("Telegram credentials missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    try:
        async with httpx.AsyncClient(
            timeout=20
        ) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": owner_id,
                    "text": message,
                },
            )
            response.raise_for_status()

        return True

    except httpx.HTTPError as error:
        print(
            "Telegram sending failed:",
            type(error).__name__,
        )
        return False


def format_signal(item, profit, profit_percent):
    name = item.get("name", "Unknown item")
    price = float(item["buy_price"])

    reference = float(
        item.get("sell_reference", 0)
    )

    item_id = item.get("item_id", "N/A")

    return (
        "CS2 MARKET SIGNAL\n\n"
        f"Предмет: {name}\n"
        f"Цена покупки: {price:.2f} ₽\n"
        f"Ориентир продажи: {reference:.2f} ₽\n"
        f"Расчётная прибыль: {profit:.2f} ₽\n"
        f"Доходность: {profit_percent:.1f}%\n"
        f"ID лота: {item_id}\n\n"
        "Это расчётный сигнал, "
        "не гарантия прибыли.\n"
        "Реальная покупка отключена."
    )


async def main():
    print("CS2 BOT STARTED")
    print("DRY RUN:", DRY_RUN)
    print("Budget:", TOTAL_BUDGET, "RUB")
    print("Max item price:", MAX_ITEM_PRICE, "RUB")

    alerts = load_json(ALERTS_FILE, {})
    purchases = load_json(PURCHASES_FILE, [])

    if not isinstance(alerts, dict):
        alerts = {}

    if not isinstance(purchases, list):
        purchases = []

    remaining = get_remaining_budget(purchases)

    print(
        f"Remaining budget: {remaining:.2f} RUB"
    )

    purchased_ids = {
        str(purchase.get("item_id"))
        for purchase in purchases
        if purchase.get("item_id") is not None
    }

    print(
        "Previously purchased lots:",
        len(purchased_ids),
    )

    print("STARTING MARKET SCANNER")

    opportunities = scan()

    if asyncio.iscoroutine(opportunities):
        opportunities = await opportunities

    if not isinstance(opportunities, list):
        raise RuntimeError(
            "Scanner must return a list"
        )

    print(
        "Scanner returned:",
        len(opportunities),
    )

    now = datetime.now(timezone.utc)

    alerts_sent = 0
    virtual_purchases = 0

    for item in opportunities:
        if alerts_sent >= MAX_ALERTS:
            break

        try:
            name = str(item["name"])
            price = float(item["buy_price"])

            reference = float(
                item.get(
                    "sell_reference",
                    item.get("buy_order", 0),
                )
            )

            item_id = item.get("item_id")

            if item_id is None:
                print(
                    "Skipping lot without ID:",
                    name,
                )
                continue

            if price <= 0 or reference <= 0:
                continue

            profit = (
                reference * (1 - SELL_FEE)
                - price
            )

            profit_percent = (
                profit / price * 100
            )

        except (KeyError, TypeError, ValueError):
            print("Skipping invalid signal")
            continue

        if already_purchased(item, purchases):
            print(
                "ALREADY PURCHASED:",
                name,
                "Lot ID:",
                item_id,
            )
            continue

        if price > MAX_ITEM_PRICE:
            continue

        if price > remaining:
            continue

        if profit < MIN_MARGIN:
            continue

        if profit_percent < MIN_PROFIT_PERCENT:
            continue

        if recently_alerted(name, alerts, now):
            print("Cooldown:", name)
            continue

        message = format_signal(
            item,
            profit,
            profit_percent,
        )

        sent = await send_telegram(message)

        if not sent:
            continue

        alerts[name] = now.isoformat()
        alerts_sent += 1

        print("ALERT SENT:", name)

        if DRY_RUN:
            purchases.append(
                {
                    "name": name,
                    "price": round(price, 2),
                    "item_id": str(item_id),
                    "timestamp": now.isoformat(),
                    "mode": "DRY_RUN",
                }
            )

            purchased_ids.add(str(item_id))

            remaining -= price
            virtual_purchases += 1

            print(
                "[DRY RUN] Virtual purchase:",
                name,
                "Lot ID:",
                item_id,
            )

        else:
            print(
                "LIVE TRADING DISABLED: "
                "real purchase API not implemented"
            )

    save_json(ALERTS_FILE, alerts)
    save_json(PURCHASES_FILE, purchases)

    print("SCAN COMPLETED")
    print("Alerts sent:", alerts_sent)
    print(
        "Virtual purchases:",
        virtual_purchases,
    )
    print(
        "Remaining test budget:",
        f"{remaining:.2f} RUB",
    )


if __name__ == "__main__":
    asyncio.run(main())
