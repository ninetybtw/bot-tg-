"""Игровая логика «Номера телефонов» v1.4. Всё решает сервер, клиент только показывает результат.

Деньги — целые копейки игрового рубля. Каждое изменение баланса пишется в ledger,
каждое действие — в одной транзакции (db.tx), дроп сохраняется до ответа клиенту.
"""
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from bot.db import Database
from bot.game import fair, phones
from bot.game.odds import pity_chances, with_pity
from bot.game.settings import DEFAULTS, fmt_money, level, level_from_xp, merge, normalize, validate
from bot.game.tiers import EPIC, LEGENDARY, RARE, SECRET, TIERS, apply_luck, one_in, tier_dict

MSK = timezone(timedelta(hours=3))
SETTINGS_KEYS = {"fast": False, "no_effects": False, "no_upgrader": False}
CLIENT_SEED_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")


class GameError(Exception):
    def __init__(self, message: str, code: str = "BAD_REQUEST", **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra


def day_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, MSK).strftime("%Y-%m-%d")


def week_key(ts: float) -> str:
    y, w, _ = datetime.fromtimestamp(ts, MSK).isocalendar()
    return f"W{y}-{w:02d}"


def month_start(ts: float) -> float:
    return datetime.fromtimestamp(ts, MSK).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def day_start(ts: float) -> float:
    return datetime.fromtimestamp(ts, MSK).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class Game:
    def __init__(self, db: Database, stars_enabled: bool = False, clock=time.time):
        self.db = db
        self.cfg = normalize(merge(DEFAULTS, {}))
        self.stars_enabled = stars_enabled
        self.clock = clock
        self.outbox: list[tuple[int, str]] = []
        self.ad: dict | None = None

    # ---------- конфиг ----------

    async def load_config(self) -> None:
        raw = await self.db.get_setting("game_config")
        self.cfg = normalize(merge(DEFAULTS, json.loads(raw) if raw else {}))
        ad = await self.db.get_setting("ad")
        self.ad = json.loads(ad) if ad else None

    async def save_config(self, override: dict) -> list[str]:
        cfg = normalize(merge(DEFAULTS, override))
        errors = validate(cfg)
        if errors:
            return errors
        await self.db.set_setting("game_config", json.dumps(override, ensure_ascii=False))
        self.cfg = cfg
        return []

    @property
    def divine(self) -> tuple:
        return tuple(tuple(x) for x in self.cfg["divine"])

    def public_config(self) -> dict:
        c = self.cfg
        common = level(c, "common")
        levels = []
        for lv in c["levels"]:
            goal_p = sum(p for t, p in lv["odds"].items() if t >= lv["goal"]["tier"])
            levels.append({
                "key": lv["key"], "name": lv["name"], "price_cents": lv["price_cents"], "pity": lv["pity"],
                "min_tier": min(lv["odds"]), "goal": {**lv["goal"], "p": goal_p},
                "odds": [{"tier": t, "p": p} for t, p in sorted(lv["odds"].items())],
            })
        return {
            "odds_version": c["odds_version"],
            "tiers": [tier_dict(t.idx) for t in TIERS],
            "ladder_cents": c["ladder_cents"],
            "sell_system_pct": c["sell_system_pct"],
            "levels": levels,
            "counts": c["counts"],
            "confirm_from_cents": c["confirm_from_cents"],
            "confirm_balance_share": c["confirm_balance_share"],
            "pity": c["pity"],
            "one_in": {t: one_in(p) for t, p in common["odds"].items()},
            "currency": c["currency"],
            "wheel_daily": [{"label": s["label"], "p": s["p"]} for s in c["wheel_daily"]],
            "wheel_weekly": [{"label": s["label"], "p": s["p"]} for s in c["wheel_weekly"]["sectors"]],
            "gift": c["gift"],
            "editions": c["editions"],
            "contracts": c["contracts"],
            "upgrader": c["upgrader"],
            "market": c["market"],
            "inventory": c["inventory"],
            "rules": phones.RULES,
            "number_masks": {k: phones.format_number(k, "•" * len(c.operators[0]), "•" * phones.TAIL)
                             for k, c in phones.COUNTRIES.items()},
            "stars_enabled": self.stars_enabled,
        }

    def pop_outbox(self) -> list[tuple[int, str]]:
        out, self.outbox = self.outbox, []
        return out

    # ---------- помощники (внутри db.tx) ----------

    def country_of(self, u: dict) -> dict:
        return self.cfg["currency"]["countries"].get(u["country"]) or self.cfg["currency"]["countries"]["RU"]

    def money(self, cents: int, u: dict) -> str:
        return fmt_money(cents, self.country_of(u))

    async def _user(self, uid: int) -> dict:
        row = await self.db.one("SELECT * FROM users WHERE id = ?", uid)
        if not row:
            raise GameError("Сначала открой игру через бота", "UNAUTHORIZED")
        return dict(row)

    async def _ledger(self, uid: int, currency: str, delta: int, reason: str) -> None:
        if delta:
            await self.db.run("INSERT INTO ledger (user_id, currency, delta, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                              uid, currency, delta, reason, self.clock())

    async def _add(self, uid: int, cents: int = 0, attempts: int = 0, reason: str = "") -> None:
        if cents or attempts:
            await self.db.run("UPDATE users SET balance_cents = balance_cents + ?, attempts = attempts + ? WHERE id = ?",
                              cents, attempts, uid)
            await self._ledger(uid, "rub", cents, reason)
            await self._ledger(uid, "attempts", attempts, reason)

    async def _counter(self, uid: int, key: str, inc: int = 0, day: str | None = None) -> int:
        day = day or day_key(self.clock())
        if inc:
            await self.db.run(
                "INSERT INTO counters (user_id, day, key, value) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, day, key) DO UPDATE SET value = value + excluded.value", uid, day, key, inc)
        return await self.db.val("SELECT value FROM counters WHERE user_id = ? AND day = ? AND key = ?", uid, day, key)

    def _energy(self, u: dict) -> tuple[int, float]:
        mx, period = self.cfg["energy"]["max"], self.cfg["energy"]["regen_minutes"] * 60
        now = self.clock()
        e, ts = u["energy"], u["energy_ts"]
        if e >= mx:
            return e, now
        gained = int((now - ts) // period)
        if gained <= 0:
            return e, ts
        e = min(mx, e + gained)
        return e, (now if e >= mx else ts + gained * period)

    def _vip(self, u: dict) -> bool:
        return bool(u["vip_until"] and u["vip_until"] > self.clock())

    def _capacity(self, u: dict) -> int:
        inv = self.cfg["inventory"]
        extra = u["slots_extra"] + (self.cfg["shop"]["vip_slots"] if self._vip(u) else 0)
        return min(inv["slots_max"], inv["slots"] + extra)

    def _coin_cap(self, u: dict) -> int:
        cs = self.cfg["coin_spins"]
        return min(cs["per_day_max"], cs["per_day_base"] + cs["per_level"] * (level_from_xp(u["xp"])[0] - 1))

    def _today_tasks(self, ts: float) -> list[dict]:
        import random as _r
        pool = self.cfg["tasks"]
        return _r.Random(day_key(ts)).sample(pool, min(self.cfg["tasks_per_day"], len(pool)))

    async def _task_event(self, uid: int, event: str, n: int = 1) -> None:
        now = self.clock()
        for t in self._today_tasks(now):
            if t["event"] == event:
                await self._counter(uid, "task:" + t["key"], n)
        for t in self.cfg["weekly_tasks"]:
            if t["event"] == event:
                await self._counter(uid, "wtask:" + t["key"], n, week_key(now))

    async def notify(self, uid: int, text: str, force: bool = False) -> None:
        """Не чаще 2 уведомлений в сутки и не с 21:00 до 8:00 по Москве (force — ответы на действия игрока)."""
        if not force:
            hour = datetime.fromtimestamp(self.clock(), MSK).hour
            if hour >= 21 or hour < 8 or await self._counter(uid, "notify") >= 2:
                return
            await self._counter(uid, "notify", 1)
        self.outbox.append((uid, text))

    async def _seed_pair(self, uid: int) -> dict:
        row = await self.db.one("SELECT * FROM seeds WHERE user_id = ? AND active = 1", uid)
        if row:
            return dict(row)
        server = fair.new_server_seed()
        cur = await self.db.run(
            "INSERT INTO seeds (user_id, server_seed, server_hash, client_seed, created_at) VALUES (?, ?, ?, ?, ?)",
            uid, server, fair.seed_hash(server), fair.new_client_seed(), self.clock())
        return dict(await self.db.one("SELECT * FROM seeds WHERE id = ?", cur.lastrowid))

    async def _next_nonce(self, pair: dict) -> int:
        pair["nonce"] += 1
        await self.db.run("UPDATE seeds SET nonce = ? WHERE id = ?", pair["nonce"], pair["id"])
        return pair["nonce"]

    async def _slots(self, u: dict) -> dict:
        used = await self.db.val("SELECT COUNT(*) FROM items WHERE user_id = ? AND state IN ('free', 'listed')", u["id"])
        overflow = await self.db.val("SELECT COUNT(*) FROM items WHERE user_id = ? AND state = 'overflow'", u["id"])
        return {"used": used, "total": self._capacity(u), "overflow": overflow,
                "overflow_max": self.cfg["inventory"]["overflow_slots"]}

    async def _promote_overflow(self, u: dict) -> None:
        """Освободилось место — предметы из переполнения переезжают в коллекцию."""
        slots = await self._slots(u)
        free = slots["total"] - slots["used"]
        if free > 0 and slots["overflow"]:
            await self.db.run(
                "UPDATE items SET state = 'free', overflow_until = NULL WHERE id IN (SELECT id FROM items "
                "WHERE user_id = ? AND state = 'overflow' ORDER BY id LIMIT ?)", u["id"], free)

    async def _place(self, u: dict, n: int) -> list[str]:
        """Куда положить n новых предметов: в коллекцию или в переполнение. Иначе INVENTORY_FULL."""
        slots = await self._slots(u)
        free = max(0, slots["total"] - slots["used"])
        over = max(0, slots["overflow_max"] - slots["overflow"])
        if n > free + over:
            raise GameError("Нет места: освободи коллекцию — продай лишнее или выставь на рынок", "INVENTORY_FULL")
        return ["free"] * min(n, free) + ["overflow"] * (n - min(n, free))

    async def _issue(self, uid: int, tier: int, rng, source: str, place: str = "free",
                     country: str | None = None) -> dict:
        """Собрать номер ступени tier и выдать экземпляр тиража. Номер — из страны игрока."""
        size = int(self.cfg["editions"].get(str(tier), 1))
        country = country or await self.db.val("SELECT country FROM users WHERE id = ?", uid)
        for _ in range(200):
            code, op, sub, rule, hl = phones.generate(tier, rng, country, self.cfg["number_country_weights"],
                                                      self.divine)
            key = phones.number_key(code, op, sub)
            row = await self.db.one("SELECT issued, size FROM editions WHERE number_key = ?", key)
            if row and row["issued"] >= row["size"]:
                continue  # тираж закрыт — собираем другой номер
            if row:
                await self.db.run("UPDATE editions SET issued = issued + 1 WHERE number_key = ?", key)
                serial = row["issued"] + 1
            else:
                await self.db.run("INSERT INTO editions (number_key, tier, size, issued) VALUES (?, ?, ?, 1)",
                                  key, tier, size)
                serial = 1
            now = self.clock()
            cur = await self.db.run(
                "INSERT INTO items (user_id, country, op, sub, number_key, tier, rule, highlight, got_price_cents, "
                "source, state, serial_no, edition_size, overflow_until, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                uid, code, op, sub, key, tier, rule, json.dumps(hl), self.cfg["ladder_cents"][tier], source, place,
                serial, size,
                now + self.cfg["inventory"]["overflow_hours"] * 3600 if place == "overflow" else None, now)
            return await self._item(cur.lastrowid)
        raise GameError("Тираж этой ступени закончился. Попробуй позже", "CONFLICT")

    async def _item(self, item_id: int) -> dict:
        row = await self.db.one("SELECT * FROM items WHERE id = ?", item_id)
        return (await self._views([row]))[0]

    async def _views(self, rows) -> list[dict]:
        keys = list({r["number_key"] for r in rows if r["edition_size"] > 1})
        in_game = {}
        if keys:
            marks = ",".join("?" * len(keys))
            for r in await self.db.all(f"SELECT number_key, COUNT(*) FROM items WHERE state != 'gone' "
                                       f"AND number_key IN ({marks}) GROUP BY number_key", *keys):
                in_game[r[0]] = r[1]
        out = []
        common = level(self.cfg, "common")["odds"]
        for r in rows:
            c = phones.COUNTRIES[r["country"]]
            price = self.cfg["ladder_cents"][r["tier"]]
            out.append({
                "id": r["id"], "user_id": r["user_id"], "country": r["country"], "flag": c.flag,
                "country_name": c.name, "dial": c.dial, "op": r["op"], "sub": r["sub"],
                "number": phones.format_number(r["country"], r["op"], r["sub"]),
                "tier": tier_dict(r["tier"]), "rule": r["rule"], "rule_name": phones.RULES[r["rule"]],
                "highlight": json.loads(r["highlight"]),
                "price_cents": price, "got_price_cents": r["got_price_cents"],
                "sell_cents": price * self.cfg["sell_system_pct"] // 100,
                "one_in": one_in(common[r["tier"]]) if r["tier"] in common else None,
                "copy": {"no": r["serial_no"], "of": r["edition_size"],
                         "in_game": in_game.get(r["number_key"], 1)} if r["edition_size"] > 1 else None,
                "state": r["state"], "locked": bool(r["locked"]), "favorite": bool(r["favorite"]),
                "is_new": bool(r["is_new"]), "source": r["source"], "created_at": r["created_at"],
                "hold_until": r["hold_until"] if r["hold_until"] and r["hold_until"] > self.clock() else None,
                "overflow_until": r["overflow_until"],
            })
        return out

    async def _owned(self, uid: int, ids: list[int], states=("free",)) -> list[dict]:
        ids = list(dict.fromkeys(int(i) for i in ids))
        if not ids:
            raise GameError("Ничего не выбрано")
        marks = ",".join("?" * len(ids))
        st = ",".join("?" * len(states))
        rows = await self.db.all(f"SELECT * FROM items WHERE user_id = ? AND id IN ({marks}) AND state IN ({st})",
                                 uid, *ids, *states)
        if len(rows) != len(ids):
            busy = await self.db.val(f"SELECT COUNT(*) FROM items WHERE user_id = ? AND id IN ({marks}) "
                                     f"AND state = 'listed'", uid, *ids)
            if busy:
                raise GameError("Номер выставлен на рынке. Сначала сними лот", "ITEM_BUSY")
            raise GameError("Часть номеров уже недоступна. Обнови коллекцию", "CONFLICT")
        return [dict(r) for r in rows]

    async def _collection_value(self, uid: int) -> int:
        rows = await self.db.all("SELECT tier, COUNT(*) FROM items WHERE user_id = ? AND state != 'gone' GROUP BY tier",
                                 uid)
        return sum(self.cfg["ladder_cents"][r[0]] * r[1] for r in rows)

    async def _reward_referrer(self, ref_id: int, friend: str) -> None:
        await self.db.run("UPDATE users SET ref_count = ref_count + 1 WHERE id = ?", ref_id)
        ref = await self._user(ref_id)
        text = f"🎉 {friend} сделал {self.cfg['referral']['required_spins']} спинов — друг засчитан!"
        for t in self.cfg["referral"]["tiers"]:
            if t["count"] == ref["ref_count"]:
                await self._add(ref_id, t.get("cents", 0), t.get("attempts", 0), "referral")
                if t.get("badge"):
                    await self._badge(ref, t["badge"])
                text += f"\nНаграда за {t['count']}: {t['title']}"
        await self.notify(ref_id, text)

    async def _badge(self, u: dict, badge: str) -> None:
        badges = json.loads(u["badges"])
        if badge not in badges:
            badges.append(badge)
            await self.db.run("UPDATE users SET badges = ? WHERE id = ?", json.dumps(badges, ensure_ascii=False), u["id"])
            u["badges"] = json.dumps(badges, ensure_ascii=False)

    async def _daily_vip(self, u: dict) -> None:
        today = day_key(self.clock())
        if self._vip(u) and u["vip_day"] != today:
            await self.db.run("UPDATE users SET vip_day = ? WHERE id = ?", today, u["id"])
            await self._add(u["id"], attempts=self.cfg["shop"]["vip_daily_attempts"], reason="vip_daily")
            u["vip_day"] = today
            u["attempts"] += self.cfg["shop"]["vip_daily_attempts"]

    # ---------- игрок ----------

    async def ensure_user(self, uid: int, username: str | None, first_name: str | None,
                          language_code: str | None = None, ref_id: int | None = None) -> bool:
        async with self.db.tx():
            now = self.clock()
            if await self.db.one("SELECT 1 FROM users WHERE id = ?", uid):
                await self.db.run("UPDATE users SET username = ?, first_name = ?, last_seen = ?, is_blocked = 0 "
                                  "WHERE id = ?", username, first_name, now, uid)
                return False
            if ref_id is not None:
                ok = ref_id != uid and await self.db.one("SELECT 1 FROM users WHERE id = ?", ref_id)
                if not ok or await self._counter(ref_id, "ref_invites") >= self.cfg["referral"]["daily_limit"]:
                    ref_id = None
            country = self.cfg["currency"]["by_language"].get((language_code or "")[:2], "RU")
            await self.db.run(
                "INSERT INTO users (id, username, first_name, language_code, ref_id, created_at, last_seen, "
                "balance_cents, energy, energy_ts, country) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                uid, username, first_name, language_code, ref_id, now, now, self.cfg["start_cents"],
                self.cfg["energy"]["max"], now, country)
            await self._ledger(uid, "rub", self.cfg["start_cents"], "start")
            if ref_id:
                await self._counter(ref_id, "ref_invites", 1)
                await self._add(uid, attempts=self.cfg["referral"]["friend_attempts"], reason="invited")
            await self._seed_pair(uid)
            return True

    async def me(self, uid: int) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            await self._daily_vip(u)
            await self._promote_overflow(u)
        now = self.clock()
        e, ets = self._energy(u)
        lvl, xp_in, need = level_from_xp(u["xp"])
        mx = self.cfg["energy"]["max"]
        today, yesterday = day_key(now), day_key(now - 86400)
        week = week_key(now)
        tasks = []
        for t in self._today_tasks(now):
            tasks.append({"key": t["key"], "title": t["title"], "target": t["target"], "cents": t["cents"],
                          "progress": min(await self._counter(uid, "task:" + t["key"]), t["target"]),
                          "claimed": bool(await self._counter(uid, "claimed:" + t["key"]))})
        weekly = []
        for t in self.cfg["weekly_tasks"]:
            weekly.append({"key": t["key"], "title": t["title"], "target": t["target"], "cents": t["cents"],
                           "badge": t.get("badge"),
                           "progress": min(await self._counter(uid, "wtask:" + t["key"], day=week), t["target"]),
                           "claimed": bool(await self._counter(uid, "wclaimed:" + t["key"], day=week))})
        task_days = await self._task_days(uid)
        common = level(self.cfg, "common")
        odds = apply_luck(common["odds"], u["luck_mult"]) if u["luck_left"] > 0 else common["odds"]
        qa, qb = pity_chances(odds, self.cfg["pity"], u["pity_epic"], u["pity_legend"])
        last = await self.db.one("SELECT i.* FROM drops d JOIN items i ON i.id = d.item_id WHERE d.user_id = ? "
                                 "AND d.action = 'spin' ORDER BY d.id DESC LIMIT 1", uid)
        sale = await self.db.one("SELECT * FROM sales WHERE user_id = ? AND undone = 0 AND undo_until > ? "
                                 "ORDER BY id DESC LIMIT 1", uid, now)
        cur = self.country_of(u)
        changed = u["country_changed_at"]
        change_after = changed + self.cfg["currency"]["change_days"] * 86400 if changed else None
        return {
            "user": {"id": u["id"], "name": u["first_name"] or "Игрок", "level": lvl, "xp": xp_in, "xp_need": need,
                     "total_spins": u["total_spins"], "badges": json.loads(u["badges"]),
                     "vip_until": u["vip_until"] if self._vip(u) else None, "created_at": u["created_at"],
                     "showcase": json.loads(u["showcase"])},
            "country": u["country"], "country_confirmed": bool(u["country_confirmed"]),
            "country_change_after": change_after if change_after and change_after > now else None,
            "currency": {"country": u["country"], **cur, "game_label": self.cfg["currency"]["show_game_label"]},
            "balance_cents": u["balance_cents"], "attempts": u["attempts"],
            "energy": {"now": e, "max": mx,
                       "next_in": 0 if e >= mx else int(self.cfg["energy"]["regen_minutes"] * 60 - (now - ets))},
            "coin_spins_left": max(0, self._coin_cap(u) - await self._counter(uid, "coin_spins")),
            "upper_spins_left": max(0, self.cfg["upper_levels_per_day"] - await self._counter(uid, "upper_spins")),
            "luck": {"mult": u["luck_mult"], "spins_left": u["luck_left"]} if u["luck_left"] > 0 else None,
            "pity": {"epic_in": self.cfg["pity"]["epic_plus"]["hard"] - u["pity_epic"], "epic_chance": qa,
                     "legend_in": self.cfg["pity"]["legend_plus"]["hard"] - u["pity_legend"], "legend_chance": qb},
            "slots": await self._slots(u),
            "starter": not u["starter_used"],
            "settings": {**SETTINGS_KEYS, **json.loads(u["settings"])},
            "today": {
                "gift": u["gift_day"] != today,
                "gift_day": ((u["gift_streak"] % 7) + 1 if u["gift_day"] == yesterday else 1)
                if u["gift_day"] != today else u["gift_streak"],
                "wheel_daily": await self._counter(uid, "wheel") == 0,
                "wheel_weekly": task_days >= self.cfg["wheel_weekly"]["unlock_days"]
                and not await self._counter(uid, "wheel_weekly", day=week),
                "wheel_weekly_used": bool(await self._counter(uid, "wheel_weekly", day=week)),
                "task_days": task_days, "tasks": tasks, "weekly_tasks": weekly,
                "tickets": await self._counter(uid, "tickets"),
            },
            "last_drop": (await self._views([last]))[0] if last else None,
            "last_sale": {"id": sale["id"], "amount_cents": sale["amount_cents"], "undo_until": sale["undo_until"],
                          "count": len(json.loads(sale["item_ids"]))} if sale else None,
            "stars_enabled": self.stars_enabled,
        }

    async def _task_days(self, uid: int) -> int:
        """В скольких днях из последних 7 выполнено хотя бы одно задание (для недельного колеса)."""
        now = self.clock()
        days = [day_key(now - i * 86400) for i in range(7)]
        marks = ",".join("?" * len(days))
        return await self.db.val(f"SELECT COUNT(DISTINCT day) FROM counters WHERE user_id = ? AND day IN ({marks}) "
                                 f"AND key LIKE 'claimed:%'", uid, *days)

    async def set_country(self, uid: int, code: str) -> dict:
        if code not in self.cfg["currency"]["countries"]:
            raise GameError("Такой страны нет в списке")
        async with self.db.tx():
            u = await self._user(uid)
            now = self.clock()
            if u["country_confirmed"] and code != u["country"]:
                after = (u["country_changed_at"] or 0) + self.cfg["currency"]["change_days"] * 86400
                if after > now:
                    d = datetime.fromtimestamp(after, MSK).strftime("%d.%m")
                    raise GameError(f"Страну можно менять раз в 30 дней. Следующая смена с {d}", "NOT_ALLOWED_YET")
            changed = now if (u["country_confirmed"] and code != u["country"]) else u["country_changed_at"]
            await self.db.run("UPDATE users SET country = ?, country_confirmed = 1, country_changed_at = ? WHERE id = ?",
                              code, changed, uid)
            return {"country": code}

    async def update_settings(self, uid: int, values: dict) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            cur = {**SETTINGS_KEYS, **json.loads(u["settings"])}
            for k, v in values.items():
                if k in SETTINGS_KEYS:
                    cur[k] = bool(v)
            await self.db.run("UPDATE users SET settings = ? WHERE id = ?", json.dumps(cur), uid)
            return cur

    # ---------- спин ----------

    async def spin(self, uid: int, level_key: str = "common", count: int = 1, confirmed: bool = False) -> dict:
        try:
            lv = level(self.cfg, level_key)
        except KeyError:
            raise GameError("Нет такого уровня крутки")
        if count not in self.cfg["counts"]:
            raise GameError("Можно крутить ×1, ×3, ×5 или ×10")
        common = lv["key"] == "common"
        async with self.db.tx():
            u = await self._user(uid)
            await self._daily_vip(u)
            await self._promote_overflow(u)
            now = self.clock()
            e, ets = self._energy(u)
            price = lv["price_cents"]
            places = await self._place(u, count)

            # чем платим: на Обычной сначала энергия, потом попытки, потом монеты
            use_e = min(e, count) if common else 0
            use_a = min(u["attempts"], count - use_e) if common else 0
            use_c = count - use_e - use_a
            if common:
                left = self._coin_cap(u) - await self._counter(uid, "coin_spins")
                if use_c > left:
                    raise GameError(f"Спины за монеты на сегодня закончились ({self._coin_cap(u)} в сутки). "
                                    "Бесплатные спины и попытки работают", "DAILY_LIMIT")
            else:
                left = self.cfg["upper_levels_per_day"] - await self._counter(uid, "upper_spins")
                if count > left:
                    raise GameError(f"Уровни выше Обычной — до {self.cfg['upper_levels_per_day']} круток в сутки. "
                                    f"Сегодня осталось {max(left, 0)}", "LEVEL_LIMIT")
            cost = use_c * price
            if cost > u["balance_cents"]:
                need = cost - u["balance_cents"]
                raise GameError(f"Не хватает {self.money(need, u)}. Задания и колесо дадут монеты", "NOT_ENOUGH_COINS",
                                need_cents=need)
            starter = common and count == self.cfg["starter"]["count"] and not u["starter_used"]
            # стартовый ×5 новичка без экрана подтверждения: первый спин должен занимать секунды
            if cost and not confirmed and not starter and (
                    cost >= self.cfg["confirm_from_cents"]
                    or cost > u["balance_cents"] * self.cfg["confirm_balance_share"]):
                raise GameError(f"Подтверди покупку: {self.money(cost, u)}", "CONFIRM_REQUIRED", cost_cents=cost)

            pair = await self._seed_pair(uid)
            luck_mult, luck_left = u["luck_mult"], u["luck_left"]
            pe, pl = u["pity_epic"], u["pity_legend"]
            drops, got_min = [], False
            for i in range(count):
                odds = dict(lv["odds"])
                luck = 1.0
                if common and luck_left > 0:
                    luck = luck_mult
                    odds = apply_luck(odds, luck)
                    luck_left -= 1
                if lv["pity"]:
                    odds = with_pity(odds, self.cfg["pity"], pe, pl)
                if starter and i == count - 1 and not got_min:  # стартовый ×5: Редкий+ гарантирован
                    m = self.cfg["starter"]["min_tier"]
                    s = sum(p for t, p in odds.items() if t >= m)
                    odds = {t: p / s for t, p in odds.items() if t >= m}
                nonce = await self._next_nonce(pair)
                u0 = fair.roll(pair["server_seed"], pair["client_seed"], nonce, 0)
                tier = fair.pick_tier(u0, odds)
                got_min = got_min or tier >= self.cfg["starter"]["min_tier"]
                rng = fair.FairRandom(pair["server_seed"], pair["client_seed"], nonce)
                item = await self._issue(uid, tier, rng, "spin" if use_c or not common else "free", places[i])
                await self.db.run(
                    "INSERT INTO drops (user_id, item_id, action, level, tier, odds_json, u0, seed_id, server_hash, "
                    "client_seed, nonce, luck, pity_epic, pity_legend, odds_version, created_at) "
                    "VALUES (?, ?, 'spin', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    uid, item["id"], lv["key"], tier, json.dumps({str(k): v for k, v in sorted(odds.items())}), u0,
                    pair["id"], pair["server_hash"], pair["client_seed"], nonce, luck, pe, pl,
                    self.cfg["odds_version"], now)
                if lv["pity"]:
                    pe = 0 if tier >= EPIC else pe + 1
                    pl = 0 if tier >= LEGENDARY else pl + 1
                item["fair"] = {"server_hash": pair["server_hash"], "client_seed": pair["client_seed"], "nonce": nonce}
                drops.append(item)

            xp_gain = count * max(10, price // 10_000)
            total = u["total_spins"] + count
            await self.db.run(
                "UPDATE users SET balance_cents = balance_cents - ?, attempts = attempts - ?, energy = ?, energy_ts = ?, "
                "energy_notify = CASE WHEN ? = 0 AND ? > 0 THEN 1 ELSE energy_notify END, pity_epic = ?, "
                "pity_legend = ?, luck_left = ?, xp = xp + ?, total_spins = ?, last_seen = ?, "
                "starter_used = CASE WHEN ? THEN 1 ELSE starter_used END WHERE id = ?",
                cost, use_a, e - use_e, ets, e - use_e, use_e, pe, pl, luck_left, xp_gain, total, now, starter, uid)
            await self._ledger(uid, "rub", -cost, f"spin_{lv['key']}")
            await self._ledger(uid, "attempts", -use_a, "spin")
            if common and use_c:
                await self._counter(uid, "coin_spins", use_c)
            if not common:
                await self._counter(uid, "upper_spins", count)
            spins_today = await self._counter(uid, "spins", count)
            await self._task_event(uid, "spin", count)
            req = self.cfg["referral"]["required_spins"]
            if u["ref_id"] and not u["ref_qualified"] and total >= req:
                await self.db.run("UPDATE users SET ref_qualified = 1 WHERE id = ?", uid)
                await self._reward_referrer(u["ref_id"], u["first_name"] or "Друг")
            hint = self.cfg["break_hint_spins"]
            return {
                "drops": drops, "level": lv["key"],
                "paid": {"energy": use_e, "attempts": use_a, "cents": cost},
                "starter": starter, "overflow": places.count("overflow"),
                "level_up": level_from_xp(u["xp"] + xp_gain)[0] > level_from_xp(u["xp"])[0],
                "player_level": level_from_xp(u["xp"] + xp_gain)[0],
                "break_hint": spins_today - count < hint <= spins_today,
            }

    # ---------- коллекция ----------

    async def collection(self, uid: int, min_tier: int = 0, q: str = "", sort: str = "rare",
                         favorites: bool = False, overflow: bool = False) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            await self._promote_overflow(u)
        order = {"new": "id DESC", "price": "tier DESC, id DESC", "rare": "tier DESC, id DESC"}.get(sort, "tier DESC")
        states = "('overflow')" if overflow else "('free', 'listed')"
        rows = await self.db.all(f"SELECT * FROM items WHERE user_id = ? AND state IN {states} AND tier >= ? "
                                 f"ORDER BY {order}", uid, min_tier)
        digits = "".join(ch for ch in q if ch.isdigit())
        rows = [r for r in rows if (not digits or digits in r["op"] + r["sub"]) and (not favorites or r["favorite"])]
        counts = await self.db.all("SELECT tier, COUNT(*) AS n FROM items WHERE user_id = ? AND state != 'gone' "
                                   "GROUP BY tier", uid)
        week_ago = self.clock() - 7 * 86400
        week = await self.db.all("SELECT tier, COUNT(*) FROM items WHERE user_id = ? AND state != 'gone' "
                                 "AND created_at >= ? GROUP BY tier", uid, week_ago)
        return {"items": await self._views(rows), "counts": {r["tier"]: r["n"] for r in counts},
                "value_cents": await self._collection_value(uid),
                "week_cents": sum(self.cfg["ladder_cents"][r[0]] * r[1] for r in week),
                "slots": await self._slots(u)}

    async def item_card(self, uid: int, item_id: int) -> dict:
        row = await self.db.one("SELECT * FROM items WHERE id = ? AND user_id = ? AND state != 'gone'", item_id, uid)
        if not row:
            raise GameError("Номер не найден", "CONFLICT")
        return (await self._views([row]))[0]

    async def mark_seen(self, uid: int) -> None:
        async with self.db.tx():
            await self.db.run("UPDATE items SET is_new = 0 WHERE user_id = ? AND is_new = 1", uid)

    async def toggle_favorite(self, uid: int, item_id: int) -> bool:
        async with self.db.tx():
            row = await self.db.one("SELECT favorite FROM items WHERE id = ? AND user_id = ? AND state != 'gone'",
                                    item_id, uid)
            if not row:
                raise GameError("Номер не найден", "CONFLICT")
            await self.db.run("UPDATE items SET favorite = ? WHERE id = ?", 1 - row[0], item_id)
            return not row[0]

    async def set_lock(self, uid: int, item_id: int, locked: bool, confirm: bool = False) -> bool:
        async with self.db.tx():
            row = await self.db.one("SELECT locked FROM items WHERE id = ? AND user_id = ? AND state != 'gone'",
                                    item_id, uid)
            if not row:
                raise GameError("Номер не найден", "CONFLICT")
            if not locked and row[0] and not confirm:
                raise GameError("Снять замок? Номер снова можно будет продать", "CONFIRM_REQUIRED")
            await self.db.run("UPDATE items SET locked = ? WHERE id = ?", int(locked), item_id)
            if locked:
                await self._task_event(uid, "lock")
            return locked

    async def set_showcase(self, uid: int, ids: list[int]) -> list[int]:
        ids = [int(i) for i in ids][:3]
        async with self.db.tx():
            if ids:
                await self._owned(uid, ids, ("free", "listed"))
            await self.db.run("UPDATE users SET showcase = ? WHERE id = ?", json.dumps(ids), uid)
        return ids

    async def sell(self, uid: int, ids: list[int], confirmed: bool = False) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            items = await self._owned(uid, ids, ("free", "overflow"))
            if any(i["locked"] for i in items):
                raise GameError("Номер под замком. Сними замок, чтобы продать", "ITEM_LOCKED")
            top = max(i["tier"] for i in items)
            if top >= LEGENDARY and len(items) > 1:
                raise GameError("Легендарные и выше продаются только по одному")
            if top >= EPIC and not confirmed:
                raise GameError("Подтверди продажу", "CONFIRM_REQUIRED")
            pct = self.cfg["sell_system_pct"]
            total = sum(self.cfg["ladder_cents"][i["tier"]] * pct // 100 for i in items)
            marks = ",".join("?" * len(items))
            await self.db.run(f"UPDATE items SET state = 'gone', gone_reason = 'sold' WHERE id IN ({marks})",
                              *[i["id"] for i in items])
            now = self.clock()
            undo_until = now + self.cfg["undo_sell"]["minutes"] * 60
            cur = await self.db.run("INSERT INTO sales (user_id, item_ids, amount_cents, created_at, undo_until) "
                                    "VALUES (?, ?, ?, ?, ?)", uid, json.dumps([i["id"] for i in items]), total, now,
                                    undo_until)
            await self._add(uid, cents=total, reason="sell")
            await self._task_event(uid, "sell", len(items))
            await self._promote_overflow(u)
            return {"sale_id": cur.lastrowid, "cents": total, "sold": len(items), "undo_until": undo_until}

    async def undo_sale(self, uid: int, sale_id: int) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            sale = await self.db.one("SELECT * FROM sales WHERE id = ? AND user_id = ?", sale_id, uid)
            if not sale or sale["undone"]:
                raise GameError("Эту продажу уже отменили", "CONFLICT")
            if sale["undo_until"] < self.clock():
                raise GameError("Отменить можно только в течение 10 минут", "NOT_ALLOWED_YET")
            if await self._counter(uid, "undo") >= self.cfg["undo_sell"]["per_day"]:
                raise GameError("Отменять продажу можно 5 раз в сутки", "DAILY_LIMIT")
            if u["balance_cents"] < sale["amount_cents"]:
                raise GameError(f"Не хватает {self.money(sale['amount_cents'] - u['balance_cents'], u)}, "
                                "чтобы вернуть номера", "NOT_ENOUGH_COINS")
            ids = json.loads(sale["item_ids"])
            places = await self._place(u, len(ids))
            for item_id, place in zip(ids, places):
                await self.db.run("UPDATE items SET state = ?, gone_reason = NULL, overflow_until = ? WHERE id = ? "
                                  "AND user_id = ? AND gone_reason = 'sold'", place,
                                  self.clock() + self.cfg["inventory"]["overflow_hours"] * 3600
                                  if place == "overflow" else None, item_id, uid)
            await self.db.run("UPDATE sales SET undone = 1 WHERE id = ?", sale_id)
            await self._add(uid, cents=-sale["amount_cents"], reason="sell_undo")
            await self._counter(uid, "undo", 1)
            return {"restored": len(ids)}

    async def sell_quote(self, uid: int, mode: str = "below_rare", max_cents: int = 0) -> dict:
        """«Продать всё ниже Редкого» и «Продать дешевле X»: замок, Легендарные+ и лоты не попадают."""
        rows = await self.db.all("SELECT id, tier FROM items WHERE user_id = ? AND state IN ('free', 'overflow') "
                                 "AND locked = 0 AND tier < ?", uid, LEGENDARY)
        lad = self.cfg["ladder_cents"]
        if mode == "below_rare":
            rows = [r for r in rows if r["tier"] < RARE]
        else:
            rows = [r for r in rows if lad[r["tier"]] < int(max_cents)]
        pct = self.cfg["sell_system_pct"]
        return {"ids": [r["id"] for r in rows], "count": len(rows),
                "cents": sum(lad[r["tier"]] * pct // 100 for r in rows)}

    # ---------- 5 в 1 и апгрейдер ----------

    async def contract(self, uid: int, ids: list[int]) -> dict:
        cc = self.cfg["contracts"]
        async with self.db.tx():
            u = await self._user(uid)
            items = await self._owned(uid, ids)
            if len(items) != cc["inputs"]:
                raise GameError(f"Нужно ровно {cc['inputs']} номеров одной ступени")
            if any(i["locked"] for i in items):
                raise GameError("Номера под замком в «5 в 1» не попадают", "ITEM_LOCKED")
            tiers = {i["tier"] for i in items}
            if len(tiers) != 1:
                raise GameError("Все 5 номеров должны быть одной ступени")
            tier = tiers.pop()
            if tier > SECRET:
                raise GameError("Эту ступень нельзя улучшить")
            marks = ",".join("?" * len(items))
            await self.db.run(f"UPDATE items SET state = 'gone', gone_reason = 'contract' WHERE id IN ({marks})",
                              *[i["id"] for i in items])
            pair = await self._seed_pair(uid)
            nonce = await self._next_nonce(pair)
            u0 = fair.roll(pair["server_seed"], pair["client_seed"], nonce, 0)
            guaranteed = tier <= cc["guaranteed_up_to_tier"]
            success = guaranteed or u0 < cc["success_pct"] / 100
            out_tier = tier + 1 if success else tier
            rng = fair.FairRandom(pair["server_seed"], pair["client_seed"], nonce)
            item = await self._issue(uid, out_tier, rng, "contract", "free")
            await self.db.run(
                "INSERT INTO drops (user_id, item_id, action, tier, odds_json, u0, seed_id, server_hash, client_seed, "
                "nonce, odds_version, created_at) VALUES (?, ?, 'contract', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                uid, item["id"], out_tier, json.dumps({"success": 1 if guaranteed else cc["success_pct"] / 100}), u0,
                pair["id"], pair["server_hash"], pair["client_seed"], nonce, self.cfg["odds_version"], self.clock())
            await self._task_event(uid, "contract")
            await self._promote_overflow(u)
            return {"success": success, "guaranteed": guaranteed, "item": item, "chance": 1 if guaranteed
                    else cc["success_pct"] / 100, "roll": u0}

    async def _upgrade_calc(self, uid: int, ids: list[int], cents: int, target: int) -> dict:
        up = self.cfg["upgrader"]
        u = await self._user(uid)
        if json.loads(u["settings"]).get("no_upgrader"):
            raise GameError("Улучшение выключено в настройках")
        if len(ids) > up["max_items"]:
            raise GameError(f"Не больше {up['max_items']} номеров за раз")
        cents = max(0, int(cents))
        items = await self._owned(uid, ids) if ids else []
        if any(i["locked"] for i in items):
            raise GameError("Номера под замком нельзя улучшать", "ITEM_LOCKED")
        if cents > u["balance_cents"]:
            raise GameError(f"Не хватает {self.money(cents - u['balance_cents'], u)}", "NOT_ENOUGH_COINS",
                            need_cents=cents - u["balance_cents"])
        lad = self.cfg["ladder_cents"]
        stake = sum(lad[i["tier"]] for i in items) + cents
        if stake <= 0:
            raise GameError("Положи номер или монеты")
        if not 0 <= target <= SECRET:
            raise GameError("Такую цель нельзя выбрать")
        if lad[target] <= stake:
            raise GameError("Цель должна стоить дороже ставки")
        value = await self._collection_value(uid) + u["balance_cents"]
        if stake > value * up["max_share_of_collection"]:
            raise GameError("За раз можно поставить не больше половины стоимости коллекции")
        base = stake / lad[target] * up["k"]
        chance = min(up["max_chance_pct"] / 100, base + u["upgrade_bonus"])
        return {"items": items, "cents": cents, "stake_cents": stake, "target": target, "target_cents": lad[target],
                "chance": round(chance, 4), "base_chance": round(base, 4), "bonus": round(u["upgrade_bonus"], 4),
                "left_today": up["per_day"] - await self._counter(uid, "upgrades"),
                "confirm": any(i["tier"] >= up["confirm_from_tier"] for i in items)}

    async def upgrade_quote(self, uid: int, ids: list[int], cents: int, target: int) -> dict:
        q = await self._upgrade_calc(uid, ids, cents, target)
        q.pop("items")
        return q

    async def upgrade(self, uid: int, ids: list[int], cents: int, target: int, quote_chance: float | None = None) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            q = await self._upgrade_calc(uid, ids, cents, target)
            if quote_chance is not None and abs(float(quote_chance) - q["chance"]) > 1e-6:
                raise GameError("Шанс изменился, посмотри ещё раз", "CONFIG_CHANGED")
            if q["left_today"] <= 0:
                raise GameError("На сегодня улучшения закончились (10 в сутки)", "DAILY_LIMIT")
            await self._counter(uid, "upgrades", 1)
            if q["items"]:
                marks = ",".join("?" * len(q["items"]))
                await self.db.run(f"UPDATE items SET state = 'gone', gone_reason = 'upgrade' WHERE id IN ({marks})",
                                  *[i["id"] for i in q["items"]])
            await self._add(uid, cents=-q["cents"], reason="upgrade")
            pair = await self._seed_pair(uid)
            nonce = await self._next_nonce(pair)
            u0 = fair.roll(pair["server_seed"], pair["client_seed"], nonce, 0)
            success = u0 < q["chance"]
            res = {"success": success, "chance": q["chance"], "roll": u0}
            if success:
                rng = fair.FairRandom(pair["server_seed"], pair["client_seed"], nonce)
                place = (await self._place(u, 1))[0]
                res["item"] = await self._issue(uid, target, rng, "upgrade", place)
                await self.db.run("UPDATE users SET upgrade_bonus = 0 WHERE id = ?", uid)
                await self.db.run(
                    "INSERT INTO drops (user_id, item_id, action, tier, odds_json, u0, seed_id, server_hash, "
                    "client_seed, nonce, odds_version, created_at) VALUES (?, ?, 'upgrade', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    uid, res["item"]["id"], target, json.dumps({"success": q["chance"]}), u0, pair["id"],
                    pair["server_hash"], pair["client_seed"], nonce, self.cfg["odds_version"], self.clock())
            else:
                up = self.cfg["upgrader"]
                parts = q["stake_cents"] * up["fail_parts_pct"] // 100
                await self._add(uid, cents=parts, reason="upgrade_parts")
                await self.db.run("UPDATE users SET upgrade_bonus = upgrade_bonus + ? WHERE id = ?",
                                  up["fail_bonus_pct"] / 100, uid)
                res.update(parts_cents=parts, next_bonus=round(q["bonus"] + up["fail_bonus_pct"] / 100, 4))
            await self._promote_overflow(u)
            return res

    # ---------- рынок за монеты ----------

    async def _expire_lots(self) -> None:
        now = self.clock()
        for r in await self.db.all("SELECT id, item_id FROM lots WHERE status = 'active' AND expires_at < ?", now):
            await self.db.run("UPDATE lots SET status = 'expired', closed_at = ? WHERE id = ?", now, r["id"])
            await self.db.run("UPDATE items SET state = 'free' WHERE id = ? AND state = 'listed'", r["item_id"])

    async def _lot_views(self, rows) -> list[dict]:
        items = await self._views(rows)
        for it, r in zip(items, rows):
            it.update(lot_id=r["lot_id"], lot_cents=r["lot_cents"], seller_id=r["seller_id"],
                      seller=r["seller_name"] or "Игрок", expires_at=r["expires_at"])
            if "lot_status" in r.keys():
                it.update(lot_status=r["lot_status"], buyer_id=r["buyer_id"], fee_cents=r["fee_cents"])
        return items

    async def market(self, uid: int, min_tier: int = 0, sort: str = "new", q: str = "") -> dict:
        async with self.db.tx():
            await self._expire_lots()
            await self._task_event(uid, "market")
        order = {"new": "l.id DESC", "cheap": "l.price_cents ASC", "rare": "i.tier DESC, l.price_cents DESC"}.get(
            sort, "l.id DESC")
        rows = await self.db.all(
            "SELECT i.*, l.id AS lot_id, l.price_cents AS lot_cents, l.seller_id, l.expires_at, "
            "u.first_name AS seller_name FROM lots l JOIN items i ON i.id = l.item_id JOIN users u ON u.id = l.seller_id "
            f"WHERE l.status = 'active' AND i.tier >= ? ORDER BY {order} LIMIT 100", min_tier)
        digits = "".join(ch for ch in q if ch.isdigit())
        rows = [r for r in rows if not digits or digits in r["op"] + r["sub"]]
        u = await self._user(uid)
        fee = self.cfg["market"]["fee_vip_pct" if self._vip(u) else "fee_pct"]
        return {"lots": await self._lot_views(rows), "fee_pct": fee}

    async def my_lots(self, uid: int) -> dict:
        rows = await self.db.all(
            "SELECT i.*, l.id AS lot_id, l.price_cents AS lot_cents, l.seller_id, l.expires_at, l.status AS lot_status, "
            "l.buyer_id, l.fee_cents, u.first_name AS seller_name FROM lots l JOIN items i ON i.id = l.item_id "
            "JOIN users u ON u.id = l.seller_id WHERE l.seller_id = ? OR l.buyer_id = ? ORDER BY l.id DESC LIMIT 60",
            uid, uid)
        views = await self._lot_views(rows)
        for v in views:
            v["side"] = "sell" if v["seller_id"] == uid else "buy"
        return {"active": [v for v in views if v["lot_status"] == "active" and v["side"] == "sell"],
                "deals": [v for v in views if v["lot_status"] == "sold"]}

    async def list_lot(self, uid: int, item_id: int, price_cents: int) -> dict:
        m = self.cfg["market"]
        async with self.db.tx():
            u = await self._user(uid)
            now = self.clock()
            if now - u["created_at"] < m["new_account_hours"] * 3600:
                raise GameError(f"Торговать можно через {m['new_account_hours']} ч после первого входа",
                                "NOT_ALLOWED_YET")
            item = (await self._owned(uid, [item_id]))[0]
            if item["hold_until"] and item["hold_until"] > now:
                raise GameError("Купленный номер можно выставить через 24 часа", "ITEM_BUSY")
            if await self.db.val("SELECT COUNT(*) FROM lots WHERE seller_id = ? AND status = 'active'", uid) \
                    >= m["lots_max"]:
                raise GameError(f"Не больше {m['lots_max']} лотов одновременно", "DAILY_LIMIT")
            ref = self.cfg["ladder_cents"][item["tier"]]
            lo, hi = ref * m["band_pct"][0] // 100, ref * m["band_pct"][1] // 100
            price_cents = int(price_cents)
            if not lo <= price_cents <= hi:
                raise GameError(f"Цена от {self.money(lo, u)} до {self.money(hi, u)}", "PRICE_OUT_OF_BAND",
                                min_cents=lo, max_cents=hi)
            await self.db.run("UPDATE items SET state = 'listed' WHERE id = ?", item_id)
            cur = await self.db.run("INSERT INTO lots (item_id, seller_id, price_cents, created_at, expires_at) "
                                    "VALUES (?, ?, ?, ?, ?)", item_id, uid, price_cents, now, now + m["lot_days"] * 86400)
            fee = m["fee_vip_pct" if self._vip(u) else "fee_pct"]
            return {"lot_id": cur.lastrowid, "you_get_cents": price_cents - price_cents * fee // 100}

    async def cancel_lot(self, uid: int, lot_id: int) -> None:
        async with self.db.tx():
            lot = await self.db.one("SELECT * FROM lots WHERE id = ? AND seller_id = ? AND status = 'active'", lot_id, uid)
            if not lot:
                raise GameError("Лот уже закрыт", "CONFLICT")
            await self.db.run("UPDATE lots SET status = 'cancelled', closed_at = ? WHERE id = ?", self.clock(), lot_id)
            await self.db.run("UPDATE items SET state = 'free' WHERE id = ?", lot["item_id"])

    async def buy_lot(self, uid: int, lot_id: int) -> dict:
        m = self.cfg["market"]
        async with self.db.tx():
            await self._expire_lots()
            u = await self._user(uid)
            now = self.clock()
            if now - u["created_at"] < m["new_account_hours"] * 3600:
                raise GameError(f"Покупать можно через {m['new_account_hours']} ч после первого входа",
                                "NOT_ALLOWED_YET")
            lot = await self.db.one("SELECT * FROM lots WHERE id = ? AND status = 'active'", lot_id)
            if not lot:
                raise GameError("Этот лот уже купили или сняли", "CONFLICT")
            if lot["seller_id"] == uid:
                raise GameError("Это твой лот")
            if u["balance_cents"] < lot["price_cents"]:
                need = lot["price_cents"] - u["balance_cents"]
                raise GameError(f"Не хватает {self.money(need, u)}", "NOT_ENOUGH_COINS", need_cents=need)
            place = (await self._place(u, 1))[0]
            seller = await self._user(lot["seller_id"])
            fee = lot["price_cents"] * m["fee_vip_pct" if self._vip(seller) else "fee_pct"] // 100
            await self._add(uid, cents=-lot["price_cents"], reason="market_buy")
            await self._add(lot["seller_id"], cents=lot["price_cents"], reason="market_sale")
            await self._add(lot["seller_id"], cents=-fee, reason="market_fee")  # комиссия уходит из игры
            await self.db.run("UPDATE lots SET status = 'sold', buyer_id = ?, fee_cents = ?, closed_at = ? WHERE id = ?",
                              uid, fee, now, lot_id)
            await self.db.run("UPDATE items SET user_id = ?, state = ?, is_new = 1, favorite = 0, locked = 0, "
                              "hold_until = ?, overflow_until = ? WHERE id = ?", uid, place, now + m["hold_hours"] * 3600,
                              now + self.cfg["inventory"]["overflow_hours"] * 3600 if place == "overflow" else None,
                              lot["item_id"])
            item = await self._item(lot["item_id"])
            await self.notify(lot["seller_id"], f"💰 Твой номер {item['number']} купили за "
                                                f"{self.money(lot['price_cents'], seller)}. "
                                                f"Тебе {self.money(lot['price_cents'] - fee, seller)}")
            return {"item": item}

    # ---------- колёса, подарок, задания ----------

    def _pick(self, sectors: list[dict]) -> int:
        x = secrets.randbelow(10 ** 9) / 10 ** 9
        for i, s in enumerate(sectors):
            x -= s["p"]
            if x < 0:
                return i
        return len(sectors) - 1

    async def _grant_sector(self, u: dict, s: dict, reason: str) -> dict:
        out = {"label": s["label"], "cents": s.get("cents", 0), "attempts": s.get("attempts", 0)}
        await self._add(u["id"], s.get("cents", 0), s.get("attempts", 0), reason)
        if s.get("item_min_tier") is not None:
            common = level(self.cfg, "common")["odds"]
            m = s["item_min_tier"]
            tot = sum(p for t, p in common.items() if t >= m)
            odds = {t: p / tot for t, p in common.items() if t >= m}
            pair = await self._seed_pair(u["id"])
            nonce = await self._next_nonce(pair)
            u0 = fair.roll(pair["server_seed"], pair["client_seed"], nonce, 0)
            tier = fair.pick_tier(u0, odds)
            place = (await self._place(u, 1))[0]
            out["item"] = await self._issue(u["id"], tier, fair.FairRandom(pair["server_seed"], pair["client_seed"],
                                                                            nonce), reason, place)
        if s.get("badge"):
            await self._badge(u, s["badge"])
            out["badge"] = s["badge"]
        return out

    async def wheel(self, uid: int, kind: str = "daily") -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            now = self.clock()
            if kind == "weekly":
                week = week_key(now)
                if await self._counter(uid, "wheel_weekly", day=week):
                    raise GameError("Недельное колесо уже крутил на этой неделе", "DAILY_LIMIT")
                if await self._task_days(uid) < self.cfg["wheel_weekly"]["unlock_days"]:
                    raise GameError("Недельное колесо открывается за задания в 5 днях из 7", "NOT_ALLOWED_YET")
                sectors = self.cfg["wheel_weekly"]["sectors"]
                idx = self._pick(sectors)
                await self._counter(uid, "wheel_weekly", 1, week)
            else:
                if await self._counter(uid, "wheel"):
                    raise GameError("Колесо уже крутил сегодня. Следующее завтра", "DAILY_LIMIT")
                sectors = self.cfg["wheel_daily"]
                idx = self._pick(sectors)
                await self._counter(uid, "wheel", 1)
                await self._task_event(uid, "wheel")
            prize = await self._grant_sector(u, sectors[idx], f"wheel_{kind}")
            return {"index": idx, **prize}

    async def gift_claim(self, uid: int) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            now = self.clock()
            today, yesterday = day_key(now), day_key(now - 86400)
            if u["gift_day"] == today:
                raise GameError("Подарок уже забран. Возвращайся завтра", "DAILY_LIMIT")
            streak = (u["gift_streak"] % 7) + 1 if u["gift_day"] == yesterday else 1
            r = self.cfg["gift"][streak - 1]
            cents, attempts = (r, 0) if isinstance(r, int) else (r.get("cents", 0), r.get("attempts", 0))
            await self.db.run("UPDATE users SET gift_day = ?, gift_streak = ? WHERE id = ?", today, streak, uid)
            await self._add(uid, cents, attempts, "gift")
            return {"day": streak, "cents": cents, "attempts": attempts}

    async def task_claim(self, uid: int, key: str) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            now = self.clock()
            weekly = next((t for t in self.cfg["weekly_tasks"] if t["key"] == key), None)
            if weekly:
                week = week_key(now)
                if await self._counter(uid, "wclaimed:" + key, day=week):
                    raise GameError("Награда уже получена", "CONFLICT")
                if await self._counter(uid, "wtask:" + key, day=week) < weekly["target"]:
                    raise GameError("Задание ещё не выполнено")
                await self._counter(uid, "wclaimed:" + key, 1, week)
                await self._add(uid, cents=weekly["cents"], reason="task_weekly")
                if weekly.get("badge"):
                    await self._badge(u, weekly["badge"])
                return {"cents": weekly["cents"], "badge": weekly.get("badge")}
            task = next((t for t in self._today_tasks(now) if t["key"] == key), None)
            if not task:
                raise GameError("Такого задания сегодня нет")
            if await self._counter(uid, "claimed:" + key):
                raise GameError("Награда уже получена", "CONFLICT")
            if await self._counter(uid, "task:" + key) < task["target"]:
                raise GameError("Задание ещё не выполнено")
            await self._counter(uid, "claimed:" + key, 1)
            await self._counter(uid, "tickets", self.cfg["tickets_per_task"])
            await self._add(uid, cents=task["cents"], reason="task")
            return {"cents": task["cents"], "tickets": self.cfg["tickets_per_task"]}

    # ---------- розыгрыш ----------

    async def _raffle_row(self, day: str) -> dict:
        row = await self.db.one("SELECT * FROM raffles WHERE day = ?", day)
        if row:
            return dict(row)
        seed = fair.new_server_seed()
        await self.db.run("INSERT INTO raffles (day, server_seed, server_hash) VALUES (?, ?, ?)",
                          day, seed, fair.seed_hash(seed))
        return dict(await self.db.one("SELECT * FROM raffles WHERE day = ?", day))

    async def raffle(self, uid: int) -> dict:
        now = self.clock()
        today, yesterday = day_key(now), day_key(now - 86400)
        async with self.db.tx():
            row = await self._raffle_row(today)
            last = await self.db.one("SELECT * FROM raffles WHERE day = ? AND drawn = 1", yesterday) \
                or await self.db.one("SELECT * FROM raffles WHERE drawn = 1 ORDER BY day DESC LIMIT 1")
        total = await self.db.val("SELECT SUM(value) FROM counters WHERE day = ? AND key = 'tickets'", today)
        return {
            "day": today, "hour_msk": self.cfg["raffle"]["hour_msk"], "server_hash": row["server_hash"],
            "drawn": bool(row["drawn"]), "my_tickets": await self._counter(uid, "tickets"), "total_tickets": total,
            "prizes": self.cfg["raffle"]["prizes"],
            "winners": json.loads(row["winners"]) if row["drawn"] else [],
            "last": {"day": last["day"], "server_seed": last["server_seed"], "server_hash": last["server_hash"],
                     "winners": json.loads(last["winners"])} if last else None,
        }

    async def raffle_draw(self, day: str | None = None) -> dict | None:
        """Розыгрыш дня: билеты по возрастанию id игрока, победитель i — HMAC(seed, "raffle:day:i")."""
        now = self.clock()
        day = day or day_key(now)
        async with self.db.tx():
            row = await self._raffle_row(day)
            if row["drawn"]:
                return None
            entries = []
            for r in await self.db.all("SELECT user_id, value FROM counters WHERE day = ? AND key = 'tickets' "
                                       "AND value > 0 ORDER BY user_id", day):
                entries += [r["user_id"]] * r["value"]
            winners = []
            for i, prize in enumerate(self.cfg["raffle"]["prizes"]):
                if not entries:
                    break
                u_i = fair.roll(row["server_seed"], "raffle", int(day.replace("-", "")), i)
                uid = entries[int(u_i * len(entries))]
                entries = [e for e in entries if e != uid]
                u = await self._user(uid)
                w = {"user_id": uid, "name": u["first_name"] or "Игрок", "place": i + 1}
                if prize.get("item_tier") is not None:
                    try:
                        place = (await self._place(u, 1))[0]
                    except GameError:  # коллекция переполнена — приз монетами по опорной цене
                        place = None
                    if place:
                        rng = fair.FairRandom(row["server_seed"], f"raffle{uid}", int(day.replace("-", "")),
                                              100 + i * 50)
                        item = await self._issue(uid, prize["item_tier"], rng, "raffle", place)
                        w["prize"] = f"{item['tier']['icon']} {item['number']}"
                    else:
                        cents = self.cfg["ladder_cents"][prize["item_tier"]]
                        await self._add(uid, cents=cents, reason="raffle")
                        w["prize"] = self.money(cents, u)
                else:
                    await self._add(uid, cents=prize["cents"], reason="raffle")
                    w["prize"] = self.money(prize["cents"], u)
                winners.append(w)
                await self.notify(uid, f"🎟 Ты выиграл в розыгрыше дня: {w['prize']}!", force=True)
            await self.db.run("UPDATE raffles SET drawn = 1, winners = ?, drawn_at = ? WHERE day = ?",
                              json.dumps(winners, ensure_ascii=False), now, day)
            return {"day": day, "winners": winners}

    # ---------- честная игра ----------

    async def fair_info(self, uid: int) -> dict:
        async with self.db.tx():
            pair = await self._seed_pair(uid)
        rows = await self.db.all(
            "SELECT d.*, s.server_seed, s.revealed_at, i.country, i.op, i.sub FROM drops d "
            "LEFT JOIN seeds s ON s.id = d.seed_id LEFT JOIN items i ON i.id = d.item_id "
            "WHERE d.user_id = ? AND d.server_hash IS NOT NULL ORDER BY d.id DESC LIMIT 50", uid)
        out = []
        for r in rows:
            out.append({
                "id": r["id"], "action": r["action"], "level": r["level"], "tier": r["tier"], "u0": r["u0"],
                "odds": json.loads(r["odds_json"]), "server_hash": r["server_hash"], "client_seed": r["client_seed"],
                "nonce": r["nonce"], "server_seed": r["server_seed"] if r["revealed_at"] else None,
                "number": phones.format_number(r["country"], r["op"], r["sub"]) if r["country"] else None,
                "created_at": r["created_at"],
            })
        return {"server_hash": pair["server_hash"], "client_seed": pair["client_seed"], "nonce": pair["nonce"],
                "rolls": out}

    async def fair_rotate(self, uid: int, client_seed: str | None = None) -> dict:
        client_seed = (client_seed or "").strip() or fair.new_client_seed()
        if not CLIENT_SEED_RE.match(client_seed):
            raise GameError("Client seed: до 32 латинских букв, цифр, «-» или «_»")
        async with self.db.tx():
            old = await self._seed_pair(uid)
            now = self.clock()
            await self.db.run("UPDATE seeds SET active = 0, revealed_at = ? WHERE id = ?", now, old["id"])
            server = fair.new_server_seed()
            await self.db.run("INSERT INTO seeds (user_id, server_seed, server_hash, client_seed, created_at) "
                              "VALUES (?, ?, ?, ?, ?)", uid, server, fair.seed_hash(server), client_seed, now)
            return {"revealed": {"server_seed": old["server_seed"], "server_hash": old["server_hash"],
                                 "client_seed": old["client_seed"], "nonce": old["nonce"]},
                    "server_hash": fair.seed_hash(server), "client_seed": client_seed, "nonce": 0}

    # ---------- друзья, рейтинг, лента ----------

    async def friends(self, uid: int) -> dict:
        u = await self._user(uid)
        rows = await self.db.all("SELECT first_name, total_spins, ref_qualified FROM users WHERE ref_id = ? "
                                 "ORDER BY created_at DESC LIMIT 100", uid)
        req = self.cfg["referral"]["required_spins"]
        return {"count": u["ref_count"], "required_spins": req, "friend_attempts": self.cfg["referral"]["friend_attempts"],
                "tiers": self.cfg["referral"]["tiers"],
                "friends": [{"name": r["first_name"] or "Друг", "spins": min(r["total_spins"], req),
                             "qualified": bool(r["ref_qualified"])} for r in rows]}

    async def _circle(self, uid: int) -> set[int]:
        u = await self._user(uid)
        ids = {uid}
        if u["ref_id"]:
            ids.add(u["ref_id"])
        ids |= {r[0] for r in await self.db.all("SELECT id FROM users WHERE ref_id = ?", uid)}
        return ids

    async def rating(self, uid: int, board: str = "collection", scope: str = "friends") -> dict:
        async with self.db.tx():
            await self._task_event(uid, "rating")
        lad = self.cfg["ladder_cents"]
        rows = []
        if board == "level":
            for r in await self.db.all("SELECT id, first_name, xp FROM users WHERE xp > 0"):
                rows.append({"id": r["id"], "name": r["first_name"], "score": r["xp"],
                             "value": level_from_xp(r["xp"])[0]})
        elif board == "rarest":
            for r in await self.db.all("SELECT u.id, u.first_name, MAX(i.tier * 1000000000 + i.id) AS s FROM users u "
                                       "JOIN items i ON i.user_id = u.id AND i.state != 'gone' GROUP BY u.id"):
                rows.append({"id": r["id"], "name": r["first_name"], "score": r["s"], "item_id": r["s"] % 1000000000})
        else:
            for r in await self.db.all("SELECT user_id, tier, COUNT(*) FROM items WHERE state != 'gone' "
                                       "GROUP BY user_id, tier"):
                rows.append({"id": r[0], "tier": r[1], "n": r[2]})
            agg: dict[int, int] = {}
            for r in rows:
                agg[r["id"]] = agg.get(r["id"], 0) + lad[r["tier"]] * r["n"]
            names = {r[0]: r[1] for r in await self.db.all("SELECT id, first_name FROM users")}
            rows = [{"id": k, "name": names.get(k), "score": v, "value_cents": v} for k, v in agg.items()]
        if scope == "friends":
            circle = await self._circle(uid)
            rows = [r for r in rows if r["id"] in circle]
        rows.sort(key=lambda r: r["score"], reverse=True)
        out = []
        for pos, r in enumerate(rows, 1):
            e = {"pos": pos, "id": r["id"], "name": r["name"] or "Игрок", "me": r["id"] == uid}
            if board == "rarest":
                if pos <= 50 or r["id"] == uid:
                    item = await self.db.one("SELECT * FROM items WHERE id = ?", r["item_id"])
                    e["item"] = (await self._views([item]))[0]
            elif board == "level":
                e["level"] = r["value"]
            else:
                e["value_cents"] = r["value_cents"]
            out.append(e)
        return {"board": board, "scope": scope, "top": out[:50], "me": next((e for e in out if e["me"]), None)}

    async def feed(self, uid: int) -> list[dict]:
        """Лента «Эпик+ у друзей и в игре»: только имя и номер."""
        circle = await self._circle(uid)
        rows = await self.db.all(
            "SELECT d.id, d.user_id, d.created_at, u.first_name, i.* FROM drops d JOIN users u ON u.id = d.user_id "
            "JOIN items i ON i.id = d.item_id WHERE d.tier >= ? ORDER BY d.id DESC LIMIT 20", EPIC)
        views = await self._views(rows)
        return [{"name": r["first_name"] or "Игрок", "friend": r["user_id"] in circle and r["user_id"] != uid,
                 "me": r["user_id"] == uid, "number": v["number"], "flag": v["flag"], "tier": v["tier"],
                 "at": r["created_at"]} for r, v in zip(rows, views)]

    async def history(self, uid: int) -> list[dict]:
        rows = await self.db.all("SELECT currency, delta, reason, created_at FROM ledger WHERE user_id = ? "
                                 "ORDER BY id DESC LIMIT 20", uid)
        return [dict(r) for r in rows]

    # ---------- магазин за Telegram Stars ----------

    async def _month_spent(self, uid: int) -> int:
        return await self.db.val("SELECT SUM(stars) FROM payments WHERE user_id = ? AND refunded = 0 "
                                 "AND created_at >= ?", uid, month_start(self.clock()))

    async def shop(self, uid: int) -> dict:
        s = self.cfg["shop"]
        u = await self._user(uid)
        products = []
        for k, p in s["products"].items():
            if p.get("once") and u["start_pack"]:
                continue
            products.append({"key": k, **p})
        return {"enabled": self.stars_enabled, "products": products, "month_spent": await self._month_spent(uid),
                "month_cap": s["monthly_cap_stars"], "warn_at_pct": s["warn_at_pct"],
                "attempts_stock_cap": s["attempts_stock_cap"]}

    async def check_purchase(self, uid: int, key: str) -> dict:
        if not self.stars_enabled:
            raise GameError("Магазин пока закрыт", "NOT_ALLOWED_YET")
        s = self.cfg["shop"]
        p = s["products"].get(key)
        if not p:
            raise GameError("Нет такого товара")
        u = await self._user(uid)
        spent = await self._month_spent(uid)
        if spent + p["stars"] > s["monthly_cap_stars"]:
            raise GameError(f"Месячный лимит покупок {s['monthly_cap_stars']} ⭐, осталось "
                            f"{s['monthly_cap_stars'] - spent} ⭐. Повысить можно через /paysupport", "STARS_MONTH_CAP")
        if p.get("once") and u["start_pack"]:
            raise GameError("Набор «Старт» можно купить один раз", "NOT_ALLOWED_YET")
        if p.get("attempts"):
            if u["attempts"] + p["attempts"] > s["attempts_stock_cap"]:
                raise GameError(f"Запас попыток не больше {s['attempts_stock_cap']}. Сначала потрать текущие",
                                "DAILY_LIMIT")
            if await self._counter(uid, "bought_attempts") + p["attempts"] > s["attempts_daily_cap"]:
                raise GameError(f"За сутки можно купить не больше {s['attempts_daily_cap']} попыток", "DAILY_LIMIT")
        if p.get("luck"):
            if u["luck_left"] > 0 and u["luck_mult"] > p["luck"]:
                raise GameError("Уже действует более сильная удача", "CONFLICT")
            if p["luck"] >= 2 and await self._counter(uid, "luck2") >= s["luck2_daily"]:
                raise GameError(f"Удачу ×2 можно купить не больше {s['luck2_daily']} раз в сутки", "DAILY_LIMIT")
        if p.get("slots") and u["slots_bought"] >= s["slots_max_buys"]:
            raise GameError("Места можно докупить не больше 3 раз", "DAILY_LIMIT")
        return {"key": key, **p}

    async def grant_purchase(self, uid: int, key: str, charge_id: str, stars: int) -> dict:
        async with self.db.tx():
            if await self.db.one("SELECT 1 FROM payments WHERE charge_id = ?", charge_id):
                return {"duplicate": True}
            p = self.cfg["shop"]["products"][key]
            u = await self._user(uid)
            now = self.clock()
            await self.db.run("INSERT INTO payments (user_id, product, stars, charge_id, created_at) VALUES (?, ?, ?, ?, ?)",
                              uid, key, stars, charge_id, now)
            if p.get("attempts"):
                await self._add(uid, attempts=p["attempts"], reason="purchase")
                await self._counter(uid, "bought_attempts", p["attempts"])
            if p.get("luck"):
                await self.db.run("UPDATE users SET luck_mult = ?, luck_left = ? WHERE id = ?", p["luck"],
                                  self.cfg["shop"]["luck_spins"], uid)
                if p["luck"] >= 2:
                    await self._counter(uid, "luck2", 1)
            if p.get("vip_days"):
                base = max(now, u["vip_until"] or 0)
                await self.db.run("UPDATE users SET vip_until = ? WHERE id = ?", base + p["vip_days"] * 86400, uid)
            if p.get("slots"):
                await self.db.run("UPDATE users SET slots_extra = slots_extra + ?, slots_bought = slots_bought + 1 "
                                  "WHERE id = ?", p["slots"], uid)
            if p.get("once"):
                await self.db.run("UPDATE users SET start_pack = 1 WHERE id = ?", uid)
            return {"granted": p["title"]}

    async def revoke_purchase(self, charge_id: str) -> dict:
        """Возврат: снимаем неиспользованное. Использованные попытки не возвращаются."""
        async with self.db.tx():
            pay = await self.db.one("SELECT * FROM payments WHERE charge_id = ? AND refunded = 0", charge_id)
            if not pay:
                raise GameError("Платёж не найден или уже возвращён", "CONFLICT")
            p = self.cfg["shop"]["products"][pay["product"]]
            u = await self._user(pay["user_id"])
            if p.get("attempts"):
                await self._add(u["id"], attempts=-min(u["attempts"], p["attempts"]), reason="refund")
            if p.get("luck") and u["luck_mult"] == p["luck"]:
                await self.db.run("UPDATE users SET luck_left = 0 WHERE id = ?", u["id"])
            if p.get("vip_days") and u["vip_until"]:
                await self.db.run("UPDATE users SET vip_until = ? WHERE id = ?",
                                  u["vip_until"] - p["vip_days"] * 86400, u["id"])
            await self.db.run("UPDATE payments SET refunded = 1 WHERE id = ?", pay["id"])
            return {"user_id": pay["user_id"], "stars": pay["stars"]}

    # ---------- реклама на главном экране ----------

    async def set_ad(self, title: str, text: str, url: str, button: str = "", icon: str = "") -> dict:
        title, text, url = title.strip(), text.strip(), url.strip()
        button, icon = (button.strip() or "Открыть"), (icon.strip() or "📣")
        if not 1 <= len(title) <= 40:
            raise GameError("Заголовок от 1 до 40 символов")
        if len(text) > 80:
            raise GameError("Текст не длиннее 80 символов")
        if not url.startswith("https://") or " " in url:
            raise GameError("Ссылка должна начинаться с https://")
        if len(button) > 16 or len(icon) > 4:
            raise GameError("Кнопка не длиннее 16 символов, значок — один эмодзи")
        ad = {"id": int(self.clock()), "title": title, "text": text, "url": url, "button": button, "icon": icon}
        await self.db.set_setting("ad", json.dumps(ad, ensure_ascii=False))
        self.ad = ad
        return ad

    async def clear_ad(self) -> None:
        await self.db.set_setting("ad", "")
        self.ad = None

    async def ad_event(self, uid: int, ad_id: int, kind: str) -> None:
        """Показ или переход по рекламе: счётчик на игрока и день, для статистики рекламодателю."""
        if kind not in ("view", "click") or not self.ad or self.ad["id"] != int(ad_id):
            return
        async with self.db.tx():
            await self._counter(uid, f"ad_{kind}:{ad_id}", 1)

    async def ad_stats(self) -> dict | None:
        if not self.ad:
            return None
        today = day_key(self.clock())
        out = {"ad": self.ad}
        for kind in ("view", "click"):
            key = f"ad_{kind}:{self.ad['id']}"
            row = await self.db.one("SELECT SUM(value), COUNT(DISTINCT user_id) FROM counters WHERE key = ?", key)
            day = await self.db.one("SELECT SUM(value), COUNT(DISTINCT user_id) FROM counters WHERE key = ? "
                                    "AND day = ?", key, today)
            out[kind] = {"total": row[0] or 0, "users": row[1], "today": day[0] or 0, "users_today": day[1]}
        return out

    # ---------- фоновые задачи ----------

    async def overflow_expire(self) -> int:
        """Предметы из переполнения старше 48 часов продаются системе по 60%."""
        async with self.db.tx():
            rows = await self.db.all("SELECT * FROM items WHERE state = 'overflow' AND overflow_until < ?", self.clock())
            pct = self.cfg["sell_system_pct"]
            for r in rows:
                cents = self.cfg["ladder_cents"][r["tier"]] * pct // 100
                await self.db.run("UPDATE items SET state = 'gone', gone_reason = 'overflow' WHERE id = ?", r["id"])
                await self._add(r["user_id"], cents=cents, reason="overflow_sold")
                u = await self._user(r["user_id"])
                await self.notify(r["user_id"], f"📦 Номер {phones.format_number(r['country'], r['op'], r['sub'])} "
                                                f"пролежал в переполнении 48 часов и продан за {self.money(cents, u)}")
            return len(rows)

    async def energy_reminders(self) -> None:
        async with self.db.tx():
            for r in await self.db.all("SELECT * FROM users WHERE energy_notify = 1 AND is_blocked = 0"):
                u = dict(r)
                if self._energy(u)[0] < 1:
                    continue
                before = len(self.outbox)
                await self.notify(u["id"], "⚡ Бесплатный спин готов! Заходи крутить")
                if len(self.outbox) > before:
                    await self.db.run("UPDATE users SET energy_notify = 0 WHERE id = ?", u["id"])

    async def admin_stats(self) -> dict:
        now = self.clock()
        ds = day_start(now)
        db = self.db
        dau = await db.val("SELECT COUNT(*) FROM users WHERE last_seen >= ?", ds)
        reasons = [dict(r) for r in await db.all(
            "SELECT reason, SUM(delta) AS cents FROM ledger WHERE currency = 'rub' AND created_at >= ? "
            "GROUP BY reason ORDER BY cents DESC", ds)]
        inflow = sum(r["cents"] for r in reasons if r["cents"] > 0 and not r["reason"].startswith(("sell", "market")))
        return {
            "users": await db.val("SELECT COUNT(*) FROM users"),
            "alive": await db.val("SELECT COUNT(*) FROM users WHERE is_blocked = 0"),
            "new_today": await db.val("SELECT COUNT(*) FROM users WHERE created_at >= ?", ds),
            "dau": dau,
            "spins_today": await db.val("SELECT COUNT(*) FROM drops WHERE action = 'spin' AND created_at >= ?", ds),
            "balance_total_cents": await db.val("SELECT SUM(balance_cents) FROM users"),
            "reasons": reasons,
            "inflow_per_active_cents": inflow // dau if dau else 0,
            "stars_month": await db.val("SELECT SUM(stars) FROM payments WHERE refunded = 0 AND created_at >= ?",
                                        month_start(now)),
            "stars_total": await db.val("SELECT SUM(stars) FROM payments WHERE refunded = 0"),
            "referrals": await db.val("SELECT COUNT(*) FROM users WHERE ref_qualified = 1"),
            "drops_by_tier": [dict(r) for r in await db.all(
                "SELECT tier, COUNT(*) AS n FROM drops WHERE action = 'spin' AND created_at >= ? GROUP BY tier "
                "ORDER BY tier", ds)],
            "editions_low": [dict(r) for r in await db.all(
                "SELECT tier, SUM(size - issued) AS left_n, SUM(size) AS size FROM editions WHERE size > 1 GROUP BY tier")],
        }
