import asyncio
import html
import json
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import (TelegramAPIError, TelegramBadRequest, TelegramForbiddenError,
                                TelegramRetryAfter)
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from bot.config import Config
from bot.game.service import Game, GameError
from bot.game.tiers import TIERS

log = logging.getLogger(__name__)
router = Router(name="admin")
_tasks: set[asyncio.Task] = set()


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, config: Config) -> bool:
        return event.from_user is not None and event.from_user.id in config.admin_ids


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class Mailing(StatesGroup):
    message = State()
    button = State()
    confirm = State()


HELP = (
    "🛠 <b>Админка</b>\n\n"
    "/stats — статистика и экономика\n"
    "/broadcast — рассылка всем игрокам\n"
    "/give ID монеты [попытки] — начислить\n"
    "/reply ID текст — ответить игроку\n"
    "/refund ID_чека — вернуть звёзды и снять неиспользованное\n"
    "/config — текущие переопределения экономики (JSON)\n"
    "/setconfig {json} — изменить шансы, цены, награды без выкладки кода\n"
    "/cancel — отменить действие"
)


@router.message(Command("admin"))
async def admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(HELP)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


@router.message(Command("stats"))
async def stats(message: Message, game: Game) -> None:
    s = await game.admin_stats()
    drops = ", ".join(f"{TIERS[r['tier']].icon}{r['n']}" for r in s["top_drops"]) or "—"
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Игроков: <b>{s['users']}</b> (живых {s['alive']})\n"
        f"🆕 Новых сегодня: <b>{s['new_today']}</b> · активных сегодня: <b>{s['dau']}</b>\n"
        f"🤝 Засчитанных рефералов: <b>{s['referrals']}</b>\n\n"
        f"🎰 Спинов сегодня: <b>{s['spins_today']}</b>\n"
        f"Дропы сегодня по ступеням: {drops}\n\n"
        f"🪙 Монет у игроков: <b>{s['coins_total']}</b>\n"
        f"Сегодня выдано: {s['coins_in_today']} · слито: {s['coins_out_today']}\n\n"
        f"⭐ Stars за месяц: <b>{s['stars_month']}</b> · всего: <b>{s['stars_total']}</b>\n"
        f"≈ {round(s['stars_month'] * 0.013 * 85, 0):.0f} ₽ за месяц до комиссий вывода"
    )


@router.message(Command("give"))
async def give(message: Message, command: CommandObject, game: Game) -> None:
    args = (command.args or "").split()
    try:
        uid, coins = int(args[0]), int(args[1])
        spins = int(args[2]) if len(args) > 2 else 0
    except (IndexError, ValueError):
        await message.answer("Формат: <code>/give ID монеты [попытки]</code>")
        return
    async with game.db.tx():
        if not await game.db.one("SELECT 1 FROM users WHERE id = ?", uid):
            await message.answer("Игрок не найден")
            return
        await game._add(uid, coins, spins, "admin")
    await message.answer("✅ Начислено")


@router.message(Command("reply"))
async def reply(message: Message, command: CommandObject, bot: Bot) -> None:
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer("Формат: <code>/reply ID текст</code>")
        return
    try:
        await bot.send_message(int(parts[0]), f"💬 Поддержка:\n\n{html.escape(parts[1])}")
        await message.answer("✅ Отправлено")
    except TelegramAPIError as e:
        await message.answer(f"❌ {html.escape(str(e))}")


@router.message(Command("refund"))
async def refund(message: Message, command: CommandObject, bot: Bot, game: Game) -> None:
    charge_id = (command.args or "").strip()
    pay = await game.db.one("SELECT * FROM payments WHERE charge_id = ?", charge_id) if charge_id else None
    if not pay:
        await message.answer("Формат: <code>/refund ID_чека</code> (чек приходит игроку после оплаты)")
        return
    try:
        await bot.refund_star_payment(user_id=pay["user_id"], telegram_payment_charge_id=charge_id)
        result = await game.revoke_purchase(charge_id)
    except (TelegramAPIError, GameError) as e:
        await message.answer(f"❌ {html.escape(getattr(e, 'message', str(e)))}")
        return
    await message.answer(f"✅ Возвращено {result['stars']} ⭐ игроку <code>{result['user_id']}</code>")


@router.message(Command("config"))
async def show_config(message: Message, game: Game) -> None:
    raw = await game.db.get_setting("game_config") or "{}"
    await message.answer_document(
        BufferedInputFile(json.dumps(game.cfg, ensure_ascii=False, indent=2).encode(), "game_config_full.json"),
        caption=f"Переопределения сейчас:\n<code>{html.escape(raw[:800])}</code>\n\n"
                "В файле полный действующий конфиг. Изменить: /setconfig {json} — "
                "передавай только нужные ключи, остальное возьмётся по умолчанию.")


@router.message(Command("setconfig"))
async def set_config(message: Message, command: CommandObject, game: Game) -> None:
    try:
        override = json.loads(command.args or "")
        if not isinstance(override, dict):
            raise ValueError
    except ValueError:
        await message.answer("Нужен JSON-объект, например: <code>/setconfig {\"start_coins\": 300}</code>")
        return
    if "odds_version" not in override:
        override["odds_version"] = game.cfg["odds_version"] + 1  # у каждой версии шансов своя дата
    await game.db.set_setting("game_config", json.dumps(override, ensure_ascii=False))
    await game.load_config()
    await message.answer(f"✅ Конфиг обновлён, версия шансов {game.cfg['odds_version']}")


# ---------- рассылка ----------

@router.message(Command("broadcast"))
async def mail_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Mailing.message)
    await message.answer("✉️ Пришли сообщение для рассылки (текст, фото, видео). /cancel — отмена")


@router.message(Mailing.message)
async def mail_message(message: Message, state: FSMContext) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Mailing.button)
    await message.answer("Кнопка «Играть» под сообщением? Ответь «да» или «нет».")


@router.message(Mailing.button, F.text)
async def mail_button(message: Message, state: FSMContext, bot: Bot, config: Config) -> None:
    with_button = message.text.strip().lower() in ("да", "yes", "+")
    await state.update_data(button=with_button and config.webapp_url.startswith("https://"))
    data = await state.get_data()
    await message.answer("👀 Так увидят игроки:")
    await bot.copy_message(message.chat.id, data["chat_id"], data["message_id"],
                           reply_markup=_play_markup(config) if data["button"] else None)
    await state.set_state(Mailing.confirm)
    await message.answer("Отправить всем? Ответь «отправить» или /cancel.")


@router.message(Mailing.confirm, F.text.lower() == "отправить")
async def mail_go(message: Message, state: FSMContext, bot: Bot, game: Game, config: Config) -> None:
    data = await state.get_data()
    await state.clear()
    task = asyncio.create_task(_broadcast(bot, game, data["chat_id"], data["message_id"],
                                          _play_markup(config) if data.get("button") else None,
                                          message.from_user.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    await message.answer("🚀 Рассылка запущена, пришлю отчёт.")


def _play_markup(config: Config) -> InlineKeyboardMarkup:
    from aiogram.types import WebAppInfo
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Играть", web_app=WebAppInfo(url=config.webapp_url))]])


async def _broadcast(bot: Bot, game: Game, from_chat: int, message_id: int,
                     markup: InlineKeyboardMarkup | None, admin_id: int) -> None:
    rows = await game.db.all("SELECT id FROM users WHERE is_blocked = 0")
    sent = blocked = failed = 0
    for (uid,) in rows:
        for _ in range(2):
            try:
                await bot.copy_message(uid, from_chat, message_id, reply_markup=markup)
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except TelegramForbiddenError:
                async with game.db.tx():
                    await game.db.run("UPDATE users SET is_blocked = 1 WHERE id = ?", uid)
                blocked += 1
            except (TelegramBadRequest, TelegramAPIError):
                failed += 1
            break
        await asyncio.sleep(0.04)
    try:
        await bot.send_message(admin_id, f"✅ Рассылка завершена\nДоставлено: <b>{sent}</b>\n"
                                         f"Заблокировали бота: <b>{blocked}</b>\nОшибки: <b>{failed}</b>")
    except TelegramAPIError:
        pass
