from aiogram import F, Router
from aiogram.enums import ChatType

from bot.handlers import admin, nick, profile, start, system, username


def setup_routers() -> Router:
    root = Router(name="root")
    # Порядок важен: nick последний — он ловит любой текст как ник
    user_routers = [start.router, username.router, profile.router, nick.router]
    for r in [admin.router, *user_routers]:
        r.message.filter(F.chat.type == ChatType.PRIVATE)
    root.include_routers(system.router, admin.router, *user_routers)
    return root
