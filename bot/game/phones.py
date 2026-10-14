"""Номера телефонов: генератор под ступень и классификатор узоров (ТЗ v1.4, «Узоры номеров»).

Ступень выбирается первой, номер собирается под неё, классификатор проверяет, что получилась
именно эта ступень и нет чёрного списка. Узор ищется в хвосте из 7 цифр, код оператора не считается;
исключения — палиндром всего номера (Секретный) и все 10 одинаковых / полная лесенка (Мифический).
"""
import random
from dataclasses import dataclass

from bot.game.tiers import COMMON, DIVINE, EPIC, LEGENDARY, MYTHIC, RARE, SECRET, UNCOMMON

DIGITS = "0123456789"
TAIL = 7


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    flag: str
    dial: str
    operators: tuple[str, ...]
    groups: tuple[int, ...]
    sep: str
    regroup: tuple[int, ...] = ()  # как принято писать номер в стране: группы по всем цифрам после кода страны


COUNTRIES: dict[str, Country] = {
    "RU": Country("RU", "Россия", "🇷🇺", "+7", tuple(str(x) for x in range(900, 1000)), (3, 2, 2), "-"),
    "KZ": Country("KZ", "Казахстан", "🇰🇿", "+7",
                  ("700", "701", "702", "705", "707", "708", "747", "750", "751", "760", "771",
                   "775", "776", "777", "778"), (3, 2, 2), "-"),
    "BY": Country("BY", "Беларусь", "🇧🇾", "+375", ("25", "29", "33", "44"), (3, 2, 2), "-"),
    "UZ": Country("UZ", "Узбекистан", "🇺🇿", "+998",
                  ("90", "91", "93", "94", "95", "97", "98", "99", "33", "88", "77", "50"), (3, 2, 2), "-"),
    "KG": Country("KG", "Кыргызстан", "🇰🇬", "+996", ("70", "50", "55", "77", "22", "99"), (3, 2, 2), " ",
                  regroup=(3, 3, 3)),
    "AM": Country("AM", "Армения", "🇦🇲", "+374", ("9", "7", "4", "5", "3"), (3, 2, 2), "-",
                  regroup=(2, 2, 2, 2)),
    "AZ": Country("AZ", "Азербайджан", "🇦🇿", "+994", ("10", "50", "51", "55", "60", "70", "77", "99"),
                  (3, 2, 2), "-"),
    "TJ": Country("TJ", "Таджикистан", "🇹🇯", "+992", ("90", "91", "92", "93", "98", "88", "55", "50", "77", "70"),
                  (3, 2, 2), "-"),
    "GE": Country("GE", "Грузия", "🇬🇪", "+995", ("55", "57", "59", "51"), (3, 2, 2), "-", regroup=(3, 2, 2, 2)),
    "AE": Country("AE", "ОАЭ", "🇦🇪", "+971", ("50", "52", "54", "55", "56", "58"), (3, 4), " "),
}

BLACKLIST = ("1488", "228", "420", "69")

RULES = {
    "none": "Без узора", "pair_end": "Пара в конце", "round_end": "Круглое окончание",
    "triple": "Тройка подряд", "mirror4": "Зеркало", "ladder3_end": "Лесенка из 3",
    "four_end": "Четыре в конце", "ladder4": "Лесенка", "two_pairs": "Две пары", "mirror6": "Зеркало из 6",
    "six_same": "Шесть одинаковых", "tail_same": "Весь хвост одинаковый", "tail_ladder": "Лесенка из 7",
    "full_same": "Все цифры одинаковые", "full_ladder": "Полная лесенка", "palindrome": "Палиндром",
    "divine": "Особый номер",
}

TAIL_LADDERS = ("0123456", "1234567", "2345678", "3456789", "9876543", "8765432", "7654321", "6543210")


def format_number(country: str, op: str, sub: str) -> str:
    """«+7 999 123-45-67». Первая группа после кода страны всегда отделена пробелом."""
    c = COUNTRIES[country]
    if c.regroup:
        digits, parts, i = op + sub, [], 0
        for g in c.regroup:
            parts.append(digits[i:i + g])
            i += g
        return f"{c.dial} {parts[0]} {c.sep.join(parts[1:])}"
    parts, i = [], 0
    for g in c.groups:
        parts.append(sub[i:i + g])
        i += g
    return f"{c.dial} {op} {c.sep.join(parts)}"


def number_key(country: str, op: str, sub: str) -> str:
    return f"{country}:{op}{sub}"


def _runs(s: str):
    """(начало, длина) самых длинных повторов одной цифры."""
    best, start = (0, 1), 0
    for i in range(1, len(s) + 1):
        if i == len(s) or s[i] != s[start]:
            if i - start > best[1]:
                best = (start, i - start)
            start = i
    return best


def _ladder(s: str) -> tuple[int, int]:
    """(начало, длина) самой длинной лесенки шагом +1 или −1."""
    best = (0, 1)
    for step in (1, -1):
        start = 0
        for i in range(1, len(s) + 1):
            if i == len(s) or int(s[i]) - int(s[i - 1]) != step:
                if i - start > best[1]:
                    best = (start, i - start)
                start = i
    return best


def _is_ladder_end(s: str, n: int) -> bool:
    t = s[-n:]
    return any(all(int(b) - int(a) == st for a, b in zip(t, t[1:])) for st in (1, -1))


def classify(country: str, op: str, sub: str, divine=()) -> tuple[int, str, list[int]]:
    """(ступень, правило, позиции подсвеченных цифр в op+sub). Один классификатор для выдачи,
    рынка и рейтинга."""
    full = op + sub
    off = len(op)
    tail = list(range(off, len(full)))
    if (country, op, sub) in divine:
        return DIVINE, "divine", list(range(len(full)))
    same_full = len(set(full)) == 1
    if full == full[::-1] and not same_full:
        return SECRET, "palindrome", list(range(len(full)))
    if same_full:
        return MYTHIC, "full_same", list(range(len(full)))
    if len(full) >= 9 and _ladder(full)[1] == len(full):
        return MYTHIC, "full_ladder", list(range(len(full)))
    s = sub
    if len(set(s)) == 1:
        return MYTHIC, "tail_same", tail
    if s in TAIL_LADDERS:
        return MYTHIC, "tail_ladder", tail
    run_start, run_len = _runs(s)
    if run_len >= 6:
        return LEGENDARY, "six_same", [off + i for i in range(run_start, run_start + run_len)]
    if len(set(s[-4:])) == 1:
        return EPIC, "four_end", tail[-4:]
    lad_start, lad_len = _ladder(s)
    if lad_len >= 4:
        return EPIC, "ladder4", [off + i for i in range(lad_start, lad_start + lad_len)]
    if s[-4] == s[-3] and s[-2] == s[-1]:
        return EPIC, "two_pairs", tail[-4:]
    if s[-6:] == s[-6:][::-1]:
        return EPIC, "mirror6", tail[-6:]
    if run_len >= 3:
        return RARE, "triple", [off + i for i in range(run_start, run_start + run_len)]
    if s[-4:] == s[-4:][::-1]:
        return RARE, "mirror4", tail[-4:]
    if _is_ladder_end(s, 3):
        return RARE, "ladder3_end", tail[-3:]
    if s[-2:] == "00":
        return UNCOMMON, "round_end", tail[-2:]
    if s[-1] == s[-2]:
        return UNCOMMON, "pair_end", tail[-2:]
    return COMMON, "none", []


def is_blacklisted(full: str) -> bool:
    return any(b in full for b in BLACKLIST)


def mythic_candidates(c: Country) -> list[tuple[str, str]]:
    """18 мифических узоров на код оператора (10 «весь хвост одинаковый» и 8 лесенок)."""
    out = []
    for op in c.operators:
        out += [(op, d * TAIL) for d in DIGITS]
        out += [(op, lad) for lad in TAIL_LADDERS]
    return out


def _rand(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(DIGITS) for _ in range(n))


def _lad(rng: random.Random, n: int) -> str | None:
    step = rng.choice((1, -1))
    start = rng.randint(0, 9)
    out = [start + i * step for i in range(n)]
    return "".join(map(str, out)) if all(0 <= d <= 9 for d in out) else None


def _build(tier: int, c: Country, rng: random.Random, divine) -> tuple[str, str] | None:
    op = rng.choice(c.operators)
    s = _rand(rng, TAIL)
    d = rng.choice(DIGITS)
    if tier == COMMON:
        return op, s
    if tier == UNCOMMON:
        return op, s[:-2] + (d * 2 if rng.random() < 0.8 else "00")
    if tier == RARE:
        kind = rng.randrange(3)
        if kind == 0:
            p = rng.randint(0, TAIL - 3)
            return op, s[:p] + d * 3 + s[p + 3:]
        if kind == 1:
            a, b = rng.choice(DIGITS), rng.choice(DIGITS)
            return op, s[:-4] + a + b + b + a
        lad = _lad(rng, 3)
        return (op, s[:-3] + lad) if lad else None
    if tier == EPIC:
        kind = rng.randrange(4)
        if kind == 0:
            return op, s[:-4] + d * 4
        if kind == 1:
            n = rng.choice((4, 4, 5))
            lad = _lad(rng, n)
            if not lad:
                return None
            p = rng.randint(0, TAIL - n)
            return op, s[:p] + lad + s[p + n:]
        if kind == 2:
            a, b = rng.sample(DIGITS, 2)
            return op, s[:-4] + a * 2 + b * 2
        half = _rand(rng, 3)
        return op, s[:-6] + half + half[::-1]
    if tier == LEGENDARY:
        p = rng.randint(0, 1)
        return op, s[:p] + d * 6 + s[p + 6:]
    if tier == MYTHIC:
        return rng.choice(mythic_candidates(c))
    if tier == SECRET:
        total = len(op) + TAIL
        head = op + _rand(rng, (total + 1) // 2 - len(op))
        full = head + head[: total // 2][::-1]
        return op, full[len(op):]
    if tier == DIVINE:
        own = [(o, sub) for cc, o, sub in divine if cc == c.code]
        return rng.choice(own) if own else None
    return None


def pick_country(rng: random.Random, weights: dict[str, int]) -> str:
    total = sum(weights.values())
    x = rng.random() * total
    for code, w in weights.items():
        x -= w
        if x < 0:
            return code
    return next(iter(weights))


def generate(tier: int, rng: random.Random, country: str | None = None, weights: dict[str, int] | None = None,
             divine=(), attempts: int = 3000) -> tuple[str, str, str, str, list[int]]:
    """(страна, код, хвост, правило, подсветка) ровно указанной ступени.
    Если страна задана — номер только этой страны (регион игрока), иначе страна по весам."""
    if country in COUNTRIES:
        order = [country]
    else:
        first = pick_country(rng, weights or {"RU": 1})
        order = [first] + [c for c in COUNTRIES if c != first]
    for code in order:
        c = COUNTRIES[code]
        for _ in range(attempts):
            built = _build(tier, c, rng, divine)
            if not built:
                continue
            op, sub = built
            if len(sub) != TAIL or (tier != DIVINE and is_blacklisted(op + sub)):
                continue
            got, rule, hl = classify(code, op, sub, divine)
            if got == tier:
                return code, op, sub, rule, hl
    raise RuntimeError(f"Не удалось собрать номер ступени {tier}")
