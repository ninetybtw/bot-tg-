import asyncio
import contextlib
import logging
import os
import ssl

from aiogram import Bot, Dispatcher
from aiogram.__meta__ import __version__ as aiogram_version
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from aiohttp import ClientSession, web

from bot.config import load_config
from bot.db import Database
from bot.game.service import Game
from bot.handlers import setup_routers
from bot.web import create_app, send_outbox

log = logging.getLogger("bot")


class EnvProxySession(AiohttpSession):
    """Для серверов, где интернет только через прокси: берёт HTTPS_PROXY и SSL_CERT_FILE из окружения."""

    def __init__(self) -> None:
        super().__init__()
        if os.getenv("SSL_CERT_FILE"):
            self._connector_init["ssl"] = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])

    async def create_session(self) -> ClientSession:
        if self._should_reset_connector:
            await self.close()
        if self._session is None or self._session.closed:
            self._session = ClientSession(connector=self._connector_type(**self._connector_init), trust_env=True,
                                          headers={"User-Agent": f"aiogram/{aiogram_version}"})
            self._should_reset_connector = False
        return self._session

DESCRIPTION = (
    "📱 Крути красивые номера телефонов!\n\n"
    "Выбивай «блатные» узоры: 777-77-77, лесенки, зеркала, палиндромы. "
    "Номера России, Казахстана, Беларуси и ОАЭ.\n\n"
    "⚡ 3 бесплатных спина на старте\n"
    "🎁 Подарок и колесо каждый день\n"
    "🏪 Рынок, «5 в 1» и апгрейдер\n"
    "🏆 Рейтинг среди друзей\n\n"
    "Все номера игровые. Жми «Старт» 👇"
)
SHORT_DESCRIPTION = "Крутилка красивых номеров: 777-77-77, лесенки, зеркала. Собирай коллекцию и обгоняй друзей"


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

    session = EnvProxySession() if os.getenv("HTTPS_PROXY") else None
    bot = Bot(config.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), game=game, config=config)
    dp.include_router(setup_routers())

    await bot.set_my_commands([
        BotCommand(command="start", description="Играть"),
        BotCommand(command="terms", description="Условия"),
        BotCommand(command="paysupport", description="Помощь с оплатой"),
    ])
    await bot.set_my_description(description=DESCRIPTION)
    await bot.set_my_short_description(short_description=SHORT_DESCRIPTION)
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
