
name: CS2 Market Monitor

on:
  workflow_dispatch:
  schedule:
    - cron: '*/5 * * * *'

permissions:
  contents: read

concurrency:
  group: cs2-market-monitor
  cancel-in-progress: false

jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: python -m pip install 'httpx>=0.27,<1'

      - name: Restore scanner state
        uses: actions/cache/restore@v4
        with:
          path: |
            scan_progress.json
            candidate_history.json
          key: cs2-state-${{ github.run_id }}
          restore-keys: |
            cs2-state-

      - name: Check Python files
        run: |
          python -m py_compile scanner.py
          python -m py_compile monitor.py

      - name: Run scanner
        env:
          MARKET_CSGO_API_KEY: ${{ secrets.MARKET_CSGO_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_OWNER_ID: ${{ secrets.TELEGRAM_OWNER_ID }}
          DRY_RUN: 'true'
          MARKET_OFFER_PRICE_UNIT: 'unknown'
          MARKET_HISTORY_PRICE_UNIT: 'unknown'
        run: python -u monitor.py

      - name: Save scanner state
        if: always()
        uses: actions/cache/save@v4
        with:
          path: |
            scan_progress.json
            candidate_history.json
          key: cs2-state-${{ github.run_id }}

      - name: Upload scan results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: cs2-results-${{ github.run_id }}
          path: |
            latest_results.json
            scan_progress.json
            scan_diagnostics.json
            profitable_candidates.json
            candidate_history.json
          if-no-files-found: warn
          retention-days: 7
