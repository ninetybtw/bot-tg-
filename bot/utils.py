from urllib.parse import quote

from aiogram import Bot

from bot.db import Database

AD_KEY = "ad_footer"


async def ad_footer(db: Database) -> str:
    """Рекламная подпись под результатами (задаётся в админке)."""
    ad = await db.get_setting(AD_KEY)
    return f"\n\n{ad}" if ad else ""


async def ref_link(bot: Bot, user_id: int) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start=r{user_id}"


async def share_url(bot: Bot, user_id: int) -> str:
    link = await ref_link(bot, user_id)
    text = "✨ Сделай себе красивый ник и найди свободный короткий @username — бесплатно!"
    return f"https://t.me/share/url?url={quote(link)}&text={quote(text)}"
