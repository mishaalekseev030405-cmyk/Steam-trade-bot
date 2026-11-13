
import httpx

BASE = "https://market.csgo.com/api/v2"

NAMES = [
    "Five-SeveN | Heat Treated (Field-Tested)",
    "UMP-45 | Crimson Foil (Field-Tested)",
    "M4A1-S | Solitude (Minimal Wear)",
]


def fetch(client, path):
    response = client.get(f"{BASE}/{path}")
    response.raise_for_status()
    return response.json()


def preview(value, depth=0):
    if depth >= 3:
        return type(value).__name__

    if isinstance(value, dict):
        return {
            str(k): preview(v, depth + 1)
            for k, v in list(value.items())[:8]
        }

    if isinstance(value, list):
        return {
            "count": len(value),
            "first": (
                preview(value[0], depth + 1)
                if value else None
            ),
        }

    return value


def main():
    print("REAL MARKET CHECK STARTED")

    with httpx.Client(timeout=40) as client:
        orders = fetch(
            client,
            "prices/orders/RUB.json",
        )

        print("ORDER RESPONSE STRUCTURE:")
        print(preview(orders))

        history_index = fetch(
            client,
            "full-history/all.json",
        )

        history_map = history_index.get(
            "history", {}
        )

        for name in NAMES:
            print("\nITEM:", name)

            history_id = history_map.get(name)

            if history_id is None:
                print("No history ID")
                continue

            history = fetch(
                client,
                f"full-history/{history_id}.json",
            )

            data = history.get("data", {})

            for field in [
                "average7d",
                "average30d",
                "sales7d",
                "sales30d",
            ]:
                print(field, ":", data.get(field))

            print(
                "History records:",
                len(data.get("history", [])),
            )

    print("\nREAL MARKET CHECK COMPLETED")


if __name__ == "__main__":
    main()
