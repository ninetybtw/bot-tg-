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
from aiogram.types import (BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject,
                           WebAppInfo)

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
    "/panel — админка страницей: статистика, игроки, подкрутка, реклама, удача для всех\n"
    "/stats — игроки, спины, приток и слив по причинам, Stars\n"
    "/broadcast — рассылка всем игрокам\n"
    "/give ID рубли [попытки] — начислить\n"
    "/reply ID текст — ответить игроку\n"
    "/refund ID_чека — вернуть звёзды и снять неиспользованное\n"
    "/raffle — провести розыгрыш дня сейчас\n"
    "/ad — реклама на главном экране (до 3): показать, поставить, снять, статистика\n"
    "/config — текущий конфиг экономики файлом\n"
    "/setconfig {json} — новая версия конфига (проверка: шансы 100%, возврат 78–82%)\n"
    "/cancel — отменить действие"
)

REASONS = {
    "start": "старт", "spin_common": "Обычная", "spin_rare": "Редкая", "spin_epic": "Эпическая",
    "spin_legendary": "Легендарная", "spin_elite": "Элитная", "sell": "продажа системе", "sell_undo": "отмена продажи",
    "wheel_daily": "колесо дня", "wheel_weekly": "колесо недели", "gift": "подарок дня", "task": "задания",
    "task_weekly": "задание недели", "referral": "рефералы", "upgrade": "улучшение", "upgrade_parts": "запчасти",
    "market_buy": "рынок: покупки", "market_sale": "рынок: продажи", "market_fee": "комиссия рынка",
    "raffle": "розыгрыш", "overflow_sold": "переполнение", "admin": "админ",
}


def rub(cents: int) -> str:
    return f"{cents // 100:,}".replace(",", " ") + " ₽"


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
    drops = ", ".join(f"{TIERS[r['tier']].icon}{r['n']}" for r in s["drops_by_tier"]) or "—"
    reasons = "\n".join(f"  {REASONS.get(r['reason'], r['reason'])}: {'+' if r['cents'] > 0 else ''}{rub(r['cents'])}"
                        for r in s["reasons"]) or "  —"
    editions = ", ".join(f"{TIERS[r['tier']].icon} осталось {r['left_n']} из {r['size']}" for r in s["editions_low"])
    await message.answer(
        "📊 <b>Статистика за сегодня</b>\n\n"
        f"👥 Игроков: <b>{s['users']}</b> (живых {s['alive']}) · новых {s['new_today']} · активных {s['dau']}\n"
        f"🤝 Засчитанных рефералов: {s['referrals']}\n"
        f"🎰 Спинов: <b>{s['spins_today']}</b> · дропы: {drops}\n\n"
        f"💰 Баланс у игроков: {rub(s['balance_total_cents'])}\n"
        f"Приток на активного игрока: <b>{rub(s['inflow_per_active_cents'])}</b> "
        f"(цель — не больше 5 платных спинов, 5 000 ₽)\n"
        f"Движение по причинам:\n{reasons}\n\n"
        f"🏷 Выпущенные тиражи: {editions or '—'}\n"
        f"⭐ Stars за месяц: <b>{s['stars_month']}</b> · всего {s['stars_total']} "
        f"(≈ {round(s['stars_month'] * 0.013 * 85):,} ₽ до комиссий)".replace(",", " ")
    )


@router.message(Command("give"))
async def give(message: Message, command: CommandObject, game: Game) -> None:
    args = (command.args or "").split()
    try:
        uid, rubles = int(args[0]), int(args[1])
        attempts = int(args[2]) if len(args) > 2 else 0
    except (IndexError, ValueError):
        await message.answer("Формат: <code>/give ID рубли [попытки]</code>")
        return
    async with game.db.tx():
        if not await game.db.one("SELECT 1 FROM users WHERE id = ?", uid):
            await message.answer("Игрок не найден")
            return
        await game._add(uid, rubles * 100, attempts, "admin")
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


@router.message(Command("raffle"))
async def raffle_now(message: Message, game: Game) -> None:
    res = await game.raffle_draw()
    if not res:
        await message.answer("Сегодняшний розыгрыш уже проведён.")
        return
    lines = "\n".join(f"{w['place']}. {html.escape(w['name'])} — {html.escape(w['prize'])}" for w in res["winners"])
    await message.answer(f"🎟 Розыгрыш {res['day']}\n\n{lines or 'Билетов не было'}")


AD_HELP = (
    "📣 <b>Реклама на главном экране</b> — до 3 баннеров, листаются по очереди\n\n"
    "Добавить:\n<code>/ad Заголовок | Текст | https://t.me/канал | Кнопка | 📣</code>\n"
    "Кнопка и значок необязательны. Заголовок до 40 символов, текст до 80.\n"
    "Снять одну: <code>/ad off 2</code> (номер из списка), снять все: <code>/ad off</code>\n"
    "Удобнее — в /panel"
)


@router.message(Command("ad"))
async def ad(message: Message, command: CommandObject, game: Game) -> None:
    args = (command.args or "").strip()
    words = args.split()
    if words and words[0].lower() in ("off", "снять", "выкл"):
        if len(words) > 1 and words[1].isdigit() and 1 <= int(words[1]) <= len(game.ads):
            await game.remove_ad(game.ads[int(words[1]) - 1]["id"])
            await message.answer(f"✅ Реклама №{words[1]} снята")
        else:
            await game.remove_ad()
            await message.answer("✅ Вся реклама снята. На главном экране заглушка (если задан ADS_CONTACT)")
        return
    if args:
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            await message.answer(AD_HELP)
            return
        try:
            a = await game.set_ad(*(parts + ["", ""])[:5])
        except GameError as e:
            await message.answer(f"❌ {html.escape(e.message)}")
            return
        await message.answer(f"✅ Реклама №{len(game.ads)} стоит на главном экране у всех игроков:\n\n"
                             f"{html.escape(a['icon'])} <b>{html.escape(a['title'])}</b>\n{html.escape(a['text'])}\n"
                             f"[{html.escape(a['button'])}] → {html.escape(a['url'])}")
        return
    stats = await game.ads_stats()
    if not stats:
        await message.answer("Сейчас своей рекламы нет.\n\n" + AD_HELP)
        return
    lines = []
    for i, st in enumerate(stats, 1):
        a, v, c = st["ad"], st["view"], st["click"]
        ctr = f"{c['users'] / v['users'] * 100:.1f}%" if v["users"] else "—"
        lines.append(f"<b>{i}.</b> {html.escape(a['icon'])} <b>{html.escape(a['title'])}</b> → {html.escape(a['url'])}\n"
                     f"👀 увидели {v['users']} (сегодня {v['users_today']}) · 👆 перешли {c['users']} "
                     f"(сегодня {c['users_today']}) · конверсия {ctr}")
    await message.answer("📣 <b>Реклама на главном экране</b>\n\n" + "\n\n".join(lines) + "\n\n" + AD_HELP)


@router.message(Command("panel"))
async def panel(message: Message, config: Config) -> None:
    from bot.web import admin_token
    if not config.webapp_url.startswith("https://"):
        await message.answer("Нужен WEBAPP_URL с https — админка открывается по тому же адресу, что и игра")
        return
    url = f"{config.webapp_url}/admin#key={admin_token(config, message.from_user.id)}"
    await message.answer(
        "🛠 Админка: статистика, игроки и подкрутка, реклама, удача для всех, рассылка.\n\n"
        "Кнопка ниже открывает её внутри Telegram. Ссылка для браузера на компьютере действует 24 часа, "
        f"никому её не пересылай:\n<code>{html.escape(url)}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🛠 Открыть админку", web_app=WebAppInfo(url=f"{config.webapp_url}/admin"))]]))


@router.message(Command("config"))
async def show_config(message: Message, game: Game) -> None:
    raw = await game.db.get_setting("game_config") or "{}"
    full = json.dumps(game.cfg, ensure_ascii=False, indent=2, default=str)
    await message.answer_document(
        BufferedInputFile(full.encode(), "game_config_full.json"),
        caption=f"Переопределения сейчас:\n<code>{html.escape(raw[:800])}</code>\n\n"
                "Изменить: /setconfig {json}. Передавай только нужные ключи, остальное возьмётся по умолчанию.")


@router.message(Command("setconfig"))
async def set_config(message: Message, command: CommandObject, game: Game) -> None:
    try:
        override = json.loads(command.args or "")
        if not isinstance(override, dict):
            raise ValueError
    except ValueError:
        await message.answer("Нужен JSON-объект, например: <code>/setconfig {\"start_cents\": 300000}</code>")
        return
    override.setdefault("odds_version", game.cfg["odds_version"] + 1)
    errors = await game.save_config(override)
    if errors:
        await message.answer("❌ Конфиг не сохранён:\n" + "\n".join(f"• {html.escape(e)}" for e in errors))
        return
    await message.answer(f"✅ Конфиг сохранён, версия шансов {game.cfg['odds_version']}. "
                         "Не забудь объявить изменение шансов в канале за 24 часа.")


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
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Играть", web_app=WebAppInfo(url=config.webapp_url))]])


async def broadcast_text(bot: Bot, game: Game, config: Config, text: str, with_button: bool, admin_id: int) -> None:
    """Рассылка из админки-страницы: обычный текст, по желанию с кнопкой «Играть»."""
    markup = _play_markup(config) if with_button and config.webapp_url.startswith("https://") else None
    rows = await game.db.all("SELECT id FROM users WHERE is_blocked = 0")
    sent = blocked = failed = 0
    for (uid,) in rows:
        for _ in range(2):
            try:
                await bot.send_message(uid, html.escape(text), reply_markup=markup)
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except TelegramForbiddenError:
                async with game.db.tx():
                    await game.db.run("UPDATE users SET is_blocked = 1 WHERE id = ?", uid)
                blocked += 1
            except TelegramAPIError:
                failed += 1
            break
        await asyncio.sleep(0.04)
    try:
        await bot.send_message(admin_id, f"✅ Рассылка из админки завершена\nДоставлено: <b>{sent}</b>\n"
                                         f"Заблокировали бота: <b>{blocked}</b>\nОшибки: <b>{failed}</b>")
    except TelegramAPIError:
        pass


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
