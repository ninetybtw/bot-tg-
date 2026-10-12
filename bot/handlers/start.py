import html

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.keyboards import main_menu

router = Router(name="start")


def welcome_text(first_name: str | None, bot_name: str) -> str:
    return (
        f"👋 Привет, {html.escape(first_name or 'друг')}!\n\n"
        f"Я — <b>{html.escape(bot_name)}</b>. Помогу сделать ник, от которого все обалдеют:\n\n"
        "✨ <b>Красивый ник</b> — 30+ шрифтов и украшений\n"
        "🎲 <b>Генератор ников</b> — идеи для игр, TikTok, Instagram и Telegram\n"
        "💎 <b>Свободные @username</b> — найду короткие свободные юзернеймы\n\n"
        "👇 Просто отправь мне любой текст — и я сделаю его красивым"
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, config: Config) -> None:
    await state.clear()
    await message.answer(welcome_text(message.from_user.first_name, config.bot_name),
                         reply_markup=main_menu())


@router.callback_query(F.data == "op_check")
async def op_passed(call: CallbackQuery, config: Config) -> None:
    # Сюда попадаем только если SubscriptionMiddleware пропустил — значит подписка есть
    await call.answer("✅ Спасибо за подписку!")
    try:
        await call.message.delete()
    except TelegramAPIError:
        pass
    await call.message.answer(welcome_text(call.from_user.first_name, config.bot_name),
                              reply_markup=main_menu())
