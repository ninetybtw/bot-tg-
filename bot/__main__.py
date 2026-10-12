import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from aiohttp import web

from bot.config import load_config
from bot.db import Database
from bot.game.service import Game
from bot.handlers import setup_routers
from bot.web import create_app, send_outbox

log = logging.getLogger("bot")


async def reminders(bot: Bot, game: Game) -> None:
    """«Спин готов»: не чаще 2 уведомлений в сутки и не ночью (правила в Game.notify)."""
    while True:
        await asyncio.sleep(300)
        try:
            await game.energy_reminders()
            await send_outbox(bot, game)
        except Exception:
            log.exception("reminders failed")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    game = Game(db, stars_enabled=config.stars_enabled)
    await game.load_config()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), game=game, config=config)
    dp.include_router(setup_routers())

    await bot.set_my_commands([
        BotCommand(command="start", description="Играть"),
        BotCommand(command="terms", description="Условия"),
        BotCommand(command="paysupport", description="Помощь с оплатой"),
    ])
    if config.webapp_url.startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Играть", web_app=WebAppInfo(url=config.webapp_url)))
    else:
        log.warning("WEBAPP_URL не задан или не https — кнопка мини-приложения не появится")

    runner = web.AppRunner(create_app(game, bot, config))
    await runner.setup()
    await web.TCPSite(runner, config.web_host, config.web_port).start()
    log.info("Мини-приложение слушает http://%s:%s", config.web_host, config.web_port)

    reminder_task = asyncio.create_task(reminders(bot, game))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        reminder_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminder_task
        await runner.cleanup()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
