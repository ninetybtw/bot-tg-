import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import load_config
from bot.db import Database
from bot.handlers import setup_routers
from bot.middlewares import SubscriptionMiddleware, UserMiddleware
from bot.services.usernames import UsernameChecker


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    checker = UsernameChecker()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), db=db, config=config, checker=checker)

    sub = SubscriptionMiddleware(config)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(UserMiddleware())
        observer.outer_middleware(sub)

    dp.include_router(setup_routers())
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await checker.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
