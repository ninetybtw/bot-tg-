"""Цифры игры по ТЗ v1.4. Все суммы в копейках игрового рубля (*_cents).
Любой ключ переопределяется без выкладки кода: /setconfig в админке сохраняет JSON в базу,
а validate() не даёт сохранить конфиг с суммой шансов не 100% или возвратом вне 78–82%."""
import copy

from bot.game.odds import consolidated
from bot.game.tiers import expected_value

R = 100  # копеек в рубле

DEFAULTS: dict = {
    "odds_version": 1,
    "start_cents": 5_000 * R,
    # опорные цены ступеней: 100, 300, 1 000, 4 000, 20 000, 100 000, 500 000, 2 500 000 ₽
    "ladder_cents": [100 * R, 300 * R, 1_000 * R, 4_000 * R, 20_000 * R, 100_000 * R, 500_000 * R, 2_500_000 * R],
    "sell_system_pct": 60,
    "levels": [
        {"key": "common", "name": "Обычная", "price_cents": 1_000 * R, "pity": True,
         "odds": {0: .638, 1: .247, 2: .074, 3: .0285, 4: .01, 5: .0025},
         "goal": {"tier": 4, "label": "Легендарный+"}},
        {"key": "rare", "name": "Редкая", "price_cents": 3_000 * R, "pity": False,
         "odds": {2: .8215, 3: .1531, 4: .0218, 5: .0031, 6: .0005},
         "goal": {"tier": 4, "label": "Легендарный+"}},
        {"key": "epic", "name": "Эпическая", "price_cents": 10_000 * R, "pity": False,
         "odds": {3: .8735, 4: .1107, 5: .014, 6: .0018},
         "goal": {"tier": 4, "label": "Легендарный+"}},
        {"key": "legendary", "name": "Легендарная", "price_cents": 30_000 * R, "pity": False,
         "odds": {4: .9583, 5: .04, 6: .0017},
         "goal": {"tier": 5, "label": "Мифический+"}},
        {"key": "elite", "name": "Элитная", "price_cents": 150_000 * R, "pity": False,
         "odds": {5: .95, 6: .05},
         "goal": {"tier": 6, "label": "Секретный"}},
    ],
    "counts": [1, 3, 5, 10],
    "confirm_from_cents": 30_000 * R,
    "confirm_balance_share": 0.3,
    "pity": {"epic_plus": {"soft": 51, "step_pct": 5, "hard": 60},
             "legend_plus": {"soft": 281, "step_pct": 5, "hard": 300}},
    "energy": {"max": 3, "regen_minutes": 180},
    "coin_spins": {"per_day_base": 30, "per_level": 1, "per_day_max": 60},
    "upper_levels_per_day": 20,
    "starter": {"count": 5, "min_tier": 2},
    "break_hint_spins": 50,
    "xp": {"spin": 10, "per_1000_cents": 1},
    "inventory": {"slots": 200, "slots_max": 1000, "overflow_slots": 20, "overflow_hours": 48},
    "undo_sell": {"minutes": 10, "per_day": 5},
    "number_country_weights": {"RU": 40, "KZ": 20, "BY": 20, "AE": 20},
    "editions": {"4": 3, "5": 5},  # Легендарный тиражом 3, Мифический 5, ниже — уникальные
    "contracts": {"inputs": 5, "guaranteed_up_to_tier": 2, "success_pct": 70},
    "upgrader": {"k": 0.8, "max_items": 3, "fail_parts_pct": 10, "fail_bonus_pct": 3, "per_day": 10,
                 "max_share_of_collection": 0.5, "max_chance_pct": 80, "confirm_from_tier": 3},
    "market": {"fee_pct": 10, "fee_vip_pct": 5, "band_pct": [50, 150], "lots_max": 20, "lot_days": 3,
               "new_account_hours": 24, "hold_hours": 24},
    "wheel_daily": [
        {"label": "500", "cents": 500 * R, "p": 0.55},
        {"label": "1 000", "cents": 1_000 * R, "p": 0.25},
        {"label": "2 500", "cents": 2_500 * R, "p": 0.12},
        {"label": "1 спин", "attempts": 1, "p": 0.06},
        {"label": "10 000", "cents": 10_000 * R, "p": 0.02},
    ],
    "wheel_weekly": {
        "unlock_days": 5,
        "sectors": [
            {"label": "5 000", "cents": 5_000 * R, "p": 0.45},
            {"label": "10 000", "cents": 10_000 * R, "p": 0.30},
            {"label": "3 спина", "attempts": 3, "p": 0.15},
            {"label": "Эпик+", "item_min_tier": 3, "p": 0.08},
            {"label": "Рамка", "badge": "Рамка недели", "p": 0.02},
        ],
    },
    "gift": [500 * R, 750 * R, 1_000 * R, 1_500 * R, 2_000 * R, 3_000 * R, {"cents": 5_000 * R, "attempts": 3}],
    "tasks": [
        {"key": "spin3", "title": "Сделай 3 спина", "event": "spin", "target": 3, "cents": 400 * R},
        {"key": "sell1", "title": "Продай 1 номер", "event": "sell", "target": 1, "cents": 300 * R},
        {"key": "rating1", "title": "Загляни в рейтинг", "event": "rating", "target": 1, "cents": 300 * R},
        {"key": "wheel1", "title": "Крутни колесо", "event": "wheel", "target": 1, "cents": 300 * R},
        {"key": "spin10", "title": "Сделай 10 спинов", "event": "spin", "target": 10, "cents": 600 * R},
        {"key": "lock1", "title": "Поставь замок на номер", "event": "lock", "target": 1, "cents": 300 * R},
        {"key": "market1", "title": "Загляни на рынок", "event": "market", "target": 1, "cents": 300 * R},
    ],
    "tasks_per_day": 3,
    "tickets_per_task": 1,
    "weekly_tasks": [
        {"key": "w_contract", "title": "Собери «5 в 1»", "event": "contract", "target": 1, "cents": 3_000 * R,
         "badge": "Мастер 5 в 1"},
        {"key": "w_spin30", "title": "Сделай 30 спинов за неделю", "event": "spin", "target": 30, "cents": 3_000 * R,
         "badge": "Неделя в игре"},
    ],
    "raffle": {"hour_msk": 20, "prizes": [
        {"item_tier": 3}, {"item_tier": 2}, {"item_tier": 2}, {"item_tier": 2},
        {"cents": 3_000 * R}, {"cents": 3_000 * R}, {"cents": 3_000 * R},
        {"cents": 3_000 * R}, {"cents": 3_000 * R}, {"cents": 3_000 * R},
    ]},
    "referral": {
        "required_spins": 10, "friend_attempts": 3, "daily_limit": 20,
        "tiers": [
            {"count": 1, "attempts": 3, "title": "3 спина"},
            {"count": 5, "cents": 3_000 * R, "title": "3 000 ₽ и рамка профиля", "badge": "Рамка друзей"},
            {"count": 10, "cents": 10_000 * R, "title": "10 000 ₽ и эффект анимации", "badge": "Эффект «Неон»"},
            {"count": 25, "title": "Значок «Амбассадор»", "badge": "Амбассадор"},
        ],
    },
    "currency": {
        "show_game_label": True,
        "change_days": 30,
        "countries": {
            "RU": {"name": "Россия", "flag": "🇷🇺", "code": "RUB", "symbol": "₽", "rate": 1, "decimals": 0},
            "BY": {"name": "Беларусь", "flag": "🇧🇾", "code": "BYN", "symbol": "Br", "rate": 0.04, "decimals": 2},
            "KZ": {"name": "Казахстан", "flag": "🇰🇿", "code": "KZT", "symbol": "₸", "rate": 6, "decimals": 0},
            "UZ": {"name": "Узбекистан", "flag": "🇺🇿", "code": "UZS", "symbol": "сум", "rate": 150, "decimals": 0},
            "KG": {"name": "Кыргызстан", "flag": "🇰🇬", "code": "KGS", "symbol": "сом", "rate": 1, "decimals": 0},
            "AM": {"name": "Армения", "flag": "🇦🇲", "code": "AMD", "symbol": "֏", "rate": 5, "decimals": 0},
            "AZ": {"name": "Азербайджан", "flag": "🇦🇿", "code": "AZN", "symbol": "₼", "rate": 0.02, "decimals": 2},
            "TJ": {"name": "Таджикистан", "flag": "🇹🇯", "code": "TJS", "symbol": "смн", "rate": 0.1, "decimals": 2},
            "GE": {"name": "Грузия", "flag": "🇬🇪", "code": "GEL", "symbol": "₾", "rate": 0.03, "decimals": 2},
        },
        "by_language": {"be": "BY", "kk": "KZ", "uz": "UZ", "ky": "KG", "hy": "AM", "az": "AZ", "tg": "TJ",
                        "ka": "GE"},
    },
    "shop": {
        "monthly_cap_stars": 500, "warn_at_pct": 80, "attempts_stock_cap": 100, "attempts_daily_cap": 50,
        "luck2_daily": 3, "luck_spins": 10, "vip_daily_attempts": 2, "vip_slots": 10, "slots_max_buys": 3,
        "products": {
            "attempts5": {"title": "Попытки ×5", "desc": "5 дополнительных спинов", "stars": 25, "attempts": 5},
            "attempts20": {"title": "Попытки ×20", "desc": "20 дополнительных спинов", "stars": 89, "attempts": 20},
            "attempts50": {"title": "Попытки ×50", "desc": "50 дополнительных спинов", "stars": 199, "attempts": 50},
            "luck15": {"title": "Удача ×1,5", "desc": "Шансы старших ступеней ×1,5 на 10 спинов Обычной", "stars": 29,
                       "luck": 1.5},
            "luck2": {"title": "Удача ×2", "desc": "Шансы старших ступеней ×2 на 10 спинов Обычной", "stars": 49,
                      "luck": 2.0},
            "vip7": {"title": "VIP на 7 дней", "desc": "Комиссия рынка 5%, +2 попытки в день, +10 мест", "stars": 79,
                     "vip_days": 7},
            "vip30": {"title": "VIP на 30 дней", "desc": "Комиссия рынка 5%, +2 попытки в день, +10 мест",
                      "stars": 249, "vip_days": 30},
            "slots5": {"title": "+5 мест в коллекции", "desc": "Не больше 3 раз", "stars": 99, "slots": 5},
            "start": {"title": "Набор «Старт»", "desc": "VIP на 7 дней, Удача ×2 и 20 попыток", "stars": 169,
                      "vip_days": 7, "luck": 2.0, "attempts": 20, "once": True},
        },
    },
    "divine": [["RU", "900", "0000000"], ["KZ", "700", "0000000"], ["BY", "25", "0000000"], ["UZ", "90", "0000000"],
               ["KG", "70", "0000000"], ["AM", "9", "0000000"], ["AZ", "50", "0000000"], ["TJ", "90", "0000000"],
               ["GE", "55", "0000000"], ["AE", "50", "0000000"]],
}


def merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def normalize(cfg: dict) -> dict:
    """После JSON ключи шансов становятся строками — приводим к int."""
    for lv in cfg["levels"]:
        lv["odds"] = {int(t): float(p) for t, p in lv["odds"].items()}
    return cfg


def level(cfg: dict, key: str) -> dict:
    for lv in cfg["levels"]:
        if lv["key"] == key:
            return lv
    raise KeyError(key)


def level_return(cfg: dict, lv: dict, with_pity: bool = True) -> float:
    odds = consolidated(lv["odds"], cfg["pity"]) if (with_pity and lv["pity"]) else lv["odds"]
    return expected_value(odds, cfg["ladder_cents"]) / lv["price_cents"]


def validate(cfg: dict) -> list[str]:
    """Проверки конфига перед сохранением (ТЗ, задачи M0 и M8)."""
    errors = []
    for lv in cfg["levels"]:
        s = sum(lv["odds"].values())
        if abs(s - 1) > 1e-6:
            errors.append(f"{lv['name']}: сумма шансов {s * 100:.2f}% вместо 100%")
            continue
        r = level_return(cfg, lv)
        if not 0.78 <= r <= 0.82:
            errors.append(f"{lv['name']}: возврат {r * 100:.1f}% вне коридора 78–82%")
        tiers = sorted(lv["odds"])
        if lv["key"] != "common" and lv["odds"][tiers[0]] < 0.5:
            errors.append(f"{lv['name']}: нижняя ступень меньше 50%")
        if any(lv["odds"][a] < lv["odds"][b] for a, b in zip(tiers, tiers[1:])):
            errors.append(f"{lv['name']}: шансы должны убывать со ступенью")
    for code, c in cfg["currency"]["countries"].items():
        if not c.get("rate") or c["rate"] <= 0:
            errors.append(f"Курс {code} должен быть больше нуля")
    return errors


def level_from_xp(xp: int) -> tuple[int, int, int]:
    """(уровень, опыт внутри уровня, нужно до следующего)."""
    lvl, need = 1, 100
    while xp >= need:
        xp -= need
        lvl += 1
        need = 100 + 50 * (lvl - 1)
    return lvl, xp, need


def fmt_money(cents: int, country: dict) -> str:
    """«1 250 ₽», «50 Br», «7 500 ₸» — для текстов ошибок и бота (клиент форматирует сам так же)."""
    value = cents / 100 * country["rate"]
    d = country["decimals"]
    s = f"{value:,.{d}f}".replace(",", " ").replace(".", ",")
    return f"{s} {country['symbol']}"
