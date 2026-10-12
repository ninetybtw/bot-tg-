import os
from datetime import datetime, timedelta, timezone

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    ref_id      INTEGER,
    balance     INTEGER NOT NULL DEFAULT 0,
    ref_count   INTEGER NOT NULL DEFAULT 0,
    passed_op   INTEGER NOT NULL DEFAULT 0,
    is_blocked  INTEGER NOT NULL DEFAULT 0,
    last_bonus  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_ref ON users(ref_id);

-- Спонсоры обязательной подписки (ОП)
CREATE TABLE IF NOT EXISTS sponsors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    target      INTEGER NOT NULL DEFAULT 0,  -- 0 = без лимита
    joined      INTEGER NOT NULL DEFAULT 0,  -- сколько подписчиков привёл бот
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

-- Пользователь увидел спонсора, будучи НЕ подписанным
CREATE TABLE IF NOT EXISTS sponsor_pending (
    user_id     INTEGER NOT NULL,
    sponsor_id  INTEGER NOT NULL,
    PRIMARY KEY (user_id, sponsor_id)
);

-- Подписка засчитана спонсору (подписался через бота)
CREATE TABLE IF NOT EXISTS sponsor_joins (
    user_id     INTEGER NOT NULL,
    sponsor_id  INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, sponsor_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if os.path.dirname(self.path):
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _fetchone(self, sql: str, *args):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, *args):
        async with self.conn.execute(sql, args) as cur:
            return await cur.fetchall()

    async def _scalar(self, sql: str, *args) -> int:
        row = await self._fetchone(sql, *args)
        return row[0] if row and row[0] is not None else 0

    async def _write(self, sql: str, *args) -> int:
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur.rowcount

    # ---------- users ----------

    async def add_user(self, user_id: int, username: str | None, first_name: str | None,
                       ref_id: int | None) -> bool:
        if ref_id is not None and (ref_id == user_id or not await self.get_user(ref_id)):
            ref_id = None
        created = await self._write(
            "INSERT OR IGNORE INTO users (id, username, first_name, ref_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            user_id, username, first_name, ref_id, _iso(_now()),
        )
        if not created:
            await self._write(
                "UPDATE users SET username = ?, first_name = ?, is_blocked = 0 WHERE id = ?",
                username, first_name, user_id,
            )
        return bool(created)

    async def get_user(self, user_id: int):
        return await self._fetchone("SELECT * FROM users WHERE id = ?", user_id)

    async def add_balance(self, user_id: int, amount: int) -> bool:
        return bool(await self._write(
            "UPDATE users SET balance = balance + ? WHERE id = ?", amount, user_id
        ))

    async def try_spend(self, user_id: int, amount: int) -> bool:
        return bool(await self._write(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            amount, user_id, amount,
        ))

    async def mark_passed_op(self, user_id: int, start_balance: int) -> bool:
        """Первое прохождение ОП. True ровно один раз на пользователя."""
        return bool(await self._write(
            "UPDATE users SET passed_op = 1, balance = balance + ? "
            "WHERE id = ? AND passed_op = 0",
            start_balance, user_id,
        ))

    async def reward_referrer(self, ref_id: int, amount: int) -> None:
        await self._write(
            "UPDATE users SET balance = balance + ?, ref_count = ref_count + 1 WHERE id = ?",
            amount, ref_id,
        )

    async def claim_bonus(self, user_id: int, amount: int,
                          cooldown: timedelta) -> tuple[bool, timedelta]:
        user = await self.get_user(user_id)
        now = _now()
        if user["last_bonus"]:
            next_at = datetime.fromisoformat(user["last_bonus"]) + cooldown
            if next_at > now:
                return False, next_at - now
        await self._write(
            "UPDATE users SET balance = balance + ?, last_bonus = ? WHERE id = ?",
            amount, _iso(now), user_id,
        )
        return True, timedelta(0)

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        await self._write("UPDATE users SET is_blocked = ? WHERE id = ?", int(blocked), user_id)

    async def active_user_ids(self) -> list[int]:
        rows = await self._fetchall("SELECT id FROM users WHERE is_blocked = 0")
        return [r[0] for r in rows]

    async def top_referrers(self, limit: int = 10):
        return await self._fetchall(
            "SELECT id, username, first_name, ref_count FROM users "
            "WHERE ref_count > 0 ORDER BY ref_count DESC LIMIT ?", limit,
        )

    async def stats(self) -> dict:
        now = _now()
        day_start = _iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
        return {
            "total": await self._scalar("SELECT COUNT(*) FROM users"),
            "alive": await self._scalar("SELECT COUNT(*) FROM users WHERE is_blocked = 0"),
            "passed_op": await self._scalar("SELECT COUNT(*) FROM users WHERE passed_op = 1"),
            "today": await self._scalar(
                "SELECT COUNT(*) FROM users WHERE created_at >= ?", day_start),
            "day": await self._scalar(
                "SELECT COUNT(*) FROM users WHERE created_at >= ?", _iso(now - timedelta(days=1))),
            "week": await self._scalar(
                "SELECT COUNT(*) FROM users WHERE created_at >= ?", _iso(now - timedelta(days=7))),
            "from_refs": await self._scalar("SELECT COUNT(*) FROM users WHERE ref_id IS NOT NULL"),
        }

    # ---------- sponsors ----------

    async def add_sponsor(self, chat_id: int, title: str, url: str, target: int) -> None:
        await self._write(
            "INSERT INTO sponsors (chat_id, title, url, target, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, url = excluded.url, "
            "target = excluded.target, joined = 0, active = 1",
            chat_id, title, url, target, _iso(_now()),
        )

    async def get_sponsors(self, active_only: bool = False):
        sql = "SELECT * FROM sponsors"
        if active_only:
            sql += " WHERE active = 1"
        return await self._fetchall(sql + " ORDER BY id")

    async def get_sponsor(self, sponsor_id: int):
        return await self._fetchone("SELECT * FROM sponsors WHERE id = ?", sponsor_id)

    async def toggle_sponsor(self, sponsor_id: int) -> None:
        await self._write("UPDATE sponsors SET active = 1 - active WHERE id = ?", sponsor_id)

    async def delete_sponsor(self, sponsor_id: int) -> None:
        await self._write("DELETE FROM sponsors WHERE id = ?", sponsor_id)
        await self._write("DELETE FROM sponsor_pending WHERE sponsor_id = ?", sponsor_id)
        await self._write("DELETE FROM sponsor_joins WHERE sponsor_id = ?", sponsor_id)

    async def mark_pending(self, user_id: int, sponsor_ids: list[int]) -> None:
        await self.conn.executemany(
            "INSERT OR IGNORE INTO sponsor_pending (user_id, sponsor_id) VALUES (?, ?)",
            [(user_id, sid) for sid in sponsor_ids],
        )
        await self.conn.commit()

    async def register_joins(self, user_id: int, sponsor_ids: list[int]) -> list:
        """Засчитывает подписки, сделанные через бота. Возвращает спонсоров,
        которые только что выполнили заказ (и были отключены)."""
        finished = []
        for sid in sponsor_ids:
            if not await self._fetchone(
                "SELECT 1 FROM sponsor_pending WHERE user_id = ? AND sponsor_id = ?", user_id, sid
            ):
                continue  # был подписан ещё до бота — не засчитываем
            inserted = await self._write(
                "INSERT OR IGNORE INTO sponsor_joins (user_id, sponsor_id, created_at) "
                "VALUES (?, ?, ?)", user_id, sid, _iso(_now()),
            )
            if not inserted:
                continue
            await self._write("UPDATE sponsors SET joined = joined + 1 WHERE id = ?", sid)
            done = await self._write(
                "UPDATE sponsors SET active = 0 "
                "WHERE id = ? AND active = 1 AND target > 0 AND joined >= target", sid,
            )
            if done:
                finished.append(await self.get_sponsor(sid))
        return finished

    # ---------- settings ----------

    async def get_setting(self, key: str) -> str | None:
        row = await self._fetchone("SELECT value FROM settings WHERE key = ?", key)
        return row[0] if row else None

    async def set_setting(self, key: str, value: str | None) -> None:
        if value is None:
            await self._write("DELETE FROM settings WHERE key = ?", key)
        else:
            await self._write(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, value,
            )
