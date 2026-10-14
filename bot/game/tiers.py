"""Единая шкала редкости (ТЗ v1.4, «Система редкостей»). Индексы ступеней с нуля."""
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


def tier_dict(i: int) -> dict:
    t = TIERS[i]
    return {"idx": t.idx, "key": t.key, "name": t.name, "icon": t.icon, "color": t.color}


LUCK_CAP = 0.9


def apply_luck(odds: dict[int, float], m: float) -> dict[int, float]:
    """Удача: все ступени, кроме двух самых частых, ×m; частые отдают разницу пропорционально.
    При большом множителе (×5, ×10) редкие ступени вместе не больше 90%, пропорции между ними те же."""
    if m <= 1 or len(odds) < 3:
        return dict(odds)
    common = sorted(odds, key=lambda t: odds[t], reverse=True)[:2]
    out = {t: p * m for t, p in odds.items() if t not in common}
    boosted = sum(out.values())
    if boosted > LUCK_CAP:
        out = {t: p * LUCK_CAP / boosted for t, p in out.items()}
    rest = 1 - sum(out.values())
    c_sum = sum(odds[t] for t in common)
    for t in common:
        out[t] = odds[t] * rest / c_sum
    return out


def expected_value(odds: dict[int, float], prices: list[int]) -> float:
    return sum(p * prices[t] for t, p in odds.items())


def one_in(p: float) -> int | None:
    return max(1, round(1 / p)) if p > 0 else None
