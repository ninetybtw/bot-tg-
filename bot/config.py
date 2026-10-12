import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    db_path: str
    bot_name: str
    start_balance: int
    ref_reward: int
    daily_bonus: int


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан (см. .env.example)")
    admin_ids = frozenset(
        int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
    )
    return Config(
        bot_token=token,
        admin_ids=admin_ids,
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        bot_name=os.getenv("BOT_NAME", "НикМастер"),
        start_balance=int(os.getenv("START_BALANCE", "2")),
        ref_reward=int(os.getenv("REF_REWARD", "3")),
        daily_bonus=int(os.getenv("DAILY_BONUS", "1")),
    )
