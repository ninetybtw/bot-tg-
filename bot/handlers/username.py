from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.db import Database
from bot.keyboards import BTN_USERNAME, FIND_COST, MENU_BUTTONS, no_balance_kb, username_kb
from bot.services.usernames import UsernameChecker, is_valid
from bot.utils import share_url

router = Router(name="username")

_busy: set[int] = set()


class CheckState(StatesGroup):
    waiting = State()


@router.message(F.text == BTN_USERNAME)
async def username_menu(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    await message.answer(
        "💎 <b>Свободные @username</b>\n\n"
        "Короткий юзернейм — как красивый номер: его легко запомнить, а 5-буквенные "
        "на аукционе Fragment стоят тысячи долларов. Я найду свободные варианты, "
        "которые можно занять прямо сейчас <b>бесплатно</b> в настройках Telegram.\n\n"
        f"Твой баланс: <b>{user['balance']} 💎</b>\n"
        "Кристаллы дают за друзей и ежедневный бонус.",
        reply_markup=username_kb(),
    )


@router.callback_query(F.data.startswith("un_find:"))
async def find_usernames(call: CallbackQuery, db: Database, checker: UsernameChecker) -> None:
    length = int(call.data.split(":")[1])
    cost = FIND_COST.get(length)
    user_id = call.from_user.id
    if cost is None:
        await call.answer()
        return
    if user_id in _busy:
        await call.answer("⏳ Уже ищу, подожди пару секунд")
        return
    if not await db.try_spend(user_id, cost):
        await call.answer()
        await call.message.answer(
            f"😔 Нужно {cost} 💎 — у тебя не хватает.\n\n"
            "Пригласи друга по своей ссылке или забери ежедневный бонус 👇",
            reply_markup=no_balance_kb(await share_url(call.bot, user_id)),
        )
        return

    _busy.add(user_id)
    found: list[str] = []
    try:
        await call.answer()
        status = await call.message.answer(f"🔍 Ищу свободные юзернеймы из {length} букв…")
        found = await checker.find_free(length)
    finally:
        _busy.discard(user_id)
        if not found:
            await db.add_balance(user_id, cost)

    if not found:
        await status.edit_text("😕 Сейчас не получилось найти — кристаллы вернул. Попробуй ещё раз.")
        return
    names = "\n".join(f"• <code>{n}</code>" for n in found)
    await status.edit_text(
        f"🎉 <b>Скорее всего свободны</b> (−{cost} 💎):\n\n{names}\n\n"
        "Как занять: Настройки → Имя пользователя → вставь вариант.\n"
        "⚡ Поторопись — их могут занять другие!",
        reply_markup=username_kb(),
    )


@router.callback_query(F.data == "un_check")
async def ask_username(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(CheckState.waiting)
    await call.message.answer("✏️ Отправь юзернейм, который хочешь проверить (без @):")


@router.message(CheckState.waiting, F.text, ~F.text.in_(MENU_BUTTONS))
async def check_username(message: Message, state: FSMContext, checker: UsernameChecker) -> None:
    name = message.text.strip().lstrip("@").removeprefix("https://t.me/")
    if not is_valid(name):
        await message.answer(
            "⚠️ Юзернейм — от 5 до 32 символов: латиница, цифры и «_», "
            "начинается с буквы. Попробуй ещё раз:"
        )
        return
    await state.clear()
    free = await checker.is_free(name)
    if free is None:
        text = "⚠️ Не получилось проверить, попробуй чуть позже."
    elif free:
        text = (f"✅ <code>{name}</code> — скорее всего свободен!\n"
                "Займи его: Настройки → Имя пользователя.")
    else:
        text = f"❌ @{name} уже занят. Хочешь, найду свободные похожей длины?"
    await message.answer(text, reply_markup=username_kb())
