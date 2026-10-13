"""Собирает webapp/config.demo.js из настоящего конфига игры: демо-режим в браузере
показывает те же шансы, цены и уровни, что и сервер, а номера берёт из пула,
собранного настоящим генератором и классификатором."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.db import Database  # noqa: E402
from bot.game import phones  # noqa: E402
from bot.game.service import Game  # noqa: E402

PER_TIER = 60

game = Game(Database(":memory:"), stars_enabled=True)
cfg = game.cfg
rng = random.Random(20261012)
pool = {}
for tier in range(7):
    seen, out = set(), []
    while len(out) < PER_TIER:
        code, op, sub, rule, hl = phones.generate(tier, rng, None, cfg["number_country_weights"], game.divine)
        key = phones.number_key(code, op, sub)
        if key in seen:
            continue
        seen.add(key)
        out.append([code, op, sub, rule, hl])
    pool[tier] = out
pool[7] = []
for code, op, sub in game.divine:
    tier, rule, hl = phones.classify(code, op, sub, game.divine)
    pool[7].append([code, op, sub, rule, hl])

data = {
    "pool": pool,
    "countries": {k: {"name": c.name, "flag": c.flag, "dial": c.dial, "groups": c.groups, "sep": c.sep}
                  for k, c in phones.COUNTRIES.items()},
    "game": {k: cfg[k] for k in ("start_cents", "energy", "coin_spins", "upper_levels_per_day", "starter",
                                 "break_hint_spins", "undo_sell", "tasks", "tasks_per_day", "tickets_per_task",
                                 "weekly_tasks", "raffle", "referral", "shop", "wheel_weekly")},
    "wheel_daily": cfg["wheel_daily"],
}
out = Path(__file__).resolve().parent.parent / "webapp" / "config.demo.js"
out.write_text("window.DEMO_CONFIG = " + json.dumps(game.public_config(), ensure_ascii=False) + ";\n"
               "window.DEMO_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
               encoding="utf-8")
print(f"{out} — {out.stat().st_size} байт")
