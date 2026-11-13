
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from scanner import scan


# ===== НАСТРОЙКИ =====

DRY_RUN = True

TOTAL_BUDGET = 3000.0
MAX_ITEM_PRICE = 500.0
MIN_PROFIT_PERCENT = 10.0

SELL_FEE = 0.10
MIN_MARGIN = 50.0

MAX_ALERTS = 3
COOLDOWN_HOURS = 24

BASE_DIR = Path(__file__).parent

HISTORY_FILE = BASE_DIR / "sent_alerts.json"
PURCHASES_FILE = BASE_DIR / "purchases.json"


# ===== РАБОТА С JSON =====

def read_json(path, default):
    if not path.exists():
        return default

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
        if isinstance(data, type(default)):
            return data
    except (OSError, ValueError):
        pass

    raise RuntimeError(
        f"Не удалось прочитать файл {path.name}"
    )


def write_json(path, data):
    temp = path.with_suffix(".tmp")

    temp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temp.replace(path)


def load_history():
    data = read_json(HISTORY_FILE, {})
    return data.get("sent", {})


def save_history(history):
    write_json(
        HISTORY_FILE,
        {"sent": history}
    )


def load_purchases():
    return read_json(PURCHASES_FILE, [])


def save_purchases(purchases):
    write_json(PURCHASES_FILE, purchases)


# ===== TELEGRAM =====

async def send_telegram(client, token, owner, message):
    url = (
        f"https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    response = await client.post(
        url,
        json={
            "chat_id": owner,
            "text": message
        }
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Ошибка Telegram: "
            f"{data.get('description', 'unknown')}"
        )


# ===== ОСНОВНАЯ ПРОГРАММА =====

async def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    owner = os.environ["TELEGRAM_OWNER_ID"]

    purchases = load_purchases()

    spent = sum(
        float(item["buy_price"])
        for item in purchases
    )

    remaining_budget = max(
        0.0,
        TOTAL_BUDGET - spent
    )

    now = datetime.now(timezone.utc)

    cutoff = now - timedelta(
        hours=COOLDOWN_HOURS
    )

    old_history = load_history()
    history = {}

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

        except (TypeError, ValueError):
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

            name = str(item["name"])

            if name in history:
                continue

            buy_price = float(
                item["buy_price"]
            )

            avg_price = float(
                item["sell_reference"]
            )

            activity = int(
                item["volume"]
            )

            discount = float(
                item["spread"]
            )

            if (
                buy_price <= 0
                or buy_price > MAX_ITEM_PRICE
            ):
                continue

            if avg_price <= 0:
                continue

            net_profit = (
                avg_price * (1 - SELL_FEE)
                - buy_price
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

            if buy_price > remaining_budget:
                continue

            message = (
                "🔎 CS2 — потенциальная "
                "перепродажа\n\n"
                f"🎮 {name}\n\n"
                f"🛒 Цена покупки: "
                f"{buy_price:.2f} ₽\n"
                f"📈 Историческая средняя: "
                f"{avg_price:.2f} ₽\n"
                f"📉 Разница с исторической "
                f"ценой: {discount:.1f}%\n"
                f"💰 Расчётная прибыль: "
                f"{net_profit:.2f} ₽\n"
                f"📊 Доходность: "
                f"{profit_percent:.1f}%\n"
                f"📊 Активность за 7 дней: "
                f"{activity}\n\n"
                "⚠️ Это оценка, а не "
                "гарантированная прибыль. "
                "Проверь текущие лоты, "
                "комиссии и ликвидность."
            )

            # Сначала отправляем сигнал
            await send_telegram(
                client,
                token,
                owner,
                message
            )

            history[name] = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            save_history(history)
            sent += 1

            # Виртуальная покупка
            if DRY_RUN:
                purchase = {
                    "name": name,
                    "buy_price": buy_price,
                    "sell_reference": avg_price,
                    "estimated_profit": round(
                        net_profit, 2
                    ),
                    "purchased_at": (
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    ),
                    "mode": "DRY_RUN"
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
