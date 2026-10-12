import logging

from aiogram import Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated, ErrorEvent

from bot.db import Database

log = logging.getLogger(__name__)
router = Router(name="system")


@router.my_chat_member()
async def bot_blocked(event: ChatMemberUpdated, db: Database) -> None:
    """Отмечаем, кто заблокировал бота — для честной статистики «живых»."""
    if event.chat.type != ChatType.PRIVATE:
        return
    blocked = event.new_chat_member.status == ChatMemberStatus.KICKED
    await db.set_blocked(event.from_user.id, blocked)


@router.errors()
async def on_error(event: ErrorEvent) -> None:
    log.exception("Ошибка при обработке апдейта: %s", event.exception, exc_info=event.exception)
