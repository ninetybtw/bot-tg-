"""Единая шкала редкости (раздел «Система редкостей» ТЗ)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    idx: int
    key: str
    name: str
    icon: str
    color: str


TIERS: list[Tier] = [
    Tier(0, "common", "Обычный", "○", "#9aa4b2"),
    Tier(1, "uncommon", "Необычный", "◇", "#4cc38a"),
    Tier(2, "rare", "Редкий", "◆", "#4c8dff"),
    Tier(3, "epic", "Эпик", "⬢", "#a06bff"),
    Tier(4, "legendary", "Легендарный", "★", "#ff5fb4"),
    Tier(5, "mythic", "Мифический", "✹", "#ff4d4d"),
    Tier(6, "secret", "Секретный", "♛", "#f5c542"),
    Tier(7, "divine", "Божественный", "✺", "rainbow"),
    Tier(8, "exclusive", "Эксклюзив", "◈", "#111111"),
]

COMMON, UNCOMMON, RARE, EPIC, LEGENDARY, MYTHIC, SECRET, DIVINE, EXCLUSIVE = range(9)

# Опорные цены телефона/номера/скина, монет (раздел 2)
PHONE_PRICES = [10, 30, 100, 400, 2_000, 10_000, 50_000, 250_000]

# Шансы по шкалам спина (раздел 3), доли по индексу ступени
SCALES: dict[str, dict] = {
    "phone": {
        "title": "Обычный спин",
        "price": 100,
        "odds": {COMMON: 0.62, UNCOMMON: 0.24, RARE: 0.09, EPIC: 0.035, LEGENDARY: 0.012, MYTHIC: 0.003},
    },
    "premium": {
        "title": "Премиум-спин",
        "price": 500,
        "odds": {RARE: 0.70, EPIC: 0.22, LEGENDARY: 0.067, MYTHIC: 0.012, SECRET: 0.001},
    },
}

# Контракт «5 в 1»
CONTRACT_SIZE = 5
CONTRACT_MAX_INPUT = SECRET  # из 5 Секретных выходит Божественный


def tier_dict(i: int) -> dict:
    t = TIERS[i]
    return {"idx": t.idx, "key": t.key, "name": t.name, "icon": t.icon, "color": t.color}


def apply_luck(odds: dict[int, float], m: float) -> dict[int, float]:
    """Удача умножает шансы всех ступеней, кроме двух самых частых.
    Освободившийся шанс забирают две частые ступени пропорционально долям."""
    if m <= 1:
        return dict(odds)
    common = sorted(odds, key=lambda t: odds[t], reverse=True)[:2]
    boosted = {t: p * m for t, p in odds.items() if t not in common}
    rest = 1 - sum(boosted.values())
    c_sum = sum(odds[t] for t in common)
    if rest <= 0:
        raise ValueError("Слишком большой множитель удачи")
    out = dict(boosted)
    for t in common:
        out[t] = odds[t] * rest / c_sum
    return out


def expected_value(odds: dict[int, float], prices: list[int] = PHONE_PRICES) -> float:
    return sum(p * prices[t] for t, p in odds.items())


def one_in(p: float) -> int:
    return max(1, round(1 / p)) if p > 0 else 0
