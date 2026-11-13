# Steam Trade Bot — safe monitoring build

**Simulation only. No real purchase or sell functionality is included.** Historical averages are NOT guaranteed executable sale prices. Never interpret signals as guaranteed profits.

## Configuration
Python 3.11+, `pip install -r requirements.txt`. Configure secrets `MARKET_CSGO_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_ID` in GitHub Settings → Secrets and variables → Actions. Never commit keys. If a token has ever been shared publicly, revoke it and create a new one.

Edit `watchlist.json` with exact market hash names. The scanner checks up to 10 names per run and saves its cursor. It uses API listing prices in kopecks, a 7-day historical average discounted by 15%, a 10% assumed selling fee, at least 20 sales in 7 days, at least 50 RUB theoretical profit, at least 10% theoretical margin, and a 50–500 RUB listing range. Verify currency and endpoint schemas with the provider before relying on results. Historical reference is **not** a live sell bid. Results may be empty. No trading calls are made.

## Run
`python check_api.py` then `python monitor.py`. GitHub Actions workflow `monitor.yml` runs scheduled scans, but GitHub schedules may be delayed or skipped; this is not an always-on server. `telegram_bot.py` is a long-running polling panel and needs separate persistent hosting; the test workflow only compiles it.

## Accounting
`purchases.json` contains **simulated** historic records. Old records with `buy_price` and new ones with `price` are both counted toward the simulated budget. Do not confuse simulated budget with real wallet funds. Existing records are preserved. To start a fresh simulation, back up then reset `purchases.json` to `[]` and `sent_alerts.json` to `{}`.

## Security
Keep GitHub secrets out of logs and source. Real trading is intentionally blocked even if `DRY_RUN=false`. The workflow commits simulation state to the default branch; do not use this approach for live trading or financial ledger integrity. Use a transactional database before any future live trading.
