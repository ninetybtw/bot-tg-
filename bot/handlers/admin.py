import asyncio
import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (TelegramAPIError, TelegramBadRequest, TelegramForbiddenError,
                                TelegramRetryAfter)
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message, MessageOriginChannel, TelegramObject)

from bot.config import Config
from bot.db import Database
from bot.keyboards import admin_kb, back_kb, confirm_mail_kb, sponsors_kb
from bot.utils import AD_KEY

log = logging.getLogger(__name__)
router = Router(name="admin")

_tasks: set[asyncio.Task] = set()


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, config: Config) -> bool:
        return event.from_user is not None and event.from_user.id in config.admin_ids


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class SponsorAdd(StatesGroup):
    chat = State()
    url = State()
    target = State()


class Mailing(StatesGroup):
    message = State()
    button = State()


# ---------- панель ----------

ADMIN_HELP = (
    "🛠 <b>Админ-панель</b>\n\n"
    "Команды:\n"
    "<code>/give ID 10</code> — начислить 💎\n"
    "<code>/setad текст</code> — реклама под каждой выдачей ников\n"
    "<code>/delad</code> — убрать рекламу\n"
    "<code>/cancel</code> — отменить текущее действие"
)


@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(ADMIN_HELP, reply_markup=admin_kb())


@router.callback_query(F.data == "adm:back")
async def admin_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await call.message.edit_text(ADMIN_HELP, reply_markup=admin_kb())


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=admin_kb())


@router.callback_query(F.data == "adm:stats")
async def admin_stats(call: CallbackQuery, db: Database) -> None:
    s = await db.stats()
    sponsors = await db.get_sponsors()
    sp_lines = "\n".join(
        f"{'🟢' if sp['active'] else '⏸'} {html.escape(sp['title'])}: "
        f"{sp['joined']}/{sp['target'] or '∞'}"
        for sp in sponsors
    ) or "нет"
    await call.answer()
    await call.message.edit_text(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{s['total']}</b>\n"
        f"💚 Живых (не заблокировали бота): <b>{s['alive']}</b>\n"
        f"✅ Прошли ОП: <b>{s['passed_op']}</b>\n"
        f"🔗 Пришли по рефссылкам: <b>{s['from_refs']}</b>\n\n"
        f"🆕 Сегодня: <b>{s['today']}</b> · 24ч: <b>{s['day']}</b> · 7 дней: <b>{s['week']}</b>\n\n"
        f"📢 <b>Спонсоры (привёл / заказ):</b>\n{sp_lines}",
        reply_markup=back_kb(),
    )


@router.callback_query(F.data == "adm:top")
async def admin_top(call: CallbackQuery, db: Database) -> None:
    rows = await db.top_referrers()
    lines = [
        f"{i}. {html.escape(r['first_name'] or '—')} "
        f"{'@' + r['username'] if r['username'] else ''} (<code>{r['id']}</code>) — {r['ref_count']}"
        for i, r in enumerate(rows, 1)
    ]
    await call.answer()
    await call.message.edit_text(
        "🏆 <b>Топ рефералов</b>\n\n" + ("\n".join(lines) or "пока пусто"),
        reply_markup=back_kb(),
    )


@router.message(Command("give"))
async def give(message: Message, command: CommandObject, db: Database) -> None:
    args = (command.args or "").split()
    if len(args) != 2 or not args[0].isdigit() or not re.fullmatch(r"-?\d+", args[1]):
        await message.answer("Формат: <code>/give ID количество</code>")
        return
    ok = await db.add_balance(int(args[0]), int(args[1]))
    await message.answer("✅ Готово" if ok else "❌ Пользователь не найден")


# ---------- реклама в выдаче ----------

@router.callback_query(F.data == "adm:ad")
async def ad_info(call: CallbackQuery, db: Database) -> None:
    ad = await db.get_setting(AD_KEY)
    await call.answer()
    await call.message.edit_text(
        "📝 <b>Реклама в выдаче</b>\n\n"
        "Этот текст показывается под каждым результатом (ники, генератор). "
        "Продавай это место рекламодателям отдельно от ОП.\n\n"
        "Установить: <code>/setad 🔥 Лучший канал про игры — @channel</code>\n"
        "Убрать: <code>/delad</code>\n\n"
        f"Сейчас: {ad or 'не задана'}",
        reply_markup=back_kb(),
        disable_web_page_preview=True,
    )


@router.message(Command("setad"))
async def set_ad(message: Message, command: CommandObject, db: Database) -> None:
    if not command.args:
        await message.answer("Формат: <code>/setad текст рекламы</code>")
        return
    # html_text сохраняет форматирование и ссылки из сообщения
    text = message.html_text.split(maxsplit=1)[1]
    await db.set_setting(AD_KEY, text)
    await message.answer(f"✅ Реклама установлена:\n\n{text}", disable_web_page_preview=True)


@router.message(Command("delad"))
async def del_ad(message: Message, db: Database) -> None:
    await db.set_setting(AD_KEY, None)
    await message.answer("✅ Реклама убрана")


# ---------- спонсоры (ОП) ----------

async def _sponsors_text(db: Database) -> tuple[str, list]:
    sponsors = await db.get_sponsors()
    lines = [
        f"{'🟢' if s['active'] else '⏸'} <b>{html.escape(s['title'])}</b> — "
        f"{s['joined']}/{s['target'] or '∞'}\n   {html.escape(s['url'])}"
        for s in sponsors
    ]
    text = (
        "📢 <b>Спонсоры обязательной подписки</b>\n\n"
        + ("\n".join(lines) if lines else "Пока нет ни одного.")
        + "\n\nНажми на спонсора — вкл/выкл, 🗑 — удалить.\n"
        "Засчитываются только те, кто подписался <b>через бота</b>. "
        "При выполнении заказа спонсор отключается сам."
    )
    return text, sponsors


@router.callback_query(F.data == "adm:sponsors")
async def sponsors_list(call: CallbackQuery, db: Database) -> None:
    text, sponsors = await _sponsors_text(db)
    await call.answer()
    await call.message.edit_text(text, reply_markup=sponsors_kb(sponsors),
                                 disable_web_page_preview=True)


@router.callback_query(F.data.startswith("adm:sp_toggle:") | F.data.startswith("adm:sp_del:"))
async def sponsor_action(call: CallbackQuery, db: Database) -> None:
    _, action, sid = call.data.split(":")
    if action == "sp_toggle":
        await db.toggle_sponsor(int(sid))
    else:
        await db.delete_sponsor(int(sid))
    text, sponsors = await _sponsors_text(db)
    await call.answer("Готово")
    await call.message.edit_text(text, reply_markup=sponsors_kb(sponsors),
                                 disable_web_page_preview=True)


@router.callback_query(F.data == "adm:sp_add")
async def sponsor_add_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SponsorAdd.chat)
    await call.answer()
    await call.message.answer(
        "1️⃣ Сначала <b>добавь бота админом</b> в канал спонсора "
        "(достаточно права «Добавлять участников»).\n\n"
        "Потом перешли сюда любой пост из канала, или пришли его @username или ID "
        "(<code>-100…</code>).\n\n/cancel — отмена"
    )


@router.message(SponsorAdd.chat)
async def sponsor_add_chat(message: Message, state: FSMContext, bot: Bot) -> None:
    if isinstance(message.forward_origin, MessageOriginChannel):
        ref: int | str = message.forward_origin.chat.id
    elif message.text and re.fullmatch(r"-?\d+", message.text.strip()):
        ref = int(message.text.strip())
    elif message.text:
        ref = "@" + message.text.strip().lstrip("@").removeprefix("https://t.me/")
    else:
        await message.answer("Перешли пост из канала или пришли @username / ID.")
        return

    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
    except TelegramAPIError as e:
        await message.answer(f"❌ Не вижу этот канал: {html.escape(str(e))}\n"
                             "Проверь, что бот добавлен в него админом.")
        return
    if me.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
        await message.answer("❌ Бот не админ в этом канале — без этого подписку не проверить.")
        return

    default_url = f"https://t.me/{chat.username}" if chat.username else None
    await state.update_data(chat_id=chat.id, title=chat.title or str(chat.id), default_url=default_url)
    await state.set_state(SponsorAdd.url)
    hint = f"или «-», чтобы использовать {default_url}" if default_url else \
        "(канал приватный — ссылка обязательна)"
    await message.answer(
        f"✅ Канал: <b>{html.escape(chat.title or '')}</b>\n\n"
        f"2️⃣ Пришли ссылку для кнопки подписки {hint}.\n"
        "Совет: создай отдельную пригласительную ссылку — рекламодатель увидит по ней, "
        "сколько людей пришло от тебя.",
        disable_web_page_preview=True,
    )


@router.message(SponsorAdd.url, F.text)
async def sponsor_add_url(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    url = message.text.strip()
    if url == "-" and data.get("default_url"):
        url = data["default_url"]
    if not url.startswith("https://t.me/"):
        await message.answer("Ссылка должна начинаться с https://t.me/")
        return
    await state.update_data(url=url)
    await state.set_state(SponsorAdd.target)
    await message.answer(
        "3️⃣ Сколько подписчиков заказал спонсор? Пришли число "
        "(0 — без лимита, спонсор висит, пока не отключишь вручную)."
    )


@router.message(SponsorAdd.target, F.text)
async def sponsor_add_target(message: Message, state: FSMContext, db: Database) -> None:
    if not message.text.strip().isdigit():
        await message.answer("Нужно число, например 1000")
        return
    data = await state.get_data()
    await db.add_sponsor(data["chat_id"], data["title"], data["url"], int(message.text.strip()))
    await state.clear()
    text, sponsors = await _sponsors_text(db)
    await message.answer("✅ Спонсор добавлен!\n\n" + text, reply_markup=sponsors_kb(sponsors),
                         disable_web_page_preview=True)


# ---------- рассылка ----------

@router.callback_query(F.data == "adm:mail")
async def mail_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Mailing.message)
    await call.answer()
    await call.message.answer(
        "✉️ Пришли сообщение для рассылки — текст, фото, видео, что угодно. "
        "Оно уйдёт всем пользователям как есть.\n\n/cancel — отмена"
    )


@router.message(Mailing.message)
async def mail_message(message: Message, state: FSMContext) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Mailing.button)
    await message.answer(
        "Добавить кнопку-ссылку? Пришли в формате:\n"
        "<code>Текст кнопки | https://t.me/channel</code>\n\nили «-», чтобы без кнопки."
    )


@router.message(Mailing.button, F.text)
async def mail_button(message: Message, state: FSMContext, bot: Bot) -> None:
    button = None
    if message.text.strip() != "-":
        parts = [p.strip() for p in message.text.split("|", 1)]
        if len(parts) != 2 or not parts[1].startswith(("https://", "http://", "tg://")):
            await message.answer("Формат: <code>Текст | https://ссылка</code> или «-»")
            return
        button = parts
    await state.update_data(button=button)
    data = await state.get_data()
    await message.answer("👀 Так увидят пользователи:")
    await bot.copy_message(message.chat.id, data["chat_id"], data["message_id"],
                           reply_markup=_mail_markup(button))
    await message.answer("Отправляем?", reply_markup=confirm_mail_kb())


def _mail_markup(button: list[str] | None) -> InlineKeyboardMarkup | None:
    if not button:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button[0], url=button[1])]])


@router.callback_query(F.data == "adm:mail_cancel")
async def mail_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer("Отменено")
    await call.message.edit_text("✖️ Рассылка отменена")


@router.callback_query(F.data == "adm:mail_go")
async def mail_go(call: CallbackQuery, state: FSMContext, bot: Bot, db: Database) -> None:
    data = await state.get_data()
    await state.clear()
    if "message_id" not in data:
        await call.answer("Нечего отправлять", show_alert=True)
        return
    await call.answer()
    await call.message.edit_text("🚀 Рассылка запущена, пришлю отчёт по завершении.")
    task = asyncio.create_task(_broadcast(
        bot, db, data["chat_id"], data["message_id"], _mail_markup(data.get("button")),
        call.from_user.id,
    ))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _broadcast(bot: Bot, db: Database, from_chat: int, message_id: int,
                     markup: InlineKeyboardMarkup | None, admin_id: int) -> None:
    user_ids = await db.active_user_ids()
    sent = blocked = failed = 0
    for uid in user_ids:
        for _ in range(2):
            try:
                await bot.copy_message(uid, from_chat, message_id, reply_markup=markup)
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except TelegramForbiddenError:
                await db.set_blocked(uid, True)
                blocked += 1
            except TelegramBadRequest:
                failed += 1
            except TelegramAPIError as e:
                log.warning("broadcast to %s failed: %s", uid, e)
                failed += 1
            break
        await asyncio.sleep(0.04)  # ~25 сообщений/сек — в пределах лимитов Telegram
    try:
        await bot.send_message(
            admin_id,
            f"✅ Рассылка завершена\n\nДоставлено: <b>{sent}</b>\n"
            f"Заблокировали бота: <b>{blocked}</b>\nОшибки: <b>{failed}</b>",
        )
    except TelegramAPIError:
        pass
