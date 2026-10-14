import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    db_path: str
    webapp_url: str          # публичный https-адрес мини-приложения
    webapp_short_name: str   # короткое имя Mini App в BotFather (для ссылок startapp), можно пусто
    web_host: str
    web_port: int
    stars_enabled: bool
    dev_auth: bool           # только для локальной отладки без Telegram
    ads_contact: str = ""    # @username для заглушки «Здесь может быть ваша реклама», пусто — без заглушки


def _bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан (см. .env.example)")
    return Config(
        bot_token=token,
        admin_ids=frozenset(int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x),
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        webapp_url=os.getenv("WEBAPP_URL", "").strip().rstrip("/"),
        webapp_short_name=os.getenv("WEBAPP_SHORT_NAME", "").strip(),
        web_host=os.getenv("WEB_HOST", "0.0.0.0"),
        web_port=int(os.getenv("WEB_PORT", "8080")),
        stars_enabled=_bool("STARS_ENABLED"),
        dev_auth=_bool("DEV_AUTH"),
        ads_contact=os.getenv("ADS_CONTACT", "").strip().lstrip("@"),
    )
