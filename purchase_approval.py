
"""Prepare a purchase proposal. No real trading."""

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from trade_guard import validate_candidate

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "latest_results.json"
PROPOSAL = ROOT / "purchase_proposal.json"


def amount(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def main():
    if os.getenv("DRY_RUN", "true").lower() != "true":
        raise RuntimeError("DRY_RUN must remain true")

    if not RESULTS.exists():
        raise FileNotFoundError("Run scanner first")

    items = json.loads(RESULTS.read_text(encoding="utf-8"))

    if not isinstance(items, list):
        raise ValueError("Invalid scanner results")

    candidates = []

    for item in items:
        if not isinstance(item, dict):
            continue

        price = amount(item.get("buy_price_rub"))
        profit = amount(item.get("estimated_profit_rub"))
        roi = amount(item.get("estimated_roi_percent"))

        if price is None or profit is None or roi is None:
            continue

        if not (
            Decimal("0") < price <= Decimal("500")
            and profit >= Decimal("50")
            and roi >= Decimal("10")
        ):
            continue

        # No proposal if independently verified data is absent.
        valid, reason = validate_candidate(
            item,
            spent_rub="0",
            balance_rub="3000"
        )

        candidates.append({
            "item": item,
            "verified": valid,
            "reason": reason
        })

    candidates.sort(
        key=lambda x: amount(
            x["item"]["estimated_profit_rub"]
        ),
        reverse=True
    )

    proposal = {
        "mode": "MANUAL_REVIEW_ONLY",
        "real_purchase_allowed": False,
        "status": "NO_CANDIDATE",
        "candidate": None
    }

    if candidates:
        best = candidates[0]
        item = best["item"]

        proposal["status"] = "REVIEW_REQUIRED"
        proposal["candidate"] = {
            "name": item.get("name"),
            "item_id": item.get("item_id"),
            "buy_price_rub": item.get("buy_price_rub"),
            "estimated_profit_rub": item.get(
                "estimated_profit_rub"
            ),
            "estimated_roi_percent": item.get(
                "estimated_roi_percent"
            ),
            "profit_verified": best["verified"],
            "verification_note": best["reason"]
        }

    PROPOSAL.write_text(
        json.dumps(
            proposal,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_OWNER_ID", "").strip()

    if candidates:
        item = proposal["candidate"]
        message = (
            "CS2: кандидат на покупку\n\n"
            f"Предмет: {item['name']}\n"
            f"Цена: {item['buy_price_rub']} RUB\n"
            f"Оценочная прибыль: "
            f"{item['estimated_profit_rub']} RUB\n"
            f"Оценочная ROI: "
            f"{item['estimated_roi_percent']}%\n\n"
            "Прибыль НЕ подтверждена.\n"
            "Покупка заблокирована.\n"
            "Это уведомление, не запрос на оплату."
        )
    else:
        message = (
            "CS2: подходящих кандидатов пока нет.\n"
            "Реальных покупок: 0."
        )

    if token and chat_id:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message
                }
            )
            response.raise_for_status()
            if not response.json().get("ok"):
                raise RuntimeError("Telegram rejected message")
    else:
        print("Telegram credentials missing")

    print(json.dumps(proposal, ensure_ascii=False, indent=2))
    print("REAL PURCHASES: 0")


if __name__ == "__main__":
    main()
