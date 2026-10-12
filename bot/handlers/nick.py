import html

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import Database
from bot.keyboards import BTN_GEN, BTN_NICK, MENU_BUTTONS, gen_more_kb, themes_kb
from bot.services import fonts, nickgen
from bot.utils import ad_footer

router = Router(name="nick")

MAX_NICK_LEN = 30


@router.message(F.text == BTN_NICK)
async def nick_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "✍️ Отправь мне свой ник или имя (до 30 символов).\n\n"
        "Латиница получит 15+ шрифтов, а украшения работают и с русскими буквами.\n"
        "Нажми на любой вариант — он скопируется 📋"
    )


@router.message(F.text == BTN_GEN)
async def gen_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🎲 Выбери тему ника:", reply_markup=themes_kb())


@router.callback_query(F.data == "gen_themes")
async def gen_themes(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text("🎲 Выбери тему ника:", reply_markup=themes_kb())


@router.callback_query(F.data.startswith("gen:"))
async def gen_nicks(call: CallbackQuery, db: Database) -> None:
    theme = call.data.split(":", 1)[1]
    if theme not in nickgen.THEMES:
        await call.answer()
        return
    lines = [
        f"• <code>{html.escape(styled)}</code>\n   <i>{html.escape(plain)}</i>"
        for plain, styled in nickgen.generate(theme)
    ]
    text = (
        f"{nickgen.THEMES[theme]['title']} — нажми, чтобы скопировать:\n\n"
        + "\n".join(lines)
        + "\n\n💡 Понравился ник? Отправь его мне — покажу в 30+ стилях"
        + await ad_footer(db)
    )
    await call.answer()
    try:
        await call.message.edit_text(text, reply_markup=gen_more_kb(theme),
                                     disable_web_page_preview=True)
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=gen_more_kb(theme),
                                  disable_web_page_preview=True)


# Любой обычный текст = ник для оформления. Роутер подключается последним.
@router.message(F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def stylize_nick(message: Message, db: Database) -> None:
    text = " ".join(message.text.split())
    if len(text) > MAX_NICK_LEN:
        await message.answer(f"✂️ Слишком длинно — максимум {MAX_NICK_LEN} символов.")
        return
    variants = fonts.stylize(text)
    lines = [f"<code>{html.escape(v)}</code>" for _, v in variants]
    tip = "" if fonts.has_latin(text) else (
        "\n\n💡 Напиши ник латиницей — откроются ещё 15 шрифтов"
    )
    await message.answer(
        "✨ <b>Твои ники</b> — нажми на любой, чтобы скопировать:\n\n"
        + "\n".join(lines) + tip + await ad_footer(db),
        disable_web_page_preview=True,
    )
