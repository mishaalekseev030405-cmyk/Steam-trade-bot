
import asyncio
import os

import httpx
from scanner import scan

MIN_MARGIN = 50
MAX_ALERTS = 3


async def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    owner = os.environ["TELEGRAM_OWNER_ID"]

    items = await scan()
    sent = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for item in items:
            if sent >= MAX_ALERTS:
                break

            margin = float(item["reference_margin"])
            if margin < MIN_MARGIN:
                continue

            message = (
                "🔎 CS2 — ценовой сигнал\n\n"
                f"🎮 {item['name']}\n"
                f"Справочная цена: {item['sell_reference']} ₽\n"
                f"Заявка покупки: {item['buy_order']} ₽\n"
                f"Спред: {item['spread']}%\n"
                f"Расчётная маржа: {margin:.2f} ₽\n"
                f"Объём: {item['volume']}\n\n"
                "⚠️ Прибыль не гарантирована. "
                "Проверь реальные цены, комиссии "
                "и возможность сделки."
            )

            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": owner,
                    "text": message,
                },
            )
            response.raise_for_status()

            result = response.json()
            if not result.get("ok"):
                raise RuntimeError("Telegram rejected message")

            sent += 1

    print(f"Проверка завершена. Отправлено: {sent}")


if __name__ == "__main__":
    asyncio.run(main())
