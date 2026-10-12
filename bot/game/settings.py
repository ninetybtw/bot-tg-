"""Параметры экономики. Значения по умолчанию взяты из ТЗ, любые можно
переопределить без выкладки кода: админ-команда /setconfig сохраняет JSON в базу."""
import copy

DEFAULTS: dict = {
    "odds_version": 1,
    "start_coins": 200,
    "energy_max": 3,
    "energy_period_sec": 3 * 3600,
    "coin_spins_daily": 30,          # +1 за уровень, до 60
    "coin_spins_daily_cap": 60,
    "pity_epic": 40,
    "pity_legendary": 200,
    "break_hint_spins": 50,
    "xp_spin": 10,
    "xp_premium": 50,
    "referral": {
        "required_spins": 10,
        "friend_spins": 3,
        "daily_limit": 20,
        "tiers": [
            {"count": 1, "spins": 3, "coins": 0, "title": "3 спина"},
            {"count": 5, "spins": 0, "coins": 300, "title": "300 монет и рамка профиля", "badge": "Рамка друзей"},
            {"count": 10, "spins": 0, "coins": 1000, "title": "1 000 монет и эффект анимации", "badge": "Эффект «Неон»"},
            {"count": 25, "spins": 0, "coins": 0, "title": "Значок «Амбассадор»", "badge": "Амбассадор"},
        ],
    },
    "wheel": [
        {"label": "50", "coins": 50, "p": 0.55},
        {"label": "100", "coins": 100, "p": 0.25},
        {"label": "250", "coins": 250, "p": 0.12},
        {"label": "1 спин", "spins": 1, "p": 0.06},
        {"label": "1 000", "coins": 1000, "p": 0.02},
    ],
    "gift": [50, 75, 100, 150, 200, 300, {"coins": 500, "spins": 3}],
    "tasks": [
        {"key": "spin3", "title": "Сделай 3 спина", "event": "spin", "target": 3, "coins": 40},
        {"key": "sell1", "title": "Продай 1 номер", "event": "sell", "target": 1, "coins": 30},
        {"key": "rating1", "title": "Загляни в рейтинг", "event": "rating", "target": 1, "coins": 30},
        {"key": "wheel1", "title": "Крутни колесо", "event": "wheel", "target": 1, "coins": 30},
        {"key": "spin10", "title": "Сделай 10 спинов", "event": "spin", "target": 10, "coins": 60},
        {"key": "contract1", "title": "Собери «5 в 1»", "event": "contract", "target": 1, "coins": 60},
        {"key": "market1", "title": "Загляни на рынок", "event": "market", "target": 1, "coins": 30},
    ],
    "tasks_per_day": 3,
    "market": {"min_k": 0.5, "max_k": 1.5, "fee": 0.10, "lot_days": 3, "max_lots": 20, "new_account_hours": 24},
    "upgrade": {"k": 0.85, "fail_bonus": 0.03, "refund": 0.10, "daily": 10, "max_items": 3, "max_chance": 0.9},
    "shop": {
        "monthly_cap_stars": 500,
        "spins_stock_cap": 100,
        "spins_daily_cap": 50,
        "luck2_daily": 3,
        "luck_spins": 10,
        "products": {
            "spins5": {"title": "Попытки ×5", "desc": "5 дополнительных спинов", "stars": 25, "spins": 5},
            "spins20": {"title": "Попытки ×20", "desc": "20 дополнительных спинов", "stars": 89, "spins": 20},
            "spins50": {"title": "Попытки ×50", "desc": "50 дополнительных спинов", "stars": 199, "spins": 50},
            "luck15": {"title": "Удача ×1,5", "desc": "Шансы старших ступеней ×1,5 на 10 спинов", "stars": 29, "luck": 1.5},
            "luck2": {"title": "Удача ×2", "desc": "Шансы старших ступеней ×2 на 10 спинов", "stars": 49, "luck": 2.0},
        },
    },
    "divine": [["RU", "900", "0000000"], ["KZ", "700", "0000000"], ["BY", "25", "0000000"], ["AE", "50", "0000000"]],
}


def merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def level_from_xp(xp: int) -> tuple[int, int, int]:
    """(уровень, опыт внутри уровня, нужно до следующего)."""
    level, need = 1, 100
    while xp >= need:
        xp -= need
        level += 1
        need = 100 + 50 * (level - 1)
    return level, xp, need
