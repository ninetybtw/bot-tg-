"""Шансы с мягкими гарантиями (docs/ODDS.md): формула на спин и точный долгосрочный расчёт.

Гарантии две, вложенные: «Эпик и выше» (A) и «Легендарный и выше» (B).
шанс(n) = base, если n < soft; base + (n − soft + 1) × step, если soft ≤ n < hard; 100% на hard-м.
"""
from bot.game.tiers import EPIC, LEGENDARY


def group_prob(base: float, n: int, soft: int, step: float, hard: int) -> float:
    """Шанс группы на n-м спине подряд без неё (n с единицы), step в долях."""
    if n >= hard:
        return 1.0
    if n >= soft:
        return min(1.0, base + (n - soft + 1) * step)
    return base


def _split(odds: dict[int, float], pa: float, pb: float) -> dict[int, float]:
    """Шанс группы A = pa, группы B = pb; внутри групп пропорционально шкале."""
    b = {t: p for t, p in odds.items() if t >= LEGENDARY}
    a = {t: p for t, p in odds.items() if EPIC <= t < LEGENDARY}
    low = {t: p for t, p in odds.items() if t < EPIC}
    pb = min(pb, 1.0)
    pa = max(min(pa, 1.0), pb)
    out = {}
    for group, share in ((b, pb), (a, pa - pb), (low, 1 - pa)):
        s = sum(group.values())
        for t, p in group.items():
            out[t] = p / s * share if s else 0.0
    return out


def pity_chances(odds: dict[int, float], pity: dict, since_epic: int, since_legend: int) -> tuple[float, float]:
    """Шанс группы Эпик+ и Легендарный+ на следующем спине."""
    A, B = pity["epic_plus"], pity["legend_plus"]
    base_a = sum(p for t, p in odds.items() if t >= EPIC)
    base_b = sum(p for t, p in odds.items() if t >= LEGENDARY)
    qb = group_prob(base_b, since_legend + 1, B["soft"], B["step_pct"] / 100, B["hard"])
    qa = max(group_prob(base_a, since_epic + 1, A["soft"], A["step_pct"] / 100, A["hard"]), qb)
    return qa, qb


def with_pity(odds: dict[int, float], pity: dict, since_epic: int, since_legend: int) -> dict[int, float]:
    qa, qb = pity_chances(odds, pity, since_epic, since_legend)
    return _split(odds, qa, qb)


def consolidated(odds: dict[int, float], pity: dict) -> dict[int, float]:
    """Точные долгосрочные доли ступеней с гарантиями (порт odds_lab.consolidated, без numpy)."""
    A, B = pity["epic_plus"], pity["legend_plus"]
    HA, HB = A["hard"], B["hard"]
    tiers = sorted(odds)
    base_a = sum(odds[t] for t in tiers if t >= EPIC)
    base_b = sum(odds[t] for t in tiers if t >= LEGENDARY)

    def norm(mask):
        s = sum(odds[t] for t in tiers if mask(t))
        return {t: (odds[t] / s if mask(t) and s else 0.0) for t in tiers}

    dB = norm(lambda t: t >= LEGENDARY)
    dA = norm(lambda t: EPIC <= t < LEGENDARY)
    dL = norm(lambda t: t < EPIC)
    qa_e = [group_prob(base_a, e + 1, A["soft"], A["step_pct"] / 100, HA) for e in range(HA)]
    alive = [0.0] * HA
    alive[0] = 1.0
    counts = {t: 0.0 for t in tiers}
    steps = 0.0
    for l in range(HB):
        qb = group_prob(base_b, l + 1, B["soft"], B["step_pct"] / 100, HB)
        qa = [max(x, qb) for x in qa_e]
        m = sum(alive)
        steps += m
        to_a = sum(alive[e] * (qa[e] - qb) for e in range(HA))
        to_l = [alive[e] * (1 - qa[e]) for e in range(HA)]
        for t in tiers:
            counts[t] += m * qb * dB[t] + to_a * dA[t] + sum(to_l) * dL[t]
        nxt = [0.0] * HA
        nxt[0] = to_a
        for e in range(HA - 1):
            nxt[e + 1] += to_l[e]
        nxt[-1] += to_l[-1]
        alive = nxt
        if sum(alive) < 1e-15:
            break
    return {t: counts[t] / steps for t in tiers}


def solve_level(prices: list[int], price: int, low: int, high: int, target: float = 0.8) -> dict[int, float]:
    """Алгоритм построения уровня крутки из ТЗ: p(t) ~ L(t)^-α, α делением пополам под возврат target,
    округление до сотых процента, разница округления нижней ступени."""
    tiers = list(range(low, high + 1))

    def shape(alpha):
        w = {t: prices[t] ** (-alpha) for t in tiers}
        s = sum(w.values())
        return {t: v / s for t, v in w.items()}

    lo, hi = 0.01, 6.0
    for _ in range(100):
        mid = (lo + hi) / 2
        ev = sum(p * prices[t] for t, p in shape(mid).items())
        if ev > target * price:
            lo = mid
        else:
            hi = mid
    raw = shape((lo + hi) / 2)
    rounded = {t: round(p * 100, 2) / 100 for t, p in raw.items()}
    rounded[low] = round(rounded[low] + (1 - sum(rounded.values())), 6)
    return rounded
