import asyncio
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
from bot.game import phones
from bot.game.service import Game, GameError
from bot.game.tiers import (COMMON, EPIC, LEGENDARY, MYTHIC, RARE, SCALES, SECRET, UNCOMMON, apply_luck,
                            expected_value)
from bot.web import create_app


def run(coro):
    return asyncio.run(coro)


# ---------- ядро ----------

@pytest.mark.parametrize("country,op,sub,tier", [
    ("RU", "912", "3846105", COMMON),       # +7 912 384-61-05
    ("RU", "912", "3846100", UNCOMMON),     # …61-00
    ("RU", "912", "7773405", RARE),         # 777-34-05
    ("RU", "912", "3841221", RARE),         # зеркало …1221
    ("RU", "912", "3847777", EPIC),         # …77-77
    ("RU", "912", "3841234", EPIC),         # лесенка …1234
    ("RU", "912", "3847788", EPIC),         # две пары …7788
    ("RU", "912", "7777777", LEGENDARY),    # 777-77-77
    ("KZ", "777", "7777777", MYTHIC),       # +7 777 777-77-77
    ("RU", "987", "6543210", MYTHIC),       # полная лесенка
    ("RU", "912", "3443219", SECRET),       # палиндром из 10 цифр
])
def test_classifier_examples_from_spec(country, op, sub, tier):
    assert phones.classify(country, op, sub) == tier


def test_generator_every_tier_every_country():
    rng = random.Random(42)
    for country in phones.COUNTRIES:
        for tier in range(8):
            for _ in range(20):
                code, op, sub = phones.generate(tier, country, rng)
                assert phones.classify(code, op, sub) == tier
                assert tier == 7 or not phones.is_blacklisted(op + sub)
                assert op in phones.COUNTRIES[code].operators


def test_economy_matches_spec():
    assert expected_value(SCALES["phone"]["odds"]) == pytest.approx(90.4)
    assert sum(SCALES["phone"]["odds"].values()) == pytest.approx(1)
    assert sum(SCALES["premium"]["odds"].values()) == pytest.approx(1)
    lucky = apply_luck(SCALES["phone"]["odds"], 2)
    assert lucky[COMMON] == pytest.approx(0.5191, abs=1e-4)
    assert lucky[RARE] == pytest.approx(0.18)
    assert expected_value(lucky) == pytest.approx(165, abs=1)


# ---------- сервис ----------

class Clock:
    def __init__(self, t=1_800_000_000.0):  # 15.01.2027, 11:00 МСК — не ночь
        self.t = t

    def __call__(self):
        return self.t


async def make_game(stars=True):
    db = Database(":memory:")
    await db.connect()
    clock = Clock()
    return Game(db, stars_enabled=stars, clock=clock), db, clock


def test_energy_spins_and_coins():
    async def scenario():
        g, db, clock = await make_game()
        await g.ensure_user(1, None, "A")
        r = await g.spin(1, 1)
        assert r["paid"] == {"energy": 1, "spins": 0, "coins": 0}
        await g.spin(1, 1)
        await g.spin(1, 1)
        r = await g.spin(1, 1)  # энергия кончилась — платим монетами
        assert r["paid"]["coins"] == 100
        assert (await g.state(1))["user"]["coins"] == 100
        clock.t += 3 * 3600 + 1
        assert (await g.state(1))["user"]["energy"] == 1
        with pytest.raises(GameError) as e:
            await g.spin(1, 5)
        assert e.value.code == "no_coins"
        await db.close()
    run(scenario())


def test_pity_guarantee():
    async def scenario():
        g, db, _ = await make_game()
        await g.ensure_user(1, None, "A")
        async with db.tx():
            await db.run("UPDATE users SET pity_epic = 39, pity_legendary = 199 WHERE id = 1")
        r = await g.spin(1, 1)
        assert r["drops"][0]["tier"]["idx"] >= LEGENDARY
        await db.close()
    run(scenario())


def test_coin_spin_daily_cap():
    async def scenario():
        g, db, _ = await make_game()
        await g.ensure_user(1, None, "A")
        async with db.tx():
            await db.run("UPDATE users SET coins = 100000, energy = 0 WHERE id = 1")
        done = 0
        with pytest.raises(GameError) as e:
            for _ in range(100):
                await g.spin(1, 1)
                done += 1
        assert e.value.code == "limit"
        assert 30 <= done <= 60  # 30 в сутки, +1 за каждый уровень
        assert (await g.state(1))["user"]["coin_spins_left"] == 0
        await db.close()
    run(scenario())


def test_referral_after_ten_spins():
    async def scenario():
        g, db, _ = await make_game()
        await g.ensure_user(1, None, "Ref")
        await g.ensure_user(2, None, "Friend", ref_id=1)
        assert (await g.state(2))["user"]["spins"] == 3
        async with db.tx():
            await db.run("UPDATE users SET coins = 5000 WHERE id = 2")
        await g.spin(2, 5)
        assert (await g.friends(1))["count"] == 0
        await g.spin(2, 5)
        assert (await g.friends(1))["count"] == 1
        assert (await g.state(1))["user"]["spins"] == 3
        assert g.pop_outbox()[0][0] == 1
        await g.ensure_user(3, None, "Self", ref_id=3)
        assert (await db.one("SELECT ref_id FROM users WHERE id = 3"))[0] is None
        await db.close()
    run(scenario())


def test_contract_and_upgrade():
    async def scenario():
        g, db, _ = await make_game()
        await g.ensure_user(1, None, "A")
        rng = random.Random(1)
        async with db.tx():
            ids = [(await g._new_item(1, COMMON, "RU", "test", rng))["id"] for _ in range(6)]
            await db.run("UPDATE users SET coins = 10000 WHERE id = 1")
        with pytest.raises(GameError):
            await g.contract(1, ids[:4])
        r = await g.contract(1, ids[:5])
        assert r["item"]["tier"]["idx"] == UNCOMMON
        q = await g.upgrade_quote(1, [ids[5]], 40, RARE)  # ставка 10 + 40 = 50, цель 100
        assert q["stake"] == 50 and q["chance"] == pytest.approx(50 / 100 * 0.85)
        with pytest.raises(GameError):
            await g.upgrade_quote(1, [], 2000, RARE)  # цель дешевле ставки
        g.cfg["upgrade"]["k"] = 0.0001  # гарантированная неудача
        res = await g.upgrade(1, [], 100, EPIC)
        assert not res["success"] and res["parts"] == 10
        assert (await g.upgrade_quote(1, [], 100, EPIC))["bonus"] == pytest.approx(0.03)
        await db.close()
    run(scenario())


def test_market_rules():
    async def scenario():
        g, db, clock = await make_game()
        await g.ensure_user(1, None, "Seller")
        await g.ensure_user(2, None, "Buyer")
        rng = random.Random(2)
        async with db.tx():
            item = await g._new_item(1, EPIC, "RU", "test", rng)
            await db.run("UPDATE users SET coins = 1000 WHERE id = 2")
        with pytest.raises(GameError) as e:
            await g.list_lot(1, item["id"], 400)
        assert e.value.code == "new_account"
        clock.t += 25 * 3600
        with pytest.raises(GameError):
            await g.list_lot(1, item["id"], 700)  # дороже 150%
        lot = await g.list_lot(1, item["id"], 500)
        assert lot["you_get"] == 450
        with pytest.raises(GameError):
            await g.sell(1, [item["id"]])  # на рынке — продать нельзя
        await g.buy_lot(2, lot["lot_id"])
        assert (await g.state(1))["user"]["coins"] == 200 + 450
        assert (await g.state(2))["user"]["coins"] == 500
        assert (await db.one("SELECT user_id FROM items WHERE id = ?", item["id"]))[0] == 2
        await db.close()
    run(scenario())


def test_shop_limits():
    async def scenario():
        g, db, _ = await make_game()
        await g.ensure_user(1, None, "A")
        await g.check_purchase(1, "spins50")
        await g.grant_purchase(1, "spins50", "c1", 199)
        await g.grant_purchase(1, "spins50", "c1", 199)  # повтор того же платежа не выдаётся дважды
        assert (await g.state(1))["user"]["spins"] == 50
        with pytest.raises(GameError) as e:
            await g.check_purchase(1, "spins5")  # больше 50 попыток в сутки
        assert e.value.code == "daily"
        await g.grant_purchase(1, "luck2", "c2", 49)
        with pytest.raises(GameError) as e:
            await g.check_purchase(1, "luck15")
        assert e.value.code == "luck_active"
        await g.grant_purchase(1, "luck2", "c3", 49)
        await g.grant_purchase(1, "luck2", "c4", 49)
        await g.grant_purchase(1, "luck2", "c5", 49)
        with pytest.raises(GameError) as e:
            await g.check_purchase(1, "luck2")  # месячный потолок 500 ⭐ (199 + 4×49 = 395, а лимит удачи ×2 — 3 в сутки)
        assert e.value.code in ("daily", "cap")
        r = await g.revoke_purchase("c1")
        assert r["stars"] == 199 and (await g.state(1))["user"]["spins"] == 0
        g.stars_enabled = False
        with pytest.raises(GameError):
            await g.check_purchase(1, "spins5")
        await db.close()
    run(scenario())


def test_notifications_quiet_hours_and_limit():
    async def scenario():
        g, db, clock = await make_game()
        await g.ensure_user(1, None, "A")
        async with db.tx():
            for _ in range(3):
                await g.notify(1, "x")
        assert len(g.pop_outbox()) == 2
        clock.t += 12 * 3600  # 23:00 МСК
        async with db.tx():
            await g.notify(1, "night")
        assert g.pop_outbox() == []
        await db.close()
    run(scenario())


# ---------- API ----------

TOKEN = "123456:TEST"


def init_data(uid: int, start: str | None = None, token: str = TOKEN) -> str:
    data = {"auth_date": str(int(time.time())), "query_id": "AA",
            "user": json.dumps({"id": uid, "first_name": "Игрок"}, ensure_ascii=False, separators=(",", ":"))}
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


def test_api_auth_and_flow():
    async def scenario():
        db = Database(":memory:")
        await db.connect()
        g = Game(db, stars_enabled=True)
        cfg = Config(TOKEN, frozenset(), ":memory:", "https://x", "", "127.0.0.1", 0, True, False)
        client = TestClient(TestServer(create_app(g, FakeBot(), cfg)))
        await client.start_server()
        try:
            r = await client.post("/api/state", headers={"Authorization": "tma " + init_data(5, "r1")})
            assert r.status == 200
            s = await r.json()
            assert s["user"]["energy"] == 3 and s["ref_link"].endswith("start=r5")
            bad = init_data(5, token="999:OTHER")
            assert (await client.post("/api/state", headers={"Authorization": "tma " + bad})).status == 401
            assert (await client.post("/api/state")).status == 401
            r = await client.post("/api/spin", json={"count": 1}, headers={"Authorization": "tma " + init_data(5)})
            assert r.status == 200 and len((await r.json())["drops"]) == 1
            r = await client.post("/api/spin", json={"count": 7}, headers={"Authorization": "tma " + init_data(5)})
            assert r.status == 400 and "error" in await r.json()
            r = await client.post("/api/shop/invoice", json={"key": "spins5"}, headers={"Authorization": "tma " + init_data(5)})
            assert (await r.json())["link"] == "https://t.me/$inv"
            assert (await client.get("/")).status == 200
            assert (await client.get("/app/app.js")).status == 200
        finally:
            await client.close()
            await db.close()
    run(scenario())


# ---------- бот: /start и оплата Stars ----------

def test_bot_start_and_payment():
    import datetime
    from aiogram import Bot, Dispatcher
    from aiogram.client.session.base import BaseSession
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.methods import AnswerPreCheckoutQuery, SendMessage
    from aiogram.types import (Chat, Message, PreCheckoutQuery, SuccessfulPayment, Update, User)
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
        db = Database(":memory:")
        await db.connect()
        g = Game(db, stars_enabled=True)
        cfg = Config(TOKEN, frozenset({1}), ":memory:", "https://game.example", "", "127.0.0.1", 0, True, False)
        bot = Bot(TOKEN, session=Session())
        dp = Dispatcher(storage=MemoryStorage(), game=g, config=cfg)
        dp.include_router(setup_routers())
        user = User(id=50, is_bot=False, first_name="Ив")
        await g.ensure_user(7, None, "Ref")

        def msg(**kw):
            return Message(message_id=2, date=datetime.datetime.now(), chat=Chat(id=50, type="private"), from_user=user, **kw)

        await dp.feed_update(bot, Update(update_id=1, message=msg(text="/start r7")))
        assert (await db.one("SELECT ref_id FROM users WHERE id = 50"))[0] == 7
        start_reply = [m for m in sent if isinstance(m, SendMessage)][-1]
        assert start_reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://game.example"

        def pcq(amount, payload="spins5:50"):
            return Update(update_id=2, pre_checkout_query=PreCheckoutQuery(
                id="q", from_user=user, currency="XTR", total_amount=amount, invoice_payload=payload))

        await dp.feed_update(bot, pcq(25))
        assert [m for m in sent if isinstance(m, AnswerPreCheckoutQuery)][-1].ok is True
        await dp.feed_update(bot, pcq(1))  # подменённая цена
        assert [m for m in sent if isinstance(m, AnswerPreCheckoutQuery)][-1].ok is False
        await dp.feed_update(bot, pcq(25, "spins5:999"))  # чужой счёт
        assert [m for m in sent if isinstance(m, AnswerPreCheckoutQuery)][-1].ok is False

        pay = SuccessfulPayment(currency="XTR", total_amount=25, invoice_payload="spins5:50",
                                telegram_payment_charge_id="ch-1", provider_payment_charge_id="")
        await dp.feed_update(bot, Update(update_id=3, message=msg(successful_payment=pay)))
        await dp.feed_update(bot, Update(update_id=4, message=msg(successful_payment=pay)))  # дубль
        assert (await g.state(50))["user"]["spins"] == 3 + 5  # 3 за приглашение + 5 купленных, один раз
        await db.close()

    run(scenario())
