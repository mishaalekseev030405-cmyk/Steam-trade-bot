
"""CS2 scanner notifications. Read-only: no purchases."""
import json
import os
from pathlib import Path

import httpx
from scanner import scan

ROOT = Path(__file__).resolve().parent


def send_telegram(client, token, chat_id, message):
    response = client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": message,
        },
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("ok"):
        raise ValueError("Telegram rejected message")


def main():
    print("CS2 MARKET SCANNER — READ ONLY", flush=True)

    results = scan()

    output = ROOT / "latest_results.json"
    output.write_text(
        json.dumps(
            results,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        "Candidates for manual review:",
        len(results),
        flush=True,
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_OWNER_ID", "").strip()

    if not token or not chat_id:
        print("Telegram credentials missing", flush=True)
        return

    # Set to false to disable routine reports.
    send_reports = (
        os.getenv("TELEGRAM_SCAN_REPORTS", "true")
        .strip()
        .lower()
        == "true"
    )

    try:
        with httpx.Client(timeout=15) as client:

            if send_reports:
                report = (
                    "🤖 CS2 Market Monitor\n\n"
                    "✅ Сканирование завершено\n"
                    f"📦 Кандидатов: {len(results)}\n"
                    "🔒 Реальных покупок: 0\n\n"
                    "Результаты предварительные."
                )

                send_telegram(
                    client, token, chat_id, report
                )

            if results:
                lines = [
                    "💰 Потенциально выгодные скины",
                    "",
                ]

                for index, item in enumerate(
                    results[:5], start=1
                ):
                    name = item.get("name", "Unknown")
                    buy = item.get("buy_price_rub")
                    profit = item.get(
                        "estimated_profit_rub"
                    )
                    roi = item.get(
                        "estimated_roi_percent"
                    )

                    lines.append(
                        f"{index}. {name}\n"
                        f"Покупка: {buy} ₽\n"
                        f"Оценочная прибыль: {profit} ₽\n"
                        f"Доходность: {roi}%\n"
                    )

                lines.append(
                    "⚠️ Прибыль не подтверждена. "
                    "Требуется ручная проверка."
                )

                send_telegram(
                    client,
                    token,
                    chat_id,
                    "\n".join(lines),
                )

            print(
                "Telegram notification sent",
                flush=True,
            )

    except (httpx.HTTPError, ValueError) as exc:
        print(
            "Telegram delivery failed:",
            type(exc).__name__,
            flush=True,
        )

    print("Real purchases: 0", flush=True)


if __name__ == "__main__":
    main()
