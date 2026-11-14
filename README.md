# Steam Trade Bot — read-only monitoring

**No real buying or selling.** The scanner produces estimates based on historical prices; they are not executable sell quotes or guaranteed profit.

## Setup
Use Python 3.11+ and `pip install -r requirements.txt`. Configure `MARKET_CSGO_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_OWNER_ID` in GitHub Actions secrets. Never commit credentials. Revoke any credential previously exposed in chat or logs.

## Current workflow
`.github/workflows/monitor.yml` schedules runs every five minutes, but GitHub Actions schedules can be delayed or skipped. It compiles Python modules, runs offline safety tests, restores state from the `scanner-state` branch, validates the purchase ledger, runs `monitor.py` and `purchase_approval.py`, then saves state. The workflow requires a valid `purchase_ledger.json` in `scanner-state`; if missing, it fails closed.

The scanner currently processes up to 100 catalog items per run (not the `watchlist.json` entries). It requires explicit `MARKET_OFFER_PRICE_UNIT` and `MARKET_HISTORY_PRICE_UNIT` configuration. The workflow currently sets these to `kopecks` and `rubles`, respectively; **verify these assumptions against real API responses before trusting the results**. Filters: 50–500 RUB offer price, 20 reported sales over seven days, at least 50 RUB estimated profit and 10% estimated ROI, assuming a 10% selling fee. Actual liquidity, fees, slippage, order availability, and selling price are not verified.

`telegram_bot.py` provides a separate polling-based, read-only Telegram panel. It is not launched by the scheduled workflow and must be hosted separately for continuous availability. Its simulated-purchase display reads legacy `purchases.json`; the newer reservation ledger is `purchase_ledger.json`. These are **not the same accounting source** and must be unified before live trading.

## Tests
Run `python -m unittest discover -s tests -v`. These are offline regression tests and do not prove that Market.CSGO or Telegram APIs are available.

## Safety and deployment
`DRY_RUN=true` is mandatory, and `trade_guard.purchase_allowed()` always returns false. No real-trading adapter exists. Do not turn on real-money operations until API behavior, prices, permissions, reconciliation, idempotency, database transactions, and error recovery have been verified. For a VPS, use a persistent service and transactional storage rather than relying on GitHub branch files as a live financial ledger.
