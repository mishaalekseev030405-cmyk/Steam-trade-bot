
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from scanner import scan

MIN_MARGIN = 50
DRY_RUN = True
TOTAL_BUDGET = 3000
MAX_ITEM_PRICE = 500
MIN_PROFIT_PERCENT = 10
MAX_ALERTS = 3
COOLDOWN_HOURS = 24
HISTORY_FILE = Path(__file__).parent / "sent_alerts.json"


def load_history():
    if not HISTORY_FILE.exists():
        return {}

    data = json.loads(
        HISTORY_FILE.read_text(encoding="utf-8")
    )
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

            buy_price = float(item["buy_price"])
            avg_price = float(item["sell_reference"])
            activity = int(item["volume"])
            discount = float(item["spread"])

            message = (
                "🔎 CS2 — потенциальная перепродажа\n\n"
                f"🎮 {name}\n\n"
                f"🛒 Цена покупки: {buy_price:.2f} ₽\n"
                f"📈 Историческая средняя: {avg_price:.2f} ₽\n"
                f"📉 Разница с исторической ценой: {discount:.1f}%\n"
                f"💰 Расчётная маржа: {margin:.2f} ₽\n"
                f"📊 Активность за 7 дней: {activity}\n\n"
                "Расчёт учитывает предполагаемую "
                "комиссию продажи 10%.\n\n"
                "⚠️ Прибыль не гарантирована. "
                "Проверь актуальный лот, "
                "историю продаж и комиссии "
                "перед покупкой."
            )

            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": owner,
                    "text": message,
                },
            )
            response.raise_for_status()

            if not response.json().get("ok"):
                raise RuntimeError("Telegram rejected message")

            history[name] = datetime.now(
                timezone.utc
            ).isoformat()
            save_history(history)
            sent += 1

    save_history(history)
    print(f"Проверка завершена. Отправлено: {sent}")


if __name__ == "__main__":
    asyncio.run(main())

