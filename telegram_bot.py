
import asyncio
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from purchase_ledger import BUDGET, MAX_ITEM, load_ledger, check_capacity

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_ID = os.getenv("TELEGRAM_OWNER_ID", "").strip()


API = f"https://api.telegram.org/bot{TOKEN}"

MENU = {
    "inline_keyboard": [
        [
            {"text": "📊 Статистика", "callback_data": "stats"},
            {"text": "💎 Находки", "callback_data": "finds"},
        ],
        [
            {"text": "💰 Бюджет", "callback_data": "budget"},
            {"text": "📜 История", "callback_data": "history"},
        ],
        [
            {"text": "🔄 Обновить", "callback_data": "home"},
            {"text": "⚙️ Настройки", "callback_data": "settings"},
        ],
    ]
}


def load_json(filename, default):
    try:
        with Path(filename).open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def money(value):
    return f"{value:,.2f}".replace(",", " ") + " ₽"


def ledger_snapshot():
    data = load_ledger()
    capacity = check_capacity(data)
    return data["operations"], capacity


def alerts():
    data = load_json("sent_alerts.json", {})
    if not isinstance(data, dict): return {}
    return {**data.get("sent", {}), **{k:v for k,v in data.items() if k != "sent"}}


def progress():
    data = load_json("scan_progress.json", {})
    return data if isinstance(data, dict) else {}


def safe(value):
    return html.escape(str(value))


def format_time(value):
    if not value:
        return "Нет данных"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime(
            "%d.%m.%Y %H:%M UTC"
        )
    except (ValueError, TypeError):
        return "Нет данных"


def screen(section):
    buys, capacity = ledger_snapshot()
    signals = alerts()
    cursor = progress().get("cursor", 0)

    if section == "stats":
        return (
            "📊 <b>СТАТИСТИКА</b>\n\n"
            f"📦 Позиция сканера: {safe(cursor)}\n"
            f"💎 Уведомлений в истории: {len(signals)}\n"
            f"🛒 Операций в журнале: {len(buys)}\n\n"
            "ℹ️ Данные из сохранённых файлов.\n"
            "Это не подтверждение, что сканер сейчас запущен."
        )

    if section == "finds":
        if not signals:
            return "💎 <b>НАХОДКИ</b>\n\nПока сигналов нет."

        lines = ["💎 <b>ПОСЛЕДНИЕ СИГНАЛЫ</b>\n"]
        recent = list(signals.items())[-5:]

        for name, timestamp in reversed(recent):
            lines.append(
                f"• {safe(name)}\n"
                f"  🕒 {format_time(timestamp)}"
            )

        return "\n\n".join(lines)

    if section == "budget":
        return (
            "💰 <b>УЧЁТ РЕЗЕРВОВ</b>\n\n"
            f"💵 Начальный: {money(BUDGET)}\n"
            f"💳 Доступно по журналу: {money(capacity['remaining_rub'])}\n"
            f"🎯 Лимит предмета: {money(MAX_ITEM)}\n"
            f"🛒 Операций в журнале: {len(buys)}\n\n"
            "🔒 Реальная торговля отключена."
        )

    if section == "history":
        if not buys:
            return "📜 <b>ИСТОРИЯ</b>\n\nОпераций пока нет."

        lines = ["📜 <b>ОПЕРАЦИИ (НЕ РЕАЛЬНЫЕ ПОКУПКИ)</b>\n"]

        for item in reversed(buys[-5:]):
            lines.append(
                f"🎮 {safe(item.get('name', 'Предмет'))}\n"
                f"💵 {money(item.get('price_rub', 0))}\n"
                f"🕒 {format_time(item.get('created_at'))}\n"
                f"Статус: {safe(item.get('status', 'UNKNOWN'))}"
            )

        return "\n\n".join(lines)

    if section == "settings":
        return (
            "⚙️ <b>НАСТРОЙКИ</b>\n\n"
            "🔒 Реальная торговля: ВЫКЛ.\n"
            "🧪 Режим: DRY RUN\n"
            f"💵 Бюджет: {money(BUDGET)}\n"
            f"🎯 Максимальная цена: {money(MAX_ITEM)}\n\n"
            "Изменение настроек через Telegram "
            "пока запрещено для безопасности."
        )

    return (
        "🎮 <b>CS2 MARKET MONITOR</b>\n\n"
        "Добро пожаловать в панель мониторинга!\n\n"
        f"💰 Доступно по журналу: {money(capacity['remaining_rub'])}\n"
        f"📦 Позиция сканера: {safe(cursor)}\n"
        f"🛒 Операций в журнале: {len(buys)}\n"
        "🔒 Реальные покупки: ВЫКЛ.\n\n"
        "👇 Выбери нужный раздел."
    )


async def api_call(client, method, payload):
    response = await client.post(
        f"{API}/{method}",
        json=payload,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError("Telegram API request failed")

    return result.get("result")


async def show(client, chat_id, section):
    await api_call(
        client,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": screen(section),
            "parse_mode": "HTML",
            "reply_markup": MENU,
        },
    )


async def main():
    if not TOKEN or not OWNER_ID:
        raise RuntimeError("Telegram credentials missing")

    owner = int(OWNER_ID)
    offset = None

    async with httpx.AsyncClient(timeout=40) as client:
        print("TELEGRAM PANEL STARTED")

        while True:
            try:
                updates = await api_call(
                    client,
                    "getUpdates",
                    {
                        "offset": offset,
                        "timeout": 25,
                        "allowed_updates": [
                            "message",
                            "callback_query",
                        ],
                    },
                )

                for update in updates:
                    offset = update["update_id"] + 1

                    message = update.get("message")
                    callback = update.get("callback_query")

                    if message:
                        chat = message.get("chat", {})
                        user = message.get("from", {})

                        if (
                            user.get("id") == owner
                            and chat.get("type") == "private"
                        ):
                            await show(
                                client,
                                chat["id"],
                                "home",
                            )

                    elif callback:
                        user = callback.get("from", {})
                        msg = callback.get("message", {})
                        chat = msg.get("chat", {})

                        await api_call(
                            client,
                            "answerCallbackQuery",
                            {
                                "callback_query_id": callback["id"]
                            },
                        )

                        if (
                            user.get("id") == owner
                            and chat.get("type") == "private"
                        ):
                            section = callback.get("data", "home")

                            if section not in {
                                "home", "stats", "finds",
                                "budget", "history", "settings"
                            }:
                                section = "home"

                            await show(
                                client,
                                chat["id"],
                                section,
                            )

            except (httpx.HTTPError, RuntimeError) as error:
                print("Telegram polling error:", type(error).__name__)
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
