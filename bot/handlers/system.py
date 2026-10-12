import logging

from aiogram import Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated, ErrorEvent

from bot.game.service import Game

log = logging.getLogger(__name__)
router = Router(name="system")


@router.my_chat_member()
async def bot_blocked(event: ChatMemberUpdated, game: Game) -> None:
    """Отмечаем, кто заблокировал бота: им не шлём уведомления и рассылки."""
    if event.chat.type != ChatType.PRIVATE:
        return
    blocked = event.new_chat_member.status == ChatMemberStatus.KICKED
    async with game.db.tx():
        await game.db.run("UPDATE users SET is_blocked = ? WHERE id = ?", int(blocked), event.from_user.id)


@router.errors()
async def on_error(event: ErrorEvent) -> None:
    log.exception("Ошибка при обработке апдейта: %s", event.exception, exc_info=event.exception)
