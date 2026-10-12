import asyncio
from types import SimpleNamespace

from aiogram.enums import ChatMemberStatus

from bot.config import Config
from bot.db import Database
from bot.middlewares import SubscriptionMiddleware, UserMiddleware
from bot.services import fonts, nickgen
from bot.services.usernames import candidates, is_valid


def run(coro):
    return asyncio.run(coro)


def test_fonts():
    variants = dict(fonts.stylize("Nick 7"))
    assert variants["Жирный"] == "𝐍𝐢𝐜𝐤 𝟕"
    assert variants["Двойной"].startswith("ℕ")
    assert variants["Капитель"] == "ɴɪᴄᴋ 7"
    assert variants["Вверх ногами"] == "7 ʞɔᴉu"
    # Кириллица: только диакритика и украшения, без латинских шрифтов
    ru = dict(fonts.stylize("Ник"))
    assert "Жирный" not in ru
    assert ru["Зачёркнутый"] == "Н̶и̶к̶"


def test_nickgen():
    for key in nickgen.THEMES:
        nicks = nickgen.generate(key)
        assert len(nicks) == 8
        assert len({p for p, _ in nicks}) == 8


def test_usernames():
    assert is_valid("kavor") and is_valid("Nick_7x")
    assert not is_valid("abcd") and not is_valid("1abcd") and not is_valid("abcd_")
    names = candidates(5, 20)
    assert len(names) == 20 and all(len(n) == 5 and is_valid(n) for n in names)


class FakeBot:
    def __init__(self):
        self.subscribed: set[tuple[int, int]] = set()
        self.sent: list[tuple[int, str]] = []

    async def get_chat_member(self, chat_id, user_id):
        ok = (chat_id, user_id) in self.subscribed
        return SimpleNamespace(status=ChatMemberStatus.MEMBER if ok else ChatMemberStatus.LEFT)

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def make_config(**kw):
    base = dict(bot_token="x", admin_ids=frozenset({1}), db_path=":memory:", bot_name="T",
                start_balance=2, ref_reward=3, daily_bonus=1)
    base.update(kw)
    return Config(**base)


def test_op_flow(tmp_path):
    async def scenario():
        db = Database(str(tmp_path / "t.db"))
        await db.connect()
        bot = FakeBot()
        config = make_config()
        await db.add_sponsor(-100500, "Спонсор", "https://t.me/sponsor", target=2)
        sponsor = (await db.get_sponsors())[0]

        await db.add_user(10, None, "Referrer", None)
        await db.add_user(20, None, "Invited", ref_id=10)
        await db.add_user(30, None, "Old", None)
        bot.subscribed.add((-100500, 30))  # был подписан до бота — не засчитывается

        mw = SubscriptionMiddleware(config, cache_ttl=0)
        calls = []

        async def handler(event, data):
            calls.append(data["event_from_user"].id)

        async def hit(uid):
            data = {"event_from_user": SimpleNamespace(id=uid, is_bot=False),
                    "event_chat": None, "bot": bot, "db": db}
            mw._show_gate = _noop_gate
            await mw(handler, object(), data)

        async def _noop_gate(event, missing):
            pass

        await hit(20)  # не подписан → гейт
        assert calls == []
        assert (await db.get_user(10))["balance"] == 0

        bot.subscribed.add((-100500, 20))
        await hit(20)  # подписался → проходит, рефереру награда
        assert calls == [20]
        assert (await db.get_user(20))["balance"] == 2
        ref = await db.get_user(10)
        assert ref["balance"] == 3 and ref["ref_count"] == 1
        assert bot.sent and bot.sent[0][0] == 10

        await hit(20)  # повторный заход не даёт награду повторно
        assert (await db.get_user(10))["balance"] == 3

        await hit(30)  # старый подписчик — проходит, но не засчитан спонсору
        assert (await db.get_sponsor(sponsor["id"]))["joined"] == 1

        await hit(10)
        bot.subscribed.add((-100500, 10))
        await hit(10)  # второй засчитанный → заказ выполнен, спонсор выключен
        sp = await db.get_sponsor(sponsor["id"])
        assert sp["joined"] == 2 and sp["active"] == 0
        assert any(chat == 1 and "выполнил заказ" in text for chat, text in bot.sent)
        await db.close()

    run(scenario())


def test_ref_and_economy(tmp_path):
    async def scenario():
        db = Database(str(tmp_path / "t.db"))
        await db.connect()
        assert await db.add_user(1, "a", "A", ref_id=1)          # сам себя — игнор
        assert (await db.get_user(1))["ref_id"] is None
        assert await db.add_user(2, "b", "B", ref_id=999)        # несуществующий — игнор
        assert (await db.get_user(2))["ref_id"] is None
        assert not await db.add_user(2, "b2", "B", ref_id=1)     # повторно не создаётся
        assert (await db.get_user(2))["ref_id"] is None

        assert not await db.try_spend(1, 1)
        from datetime import timedelta
        ok, _ = await db.claim_bonus(1, 5, timedelta(hours=24))
        ok2, left = await db.claim_bonus(1, 5, timedelta(hours=24))
        assert ok and not ok2 and left.total_seconds() > 0
        assert await db.try_spend(1, 5) and (await db.get_user(1))["balance"] == 0
        await db.close()

    run(scenario())


def test_user_middleware_parses_ref(tmp_path):
    async def scenario():
        from aiogram.types import Chat, Message, User
        import datetime
        db = Database(str(tmp_path / "t.db"))
        await db.connect()
        await db.add_user(5, None, "R", None)
        msg = Message(message_id=1, date=datetime.datetime.now(),
                      chat=Chat(id=7, type="private"),
                      from_user=User(id=7, is_bot=False, first_name="N"), text="/start r5")
        async def handler(e, d):
            return "ok"
        res = await UserMiddleware()(handler, msg, {"event_from_user": msg.from_user,
                                                    "event_chat": msg.chat, "db": db})
        assert res == "ok" and (await db.get_user(7))["ref_id"] == 5
        await db.close()

    run(scenario())
