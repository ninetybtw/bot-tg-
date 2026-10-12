import html
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db import Database
from bot.keyboards import BTN_BONUS, BTN_FRIENDS, BTN_PROFILE, share_kb
from bot.utils import ref_link, share_url

router = Router(name="profile")

BONUS_COOLDOWN = timedelta(hours=24)


@router.message(F.text == BTN_FRIENDS)
async def friends(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    link = await ref_link(message.bot, message.from_user.id)
    await message.answer(
        "👥 <b>Приглашай друзей — получай кристаллы</b>\n\n"
        f"За каждого друга, который запустит бота: <b>+{config.ref_reward} 💎</b>\n"
        f"Ты пригласил: <b>{user['ref_count']}</b>\n\n"
        f"Твоя ссылка (нажми, чтобы скопировать):\n<code>{link}</code>",
        reply_markup=share_kb(await share_url(message.bot, message.from_user.id)),
    )


@router.message(F.text == BTN_PROFILE)
async def profile(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    await message.answer(
        f"👤 <b>{html.escape(message.from_user.first_name or 'Профиль')}</b>\n\n"
        f"🆔 ID: <code>{user['id']}</code>\n"
        f"💎 Баланс: <b>{user['balance']}</b>\n"
        f"👥 Друзей приглашено: <b>{user['ref_count']}</b>\n"
        f"📅 С нами с {user['created_at'][:10]}"
    )


async def _claim(user_id: int, db: Database, config: Config) -> str:
    ok, left = await db.claim_bonus(user_id, config.daily_bonus, BONUS_COOLDOWN)
    if ok:
        return f"🎁 +{config.daily_bonus} 💎! Возвращайся завтра за новым бонусом."
    hours, rem = divmod(int(left.total_seconds()), 3600)
    return f"⏳ Бонус уже получен. Следующий через {hours} ч {rem // 60} мин."


@router.message(F.text == BTN_BONUS)
async def bonus(message: Message, state: FSMContext, db: Database, config: Config) -> None:
    await state.clear()
    await message.answer(await _claim(message.from_user.id, db, config))


@router.callback_query(F.data == "bonus")
async def bonus_cb(call: CallbackQuery, db: Database, config: Config) -> None:
    await call.answer(await _claim(call.from_user.id, db, config), show_alert=True)
