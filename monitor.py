
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

HISTORY_FILE = Path(__file__).parent / "sent_alerts.json"
PURCHASES_FILE = Path(__file__).parent / "virtual_purchases.json"



# ===== ИСТОРИЯ УВЕДОМЛЕНИЙ =====

def load_history():
    if not HISTORY_FILE.exists():
        return {}

    try:
        data = json.loads(
            HISTORY_FILE.read_text(encoding="utf-8")
        )
        return data.get("sent", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(
            {"sent": history},
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ===== TELEGRAM =====


# История виртуальных покупок
def load_purchases():
    if not PURCHASES_FILE.exists():
        return []

    try:
        data = json.loads(
            PURCHASES_FILE.read_text(encoding="utf-8")
        )
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass

    raise RuntimeError(
        "Не удалось загрузить историю покупок"
    )


def save_purchases(purchases):
    PURCHASES_FILE.write_text(
        json.dumps(
            purchases,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )
async def send_telegram(client, token, owner, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"

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
        raise RuntimeError("Telegram API error")


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
    cutoff = now - timedelta(hours=COOLDOWN_HOURS)

    old_history = load_history()
    history = {}

    for name, timestamp in old_history.items():
        try:
            sent_at = datetime.fromisoformat(timestamp)

            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)

            if sent_at > cutoff:
                history[name] = timestamp

        except (TypeError, ValueError):
            continue

    print("CS2 BOT STARTED")
    print(f"DRY RUN: {DRY_RUN}")
    print(f"Budget: {TOTAL_BUDGET} RUB")
    print(f"Max item price: {MAX_ITEM_PRICE} RUB")

    items = await scan()

    sent = 0
    virtual_purchases = 0

    async with httpx.AsyncClient(timeout=30) as client:

        for item in items:

            if sent >= MAX_ALERTS:
                break

            try:
                name = str(item["name"])
                buy_price = float(item["buy_price"])
                avg_price = float(item["sell_reference"])
                activity = int(item["volume"])

                discount = float(item.get("spread", 0))

            except (KeyError, ValueError, TypeError):
                continue

            # Проверка цены
            if buy_price <= 0:
                continue

            if buy_price > MAX_ITEM_PRICE:
                continue

            # Проверка бюджета
            if buy_price > remaining_budget:
                continue

            # Проверка повторных уведомлений
            if name in history:
                continue

            # Чистая расчётная прибыль
            net_profit = avg_price * (1 - SELL_FEE) - buy_price

            profit_percent = (
                net_profit / buy_price
            ) * 100

            # Проверка минимальной прибыли
            if net_profit < MIN_MARGIN:
                continue

            if profit_percent < MIN_PROFIT_PERCENT:
                continue

            # Виртуальная покупка
            if DRY_RUN:

                remaining_budget -= buy_price
                virtual_purchases += 1

                print(
                    f"[DRY RUN] Virtual purchase: {name} | "
                    f"Price: {buy_price:.2f} RUB | "
                    f"Remaining: {remaining_budget:.2f} RUB"
                )

            message = (
                "🔎 CS2 — ТЕСТОВЫЙ СИГНАЛ\n\n"
                f"🎮 {name}\n\n"
                f"🛒 Цена покупки: {buy_price:.2f} ₽\n"
                f"📈 Историческая средняя: {avg_price:.2f} ₽\n"
                f"📉 Разница: {discount:.1f}%\n"
                f"💰 Расчётная прибыль: {net_profit:.2f} ₽\n"
                f"📊 Доходность: {profit_percent:.1f}%\n"
                f"📦 Активность за 7 дней: {activity}\n"
                f"💳 Остаток тестового бюджета: "
                f"{remaining_budget:.2f} ₽\n\n"
                "🧪 Режим симуляции. Реальных покупок нет.\n"
                "Комиссия продажи в расчёте: 10%.\n"
                "Фактическая прибыль не гарантирована."
            )

            await send_telegram(
                client,
                token,
                owner,
                message
            )

            history[name] = datetime.now(
                timezone.utc
            ).isoformat()

            save_history(history)

            sent += 1

    save_history(history)

    print("SCAN COMPLETED")
    print(f"Alerts sent: {sent}")
    print(f"Virtual purchases: {virtual_purchases}")
    print(f"Remaining test budget: {remaining_budget:.2f} RUB")


if __name__ == "__main__":
    asyncio.run(main())
