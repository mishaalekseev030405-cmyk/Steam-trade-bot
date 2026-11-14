
import json
import os
from pathlib import Path

import httpx

from scanner import scan

ROOT = Path(__file__).resolve().parent


def load_json(filename, default):
    path = ROOT / filename
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(filename, data):
    path = ROOT / filename
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp.replace(path)


def notify(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    owner = os.getenv("TELEGRAM_OWNER_ID", "").strip()

    if not token or not owner:
        print("Telegram not configured")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                url,
                json={
                    "chat_id": owner,
                    "text": message[:4000]
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("ok") is True

    except httpx.HTTPError as error:
        print("Telegram error:", type(error).__name__)
        return False


def main():
    print("CS2 BOT STARTED", flush=True)

    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    print("DRY RUN:", dry_run)
    print("Budget: 3000 RUB")
    print("Max item price: 500 RUB")

    print("STARTING MARKET SCANNER", flush=True)

    candidates = scan()

    save_json("latest_results.json", candidates)

    print("SCAN COMPLETED")
    print("Candidates:", len(candidates))

    sent = load_json("sent_alerts.json", [])

    if not isinstance(sent, list):
        sent = []

    sent_ids = set(str(item) for item in sent)

    alerts_sent = 0

    for item in candidates:
        item_id = str(item["item_id"])

        if item_id in sent_ids:
            continue

        message = (
            "CS2: найден потенциально выгодный лот\n\n"
            f"Предмет: {item['name']}\n"
            f"Цена: {item['buy_price']} RUB\n"
            f"Оценка продажи: {item['sell_reference']} RUB\n"
            f"Расчётная прибыль: {item['estimated_profit']} RUB\n"
            f"ROI: {item['roi_percent']}%\n"
            f"Продаж за 7 дней: {item['sales7d']}\n\n"
            "Это оценка по истории, прибыль не гарантирована.\n"
            "Покупка не выполнялась."
        )

        if notify(message):
            sent_ids.add(item_id)
            alerts_sent += 1

    save_json("sent_alerts.json", sorted(sent_ids))

    print("Alerts sent:", alerts_sent)
    print("Real purchases: 0")
    print("CS2 BOT FINISHED")


if __name__ == "__main__":
    main()
