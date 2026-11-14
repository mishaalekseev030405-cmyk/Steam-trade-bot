"""Offline configuration and state validation for VPS. Never prints secrets."""
import os
import sys
from pathlib import Path

from purchase_ledger import load_ledger, check_capacity

def main():
    required = ("MARKET_CSGO_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_ID")
    missing = [key for key in required if not os.getenv(key, "").strip() or os.getenv(key) == "REPLACE_ME"]
    if missing:
        raise RuntimeError("Missing configuration: " + ", ".join(missing))
    if os.getenv("DRY_RUN", "true").lower() != "true":
        raise RuntimeError("Real trading must remain disabled")
    if os.getenv("MARKET_OFFER_PRICE_UNIT") not in ("kopecks", "rubles"):
        raise RuntimeError("Invalid offer price unit")
    if os.getenv("MARKET_HISTORY_PRICE_UNIT") not in ("kopecks", "rubles"):
        raise RuntimeError("Invalid history price unit")
    directory = Path(os.environ["CS2_STATE_DIR"]).resolve()
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        raise RuntimeError("State directory is missing or not writable")
    capacity = check_capacity(load_ledger())
    print("OFFLINE PREFLIGHT OK (no external API verification)")
    print("State directory:", directory)
    print("Reserved RUB:", capacity["reserved_rub"])
    print("Real trading: disabled")

if __name__ == "__main__":
    main()
