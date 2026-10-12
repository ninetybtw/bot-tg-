from aiogram import F, Router
from aiogram.enums import ChatType

from bot.handlers import admin, payments, start, system


def setup_routers() -> Router:
    root = Router(name="root")
    for r in (admin.router, start.router):
        r.message.filter(F.chat.type == ChatType.PRIVATE)
    root.include_routers(system.router, payments.router, admin.router, start.router)
    return root
