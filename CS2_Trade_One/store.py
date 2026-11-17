"""Persistent SQLite record of trading state. Server filesystem must be persistent."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from config import Settings
from strategy import Candidate


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def conn(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=15000')
        try:
            yield db
        finally:
            db.close()

    def init(self):
        with self.conn() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS state (
                  key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                  item_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                  ask_kopecks INTEGER NOT NULL, bid_rub TEXT NOT NULL,
                  profit_rub TEXT NOT NULL, roi_percent TEXT NOT NULL,
                  sales_7d INTEGER NOT NULL, seen_at TEXT NOT NULL,
                  alerted INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS purchases (
                  item_id TEXT PRIMARY KEY, custom_id TEXT UNIQUE NOT NULL,
                  name TEXT NOT NULL, ask_kopecks INTEGER NOT NULL,
                  status TEXT NOT NULL, created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL, response TEXT DEFAULT ''
                );
            ''')
            for key, value in [('scanning', '1'), ('auto', '0'),
                               ('cursor', '0'), ('tg_offset', '0')]:
                db.execute('INSERT OR IGNORE INTO state (key,value) VALUES (?,?)',
                           (key, value))

    def get(self, key: str, default: str = '') -> str:
        with self.conn() as db:
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            return str(row['value']) if row else default

    def set(self, key: str, value: str) -> None:
        with self.conn() as db:
            db.execute('INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, str(value)))

    def save_candidates(self, items: list[Candidate]) -> list[dict]:
        new = []
        with self.conn() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                for item in items:
                    old = db.execute('SELECT item_id FROM candidates WHERE item_id=?',
                                     (item.item_id,)).fetchone()
                    db.execute('''INSERT INTO candidates(item_id,name,ask_kopecks,bid_rub,profit_rub,roi_percent,sales_7d,seen_at)
                        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
                        bid_rub=excluded.bid_rub, profit_rub=excluded.profit_rub,
                        roi_percent=excluded.roi_percent, sales_7d=excluded.sales_7d,
                        seen_at=excluded.seen_at, ask_kopecks=excluded.ask_kopecks''',
                        (item.item_id, item.name, item.ask_kopecks, item.bid_rub,
                         item.profit_rub, item.roi_percent, item.sales_7d, utcnow()))
                    if not old:
                        new.append(item.serialize())
                db.commit()
            except Exception:
                db.rollback()
                raise
        return new

    def mark_alerted(self, item_ids: list[str]):
        with self.conn() as db:
            db.executemany('UPDATE candidates SET alerted=1 WHERE item_id=?',
                           [(i,) for i in item_ids])

    def unalerted(self, limit: int = 5) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        with self.conn() as db:
            rows = db.execute('''SELECT * FROM candidates WHERE alerted=0 AND seen_at>?
                            ORDER BY CAST(profit_rub AS REAL) DESC LIMIT ?''',
                            (cutoff, limit)).fetchall()
            return [dict(r) for r in rows]

    def candidates(self, limit: int = 10) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        with self.conn() as db:
            rows = db.execute('''SELECT c.* FROM candidates c
                LEFT JOIN purchases p ON c.item_id=p.item_id
                WHERE c.seen_at>? AND p.item_id IS NULL
                ORDER BY CAST(c.profit_rub AS REAL) DESC LIMIT ?''',
                (cutoff, limit)).fetchall()
            return [dict(r) for r in rows]

    def candidate(self, item_id: str) -> dict | None:
        with self.conn() as db:
            row = db.execute('SELECT * FROM candidates WHERE item_id=?', (item_id,)).fetchone()
            return dict(row) if row else None

    def positions(self, db) -> tuple[int, Decimal, int]:
        active = db.execute('''SELECT ask_kopecks FROM purchases WHERE
              status IN ('RESERVED','UNKNOWN','ACCEPTED','CONFIRMED')''').fetchall()
        spent = sum((Decimal(row['ask_kopecks']) / 100 for row in active), Decimal(0))
        first = db.execute("SELECT COUNT(*) AS n FROM purchases WHERE status='CONFIRMED'").fetchone()['n']
        return len(active), spent, int(first)

    def overview(self, cfg: Settings) -> dict:
        with self.conn() as db:
            count, spent, first = self.positions(db)
            unknown = db.execute("SELECT COUNT(*) AS n FROM purchases WHERE status IN ('RESERVED','UNKNOWN','ACCEPTED')").fetchone()['n']
            return {'positions': count, 'reserved_rub': spent,
                    'remaining_rub': max(Decimal(0), cfg.budget_rub - spent),
                    'confirmed': first, 'unresolved': int(unknown)}

    def reserve(self, item: dict, cfg: Settings) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        with self.conn() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                fresh = db.execute('SELECT * FROM candidates WHERE item_id=?',
                                   (item['item_id'],)).fetchone()
                if (fresh is None or fresh['seen_at'] < cutoff or
                        fresh['ask_kopecks'] != item['ask_kopecks']):
                    raise RuntimeError('Кандидат устарел; обнови сканирование')
                if db.execute('SELECT 1 FROM purchases WHERE item_id=?',
                              (item['item_id'],)).fetchone():
                    raise RuntimeError('По этому лоту уже была операция')
                count, spent, _ = self.positions(db)
                pending = db.execute("SELECT 1 FROM purchases WHERE status IN ('RESERVED','UNKNOWN','ACCEPTED') LIMIT 1").fetchone()
                if pending:
                    raise RuntimeError('Есть незавершённая покупка; новые блокированы')
                price = Decimal(item['ask_kopecks']) / 100
                if price <= 0 or price > cfg.max_item_rub or price + spent > cfg.budget_rub:
                    raise RuntimeError('Превышен лимит суммы или бюджета')
                if count >= cfg.max_positions:
                    raise RuntimeError('Достигнут лимит позиций')
                custom = uuid4().hex
                now = utcnow()
                db.execute('''INSERT INTO purchases(item_id,custom_id,name,ask_kopecks,status,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?)''',
                           (item['item_id'], custom, item['name'], item['ask_kopecks'],
                            'RESERVED', now, now))
                db.commit()
                return {'item_id': item['item_id'], 'custom_id': custom,
                        'ask_kopecks': item['ask_kopecks'], 'name': item['name']}
            except Exception:
                db.rollback()
                raise

    def update_purchase(self, item_id: str, status: str, response: str = ''):
        if status not in ('RESERVED', 'UNKNOWN', 'ACCEPTED', 'CONFIRMED',
                          'FAILED', 'CANCELLED', 'SIMULATED'):
            raise ValueError('Invalid status')
        with self.conn() as db:
            db.execute('''UPDATE purchases SET status=?,updated_at=?,response=? WHERE item_id=?''',
                       (status, utcnow(), response[:400], item_id))

    def history(self, limit: int = 10) -> list[dict]:
        with self.conn() as db:
            return [dict(row) for row in db.execute('''SELECT * FROM purchases
                ORDER BY created_at DESC LIMIT ?''', (limit,)).fetchall()]

    def unresolved(self) -> list[dict]:
        with self.conn() as db:
            return [dict(row) for row in db.execute('''SELECT * FROM purchases
                WHERE status IN ('RESERVED','UNKNOWN','ACCEPTED')''').fetchall()]
