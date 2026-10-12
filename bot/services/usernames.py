"""Поиск свободных коротких @username в Telegram.

Проверка идёт через публичную страницу t.me/<name>: у занятого юзернейма
(человек, бот, канал, группа) на странице есть карточка с заголовком.
Юзернеймы, выставленные на аукцион Fragment или зарезервированные Telegram,
так не отличить, поэтому бот пишет «скорее всего свободен».
"""
import asyncio
import logging
import random
import re
import time

import aiohttp

log = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{3,30}[a-zA-Z0-9]$")

_CONSONANTS = "bdfgklmnprstvz"
_RARE = "cjxy"
_VOWELS = "aeiou"


def is_valid(name: str) -> bool:
    return bool(USERNAME_RE.match(name))


def _pronounceable(length: int) -> str:
    """Читаемое слово вида «kavor», «limena»: чередование согласных и гласных."""
    start_vowel = random.random() < 0.2
    out = []
    for i in range(length):
        vowel = (i % 2 == 0) == start_vowel
        if vowel:
            out.append(random.choice(_VOWELS))
        else:
            out.append(random.choice(_CONSONANTS + (_RARE if random.random() < 0.15 else "")))
    return "".join(out)


def candidates(length: int, count: int) -> list[str]:
    seen: set[str] = set()
    while len(seen) < count:
        seen.add(_pronounceable(length))
    return list(seen)


class UsernameChecker:
    def __init__(self, concurrency: int = 4, cache_ttl: float = 1800):
        self._sem = asyncio.Semaphore(concurrency)
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, tuple[bool, float]] = {}
        self._cache_ttl = cache_ttl

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Mozilla/5.0 (compatible; NickBot/1.0)"},
                trust_env=True,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def is_free(self, name: str) -> bool | None:
        """True — свободен, False — занят, None — проверить не удалось."""
        name = name.lower()
        cached = self._cache.get(name)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        async with self._sem:
            try:
                session = await self._get_session()
                async with session.get(f"https://t.me/{name}") as resp:
                    if resp.status != 200:
                        return None
                    html = await resp.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.warning("t.me check failed for %s: %r", name, e)
                return None
        free = "tgme_page_title" not in html
        self._cache[name] = (free, time.monotonic() + self._cache_ttl)
        if len(self._cache) > 50_000:
            self._cache.clear()
        return free

    async def find_free(self, length: int, want: int = 5, max_checks: int = 30) -> list[str]:
        found: list[str] = []
        pool = candidates(length, max_checks)
        for i in range(0, len(pool), 6):
            batch = pool[i:i + 6]
            results = await asyncio.gather(*(self.is_free(n) for n in batch))
            found += [n for n, free in zip(batch, results) if free]
            if len(found) >= want:
                break
        return found[:want]
