"""Бот «Телефоны»: генератор номеров под ступень и классификатор узоров.

Главное правило (ТЗ): ступень выбирается первой, номер собирается под неё,
а классификатор проверяет, что получилась именно эта ступень.
"""
import random
from dataclasses import dataclass

from bot.game.tiers import COMMON, DIVINE, EPIC, LEGENDARY, MYTHIC, RARE, SECRET, UNCOMMON

DIGITS = "0123456789"


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    flag: str
    dial: str
    operators: tuple[str, ...]
    sub_len: int
    groups: tuple[int, ...]  # как разбивать абонентскую часть
    sep: str


COUNTRIES: dict[str, Country] = {
    "RU": Country("RU", "Россия", "🇷🇺", "+7", tuple(str(x) for x in range(900, 1000)), 7, (3, 2, 2), "-"),
    "KZ": Country("KZ", "Казахстан", "🇰🇿", "+7",
                  ("700", "701", "702", "705", "707", "708", "747", "750", "751", "760", "771",
                   "775", "776", "777", "778"), 7, (3, 2, 2), "-"),
    "BY": Country("BY", "Беларусь", "🇧🇾", "+375", ("25", "29", "33", "44"), 7, (3, 2, 2), "-"),
    "AE": Country("AE", "ОАЭ", "🇦🇪", "+971", ("50", "52", "54", "55", "56", "58"), 7, (3, 4), " "),
}

# Сочетания, которые генератор не выдаёт никогда (ТЗ, раздел 7)
BLACKLIST = ("1488", "228", "420", "69")

# Закрытый список Божественных номеров (в продакшене ведётся в админке)
DEFAULT_DIVINE = (("RU", "900", "0000000"), ("KZ", "700", "0000000"),
                  ("BY", "25", "0000000"), ("AE", "50", "0000000"))


def format_number(country: str, op: str, sub: str) -> str:
    c = COUNTRIES[country]
    parts, i = [], 0
    for g in c.groups:
        parts.append(sub[i:i + g])
        i += g
    return f"{c.dial} {op} {c.sep.join(parts)}"


def _max_run(s: str) -> int:
    best = cur = 1
    for a, b in zip(s, s[1:]):
        cur = cur + 1 if a == b else 1
        best = max(best, cur)
    return best


def _max_ladder(s: str) -> int:
    """Длина самой длинной лесенки (…1234 или …4321)."""
    best = 1
    for step in (1, -1):
        cur = 1
        for a, b in zip(s, s[1:]):
            cur = cur + 1 if int(b) - int(a) == step else 1
            best = max(best, cur)
    return best


def _ladder_at_end(s: str, n: int) -> bool:
    tail = s[-n:]
    return any(all(int(b) - int(a) == step for a, b in zip(tail, tail[1:])) for step in (1, -1))


def _is_pal(s: str) -> bool:
    return s == s[::-1]


def classify(country: str, op: str, sub: str, divine=DEFAULT_DIVINE) -> int:
    full = op + sub
    if (country, op, sub) in divine:
        return DIVINE
    all_same = len(set(full)) == 1
    if _is_pal(full) and not all_same:
        return SECRET
    if all_same or (len(full) >= 9 and _max_ladder(full) == len(full)):
        return MYTHIC
    s = sub  # код оператора для остальных ступеней не считается
    if _max_run(s) >= 6:
        return LEGENDARY
    if (len(set(s[-4:])) == 1 or _max_ladder(s) >= 4
            or (s[-4] == s[-3] and s[-2] == s[-1]) or _is_pal(s[-6:])):
        return EPIC
    if _max_run(s) >= 3 or _is_pal(s[-4:]) or _ladder_at_end(s, 3):
        return RARE
    if s[-1] == s[-2]:
        return UNCOMMON
    return COMMON


def is_blacklisted(full: str) -> bool:
    return any(b in full for b in BLACKLIST)


def _rand(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(DIGITS) for _ in range(n))


def _ladder(rng: random.Random, n: int) -> str | None:
    step = rng.choice((1, -1))
    start = rng.randint(0, 9)
    out = [start + i * step for i in range(n)]
    if not all(0 <= d <= 9 for d in out):
        return None
    return "".join(map(str, out))


def _build(tier: int, c: Country, rng: random.Random, divine) -> tuple[str, str] | None:
    n = c.sub_len
    op = rng.choice(c.operators)
    s = _rand(rng, n)
    d = rng.choice(DIGITS)

    if tier == COMMON:
        return op, s
    if tier == UNCOMMON:
        return op, s[:-2] + (d * 2 if rng.random() < 0.8 else "00")
    if tier == RARE:
        kind = rng.randrange(3)
        if kind == 0:
            p = rng.randint(0, n - 3)
            return op, s[:p] + d * 3 + s[p + 3:]
        if kind == 1:
            a, b = rng.choice(DIGITS), rng.choice(DIGITS)
            return op, s[:-4] + a + b + b + a
        lad = _ladder(rng, 3)
        return (op, s[:-3] + lad) if lad else None
    if tier == EPIC:
        kind = rng.randrange(4)
        if kind == 0:
            return op, s[:-4] + d * 4
        if kind == 1:
            ln = rng.choice((4, 4, 5))
            lad = _ladder(rng, ln)
            if not lad:
                return None
            p = rng.randint(0, n - ln)
            return op, s[:p] + lad + s[p + ln:]
        if kind == 2:
            a, b = rng.sample(DIGITS, 2)
            return op, s[:-4] + a * 2 + b * 2
        half = _rand(rng, 3)
        return op, s[:-6] + half + half[::-1]
    if tier == LEGENDARY:
        ln = rng.choice((6, 6, 7))
        p = rng.randint(0, n - ln)
        return op, s[:p] + d * ln + s[p + ln:]
    if tier == MYTHIC:
        options = []
        for o in c.operators:
            if len(set(o)) == 1:
                options.append((o, o[0] * n))
            for lad in ("0123456789", "9876543210", "123456789", "987654321"):
                if len(lad) == len(o) + n and lad.startswith(o):
                    options.append((o, lad[len(o):]))
        return rng.choice(options) if options else None
    if tier == SECRET:
        total = len(op) + n
        head_len = (total + 1) // 2
        head = op + _rand(rng, head_len - len(op))
        full = head + head[: total // 2][::-1]
        return op, full[len(op):]
    if tier == DIVINE:
        own = [(o, sub) for cc, o, sub in divine if cc == c.code]
        return rng.choice(own) if own else None
    return None


def generate(tier: int, country: str, rng: random.Random | None = None,
             divine=DEFAULT_DIVINE) -> tuple[str, str, str]:
    """Возвращает (страна, код оператора, абонентская часть) ровно указанной ступени."""
    rng = rng or random.Random()
    codes = [country] + [c for c in COUNTRIES if c != country]
    for code in codes:  # если в стране ступень невозможна (Мифический), берём соседнюю
        c = COUNTRIES[code]
        for _ in range(2000):
            built = _build(tier, c, rng, divine)
            if not built:
                continue
            op, sub = built
            if len(sub) != c.sub_len or (tier != DIVINE and is_blacklisted(op + sub)):
                continue
            if classify(code, op, sub, divine) == tier:
                return code, op, sub
    raise RuntimeError(f"Не удалось собрать номер ступени {tier}")
