"""Игровая логика. Всё решает сервер: клиент получает только готовый результат."""
import json
import random
import secrets
import time
from datetime import datetime, timedelta, timezone

from bot.db import Database
from bot.game import phones
from bot.game.settings import DEFAULTS, level_from_xp, merge
from bot.game.tiers import (CONTRACT_MAX_INPUT, CONTRACT_SIZE, DIVINE, EPIC, LEGENDARY, PHONE_PRICES,
                            RARE, SCALES, SECRET, TIERS, apply_luck, one_in, tier_dict)

MSK = timezone(timedelta(hours=3))
SETTINGS_KEYS = {"fast": False, "no_effects": False, "no_upgrader": False}


class GameError(Exception):
    def __init__(self, message: str, code: str = "error", **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra


def day_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, MSK).strftime("%Y-%m-%d")


def month_start(ts: float) -> float:
    d = datetime.fromtimestamp(ts, MSK)
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def chance_for(tier: int) -> int | None:
    for scale in ("phone", "premium"):
        p = SCALES[scale]["odds"].get(tier)
        if p:
            return one_in(p)
    return None


def item_dict(row) -> dict:
    c = phones.COUNTRIES[row["country"]]
    return {
        "id": row["id"],
        "country": row["country"],
        "flag": c.flag,
        "country_name": c.name,
        "dial": c.dial,
        "op": row["op"],
        "sub": row["sub"],
        "number": phones.format_number(row["country"], row["op"], row["sub"]),
        "tier": tier_dict(row["tier"]),
        "price": row["price"],
        "chance": chance_for(row["tier"]),
        "status": row["status"],
        "is_new": bool(row["is_new"]),
        "favorite": bool(row["favorite"]),
        "created_at": row["created_at"],
    }


class Game:
    def __init__(self, db: Database, stars_enabled: bool = False, clock=time.time):
        self.db = db
        self.cfg = merge(DEFAULTS, {})
        self.stars_enabled = stars_enabled
        self.clock = clock
        self.outbox: list[tuple[int, str]] = []

    async def load_config(self) -> None:
        raw = await self.db.get_setting("game_config")
        self.cfg = merge(DEFAULTS, json.loads(raw) if raw else {})

    @property
    def divine(self) -> tuple:
        return tuple(tuple(x) for x in self.cfg["divine"])

    def pop_outbox(self) -> list[tuple[int, str]]:
        out, self.outbox = self.outbox, []
        return out

    # ---------- внутренние помощники (вызываются внутри db.tx) ----------

    async def _user(self, uid: int) -> dict:
        row = await self.db.one("SELECT * FROM users WHERE id = ?", uid)
        if not row:
            raise GameError("Сначала запусти бота: /start", "no_user")
        return dict(row)

    async def _ledger(self, uid: int, currency: str, delta: int, reason: str) -> None:
        if delta:
            await self.db.run("INSERT INTO ledger (user_id, currency, delta, reason, created_at) "
                              "VALUES (?, ?, ?, ?, ?)", uid, currency, delta, reason, self.clock())

    async def _add(self, uid: int, coins: int = 0, spins: int = 0, reason: str = "") -> None:
        if coins or spins:
            await self.db.run("UPDATE users SET coins = coins + ?, spins = spins + ? WHERE id = ?",
                              coins, spins, uid)
            await self._ledger(uid, "coins", coins, reason)
            await self._ledger(uid, "spins", spins, reason)

    async def _counter(self, uid: int, key: str, inc: int = 0, day: str | None = None) -> int:
        day = day or day_key(self.clock())
        if inc:
            await self.db.run(
                "INSERT INTO counters (user_id, day, key, value) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, day, key) DO UPDATE SET value = value + excluded.value",
                uid, day, key, inc)
        return await self.db.val("SELECT value FROM counters WHERE user_id = ? AND day = ? AND key = ?",
                                 uid, day, key)

    def _energy(self, u: dict) -> tuple[int, float]:
        mx, period = self.cfg["energy_max"], self.cfg["energy_period_sec"]
        now = self.clock()
        e, ts = u["energy"], u["energy_ts"]
        if e >= mx:
            return e, now
        gained = int((now - ts) // period)
        if gained <= 0:
            return e, ts
        e = min(mx, e + gained)
        return e, (now if e >= mx else ts + gained * period)

    def _coin_spin_cap(self, u: dict) -> int:
        level = level_from_xp(u["xp"])[0]
        return min(self.cfg["coin_spins_daily_cap"], self.cfg["coin_spins_daily"] + level - 1)

    def _today_tasks(self, ts: float) -> list[dict]:
        pool = self.cfg["tasks"]
        rng = random.Random(day_key(ts))
        return rng.sample(pool, min(self.cfg["tasks_per_day"], len(pool)))

    async def _task_event(self, uid: int, event: str, n: int = 1) -> None:
        for t in self._today_tasks(self.clock()):
            if t["event"] == event:
                await self._counter(uid, "task:" + t["key"], n)

    async def notify(self, uid: int, text: str) -> None:
        """Не чаще 2 уведомлений в сутки и не с 21:00 до 8:00 по Москве."""
        hour = datetime.fromtimestamp(self.clock(), MSK).hour
        if hour >= 21 or hour < 8:
            return
        if await self._counter(uid, "notify") >= 2:
            return
        await self._counter(uid, "notify", 1)
        self.outbox.append((uid, text))

    async def _new_item(self, uid: int, tier: int, country: str, source: str,
                        rng: random.Random, scale: str = "", luck: float = 1, seed: str = "") -> dict:
        code, op, sub = phones.generate(tier, country, rng, self.divine)
        now = self.clock()
        cur = await self.db.run(
            "INSERT INTO items (user_id, country, op, sub, tier, price, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", uid, code, op, sub, tier, PHONE_PRICES[tier], source, now)
        await self.db.run(
            "INSERT INTO drops (user_id, item_id, tier, scale, luck, seed, odds_version, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            uid, cur.lastrowid, tier, scale or source, luck, seed, self.cfg["odds_version"], now)
        return item_dict(await self.db.one("SELECT * FROM items WHERE id = ?", cur.lastrowid))

    async def _owned(self, uid: int, ids: list[int], status: str = "owned") -> list[dict]:
        ids = list(dict.fromkeys(int(i) for i in ids))
        if not ids:
            raise GameError("Ничего не выбрано")
        marks = ",".join("?" * len(ids))
        rows = await self.db.all(
            f"SELECT * FROM items WHERE user_id = ? AND status = ? AND id IN ({marks})", uid, status, *ids)
        if len(rows) != len(ids):
            raise GameError("Часть номеров уже недоступна. Обнови коллекцию")
        return [dict(r) for r in rows]

    async def _collection_value(self, uid: int) -> int:
        return await self.db.val(
            "SELECT SUM(price) FROM items WHERE user_id = ? AND status IN ('owned', 'listed')", uid)

    async def _reward_referrer(self, ref_id: int, friend_name: str) -> None:
        await self.db.run("UPDATE users SET ref_count = ref_count + 1 WHERE id = ?", ref_id)
        ref = await self._user(ref_id)
        text = f"🎉 Твой друг {friend_name} сделал {self.cfg['referral']['required_spins']} спинов и засчитан!"
        for tier in self.cfg["referral"]["tiers"]:
            if tier["count"] == ref["ref_count"]:
                await self._add(ref_id, tier.get("coins", 0), tier.get("spins", 0), "referral")
                if tier.get("badge"):
                    badges = json.loads(ref["badges"])
                    badges.append(tier["badge"])
                    await self.db.run("UPDATE users SET badges = ? WHERE id = ?",
                                      json.dumps(badges, ensure_ascii=False), ref_id)
                text += f"\nНаграда за {tier['count']}: {tier['title']}"
        await self.notify(ref_id, text)

    # ---------- пользователь ----------

    async def ensure_user(self, uid: int, username: str | None, first_name: str | None,
                          ref_id: int | None = None) -> bool:
        async with self.db.tx():
            now = self.clock()
            row = await self.db.one("SELECT id FROM users WHERE id = ?", uid)
            if row:
                await self.db.run("UPDATE users SET username = ?, first_name = ?, last_seen = ?, "
                                  "is_blocked = 0 WHERE id = ?", username, first_name, now, uid)
                return False
            if ref_id is not None:
                ok = ref_id != uid and await self.db.one("SELECT id FROM users WHERE id = ?", ref_id)
                today = await self._counter(ref_id, "ref_invites") if ok else 0
                if not ok or today >= self.cfg["referral"]["daily_limit"]:
                    ref_id = None
            await self.db.run(
                "INSERT INTO users (id, username, first_name, ref_id, created_at, last_seen, coins, "
                "energy, energy_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                uid, username, first_name, ref_id, now, now, self.cfg["start_coins"],
                self.cfg["energy_max"], now)
            await self._ledger(uid, "coins", self.cfg["start_coins"], "start")
            if ref_id:
                await self._counter(ref_id, "ref_invites", 1)
                await self._add(uid, spins=self.cfg["referral"]["friend_spins"], reason="invited")
            return True

    async def state(self, uid: int) -> dict:
        now = self.clock()
        u = await self._user(uid)
        e, ets = self._energy(u)
        level, xp_in, need = level_from_xp(u["xp"])
        mx = self.cfg["energy_max"]
        today = day_key(now)
        yesterday = day_key(now - 86400)
        tasks = []
        for t in self._today_tasks(now):
            progress = await self._counter(uid, "task:" + t["key"])
            claimed = await self._counter(uid, "claimed:" + t["key"])
            tasks.append({"key": t["key"], "title": t["title"], "target": t["target"],
                          "progress": min(progress, t["target"]), "coins": t["coins"], "claimed": bool(claimed)})
        streak_next = (u["gift_streak"] % 7) + 1 if u["gift_day"] == yesterday else 1
        last = await self.db.one(
            "SELECT i.* FROM drops d JOIN items i ON i.id = d.item_id WHERE d.user_id = ? "
            "ORDER BY d.id DESC LIMIT 1", uid)
        luck = u["luck_mult"] if u["luck_left"] > 0 else 1
        odds = {}
        for key, sc in SCALES.items():
            boosted = apply_luck(sc["odds"], luck) if luck > 1 else sc["odds"]
            odds[key] = {"title": sc["title"], "price": sc["price"], "rows": [
                {"tier": tier_dict(t), "p": sc["odds"][t], "p_luck": boosted[t]}
                for t in sorted(sc["odds"])]}
        return {
            "user": {
                "id": u["id"], "name": u["first_name"] or "Игрок", "username": u["username"],
                "coins": u["coins"], "spins": u["spins"], "energy": e, "energy_max": mx,
                "next_energy_in": 0 if e >= mx else int(self.cfg["energy_period_sec"] - (now - ets)),
                "level": level, "xp": xp_in, "xp_need": need, "total_spins": u["total_spins"],
                "luck": luck, "luck_left": u["luck_left"], "country": u["country"],
                "settings": {**SETTINGS_KEYS, **json.loads(u["settings"])},
                "badges": json.loads(u["badges"]),
                "coin_spins_left": self._coin_spin_cap(u) - await self._counter(uid, "coin_spins"),
                "pity_epic_left": self.cfg["pity_epic"] - u["pity_epic"],
                "pity_legendary_left": self.cfg["pity_legendary"] - u["pity_legendary"],
                "created_at": u["created_at"],
            },
            "today": {
                "wheel": await self._counter(uid, "wheel") == 0,
                "gift": u["gift_day"] != today,
                "gift_day": streak_next if u["gift_day"] != today else u["gift_streak"],
                "gift_rewards": self.cfg["gift"],
                "tasks": tasks,
            },
            "wheel": [{"label": s["label"], "p": s["p"]} for s in self.cfg["wheel"]],
            "odds": odds,
            "countries": [{"code": c.code, "name": c.name, "flag": c.flag, "dial": c.dial}
                          for c in phones.COUNTRIES.values()],
            "tiers": [tier_dict(t.idx) for t in TIERS],
            "last_drop": item_dict(last) if last else None,
            "stars_enabled": self.stars_enabled,
        }

    async def set_country(self, uid: int, code: str) -> None:
        if code not in phones.COUNTRIES:
            raise GameError("Нет такой страны")
        async with self.db.tx():
            await self.db.run("UPDATE users SET country = ? WHERE id = ?", code, uid)

    async def update_settings(self, uid: int, values: dict) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            current = {**SETTINGS_KEYS, **json.loads(u["settings"])}
            for k, v in values.items():
                if k in SETTINGS_KEYS:
                    current[k] = bool(v)
            await self.db.run("UPDATE users SET settings = ? WHERE id = ?", json.dumps(current), uid)
            return current

    # ---------- спин ----------

    async def spin(self, uid: int, count: int = 1, scale: str = "phone") -> dict:
        if count not in (1, 5, 10):
            raise GameError("Можно крутить ×1, ×5 или ×10")
        if scale not in SCALES:
            raise GameError("Нет такого спина")
        async with self.db.tx():
            u = await self._user(uid)
            now = self.clock()
            e, ets = self._energy(u)
            price = SCALES[scale]["price"]
            coin_left = self._coin_spin_cap(u) - await self._counter(uid, "coin_spins")
            plan, coins, spins = [], u["coins"], u["spins"]
            for _ in range(count):
                if scale == "phone" and e - plan.count("energy") > 0:
                    plan.append("energy")
                elif scale == "phone" and spins - plan.count("spins") > 0:
                    plan.append("spins")
                elif coins - price * plan.count("coins") >= price and coin_left - plan.count("coins") > 0:
                    plan.append("coins")
                else:
                    break
            if len(plan) < count:
                if coin_left - plan.count("coins") <= 0:
                    raise GameError(f"Спины за монеты на сегодня закончились ({self._coin_spin_cap(u)} в сутки). "
                                    "Бесплатные спины и попытки работают", "limit")
                need = price * (count - len(plan)) - (coins - price * plan.count("coins"))
                raise GameError(f"Не хватает {need}", "no_coins", need=need)

            used_energy, used_spins, used_coins = plan.count("energy"), plan.count("spins"), plan.count("coins")
            e -= used_energy
            pity_e, pity_l = u["pity_epic"], u["pity_legendary"]
            luck_mult, luck_left = u["luck_mult"], u["luck_left"]
            drops = []
            for _ in range(count):
                seed = secrets.randbits(64)
                rng = random.Random(seed)
                odds = dict(SCALES[scale]["odds"])
                luck = luck_mult if luck_left > 0 else 1
                if luck > 1:
                    odds = apply_luck(odds, luck)
                    luck_left -= 1
                floor = LEGENDARY if pity_l + 1 >= self.cfg["pity_legendary"] else (
                    EPIC if pity_e + 1 >= self.cfg["pity_epic"] else None)
                if floor is not None:  # гарантия: Эпик не позже 40-го спина, Легендарный не позже 200-го
                    odds = {t: p for t, p in odds.items() if t >= floor}
                    total = sum(odds.values())
                    odds = {t: p / total for t, p in odds.items()}
                roll, acc, tier = rng.random(), 0.0, max(odds)
                for t in sorted(odds):
                    acc += odds[t]
                    if roll < acc:
                        tier = t
                        break
                pity_e = 0 if tier >= EPIC else pity_e + 1
                pity_l = 0 if tier >= LEGENDARY else pity_l + 1
                drops.append(await self._new_item(uid, tier, u["country"], "spin", rng, scale, luck, str(seed)))

            xp = u["xp"] + count * self.cfg["xp_premium" if scale == "premium" else "xp_spin"]
            total_spins = u["total_spins"] + count
            await self.db.run(
                "UPDATE users SET coins = coins - ?, spins = spins - ?, energy = ?, energy_ts = ?, "
                "energy_notify = CASE WHEN ? = 0 AND ? > 0 THEN 1 ELSE energy_notify END, "
                "pity_epic = ?, pity_legendary = ?, luck_left = ?, xp = ?, total_spins = ?, last_seen = ? "
                "WHERE id = ?",
                used_coins * price, used_spins, e, ets, e, used_energy, pity_e, pity_l, luck_left, xp,
                total_spins, now, uid)
            await self._ledger(uid, "coins", -used_coins * price, "spin")
            await self._ledger(uid, "spins", -used_spins, "spin")
            if used_coins:
                await self._counter(uid, "coin_spins", used_coins)
            spins_today = await self._counter(uid, "spins", count)
            await self._task_event(uid, "spin", count)

            req = self.cfg["referral"]["required_spins"]
            if u["ref_id"] and not u["ref_qualified"] and total_spins >= req:
                await self.db.run("UPDATE users SET ref_qualified = 1 WHERE id = ?", uid)
                await self._reward_referrer(u["ref_id"], u["first_name"] or "Друг")

            hint = self.cfg["break_hint_spins"]
            return {
                "drops": drops,
                "paid": {"energy": used_energy, "spins": used_spins, "coins": used_coins * price},
                "level_up": level_from_xp(xp)[0] > level_from_xp(u["xp"])[0],
                "level": level_from_xp(xp)[0],
                "break_hint": spins_today - count < hint <= spins_today,
            }

    # ---------- коллекция ----------

    async def collection(self, uid: int, min_tier: int = 0, q: str = "", favorites: bool = False) -> dict:
        rows = await self.db.all(
            "SELECT * FROM items WHERE user_id = ? AND status IN ('owned', 'listed') AND tier >= ? "
            "ORDER BY tier DESC, price DESC, id DESC", uid, min_tier)
        digits = "".join(ch for ch in q if ch.isdigit())
        items = [item_dict(r) for r in rows
                 if (not digits or digits in r["op"] + r["sub"]) and (not favorites or r["favorite"])]
        counts = await self.db.all(
            "SELECT tier, COUNT(*) AS n FROM items WHERE user_id = ? AND status IN ('owned', 'listed') "
            "GROUP BY tier", uid)
        return {"items": items, "counts": {r["tier"]: r["n"] for r in counts},
                "value": await self._collection_value(uid)}

    async def mark_seen(self, uid: int) -> None:
        async with self.db.tx():
            await self.db.run("UPDATE items SET is_new = 0 WHERE user_id = ? AND is_new = 1", uid)

    async def toggle_favorite(self, uid: int, item_id: int) -> bool:
        async with self.db.tx():
            row = await self.db.one("SELECT favorite FROM items WHERE id = ? AND user_id = ? "
                                    "AND status != 'gone'", item_id, uid)
            if not row:
                raise GameError("Номер не найден")
            await self.db.run("UPDATE items SET favorite = ? WHERE id = ?", 1 - row[0], item_id)
            return not row[0]

    async def sell(self, uid: int, ids: list[int]) -> dict:
        async with self.db.tx():
            items = await self._owned(uid, ids)
            total = sum(i["price"] for i in items)
            marks = ",".join("?" * len(items))
            await self.db.run(f"UPDATE items SET status = 'gone' WHERE id IN ({marks})", *[i["id"] for i in items])
            await self._add(uid, coins=total, reason="sell")
            await self._task_event(uid, "sell", len(items))
            return {"coins": total, "sold": len(items)}

    async def bulk_preview(self, uid: int, max_tier: int) -> dict:
        max_tier = min(int(max_tier), RARE)
        row = await self.db.one(
            "SELECT COUNT(*), COALESCE(SUM(price), 0) FROM items WHERE user_id = ? AND status = 'owned' "
            "AND favorite = 0 AND tier <= ?", uid, max_tier)
        return {"count": row[0], "coins": row[1], "max_tier": max_tier}

    async def bulk_sell(self, uid: int, max_tier: int) -> dict:
        max_tier = min(int(max_tier), RARE)
        rows = await self.db.all("SELECT id FROM items WHERE user_id = ? AND status = 'owned' "
                                 "AND favorite = 0 AND tier <= ?", uid, max_tier)
        if not rows:
            raise GameError("Нечего продавать: избранное не продаётся пачкой")
        return await self.sell(uid, [r[0] for r in rows])

    async def contract(self, uid: int, ids: list[int]) -> dict:
        async with self.db.tx():
            items = await self._owned(uid, ids)
            if len(items) != CONTRACT_SIZE:
                raise GameError(f"Нужно ровно {CONTRACT_SIZE} номеров одной ступени")
            tiers = {i["tier"] for i in items}
            if len(tiers) != 1:
                raise GameError("Все 5 номеров должны быть одной ступени")
            tier = tiers.pop()
            if tier > CONTRACT_MAX_INPUT:
                raise GameError("Эту ступень нельзя улучшить")
            marks = ",".join("?" * len(items))
            await self.db.run(f"UPDATE items SET status = 'gone' WHERE id IN ({marks})", *[i["id"] for i in items])
            seed = secrets.randbits(64)
            rng = random.Random(seed)
            item = await self._new_item(uid, tier + 1, rng.choice(items)["country"], "contract", rng,
                                        seed=str(seed))
            await self._task_event(uid, "contract")
            return {"item": item}

    # ---------- апгрейдер ----------

    async def _upgrade_calc(self, uid: int, ids: list[int], coins: int, target: int) -> dict:
        cfg = self.cfg["upgrade"]
        u = await self._user(uid)
        if json.loads(u["settings"]).get("no_upgrader"):
            raise GameError("Апгрейдер выключен в настройках")
        if len(ids) > cfg["max_items"]:
            raise GameError(f"Не больше {cfg['max_items']} номеров за раз")
        coins = max(0, int(coins))
        items = await self._owned(uid, ids) if ids else []
        if coins > u["coins"]:
            raise GameError("Не хватает монет")
        stake = sum(i["price"] for i in items) + coins
        if stake <= 0:
            raise GameError("Положи номер или монеты")
        if not (0 <= target <= SECRET):
            raise GameError("Такую цель нельзя выбрать")
        target_price = PHONE_PRICES[target]
        if target_price <= stake:
            raise GameError("Цель должна стоить дороже ставки")
        value = await self._collection_value(uid) + u["coins"]
        if stake > value / 2:
            raise GameError("За раз можно поставить не больше половины стоимости коллекции")
        base = stake / target_price * cfg["k"]
        chance = min(cfg["max_chance"], base + u["upgrade_bonus"])
        return {"items": items, "coins": coins, "stake": stake, "target": target, "target_price": target_price,
                "chance": round(chance, 4), "base_chance": round(base, 4), "bonus": u["upgrade_bonus"],
                "left_today": cfg["daily"] - await self._counter(uid, "upgrades")}

    async def upgrade_quote(self, uid: int, ids: list[int], coins: int, target: int) -> dict:
        q = await self._upgrade_calc(uid, ids, coins, target)
        q.pop("items")
        return q

    async def upgrade(self, uid: int, ids: list[int], coins: int, target: int) -> dict:
        async with self.db.tx():
            q = await self._upgrade_calc(uid, ids, coins, target)
            if q["left_today"] <= 0:
                raise GameError("На сегодня апгрейды закончились (10 в сутки)")
            await self._counter(uid, "upgrades", 1)
            if q["items"]:
                marks = ",".join("?" * len(q["items"]))
                await self.db.run(f"UPDATE items SET status = 'gone' WHERE id IN ({marks})",
                                  *[i["id"] for i in q["items"]])
            await self._add(uid, coins=-q["coins"], reason="upgrade")
            seed = secrets.randbits(64)
            rng = random.Random(seed)
            roll = rng.random()
            success = roll < q["chance"]
            result = {"success": success, "chance": q["chance"], "roll": round(roll, 4)}
            if success:
                country = rng.choice(q["items"])["country"] if q["items"] else "RU"
                result["item"] = await self._new_item(uid, target, country, "upgrade", rng, seed=str(seed))
                await self.db.run("UPDATE users SET upgrade_bonus = 0 WHERE id = ?", uid)
            else:
                refund = int(q["stake"] * self.cfg["upgrade"]["refund"])
                await self._add(uid, coins=refund, reason="upgrade_parts")
                await self.db.run("UPDATE users SET upgrade_bonus = upgrade_bonus + ? WHERE id = ?",
                                  self.cfg["upgrade"]["fail_bonus"], uid)
                result["parts"] = refund
                result["next_bonus"] = round(q["bonus"] + self.cfg["upgrade"]["fail_bonus"], 4)
            return result

    # ---------- рынок за монеты ----------

    async def _expire_lots(self) -> None:
        now = self.clock()
        rows = await self.db.all("SELECT id, item_id FROM lots WHERE status = 'active' AND expires_at < ?", now)
        for r in rows:
            await self.db.run("UPDATE lots SET status = 'expired', closed_at = ? WHERE id = ?", now, r["id"])
            await self.db.run("UPDATE items SET status = 'owned' WHERE id = ? AND status = 'listed'", r["item_id"])

    async def _check_trader(self, u: dict) -> None:
        hours = self.cfg["market"]["new_account_hours"]
        if self.clock() - u["created_at"] < hours * 3600:
            raise GameError(f"Торговать можно через {hours} ч после первого входа", "new_account")

    def _lot_dict(self, r) -> dict:
        d = item_dict(r)
        d.update({"lot_id": r["lot_id"], "lot_price": r["lot_price"], "seller_id": r["seller_id"],
                  "seller": r["seller_name"] or "Игрок", "expires_at": r["expires_at"]})
        return d

    async def market(self, uid: int, min_tier: int = 0, country: str = "", sort: str = "new") -> dict:
        async with self.db.tx():
            await self._expire_lots()
            await self._task_event(uid, "market")
        order = {"new": "l.id DESC", "cheap": "l.price ASC", "rare": "i.tier DESC, l.price DESC"}.get(sort, "l.id DESC")
        rows = await self.db.all(
            "SELECT i.*, l.id AS lot_id, l.price AS lot_price, l.seller_id, l.expires_at, "
            "u.first_name AS seller_name FROM lots l JOIN items i ON i.id = l.item_id "
            "JOIN users u ON u.id = l.seller_id WHERE l.status = 'active' AND i.tier >= ? "
            f"AND (? = '' OR i.country = ?) ORDER BY {order} LIMIT 100", min_tier, country, country)
        return {"lots": [self._lot_dict(r) for r in rows], "fee": self.cfg["market"]["fee"]}

    async def my_lots(self, uid: int) -> dict:
        rows = await self.db.all(
            "SELECT i.*, l.id AS lot_id, l.price AS lot_price, l.seller_id, l.expires_at, l.status AS lot_status, "
            "l.closed_at, u.first_name AS seller_name FROM lots l JOIN items i ON i.id = l.item_id "
            "JOIN users u ON u.id = l.seller_id WHERE l.seller_id = ? OR l.buyer_id = ? "
            "ORDER BY l.id DESC LIMIT 50", uid, uid)
        active, deals = [], []
        for r in rows:
            d = self._lot_dict(r)
            d["lot_status"] = r["lot_status"]
            d["side"] = "sell" if r["seller_id"] == uid else "buy"
            (active if r["lot_status"] == "active" and r["seller_id"] == uid else deals).append(d)
        return {"active": active, "deals": [d for d in deals if d["lot_status"] == "sold"]}

    async def list_lot(self, uid: int, item_id: int, price: int) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            await self._check_trader(u)
            item = (await self._owned(uid, [item_id]))[0]
            m = self.cfg["market"]
            active = await self.db.val("SELECT COUNT(*) FROM lots WHERE seller_id = ? AND status = 'active'", uid)
            if active >= m["max_lots"]:
                raise GameError(f"Не больше {m['max_lots']} лотов одновременно")
            lo, hi = int(item["price"] * m["min_k"]), int(item["price"] * m["max_k"])
            price = int(price)
            if not lo <= price <= hi:
                raise GameError(f"Цена должна быть от {lo} до {hi}", "price_range", min=lo, max=hi)
            now = self.clock()
            await self.db.run("UPDATE items SET status = 'listed' WHERE id = ?", item_id)
            cur = await self.db.run("INSERT INTO lots (item_id, seller_id, price, created_at, expires_at) "
                                    "VALUES (?, ?, ?, ?, ?)", item_id, uid, price, now, now + m["lot_days"] * 86400)
            return {"lot_id": cur.lastrowid, "you_get": price - int(price * m["fee"])}

    async def cancel_lot(self, uid: int, lot_id: int) -> None:
        async with self.db.tx():
            lot = await self.db.one("SELECT * FROM lots WHERE id = ? AND seller_id = ? AND status = 'active'",
                                    lot_id, uid)
            if not lot:
                raise GameError("Лот уже закрыт")
            await self.db.run("UPDATE lots SET status = 'cancelled', closed_at = ? WHERE id = ?", self.clock(), lot_id)
            await self.db.run("UPDATE items SET status = 'owned' WHERE id = ?", lot["item_id"])

    async def buy_lot(self, uid: int, lot_id: int) -> dict:
        async with self.db.tx():
            await self._expire_lots()
            u = await self._user(uid)
            await self._check_trader(u)
            lot = await self.db.one("SELECT * FROM lots WHERE id = ? AND status = 'active'", lot_id)
            if not lot:
                raise GameError("Этот лот уже купили или сняли")
            if lot["seller_id"] == uid:
                raise GameError("Нельзя купить свой лот")
            if u["coins"] < lot["price"]:
                raise GameError(f"Не хватает {lot['price'] - u['coins']}", "no_coins",
                                need=lot["price"] - u["coins"])
            fee = int(lot["price"] * self.cfg["market"]["fee"])
            now = self.clock()
            await self._add(uid, coins=-lot["price"], reason="market_buy")
            await self._add(lot["seller_id"], coins=lot["price"] - fee, reason="market_sell")
            await self.db.run("UPDATE lots SET status = 'sold', buyer_id = ?, closed_at = ? WHERE id = ?",
                              uid, now, lot_id)
            await self.db.run("UPDATE items SET user_id = ?, status = 'owned', is_new = 1, favorite = 0 "
                              "WHERE id = ?", uid, lot["item_id"])
            item = item_dict(await self.db.one("SELECT * FROM items WHERE id = ?", lot["item_id"]))
            await self.notify(lot["seller_id"], f"💰 Твой номер {item['number']} купили за "
                                                f"{lot['price']} 🪙. Тебе +{lot['price'] - fee} 🪙")
            return {"item": item}

    # ---------- колесо, подарок дня, задания ----------

    async def wheel_spin(self, uid: int) -> dict:
        async with self.db.tx():
            await self._user(uid)
            if await self._counter(uid, "wheel"):
                raise GameError("Колесо уже крутил сегодня. Следующее завтра", "used")
            sectors = self.cfg["wheel"]
            roll, acc, idx = secrets.randbelow(10**9) / 10**9, 0.0, len(sectors) - 1
            for i, s in enumerate(sectors):
                acc += s["p"]
                if roll < acc:
                    idx = i
                    break
            s = sectors[idx]
            await self._counter(uid, "wheel", 1)
            await self._add(uid, s.get("coins", 0), s.get("spins", 0), "wheel")
            await self._task_event(uid, "wheel")
            return {"index": idx, "label": s["label"], "coins": s.get("coins", 0), "spins": s.get("spins", 0)}

    async def gift_claim(self, uid: int) -> dict:
        async with self.db.tx():
            u = await self._user(uid)
            now = self.clock()
            today, yesterday = day_key(now), day_key(now - 86400)
            if u["gift_day"] == today:
                raise GameError("Подарок уже забран. Возвращайся завтра", "used")
            streak = (u["gift_streak"] % 7) + 1 if u["gift_day"] == yesterday else 1
            reward = self.cfg["gift"][streak - 1]
            coins, spins = (reward, 0) if isinstance(reward, int) else (reward.get("coins", 0), reward.get("spins", 0))
            await self.db.run("UPDATE users SET gift_day = ?, gift_streak = ? WHERE id = ?", today, streak, uid)
            await self._add(uid, coins, spins, "gift")
            return {"day": streak, "coins": coins, "spins": spins}

    async def task_claim(self, uid: int, key: str) -> dict:
        async with self.db.tx():
            task = next((t for t in self._today_tasks(self.clock()) if t["key"] == key), None)
            if not task:
                raise GameError("Такого задания сегодня нет")
            if await self._counter(uid, "claimed:" + key):
                raise GameError("Награда уже получена")
            if await self._counter(uid, "task:" + key) < task["target"]:
                raise GameError("Задание ещё не выполнено")
            await self._counter(uid, "claimed:" + key, 1)
            await self._add(uid, coins=task["coins"], reason="task")
            return {"coins": task["coins"]}

    # ---------- друзья и рейтинг ----------

    async def friends(self, uid: int) -> dict:
        u = await self._user(uid)
        rows = await self.db.all("SELECT id, first_name, total_spins, ref_qualified FROM users "
                                 "WHERE ref_id = ? ORDER BY created_at DESC LIMIT 100", uid)
        req = self.cfg["referral"]["required_spins"]
        return {
            "count": u["ref_count"], "required_spins": req,
            "friend_spins": self.cfg["referral"]["friend_spins"],
            "tiers": self.cfg["referral"]["tiers"],
            "friends": [{"name": r["first_name"] or "Друг", "spins": min(r["total_spins"], req),
                         "qualified": bool(r["ref_qualified"])} for r in rows],
        }

    async def rating(self, uid: int, kind: str = "value", scope: str = "all") -> dict:
        async with self.db.tx():
            await self._task_event(uid, "rating")
        if kind == "best":
            sql = ("SELECT u.id, u.first_name, MAX(i.tier * 1000000000 + i.price) AS score FROM users u "
                   "JOIN items i ON i.user_id = u.id AND i.status IN ('owned', 'listed') GROUP BY u.id")
        else:
            sql = ("SELECT u.id, u.first_name, SUM(i.price) AS score FROM users u "
                   "JOIN items i ON i.user_id = u.id AND i.status IN ('owned', 'listed') GROUP BY u.id")
        rows = [dict(r) for r in await self.db.all(sql)]
        if scope == "friends":
            u = await self._user(uid)
            circle = {uid, u["ref_id"]} | {r[0] for r in await self.db.all("SELECT id FROM users WHERE ref_id = ?", uid)}
            rows = [r for r in rows if r["id"] in circle]
        rows.sort(key=lambda r: r["score"], reverse=True)
        out = []
        for pos, r in enumerate(rows, 1):
            entry = {"pos": pos, "id": r["id"], "name": r["first_name"] or "Игрок", "me": r["id"] == uid}
            if kind == "best":
                best = await self.db.one(
                    "SELECT * FROM items WHERE user_id = ? AND status IN ('owned', 'listed') "
                    "ORDER BY tier DESC, price DESC LIMIT 1", r["id"])
                entry["item"] = item_dict(best)
            else:
                entry["value"] = r["score"]
            out.append(entry)
        mine = next((e for e in out if e["me"]), None)
        return {"top": out[:50], "me": mine}

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
        return {
            "enabled": self.stars_enabled,
            "products": [{"key": k, **v} for k, v in s["products"].items()],
            "month_spent": await self._month_spent(uid),
            "month_cap": s["monthly_cap_stars"],
            "spins_stock_cap": s["spins_stock_cap"],
        }

    async def check_purchase(self, uid: int, key: str) -> dict:
        if not self.stars_enabled:
            raise GameError("Магазин пока закрыт", "shop_closed")
        s = self.cfg["shop"]
        p = s["products"].get(key)
        if not p:
            raise GameError("Нет такого товара")
        u = await self._user(uid)
        spent = await self._month_spent(uid)
        if spent + p["stars"] > s["monthly_cap_stars"]:
            raise GameError(f"Месячный лимит покупок {s['monthly_cap_stars']} ⭐. Осталось "
                            f"{s['monthly_cap_stars'] - spent} ⭐. Повысить можно через /paysupport", "cap")
        if p.get("spins"):
            if u["spins"] + p["spins"] > s["spins_stock_cap"]:
                raise GameError(f"Запас попыток не больше {s['spins_stock_cap']}. Сначала потрать текущие", "stock")
            if await self._counter(uid, "bought_spins") + p["spins"] > s["spins_daily_cap"]:
                raise GameError(f"За сутки можно купить не больше {s['spins_daily_cap']} попыток", "daily")
        if p.get("luck"):
            if u["luck_left"] > 0 and u["luck_mult"] > p["luck"]:
                raise GameError("Уже действует более сильная удача", "luck_active")
            if p["luck"] >= 2 and await self._counter(uid, "luck2") >= s["luck2_daily"]:
                raise GameError(f"Удачу ×2 можно купить не больше {s['luck2_daily']} раз в сутки", "daily")
        return {"key": key, **p}

    async def grant_purchase(self, uid: int, key: str, charge_id: str, stars: int) -> dict:
        async with self.db.tx():
            if await self.db.one("SELECT 1 FROM payments WHERE charge_id = ?", charge_id):
                return {"duplicate": True}
            p = self.cfg["shop"]["products"][key]
            await self.db.run("INSERT INTO payments (user_id, product, stars, charge_id, created_at) "
                              "VALUES (?, ?, ?, ?, ?)", uid, key, stars, charge_id, self.clock())
            if p.get("spins"):
                await self._add(uid, spins=p["spins"], reason="purchase")
                await self._counter(uid, "bought_spins", p["spins"])
            if p.get("luck"):
                await self.db.run("UPDATE users SET luck_mult = ?, luck_left = ? WHERE id = ?",
                                  p["luck"], self.cfg["shop"]["luck_spins"], uid)
                if p["luck"] >= 2:
                    await self._counter(uid, "luck2", 1)
            return {"granted": p["title"]}

    async def revoke_purchase(self, charge_id: str) -> dict:
        """Возврат: снимаем неиспользованное. Использованные попытки не возвращаются."""
        async with self.db.tx():
            pay = await self.db.one("SELECT * FROM payments WHERE charge_id = ? AND refunded = 0", charge_id)
            if not pay:
                raise GameError("Платёж не найден или уже возвращён")
            p = self.cfg["shop"]["products"][pay["product"]]
            u = await self._user(pay["user_id"])
            if p.get("spins"):
                take = min(u["spins"], p["spins"])
                await self._add(u["id"], spins=-take, reason="refund")
            if p.get("luck") and u["luck_mult"] == p["luck"]:
                await self.db.run("UPDATE users SET luck_left = 0 WHERE id = ?", u["id"])
            await self.db.run("UPDATE payments SET refunded = 1 WHERE id = ?", pay["id"])
            return {"user_id": pay["user_id"], "stars": pay["stars"]}

    # ---------- фоновые уведомления и статистика ----------

    async def energy_reminders(self) -> None:
        async with self.db.tx():
            rows = await self.db.all("SELECT * FROM users WHERE energy_notify = 1 AND is_blocked = 0")
            for r in rows:
                u = dict(r)
                e, _ = self._energy(u)
                if e < 1:
                    continue
                before = len(self.outbox)
                await self.notify(u["id"], "⚡ Бесплатный спин готов! Заходи крутить")
                if len(self.outbox) > before:
                    await self.db.run("UPDATE users SET energy_notify = 0 WHERE id = ?", u["id"])

    async def admin_stats(self) -> dict:
        now = self.clock()
        day_start = datetime.fromtimestamp(now, MSK).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        db = self.db
        return {
            "users": await db.val("SELECT COUNT(*) FROM users"),
            "alive": await db.val("SELECT COUNT(*) FROM users WHERE is_blocked = 0"),
            "new_today": await db.val("SELECT COUNT(*) FROM users WHERE created_at >= ?", day_start),
            "dau": await db.val("SELECT COUNT(*) FROM users WHERE last_seen >= ?", day_start),
            "spins_today": await db.val("SELECT COUNT(*) FROM drops WHERE created_at >= ? AND scale IN "
                                        "('phone', 'premium')", day_start),
            "coins_total": await db.val("SELECT SUM(coins) FROM users"),
            "coins_in_today": await db.val("SELECT SUM(delta) FROM ledger WHERE currency = 'coins' AND delta > 0 "
                                           "AND created_at >= ?", day_start),
            "coins_out_today": -await db.val("SELECT SUM(delta) FROM ledger WHERE currency = 'coins' AND delta < 0 "
                                             "AND created_at >= ?", day_start),
            "stars_month": await db.val("SELECT SUM(stars) FROM payments WHERE refunded = 0 AND created_at >= ?",
                                        month_start(now)),
            "stars_total": await db.val("SELECT SUM(stars) FROM payments WHERE refunded = 0"),
            "referrals": await db.val("SELECT COUNT(*) FROM users WHERE ref_qualified = 1"),
            "top_drops": [dict(r) for r in await db.all(
                "SELECT tier, COUNT(*) AS n FROM drops WHERE created_at >= ? GROUP BY tier ORDER BY tier",
                day_start)],
        }
