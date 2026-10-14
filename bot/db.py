import asyncio
import os
from contextlib import asynccontextmanager

import aiosqlite

# Деньги — целые копейки игрового рубля (*_cents). ledger и drops только дописываются.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY,
    username           TEXT,
    first_name         TEXT,
    language_code      TEXT,
    ref_id             INTEGER,
    ref_qualified      INTEGER NOT NULL DEFAULT 0,
    ref_count          INTEGER NOT NULL DEFAULT 0,
    created_at         REAL NOT NULL,
    last_seen          REAL,
    balance_cents      INTEGER NOT NULL DEFAULT 0,
    attempts           INTEGER NOT NULL DEFAULT 0,
    energy             INTEGER NOT NULL DEFAULT 0,
    energy_ts          REAL NOT NULL DEFAULT 0,
    energy_notify      INTEGER NOT NULL DEFAULT 0,
    xp                 INTEGER NOT NULL DEFAULT 0,
    total_spins        INTEGER NOT NULL DEFAULT 0,
    pity_epic          INTEGER NOT NULL DEFAULT 0,
    pity_legend        INTEGER NOT NULL DEFAULT 0,
    luck_mult          REAL NOT NULL DEFAULT 1,
    luck_left          INTEGER NOT NULL DEFAULT 0,
    upgrade_bonus      REAL NOT NULL DEFAULT 0,
    gift_day           TEXT,
    gift_streak        INTEGER NOT NULL DEFAULT 0,
    country            TEXT NOT NULL DEFAULT 'RU',
    country_confirmed  INTEGER NOT NULL DEFAULT 0,
    country_changed_at REAL,
    settings           TEXT NOT NULL DEFAULT '{}',
    badges             TEXT NOT NULL DEFAULT '[]',
    showcase           TEXT NOT NULL DEFAULT '[]',
    slots_extra        INTEGER NOT NULL DEFAULT 0,
    slots_bought       INTEGER NOT NULL DEFAULT 0,
    vip_until          REAL,
    vip_day            TEXT,
    starter_used       INTEGER NOT NULL DEFAULT 0,
    start_pack         INTEGER NOT NULL DEFAULT 0,
    is_blocked         INTEGER NOT NULL DEFAULT 0,
    region             TEXT,                       -- страна номеров (меняется в любой момент), пусто — как country
    boost_min_tier     INTEGER                     -- подкрутка админа: следующий дроп не ниже этой ступени
);
CREATE INDEX IF NOT EXISTS idx_users_ref ON users(ref_id);

-- Пары зёрен «обещание и раскрытие»: одна активная на игрока
CREATE TABLE IF NOT EXISTS seeds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    server_seed  TEXT NOT NULL,
    server_hash  TEXT NOT NULL,
    client_seed  TEXT NOT NULL,
    nonce        INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   REAL NOT NULL,
    revealed_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_seeds_user ON seeds(user_id, active);

CREATE TABLE IF NOT EXISTS items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    country        TEXT NOT NULL,
    op             TEXT NOT NULL,
    sub            TEXT NOT NULL,
    number_key     TEXT NOT NULL,
    tier           INTEGER NOT NULL,
    rule           TEXT NOT NULL,
    highlight      TEXT NOT NULL DEFAULT '[]',
    got_price_cents INTEGER NOT NULL,
    source         TEXT NOT NULL,
    state          TEXT NOT NULL DEFAULT 'free',  -- free | listed | overflow | gone
    gone_reason    TEXT,
    locked         INTEGER NOT NULL DEFAULT 0,
    favorite       INTEGER NOT NULL DEFAULT 0,
    is_new         INTEGER NOT NULL DEFAULT 1,
    serial_no      INTEGER NOT NULL DEFAULT 1,
    edition_size   INTEGER NOT NULL DEFAULT 1,
    hold_until     REAL,
    overflow_until REAL,
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id, state);
CREATE INDEX IF NOT EXISTS idx_items_key ON items(number_key);

-- Тиражи: ниже Легендарного каждый номер в одном экземпляре
CREATE TABLE IF NOT EXISTS editions (
    number_key TEXT PRIMARY KEY,
    tier       INTEGER NOT NULL,
    size       INTEGER NOT NULL,
    issued     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS drops (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    item_id       INTEGER NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'number',  -- number | device
    action        TEXT NOT NULL,      -- spin | contract | upgrade | wheel | raffle
    level         TEXT,
    tier          INTEGER NOT NULL,
    odds_json     TEXT NOT NULL,
    u0            REAL NOT NULL,
    seed_id       INTEGER,
    server_hash   TEXT,
    client_seed   TEXT,
    nonce         INTEGER,
    luck          REAL NOT NULL DEFAULT 1,
    pity_epic     INTEGER,
    pity_legend   INTEGER,
    odds_version  INTEGER NOT NULL,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drops_user ON drops(user_id, id);
CREATE INDEX IF NOT EXISTS idx_drops_tier ON drops(tier, id);

CREATE TABLE IF NOT EXISTS ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    currency    TEXT NOT NULL,      -- rub | attempts
    delta       INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, id);
CREATE INDEX IF NOT EXISTS idx_ledger_time ON ledger(created_at);

CREATE TABLE IF NOT EXISTS sales (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    item_ids      TEXT NOT NULL,
    amount_cents  INTEGER NOT NULL,
    created_at    REAL NOT NULL,
    undo_until    REAL NOT NULL,
    undone        INTEGER NOT NULL DEFAULT 0,
    kind          TEXT NOT NULL DEFAULT 'number'
);

-- Телефоны из кейса «Телефоны»: модель из каталога bot/game/devices.py
CREATE TABLE IF NOT EXISTS devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    model       TEXT NOT NULL,
    tier        INTEGER NOT NULL,
    price_cents INTEGER NOT NULL,
    source      TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'free',   -- free | gone
    gone_reason TEXT,
    locked      INTEGER NOT NULL DEFAULT 0,
    is_new      INTEGER NOT NULL DEFAULT 1,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id, state);

CREATE TABLE IF NOT EXISTS lots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      INTEGER NOT NULL,
    seller_id    INTEGER NOT NULL,
    price_cents  INTEGER NOT NULL,
    fee_cents    INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'active',
    buyer_id     INTEGER,
    created_at   REAL NOT NULL,
    expires_at   REAL NOT NULL,
    closed_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_lots_status ON lots(status);

CREATE TABLE IF NOT EXISTS counters (
    user_id INTEGER NOT NULL,
    day     TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, key)
);

CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    product     TEXT NOT NULL,
    stars       INTEGER NOT NULL,
    charge_id   TEXT NOT NULL UNIQUE,
    refunded    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    user_id     INTEGER NOT NULL,
    key         TEXT NOT NULL,
    path        TEXT NOT NULL,
    status      INTEGER NOT NULL,
    response    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS raffles (
    day          TEXT PRIMARY KEY,
    server_seed  TEXT NOT NULL,
    server_hash  TEXT NOT NULL,
    drawn        INTEGER NOT NULL DEFAULT 0,
    winners      TEXT NOT NULL DEFAULT '[]',
    drawn_at     REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TRIGGER IF NOT EXISTS ledger_append_only_u BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger только дописывается'); END;
CREATE TRIGGER IF NOT EXISTS ledger_append_only_d BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger только дописывается'); END;
CREATE TRIGGER IF NOT EXISTS drops_append_only_u BEFORE UPDATE ON drops
BEGIN SELECT RAISE(ABORT, 'drops только дописывается'); END;
CREATE TRIGGER IF NOT EXISTS drops_append_only_d BEFORE DELETE ON drops
BEGIN SELECT RAISE(ABORT, 'drops только дописывается'); END;
"""

# Колонки, добавленные после первого запуска: старые базы получают их через ALTER TABLE
MIGRATIONS = [
    ("users", "region", "TEXT"),
    ("users", "boost_min_tier", "INTEGER"),
    ("drops", "kind", "TEXT NOT NULL DEFAULT 'number'"),
    ("sales", "kind", "TEXT NOT NULL DEFAULT 'number'"),
]


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.path != ":memory:" and os.path.dirname(self.path):
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        conn = aiosqlite.connect(self.path)
        conn.daemon = True  # поток базы не держит процесс при аварийной остановке
        self.conn = await conn
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.executescript(SCHEMA)
        for table, column, decl in MIGRATIONS:
            cols = {r[1] for r in await self.all(f"PRAGMA table_info({table})")}
            if column not in cols:
                await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    @asynccontextmanager
    async def tx(self):
        """Все изменения игры идут через одну очередь — это аналог SELECT … FOR UPDATE:
        двойной тап и параллельные запросы не создают лишних дропов и не уводят баланс в минус."""
        async with self.lock:
            try:
                yield self
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise

    async def one(self, sql: str, *args):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchone()

    async def all(self, sql: str, *args):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchall()

    async def val(self, sql: str, *args):
        row = await self.one(sql, *args)
        return row[0] if row and row[0] is not None else 0

    async def run(self, sql: str, *args) -> aiosqlite.Cursor:
        return await self.conn.execute(sql, args)

    async def get_setting(self, key: str) -> str | None:
        row = await self.one("SELECT value FROM settings WHERE key = ?", key)
        return row[0] if row else None

    async def set_setting(self, key: str, value: str | None) -> None:
        async with self.tx():
            if value is None:
                await self.run("DELETE FROM settings WHERE key = ?", key)
            else:
                await self.run(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, value)
