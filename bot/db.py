import asyncio
import os
from contextlib import asynccontextmanager

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    ref_id          INTEGER,
    ref_qualified   INTEGER NOT NULL DEFAULT 0,  -- друг сделал нужное число спинов
    ref_count       INTEGER NOT NULL DEFAULT 0,  -- сколько засчитанных друзей
    created_at      REAL NOT NULL,
    last_seen       REAL,
    coins           INTEGER NOT NULL DEFAULT 0,
    spins           INTEGER NOT NULL DEFAULT 0,  -- запас попыток (рефералы, колесо, покупки)
    energy          INTEGER NOT NULL DEFAULT 0,
    energy_ts       REAL NOT NULL DEFAULT 0,
    energy_notify   INTEGER NOT NULL DEFAULT 0,
    xp              INTEGER NOT NULL DEFAULT 0,
    total_spins     INTEGER NOT NULL DEFAULT 0,
    pity_epic       INTEGER NOT NULL DEFAULT 0,
    pity_legendary  INTEGER NOT NULL DEFAULT 0,
    luck_mult       REAL NOT NULL DEFAULT 1,
    luck_left       INTEGER NOT NULL DEFAULT 0,
    upgrade_bonus   REAL NOT NULL DEFAULT 0,
    gift_day        TEXT,
    gift_streak     INTEGER NOT NULL DEFAULT 0,
    country         TEXT NOT NULL DEFAULT 'RU',
    settings        TEXT NOT NULL DEFAULT '{}',
    badges          TEXT NOT NULL DEFAULT '[]',
    is_blocked      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_users_ref ON users(ref_id);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    country     TEXT NOT NULL,
    op          TEXT NOT NULL,
    sub         TEXT NOT NULL,
    tier        INTEGER NOT NULL,
    price       INTEGER NOT NULL,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'owned',   -- owned | listed | gone
    is_new      INTEGER NOT NULL DEFAULT 1,
    favorite    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id, status);

-- Каждый дроп с зерном генератора и версией шансов — для разбора споров
CREATE TABLE IF NOT EXISTS drops (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    item_id      INTEGER NOT NULL,
    tier         INTEGER NOT NULL,
    scale        TEXT NOT NULL,
    luck         REAL NOT NULL,
    seed         TEXT NOT NULL,
    odds_version INTEGER NOT NULL,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drops_time ON drops(created_at);

CREATE TABLE IF NOT EXISTS ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    currency    TEXT NOT NULL,      -- coins | spins
    delta       INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON ledger(user_id, id);

CREATE TABLE IF NOT EXISTS lots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL,
    seller_id   INTEGER NOT NULL,
    price       INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',  -- active | sold | cancelled | expired
    buyer_id    INTEGER,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    closed_at   REAL
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

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


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
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    @asynccontextmanager
    async def tx(self):
        """Все изменения игры идут через одну очередь: защищает от двойных
        нажатий и гонок (двойной спин, двойная покупка лота)."""
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
