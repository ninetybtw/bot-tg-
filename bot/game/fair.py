"""Честный бросок «обещание и раскрытие» (docs/ODDS.md).

u_i = HMAC-SHA256(server_seed, "client_seed:nonce:i"), первые 52 бита / 2^52.
i = 0 — ступень, i ≥ 1 — страна, узор и остальные решения генератора.
"""
import hashlib
import hmac
import random
import secrets


def new_server_seed() -> str:
    return secrets.token_hex(32)


def new_client_seed() -> str:
    return secrets.token_hex(8)


def seed_hash(server_seed_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(server_seed_hex)).hexdigest()


def roll(server_seed_hex: str, client_seed: str, nonce: int, i: int = 0) -> float:
    h = hmac.new(bytes.fromhex(server_seed_hex), f"{client_seed}:{nonce}:{i}".encode(), hashlib.sha256).hexdigest()
    return int(h[:13], 16) / 2 ** 52


def pick_tier(u: float, odds: dict[int, float]) -> int:
    acc = 0.0
    for t in sorted(odds):
        acc += odds[t]
        if u < acc:
            return t
    return max(odds)


class FairRandom(random.Random):
    """Последовательность u_1, u_2, … для генератора номера. Все методы random.Random
    (choice, randint, sample…) идут через random(), поэтому весь номер повторяем по зерну."""

    def __init__(self, server_seed_hex: str, client_seed: str, nonce: int, start: int = 1):
        self._fair = (server_seed_hex, client_seed, nonce)
        self._i = start
        super().__init__(0)

    def seed(self, *args, **kwargs):  # базовый конструктор зовёт seed(); наша случайность от зерна
        pass

    def random(self) -> float:
        u = roll(*self._fair, self._i)
        self._i += 1
        return u
