from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.services.nickgen import THEMES

BTN_NICK = "✨ Красивый ник"
BTN_GEN = "🎲 Генератор ников"
BTN_USERNAME = "💎 Свободные @username"
BTN_BONUS = "🎁 Бонус"
BTN_FRIENDS = "👥 Пригласить друзей"
BTN_PROFILE = "👤 Профиль"

MENU_BUTTONS = {BTN_NICK, BTN_GEN, BTN_USERNAME, BTN_BONUS, BTN_FRIENDS, BTN_PROFILE}

# Стоимость поиска свободных @username по длине
FIND_COST = {5: 3, 6: 1}


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NICK), KeyboardButton(text=BTN_GEN)],
            [KeyboardButton(text=BTN_USERNAME)],
            [KeyboardButton(text=BTN_BONUS), KeyboardButton(text=BTN_FRIENDS)],
            [KeyboardButton(text=BTN_PROFILE)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Отправь текст — сделаю красивый ник",
    )


def _ikb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """rows: [[(text, callback_data или https://url), ...], ...]"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t, url=d) if d.startswith(("http://", "https://", "tg://"))
            else InlineKeyboardButton(text=t, callback_data=d)
            for t, d in row
        ]
        for row in rows
    ])


def subscribe_kb(sponsors) -> InlineKeyboardMarkup:
    rows = [[(f"➕ {s['title']}", s["url"])] for s in sponsors]
    rows.append([("✅ Я подписался", "op_check")])
    return _ikb(rows)


def themes_kb() -> InlineKeyboardMarkup:
    items = [(t["title"], f"gen:{key}") for key, t in THEMES.items()]
    return _ikb([items[i:i + 2] for i in range(0, len(items), 2)])


def gen_more_kb(theme: str) -> InlineKeyboardMarkup:
    return _ikb([[("🔄 Ещё", f"gen:{theme}"), ("📂 Темы", "gen_themes")]])


def username_kb() -> InlineKeyboardMarkup:
    return _ikb([
        [(f"🔍 5 букв — {FIND_COST[5]} 💎", "un_find:5"), (f"🔍 6 букв — {FIND_COST[6]} 💎", "un_find:6")],
        [("✏️ Проверить свой вариант", "un_check")],
    ])


def no_balance_kb(share_url: str) -> InlineKeyboardMarkup:
    return _ikb([[("👥 Пригласить друга", share_url)], [("🎁 Забрать бонус", "bonus")]])


def share_kb(share_url: str) -> InlineKeyboardMarkup:
    return _ikb([[("📤 Отправить друзьям", share_url)]])


# ---------- админка ----------

def admin_kb() -> InlineKeyboardMarkup:
    return _ikb([
        [("📊 Статистика", "adm:stats"), ("🏆 Топ рефералов", "adm:top")],
        [("📢 Спонсоры (ОП)", "adm:sponsors")],
        [("✉️ Рассылка", "adm:mail"), ("📝 Реклама в выдаче", "adm:ad")],
    ])


def sponsors_kb(sponsors) -> InlineKeyboardMarkup:
    rows = []
    for s in sponsors:
        state = "🟢" if s["active"] else "⏸"
        rows.append([
            (f"{state} {s['title']}", f"adm:sp_toggle:{s['id']}"),
            ("🗑", f"adm:sp_del:{s['id']}"),
        ])
    rows.append([("➕ Добавить спонсора", "adm:sp_add")])
    rows.append([("⬅️ Назад", "adm:back")])
    return _ikb(rows)


def back_kb() -> InlineKeyboardMarkup:
    return _ikb([[("⬅️ Назад", "adm:back")]])


def confirm_mail_kb() -> InlineKeyboardMarkup:
    return _ikb([[("🚀 Отправить всем", "adm:mail_go"), ("✖️ Отмена", "adm:mail_cancel")]])
