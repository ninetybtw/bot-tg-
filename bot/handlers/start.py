import html

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from bot.config import Config
from bot.game.service import Game
from bot.web import parse_ref

router = Router(name="start")


class Support(StatesGroup):
    waiting = State()


TERMS = (
    "📄 <b>Условия</b>\n\n"
    "• Монеты, номера и попытки — игровые. Монеты нельзя купить за деньги и нельзя вывести.\n"
    "• Номера сгенерированы игрой и помечены «игровой номер». Это не настоящие SIM-карты, "
    "номера нельзя купить или проверить по базам операторов. Совпадение с реальным номером случайно.\n"
    "• За Telegram Stars продаются только попытки и удача, с лимитами: не больше 500 ⭐ в месяц, "
    "запас попыток до 100. Шансы показаны в игре до покупки.\n"
    "• Покупка выдаётся сразу после оплаты и окончательна. Если что-то не выдалось — пиши /paysupport, "
    "вернём звёзды за неиспользованное.\n"
    "• Не играй, если тебе это вредит. После 50 спинов в сутки игра напомнит сделать перерыв."
)


def play_kb(config: Config) -> InlineKeyboardMarkup | None:
    if not config.webapp_url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Крутить номера", web_app=WebAppInfo(url=config.webapp_url))
    ]])


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, game: Game,
                    config: Config) -> None:
    await state.clear()
    u = message.from_user
    await game.ensure_user(u.id, u.username, u.first_name, parse_ref(command.args))
    kb = play_kb(config)
    text = (
        f"📱 Привет, {html.escape(u.first_name or 'игрок')}!\n\n"
        "Крути красивые номера телефонов России, Казахстана, Беларуси и ОАЭ. "
        "Собирай «блатные» узоры: 777-77-77, лесенки, зеркала.\n\n"
        "⚡ 3 бесплатных спина уже ждут тебя. Жми кнопку 👇"
    )
    if not kb:
        text += "\n\n<i>Мини-приложение ещё не подключено: админ должен указать WEBAPP_URL.</i>"
    await message.answer(text, reply_markup=kb)


@router.message(Command("terms"))
async def cmd_terms(message: Message) -> None:
    await message.answer(TERMS)


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, state: FSMContext) -> None:
    await state.set_state(Support.waiting)
    await message.answer(
        "💬 <b>Поддержка по оплате</b>\n\n"
        "Опиши проблему одним сообщением: что купил, когда и что пошло не так. "
        "Мы ответим в течение суток. Возврат звёзд возможен за неиспользованные попытки и удачу."
    )


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    await message.answer(
        "Как играть: открой приложение, жми «Крутить». Номер сохраняется в коллекцию, "
        "дубли можно продать за монеты и крутить дальше.\n\n"
        "/terms — условия\n/paysupport — помощь с оплатой",
        reply_markup=play_kb(config),
    )


@router.message(Support.waiting, F.text, ~F.text.startswith("/"))
async def support_message(message: Message, state: FSMContext, config: Config) -> None:
    await state.clear()
    u = message.from_user
    text = (f"🆘 Обращение по оплате от {html.escape(u.full_name)} "
            f"(<code>{u.id}</code>{', @' + u.username if u.username else ''}):\n\n{html.escape(message.text)}\n\n"
            f"Ответить: <code>/reply {u.id} текст</code> · Вернуть: <code>/refund ID_чека</code>")
    for admin_id in config.admin_ids:
        try:
            await message.bot.send_message(admin_id, text)
        except TelegramAPIError:
            pass
    await message.answer("✅ Отправили в поддержку. Ответим здесь, в чате с ботом.")
