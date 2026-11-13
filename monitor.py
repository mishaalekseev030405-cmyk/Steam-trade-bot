
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scanner import scan


# ===== НАСТРОЙКИ =====

TOTAL_BUDGET = 3000.0
MAX_ITEM_PRICE = 500.0

MIN_MARGIN = 50.0
MIN_PROFIT_PERCENT = 10.0

SELL_FEE = 0.10

MAX_ALERTS = 5
COOLDOWN_HOURS = 0

# Только тестовый режим.
DRY_RUN = True

HISTORY_FILE = Path("sent_alerts.json")
PURCHASES_FILE = Path("purchases.json")


# ===== РАБОТА С JSON =====

def read_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open(
            "r", encoding="utf-8"
        ) as file:
            return json.load(file)
    except (
        OSError,
        ValueError,
        TypeError,
    ):
        return default


def write_json(path, data):
    temporary = path.with_name(
        path.name + ".tmp"
    )

    with temporary.open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    temporary.replace(path)


def load_history():
    data = read_json(
        HISTORY_FILE,
        {"sent": {}},
    )

    if not isinstance(data, dict):
        return {}

    sent = data.get("sent", {})

    if not isinstance(sent, dict):
        return {}

    return sent


def save_history(history):
    write_json(
        HISTORY_FILE,
        {"sent": history},
    )


def load_purchases():
    data = read_json(
        PURCHASES_FILE,
        [],
    )

    if not isinstance(data, list):
        return []

    return [
        item for item in data
        if isinstance(item, dict)
        and item.get("mode") == "DRY_RUN"
    ]


def save_purchases(purchases):
    write_json(
        PURCHASES_FILE,
        purchases,
    )


# ===== TELEGRAM =====

async def send_telegram(
    client,
    token,
    owner,
    message,
):
    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    response = await client.post(
        url,
        json={
            "chat_id": owner,
            "text": message,
        },
    )

    response.raise_for_status()

    data = response.json()

    if data.get("ok") is not True:
        raise RuntimeError(
            "Telegram API rejected message"
        )

    return True


# ===== ОСНОВНАЯ ПРОГРАММА =====

async def main():

    token = os.environ[
        "TELEGRAM_BOT_TOKEN"
    ]

    owner = os.environ[
        "TELEGRAM_OWNER_ID"
    ]

    purchases = load_purchases()

    spent = sum(
        float(item.get("buy_price", 0))
        for item in purchases
    )

    remaining_budget = max(
        0.0,
        TOTAL_BUDGET - spent,
    )

    now = datetime.now(timezone.utc)

    cutoff = now - timedelta(
        hours=COOLDOWN_HOURS
    )

    old_history = load_history()
    history = {}

    # ===== ИСТОРИЯ СИГНАЛОВ =====

    for name, timestamp in old_history.items():

        try:
            sent_at = datetime.fromisoformat(
                timestamp
            )

            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(
                    tzinfo=timezone.utc
                )

            if sent_at > cutoff:
                history[name] = timestamp

        except (
            TypeError,
            ValueError,
            AttributeError,
        ):
            continue

    print("CS2 BOT STARTED")
    print(f"DRY RUN: {DRY_RUN}")
    print(f"Budget: {TOTAL_BUDGET} RUB")
    print(
        f"Max item price: "
        f"{MAX_ITEM_PRICE} RUB"
    )
    print(
        f"Remaining budget: "
        f"{remaining_budget:.2f} RUB"
    )

    # ===== СКАНИРОВАНИЕ =====

    items = await scan()

    print(
        f"Подходящих сигналов: {len(items)}"
    )

    sent = 0
    virtual_purchases = 0

    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        for item in items:

            if sent >= MAX_ALERTS:
                break

            name = str(
                item.get("name", "")
            )

            if not name:
                continue

            if name in history:
                continue

            try:
                buy_price = float(
                    item["buy_price"]
                )

                sell_reference = float(
                    item["sell_reference"]
                )

                activity = int(
                    item["volume"]
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            # ===== ПРОВЕРКА ЦЕНЫ =====

            if (
                buy_price <= 0
                or buy_price > MAX_ITEM_PRICE
            ):
                continue

            if sell_reference <= 0:
                continue

            if buy_price > remaining_budget:
                continue

            # ===== РАСЧЁТ ПРИБЫЛИ =====

            estimated_sale = (
                sell_reference
                * (1 - SELL_FEE)
            )

            net_profit = (
                estimated_sale - buy_price
            )

            profit_percent = (
                net_profit / buy_price
            ) * 100

            if net_profit < MIN_MARGIN:
                continue

            if (
                profit_percent
                < MIN_PROFIT_PERCENT
            ):
                continue

            # ===== TELEGRAM СООБЩЕНИЕ =====

            message = (
                "🔎 CS2 — потенциальная "
                "перепродажа\n\n"
                f"🎮 {name}\n\n"
                f"🛒 Цена покупки: "
                f"{buy_price:.2f} ₽\n"
                f"📉 Ориентир продажи "
                f"(buy_order): "
                f"{sell_reference:.2f} ₽\n"
                f"💰 Расчётная прибыль: "
                f"{net_profit:.2f} ₽\n"
                f"📊 Доходность: "
                f"{profit_percent:.1f}%\n"
                f"📈 Активность за 7 дней: "
                f"{activity}\n\n"
                "⚠️ Это предварительная "
                "оценка, не гарантированная "
                "прибыль. Проверь реальные "
                "лоты, комиссии, ликвидность "
                "и возможность продажи."
            )

            # ===== ОТПРАВКА =====

            await send_telegram(
                client,
                token,
                owner,
                message,
            )

            history[name] = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            save_history(history)

            sent += 1

            # ===== ТЕСТОВАЯ ПОКУПКА =====

            if DRY_RUN:

                purchase = {
                    "name": name,
                    "buy_price": buy_price,
                    "sell_reference": (
                        sell_reference
                    ),
                    "estimated_profit": round(
                        net_profit, 2
                    ),
                    "purchased_at": (
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    ),
                    "mode": "DRY_RUN",
                }

                purchases.append(purchase)

                save_purchases(purchases)

                remaining_budget -= buy_price

                virtual_purchases += 1

                print(
                    f"[DRY RUN] "
                    f"Виртуальная покупка: "
                    f"{name}, "
                    f"цена {buy_price:.2f} ₽, "
                    f"остаток "
                    f"{remaining_budget:.2f} ₽"
                )

            else:
                print(
                    "LIVE TRADING DISABLED: "
                    "Real purchases are not "
                    "implemented."
                )

    save_history(history)

    print("SCAN COMPLETED")
    print(f"Alerts sent: {sent}")
    print(
        f"Virtual purchases: "
        f"{virtual_purchases}"
    )
    print(
        f"Remaining test budget: "
        f"{remaining_budget:.2f} RUB"
    )


if __name__ == "__main__":
    asyncio.run(main())
