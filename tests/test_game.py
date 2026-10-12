"""Проверки из docs/TASKS.md (M0–M7), перенесённые на наш стек."""
import asyncio
import datetime
import hashlib
import hmac
import json
import random
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Config
from bot.db import Database
from bot.game import fair, phones
from bot.game.odds import consolidated, solve_level, with_pity
from bot.game.service import Game, GameError
from bot.game.settings import DEFAULTS, fmt_money, level, level_return, merge, normalize, validate
from bot.game.tiers import (COMMON, EPIC, LEGENDARY, MYTHIC, RARE, SECRET, UNCOMMON, apply_luck,
                            expected_value)
from bot.web import create_app

CFG = normalize(merge(DEFAULTS, {}))


def run(coro):
    return asyncio.run(coro)


# ---------- M0: конфиг и экономика ----------

def test_config_economy_matches_spec():
    assert validate(CFG) == []
    common = level(CFG, "common")
    assert level_return(CFG, common, False) == pytest.approx(0.776, abs=0.001)
    assert level_return(CFG, common) == pytest.approx(0.805, abs=0.001)
    for key, target in (("rare", 0.81), ("epic", 0.80), ("legendary", 0.80), ("elite", 0.80)):
        assert level_return(CFG, level(CFG, key)) == pytest.approx(target, abs=0.0015)
    ev = sum(s["p"] * (s.get("cents", 0) + s.get("attempts", 0) * 100_000) for s in CFG["wheel_daily"]) / 100
    assert ev == pytest.approx(1080, abs=10)


def test_level_solver_reproduces_tables():
    rare = solve_level(CFG["ladder_cents"], 300_000, RARE, SECRET)
    assert rare[RARE] == pytest.approx(0.8215, abs=0.0002)
    assert rare[EPIC] == pytest.approx(0.1531, abs=0.0001)
    epic = solve_level(CFG["ladder_cents"], 1_000_000, EPIC, SECRET)
    assert epic[EPIC] == pytest.approx(0.8735, abs=0.0001)


def test_config_validation_rejects_bad_versions():
    bad = normalize(merge(DEFAULTS, {}))
    bad["levels"][0]["odds"][0] = 0.5
    assert validate(bad)
    rich = normalize(merge(DEFAULTS, {}))
    rich["levels"][1]["odds"] = {2: .5, 3: .3, 4: .15, 5: .04, 6: .01}
    assert any("возврат" in e for e in validate(rich))


# ---------- M1: шансы, удача, гарантии, честный бросок ----------

def test_consolidated_and_luck_match_spec():
    c = consolidated(level(CFG, "common")["odds"], CFG["pity"])
    assert c[EPIC] == pytest.approx(0.0329, abs=0.0001)
    assert c[LEGENDARY] == pytest.approx(0.0103, abs=0.0001)
    lucky = apply_luck(level(CFG, "common")["odds"], 2)
    assert lucky[EPIC] == pytest.approx(0.057)
    assert lucky[COMMON] == pytest.approx(0.5551, abs=0.0001)


def test_pity_simulation():
    """100 000 спинов: частоты совпадают с consolidated, серий без Эпика длиннее 59 нет."""
    odds = level(CFG, "common")["odds"]
    expect = consolidated(odds, CFG["pity"])
    rng = random.Random(11)
    n, pe, pl, longest = 100_000, 0, 0, 0
    hits = {t: 0 for t in odds}
    for _ in range(n):
        tier = fair.pick_tier(rng.random(), with_pity(odds, CFG["pity"], pe, pl))
        hits[tier] += 1
        pe = 0 if tier >= EPIC else pe + 1
        pl = 0 if tier >= LEGENDARY else pl + 1
        longest = max(longest, pe)
    assert longest <= 59
    for t in (EPIC, LEGENDARY):
        p = expect[t]
        sigma = (p * (1 - p) / n) ** 0.5
        assert abs(hits[t] / n - p) < 3 * sigma


def test_fair_roll_matches_reference_formula():
    ss = "9f" * 32
    h = hmac.new(bytes.fromhex(ss), b"artem:1:0", hashlib.sha256).hexdigest()
    assert fair.roll(ss, "artem", 1) == int(h[:13], 16) / 2 ** 52
    a = fair.FairRandom(ss, "artem", 1)
    b = fair.FairRandom(ss, "artem", 1)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]
    assert phones.generate(EPIC, fair.FairRandom(ss, "x", 3), weights={"RU": 1}) == \
        phones.generate(EPIC, fair.FairRandom(ss, "x", 3), weights={"RU": 1})


# ---------- M2: генератор номеров ----------

@pytest.mark.parametrize("op,sub,tier", [
    ("912", "3846105", COMMON), ("912", "3846100", UNCOMMON), ("912", "7773405", RARE),
    ("912", "3841221", RARE), ("912", "3847777", EPIC), ("912", "3841234", EPIC), ("912", "3847788", EPIC),
    ("912", "3777777", LEGENDARY), ("912", "7777777", MYTHIC), ("912", "1234567", MYTHIC),
    ("987", "6543210", MYTHIC), ("912", "3443219", SECRET),
])
def test_classifier_examples_from_spec(op, sub, tier):
    assert phones.classify("RU", op, sub)[0] == tier


def test_generator_100k():
    rng = random.Random(3)
    w = CFG["number_country_weights"]
    for i in range(100_000):
        tier = i % 7
        code, op, sub, rule, hl = phones.generate(tier, rng, weights=w)
        assert phones.classify(code, op, sub)[0] == tier
        assert not phones.is_blacklisted(op + sub)
    assert len(phones.mythic_candidates(phones.COUNTRIES["RU"])) == 18 * 100


# ---------- сервис ----------

class Clock:
    def __init__(self, t=1_800_000_000.0):  # 15.01.2027 11:00 МСК — не ночь
        self.t = t

    def __call__(self):
        return self.t


async def make_game():
    db = Database(":memory:")
    await db.connect()
    clock = Clock()
    return Game(db, stars_enabled=True, clock=clock), db, clock


async def ledger_ok(db, uid):
    led = await db.val("SELECT SUM(delta) FROM ledger WHERE user_id = ? AND currency = 'rub'", uid)
    bal = await db.val("SELECT balance_cents FROM users WHERE id = ?", uid)
    att_l = await db.val("SELECT SUM(delta) FROM ledger WHERE user_id = ? AND currency = 'attempts'", uid)
    att = await db.val("SELECT attempts FROM users WHERE id = ?", uid)
    return led == bal and att_l == att


def test_mythic_edition_of_five_under_concurrency():
    async def scenario():
        g, db, _ = await make_game()
        try:
            await g.ensure_user(1, None, "A")

            async def issue():
                async with db.tx():
                    rng = random.Random(0)  # каждый раз тот же номер — проверяем тираж
                    return await g._issue(1, MYTHIC, rng, "test", "free", "RU")

            items = await asyncio.gather(*(issue() for _ in range(50)))
            same = [i for i in items if i["number"] == items[0]["number"]]
            assert sorted(i["copy"]["no"] for i in same) == [1, 2, 3, 4, 5]
            assert all(i["copy"]["of"] == 5 for i in same)
        finally:
            await db.close()
    run(scenario())


def test_spin_levels_energy_confirm_and_currency():
    async def scenario():
        g, db, clock = await make_game()
        try:
            await g.ensure_user(1, None, "Ru", "ru")
            await g.ensure_user(2, None, "Kz", "kk")
            me1, me2 = await g.me(1), await g.me(2)
            assert me2["country"] == "KZ" and me2["currency"]["symbol"] == "₸"
            r = await g.spin(1, "common", 3)
            assert r["paid"] == {"energy": 3, "attempts": 0, "cents": 0}
            r1 = await g.spin(1, "common", 1)
            await g.spin(2, "common", 3)
            r2 = await g.spin(2, "common", 1)
            assert r1["paid"]["cents"] == r2["paid"]["cents"] == 100_000  # одинаково копеек рубля
            with pytest.raises(GameError) as e:
                await g.spin(1, "rare", 3)
            assert e.value.code == "NOT_ENOUGH_COINS"
            async with db.tx():
                await g._add(1, 10_000_000, 0, "admin")
            with pytest.raises(GameError) as e:
                await g.spin(1, "legendary", 1)
            assert e.value.code == "CONFIRM_REQUIRED"
            r = await g.spin(1, "legendary", 1, confirmed=True)
            assert r["drops"][0]["tier"]["idx"] >= LEGENDARY
            clock.t += 3 * 3600 + 1
            assert (await g.me(1))["energy"]["now"] == 1
            assert await ledger_ok(db, 1) and await ledger_ok(db, 2)
            await g.set_country(2, "KZ")  # первое подтверждение страны — сразу
            await g.set_country(2, "RU")  # первая смена после подтверждения
            with pytest.raises(GameError) as e:
                await g.set_country(2, "BY")  # вторая — только через 30 дней
            assert e.value.code == "NOT_ALLOWED_YET"
            clock.t += 31 * 86400
            await g.set_country(2, "BY")
        finally:
            await db.close()
    run(scenario())


def test_starter_x5_guarantees_rare():
    async def scenario():
        g, db, _ = await make_game()
        try:
            for uid in range(1, 21):
                await g.ensure_user(uid, None, "P")
                r = await g.spin(uid, "common", 5)
                assert max(d["tier"]["idx"] for d in r["drops"]) >= RARE
                assert r["starter"]
        finally:
            await db.close()
    run(scenario())


def test_sell_60_undo_lock_and_bulk():
    async def scenario():
        g, db, _ = await make_game()
        try:
            await g.ensure_user(1, None, "A")
            async with db.tx():
                items = [await g._issue(1, t, random.Random(t), "test") for t in (COMMON, UNCOMMON, RARE, LEGENDARY)]
            bal0 = (await g.me(1))["balance_cents"]
            s = await g.sell(1, [items[0]["id"], items[1]["id"]])
            assert s["cents"] == (10_000 + 30_000) * 60 // 100
            await g.undo_sale(1, s["sale_id"])
            assert (await g.me(1))["balance_cents"] == bal0
            assert {i["id"] for i in (await g.collection(1))["items"]} >= {items[0]["id"], items[1]["id"]}
            await g.set_lock(1, items[2]["id"], True)
            with pytest.raises(GameError) as e:
                await g.sell(1, [items[2]["id"]])
            assert e.value.code == "ITEM_LOCKED"
            with pytest.raises(GameError):
                await g.sell(1, [items[3]["id"], items[0]["id"]], True)  # Легендарный только по одному
            q = await g.sell_quote(1, "below_rare")
            assert set(q["ids"]) == {items[0]["id"], items[1]["id"]}
            assert await ledger_ok(db, 1)
        finally:
            await db.close()
    run(scenario())


def test_overflow_and_capacity():
    async def scenario():
        g, db, clock = await make_game()
        try:
            await g.ensure_user(1, None, "A")
            g.cfg["inventory"]["slots"] = 2
            g.cfg["inventory"]["overflow_slots"] = 2
            r = await g.spin(1, "common", 3)
            assert r["overflow"] == 1
            await g.spin(1, "common", 1)
            with pytest.raises(GameError) as e:
                await g.spin(1, "common", 1)
            assert e.value.code == "INVENTORY_FULL"
            clock.t += 49 * 3600
            assert await g.overflow_expire() == 2
            assert await ledger_ok(db, 1)
        finally:
            await db.close()
    run(scenario())


def test_contract_and_upgrade_rules():
    async def scenario():
        g, db, _ = await make_game()
        try:
            await g.ensure_user(1, None, "A")
            async with db.tx():
                low = [(await g._issue(1, COMMON, random.Random(i), "t"))["id"] for i in range(5)]
                epics = [(await g._issue(1, EPIC, random.Random(100 + i), "t"))["id"] for i in range(5)]
                await g._add(1, 10_000_000, 0, "admin")
            r = await g.contract(1, low)
            assert r["success"] and r["item"]["tier"]["idx"] == UNCOMMON
            r = await g.contract(1, epics)
            assert r["item"]["tier"]["idx"] == (LEGENDARY if r["success"] else EPIC)
            q = await g.upgrade_quote(1, [], 100_000, EPIC)
            assert q["chance"] == pytest.approx(100_000 / 400_000 * 0.8)
            q = await g.upgrade_quote(1, [], 1_900_000, LEGENDARY)
            assert q["chance"] <= 0.8
            assert await ledger_ok(db, 1)
        finally:
            await db.close()
    run(scenario())


def test_market_fee_hold_and_ledger():
    async def scenario():
        g, db, clock = await make_game()
        try:
            await g.ensure_user(1, None, "Seller")
            await g.ensure_user(2, None, "Buyer")
            async with db.tx():
                item = await g._issue(1, EPIC, random.Random(5), "t")
            with pytest.raises(GameError) as e:
                await g.list_lot(1, item["id"], 400_000)
            assert e.value.code == "NOT_ALLOWED_YET"
            clock.t += 25 * 3600
            with pytest.raises(GameError) as e:
                await g.list_lot(1, item["id"], 700_000)
            assert e.value.code == "PRICE_OUT_OF_BAND"
            lot = await g.list_lot(1, item["id"], 500_000)
            with pytest.raises(GameError) as e:
                await g.sell(1, [item["id"]], True)
            assert e.value.code == "ITEM_BUSY"
            await g.buy_lot(2, lot["lot_id"])
            assert (await g.me(1))["balance_cents"] == 500_000 + 450_000
            with pytest.raises(GameError) as e:
                await g.list_lot(2, item["id"], 400_000)
            assert e.value.code == "ITEM_BUSY"  # удержание 24 часа
            assert await ledger_ok(db, 1) and await ledger_ok(db, 2)
            fee = await db.val("SELECT SUM(delta) FROM ledger WHERE reason = 'market_fee'")
            assert fee == -50_000
        finally:
            await db.close()
    run(scenario())


def test_referral_wheel_tasks_raffle():
    async def scenario():
        g, db, clock = await make_game()
        try:
            await g.ensure_user(1, None, "Ref")
            await g.ensure_user(2, None, "Friend", ref_id=1)
            assert (await g.me(2))["attempts"] == 3
            async with db.tx():
                await g._add(2, 5_000_000, 0, "admin")
            await g.spin(2, "common", 5)
            assert (await g.friends(1))["count"] == 0
            await g.spin(2, "common", 5)
            assert (await g.friends(1))["count"] == 1
            w = await g.wheel(2)
            assert 0 <= w["index"] < 5
            with pytest.raises(GameError):
                await g.wheel(2)
            me = await g.me(2)
            done = [t for t in me["today"]["tasks"] if t["progress"] >= t["target"]]
            for t in done:
                await g.task_claim(2, t["key"])
            res = await g.raffle_draw()
            if done:
                assert res["winners"] and res["winners"][0]["user_id"] == 2
            assert await g.raffle_draw() is None
            assert await ledger_ok(db, 1) and await ledger_ok(db, 2)
        finally:
            await db.close()
    run(scenario())


def test_shop_limits_and_once_pack():
    async def scenario():
        g, db, _ = await make_game()
        try:
            await g.ensure_user(1, None, "A")
            await g.grant_purchase(1, "attempts50", "c1", 199)
            await g.grant_purchase(1, "attempts50", "c1", 199)  # повторное successful_payment
            assert (await g.me(1))["attempts"] == 50
            with pytest.raises(GameError):
                await g.check_purchase(1, "attempts5")
            await g.grant_purchase(1, "start", "c2", 169)
            with pytest.raises(GameError):
                await g.check_purchase(1, "start")
            assert (await g.me(1))["user"]["vip_until"]
            await g.grant_purchase(1, "vip30", "c3", 249)
            with pytest.raises(GameError) as e:
                await g.check_purchase(1, "slots5")  # 199 + 169 + 249 > 500
            assert e.value.code == "STARS_MONTH_CAP"
        finally:
            await db.close()
    run(scenario())


def test_fair_rotate_reveals_and_verifies():
    async def scenario():
        g, db, _ = await make_game()
        try:
            await g.ensure_user(1, None, "A")
            await g.spin(1, "common", 3)
            info = await g.fair_info(1)
            assert info["nonce"] == 3 and info["rolls"][0]["server_seed"] is None
            rot = await g.fair_rotate(1, "artem")
            assert fair.seed_hash(rot["revealed"]["server_seed"]) == info["server_hash"]
            for r in (await g.fair_info(1))["rolls"]:
                u0 = fair.roll(r["server_seed"], r["client_seed"], r["nonce"])
                assert u0 == pytest.approx(r["u0"])
                assert fair.pick_tier(u0, {int(k): v for k, v in r["odds"].items()}) == r["tier"]
        finally:
            await db.close()
    run(scenario())


def test_money_format():
    c = CFG["currency"]["countries"]
    assert fmt_money(100_000, c["RU"]) == "1 000 ₽"
    assert fmt_money(100_000, c["BY"]) == "40,00 Br"
    assert fmt_money(100_000, c["KZ"]) == "6 000 ₸"


# ---------- M3: API, идемпотентность и гонки ----------

TOKEN = "123456:TEST"


def init_data(uid: int, start: str | None = None, token: str = TOKEN, lang: str = "ru") -> str:
    data = {"auth_date": str(int(time.time())), "query_id": "AA",
            "user": json.dumps({"id": uid, "first_name": "Игрок", "language_code": lang}, ensure_ascii=False,
                               separators=(",", ":"))}
    if start:
        data["start_param"] = start
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class FakeBot:
    async def me(self):
        return SimpleNamespace(username="TestBot")

    async def create_invoice_link(self, **kw):
        assert kw["currency"] == "XTR"
        return "https://t.me/$inv"


async def api_client(game):
    cfg = Config(TOKEN, frozenset(), ":memory:", "https://x", "", "127.0.0.1", 0, True, False)
    client = TestClient(TestServer(create_app(game, FakeBot(), cfg)))
    await client.start_server()
    return client


def test_api_idempotency_and_races():
    async def scenario():
        g, db, _ = await make_game()
        g.clock = time.time
        client = await api_client(g)
        try:
            h = {"Authorization": "tma " + init_data(5)}
            assert (await client.post("/api/me", headers=h)).status == 200
            async with db.tx():  # 3 энергии + баланс ровно на 10 платных спинов
                await db.run("UPDATE users SET energy = 0, balance_cents = 1000000 WHERE id = 5")
                await g._ledger(5, "rub", 1000000 - 500000, "admin")
            same = {**h, "Idempotency-Key": "k-1"}
            res = await asyncio.gather(*(client.post("/api/spin", json={"count": 1}, headers=same) for _ in range(20)))
            bodies = [await r.text() for r in res if r.status == 200]
            assert len(set(bodies)) == 1
            assert await db.val("SELECT COUNT(*) FROM drops WHERE user_id = 5") == 1
            await asyncio.sleep(1.1)
            ok = 0
            for i in range(14):
                r = await client.post("/api/spin", json={"count": 1, "confirmed": True},
                                      headers={**h, "Idempotency-Key": f"k{i + 2}"})
                ok += r.status == 200
                await asyncio.sleep(0.55)
            assert await db.val("SELECT COUNT(*) FROM drops WHERE user_id = 5") == 10
            assert await db.val("SELECT balance_cents FROM users WHERE id = 5") == 0
            assert await ledger_ok(db, 5)
            bad = init_data(5, token="999:OTHER")
            assert (await client.post("/api/me", headers={"Authorization": "tma " + bad})).status == 401
            r = await client.post("/api/spin", json={"count": 2}, headers={**h, "Idempotency-Key": "x"})
            assert r.status == 400 and (await r.json())["error"]["code"] == "BAD_REQUEST"
            assert (await client.get("/")).status == 200 and (await client.get("/app/app.js")).status == 200
        finally:
            await client.close()
            await db.close()
    run(scenario())


# ---------- M5: бот и оплата ----------

def test_bot_start_and_payment():
    from aiogram import Bot, Dispatcher
    from aiogram.client.session.base import BaseSession
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.methods import AnswerPreCheckoutQuery, SendMessage
    from aiogram.types import Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update, User
    from bot.handlers import setup_routers

    sent = []

    class Session(BaseSession):
        async def make_request(self, bot, method, timeout=None):
            sent.append(method)
            if isinstance(method, SendMessage):
                return Message(message_id=1, date=datetime.datetime.now(), chat=Chat(id=method.chat_id, type="private"),
                               text=method.text)
            return True

        async def close(self):
            pass

        async def stream_content(self, *a, **k):
            yield b""

    async def scenario():
        g, db, _ = await make_game()
        try:
            cfg = Config(TOKEN, frozenset({1}), ":memory:", "https://game.example", "", "127.0.0.1", 0, True, False)
            bot = Bot(TOKEN, session=Session())
            dp = Dispatcher(storage=MemoryStorage(), game=g, config=cfg)
            dp.include_router(setup_routers())
            user = User(id=50, is_bot=False, first_name="Ив", language_code="be")
            await g.ensure_user(7, None, "Ref")

            def msg(**kw):
                return Message(message_id=2, date=datetime.datetime.now(), chat=Chat(id=50, type="private"),
                               from_user=user, **kw)

            await dp.feed_update(bot, Update(update_id=1, message=msg(text="/start r7")))
            row = await db.one("SELECT ref_id, country FROM users WHERE id = 50")
            assert row["ref_id"] == 7 and row["country"] == "BY"
            start_reply = [m for m in sent if isinstance(m, SendMessage)][-1]
            assert start_reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://game.example"

            def pcq(amount, payload="attempts5:50"):
                return Update(update_id=2, pre_checkout_query=PreCheckoutQuery(
                    id="q", from_user=user, currency="XTR", total_amount=amount, invoice_payload=payload))

            await dp.feed_update(bot, pcq(25))
            assert [m for m in sent if isinstance(m, AnswerPreCheckoutQuery)][-1].ok is True
            await dp.feed_update(bot, pcq(1))
            assert [m for m in sent if isinstance(m, AnswerPreCheckoutQuery)][-1].ok is False
            await dp.feed_update(bot, pcq(25, "attempts5:999"))
            assert [m for m in sent if isinstance(m, AnswerPreCheckoutQuery)][-1].ok is False
            pay = SuccessfulPayment(currency="XTR", total_amount=25, invoice_payload="attempts5:50",
                                    telegram_payment_charge_id="ch-1", provider_payment_charge_id="")
            await dp.feed_update(bot, Update(update_id=3, message=msg(successful_payment=pay)))
            await dp.feed_update(bot, Update(update_id=4, message=msg(successful_payment=pay)))
            assert (await g.me(50))["attempts"] == 3 + 5
        finally:
            await db.close()

    run(scenario())
