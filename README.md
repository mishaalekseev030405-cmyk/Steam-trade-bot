# Steam-trade-bot
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from scanner import scan

MIN_MARGIN = 50
MAX_ALERTS = 3
HISTORY_FILE = Path(__file__).parent / "sent_alerts.json"


def load_history():
    if not HISTORY_FILE.exists():
        return {}

    data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return data.get("sent", {})


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(
            {"sent": history},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    owner = os.environ["TELEGRAM_OWNER_ID"]

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    history = load_history()

    history = {
        name: timestamp
        for name, timestamp in history.items()
        if datetime.fromisoformat(timestamp) > cutoff
    }

    items = await scan()
    sent = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for item in items:
            if sent >= MAX_ALERTS:
                break

            name = str(item["name"])
            margin = float(item["reference_margin"])

            if margin < MIN_MARGIN or name in history:
                continue

            message = (
                "🔎 CS2 — ценовой сигнал\n\n"
                f"🎮 {name}\n"
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
                json={"chat_id": owner, "text": message},
            )
            response.raise_for_status()

            if not response.json().get("ok"):
                raise RuntimeError("Telegram rejected message")

            history[name] = now.isoformat()
            save_history(history)
            sent += 1

    print(f"Проверка завершена. Отправлено: {sent}")


if __name__ == "__main__":
    asyncio.run(main())
