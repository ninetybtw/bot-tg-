import html
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Config
from bot.db import Database
from bot.keyboards import subscribe_kb

log = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

SUBSCRIBED = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


def _parse_ref(text: str) -> int | None:
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("r") and parts[1][1:].isdigit():
        return int(parts[1][1:])
    return None


def _is_private(data: dict[str, Any]) -> bool:
    chat = data.get("event_chat")
    return chat is None or chat.type == ChatType.PRIVATE


class UserMiddleware(BaseMiddleware):
    """Регистрирует пользователя и запоминает, кто его пригласил."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot or not _is_private(data):
            return await handler(event, data)
        db: Database = data["db"]
        ref_id = None
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            ref_id = _parse_ref(event.text)
        await db.add_user(user.id, user.username, user.first_name, ref_id)
        return await handler(event, data)


class SubscriptionMiddleware(BaseMiddleware):
    """Обязательная подписка на спонсоров (ОП) — основной источник дохода бота."""

    def __init__(self, config: Config, cache_ttl: float = 300):
        self.config = config
        self.cache_ttl = cache_ttl
        self._ok_until: dict[int, float] = {}

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot or not _is_private(data) or user.id in self.config.admin_ids:
            return await handler(event, data)

        now = time.monotonic()
        if self._ok_until.get(user.id, 0) > now:
            return await handler(event, data)

        bot: Bot = data["bot"]
        db: Database = data["db"]
        missing = await self._check(bot, db, user.id)
        if missing:
            await self._show_gate(event, missing)
            return None

        if len(self._ok_until) > 100_000:
            self._ok_until = {k: v for k, v in self._ok_until.items() if v > now}
        self._ok_until[user.id] = now + self.cache_ttl
        await self._on_passed(bot, db, user.id)
        return await handler(event, data)

    async def _check(self, bot: Bot, db: Database, user_id: int) -> list:
        sponsors = await db.get_sponsors(active_only=True)
        missing, subscribed = [], []
        for s in sponsors:
            try:
                member = await bot.get_chat_member(s["chat_id"], user_id)
            except TelegramAPIError as e:
                # Бот не админ в канале / канал удалён — не блокируем людей из-за этого
                log.warning("Не удалось проверить спонсора %s (%s): %s", s["id"], s["title"], e)
                continue
            ok = member.status in SUBSCRIBED or (
                member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False)
            )
            (subscribed if ok else missing).append(s)

        if missing:
            await db.mark_pending(user_id, [s["id"] for s in missing])
        if subscribed:
            finished = await db.register_joins(user_id, [s["id"] for s in subscribed])
            for s in finished:
                await self._notify_admins(
                    bot,
                    f"✅ Спонсор <b>{html.escape(s['title'])}</b> выполнил заказ: "
                    f"{s['joined']}/{s['target']} подписчиков. Он отключён из ОП.",
                )
        return missing

    async def _show_gate(self, event: TelegramObject, missing: list) -> None:
        text = (
            "🔒 <b>Чтобы пользоваться ботом, подпишись на каналы наших спонсоров</b>\n\n"
            "Это бесплатно и помогает боту оставаться бесплатным для тебя 💜\n"
            "После подписки нажми «✅ Я подписался»."
        )
        kb = subscribe_kb(missing)
        if isinstance(event, CallbackQuery):
            if event.data == "op_check":
                await event.answer("❌ Ты подписался не на все каналы", show_alert=True)
                try:
                    await event.message.edit_reply_markup(reply_markup=kb)
                except TelegramAPIError:
                    pass
            else:
                await event.answer()
                await event.message.answer(text, reply_markup=kb)
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=kb)

    async def _on_passed(self, bot: Bot, db: Database, user_id: int) -> None:
        if not await db.mark_passed_op(user_id, self.config.start_balance):
            return
        user = await db.get_user(user_id)
        if not user["ref_id"]:
            return
        await db.reward_referrer(user["ref_id"], self.config.ref_reward)
        name = html.escape(user["first_name"] or "Друг")
        try:
            await bot.send_message(
                user["ref_id"],
                f"🎉 По твоей ссылке пришёл <b>{name}</b>! +{self.config.ref_reward} 💎",
            )
        except TelegramAPIError:
            pass

    async def _notify_admins(self, bot: Bot, text: str) -> None:
        for admin_id in self.config.admin_ids:
            try:
                await bot.send_message(admin_id, text)
            except TelegramAPIError:
                pass
