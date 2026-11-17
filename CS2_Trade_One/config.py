"""Unified CS2 trading bot configuration. Never commit .env credentials."""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


def dotenv(path: Path = Path('.env')) -> None:
    # The local .env is convenient for server installs; real environment wins.
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key.isidentifier():
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def yes(value: str) -> bool:
    return value.strip().lower() in {'true', '1', 'yes', 'on'}


@dataclass(frozen=True)
class Settings:
    market_key: str
    telegram_token: str
    owner_id: int
    db_path: Path
    scope: str = 'watchlist'
    scan_every_s: int = 300
    batch_size: int = 20
    request_delay_s: float = 0.5
    budget_rub: Decimal = Decimal('3000')
    max_item_rub: Decimal = Decimal('500')
    min_item_rub: Decimal = Decimal('50')
    min_profit_rub: Decimal = Decimal('50')
    min_roi_percent: Decimal = Decimal('10')
    min_sales_7d: int = 20
    sell_fee: Decimal = Decimal('0.10')
    max_positions: int = 3
    dry_run: bool = True
    live_enabled: bool = False
    enable_auto_after_first: bool = False
    live_ack: str = ''
    price_min_bid_ask_ratio: Decimal = Decimal('1.12')

    @property
    def live_ready(self) -> bool:
        return (not self.dry_run and self.live_enabled and
                self.live_ack == 'I_ACCEPT_REAL_MONEY_RISK')

    @staticmethod
    def load() -> 'Settings':
        dotenv()
        base = Path(__file__).resolve().parent
        def dec(name: str, default: str) -> Decimal:
            return Decimal(os.getenv(name, default))
        c = Settings(
            market_key=os.getenv('MARKET_CSGO_API_KEY', '').strip(),
            telegram_token=os.getenv('TELEGRAM_BOT_TOKEN', '').strip(),
            owner_id=int(os.getenv('TELEGRAM_OWNER_ID', '0')),
            db_path=Path(os.getenv('DB_PATH', str(base/'data'/'state.sqlite3'))),
            scope=os.getenv('SCAN_SCOPE', 'watchlist').strip().lower(),
            scan_every_s=int(os.getenv('SCAN_EVERY_SECONDS', '300')),
            batch_size=int(os.getenv('BATCH_SIZE', '20')),
            request_delay_s=float(os.getenv('REQUEST_DELAY_SECONDS', '0.5')),
            budget_rub=dec('BUDGET_RUB', '3000'),
            max_item_rub=dec('MAX_ITEM_RUB', '500'),
            min_item_rub=dec('MIN_ITEM_RUB', '50'),
            min_profit_rub=dec('MIN_PROFIT_RUB', '50'),
            min_roi_percent=dec('MIN_ROI_PERCENT', '10'),
            min_sales_7d=int(os.getenv('MIN_SALES_7D', '20')),
            sell_fee=dec('SELL_FEE', '0.10'),
            max_positions=int(os.getenv('MAX_POSITIONS', '3')),
            dry_run=yes(os.getenv('DRY_RUN', 'true')),
            live_enabled=yes(os.getenv('LIVE_TRADING_ENABLED', 'false')),
            enable_auto_after_first=yes(os.getenv('AUTO_BUY_AFTER_FIRST', 'false')),
            live_ack=os.getenv('LIVE_TRADE_ACK', ''),
        )
        if c.scope not in ('watchlist', 'catalog'):
            raise ValueError('SCAN_SCOPE must be watchlist or catalog')
        if not 30 <= c.scan_every_s <= 86400 or not 1 <= c.batch_size <= 100:
            raise ValueError('Invalid scan interval or batch size')
        if c.owner_id <= 0 or c.request_delay_s < .35 or c.max_positions < 1:
            raise ValueError('Invalid owner ID, request delay or positions')
        if not (Decimal('0') <= c.sell_fee < Decimal('1')):
            raise ValueError('Invalid fee')
        if not (0 < c.min_item_rub <= c.max_item_rub <= c.budget_rub):
            raise ValueError('Invalid price/budget bounds')
        if c.min_profit_rub <= 0 or c.min_roi_percent <= 0 or c.min_sales_7d < 1:
            raise ValueError('Invalid strategy thresholds')
        return c
