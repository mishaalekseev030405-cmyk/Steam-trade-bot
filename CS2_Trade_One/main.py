"""Main entry point."""
import asyncio
import logging

from config import Settings
from market import Market
from store import Store
from telegram_app import App


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    # httpx default INFO logs contain complete URLs (including Telegram tokens and API keys).
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    cfg = Settings.load()
    if not cfg.telegram_token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is required')
    if not cfg.market_key:
        raise RuntimeError('MARKET_CSGO_API_KEY is required')
    logging.info('Starting. Scope=%s, dry_run=%s, live_ready=%s',
                 cfg.scope, cfg.dry_run, cfg.live_ready)
    if not cfg.live_ready and not cfg.dry_run:
        logging.warning('DRY_RUN=false but live gates are incomplete. All buys remain simulated.')
    store = Store(cfg.db_path)
    market = Market(cfg.market_key, cfg.request_delay_s)
    asyncio.run(App(cfg, market, store).run())


if __name__ == '__main__':
    main()
