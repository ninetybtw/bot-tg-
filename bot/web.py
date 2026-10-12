"""HTTP API мини-приложения. Каждый запрос подписан Telegram (initData)."""
import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import LabeledPrice
from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web

from bot.config import Config
from bot.game.service import Game, GameError

log = logging.getLogger(__name__)

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
INIT_DATA_TTL = 7 * 86400
RATE_LIMIT = 15  # запросов в секунду на игрока


def parse_ref(param: str | None) -> int | None:
    if param and param.startswith("r") and param[1:].isdigit():
        return int(param[1:])
    return None


async def ref_link(bot: Bot, config: Config, uid: int) -> str:
    me = await bot.me()
    if config.webapp_short_name:
        return f"https://t.me/{me.username}/{config.webapp_short_name}?startapp=r{uid}"
    return f"https://t.me/{me.username}?start=r{uid}"


async def send_outbox(bot: Bot, game: Game) -> None:
    for uid, text in game.pop_outbox():
        try:
            await bot.send_message(uid, text)
        except TelegramAPIError as e:
            log.info("notify %s failed: %s", uid, e)


def create_app(game: Game, bot: Bot, config: Config) -> web.Application:
    hits: dict[int, list[float]] = {}

    def auth(request: web.Request) -> dict:
        header = request.headers.get("Authorization", "")
        if header.startswith("tma "):
            try:
                data = safe_parse_webapp_init_data(config.bot_token, header[4:])
            except ValueError:
                raise web.HTTPUnauthorized(text='{"error": "Неверная подпись Telegram"}',
                                           content_type="application/json")
            if time.time() - data.auth_date.timestamp() > INIT_DATA_TTL or not data.user:
                raise web.HTTPUnauthorized(text='{"error": "Сессия устарела, перезапусти приложение"}',
                                           content_type="application/json")
            return {"id": data.user.id, "username": data.user.username,
                    "first_name": data.user.first_name, "start_param": data.start_param}
        if config.dev_auth and header.startswith("dev "):
            uid = int(header[4:])
            return {"id": uid, "username": None, "first_name": f"Dev {uid}", "start_param": None}
        raise web.HTTPUnauthorized(text='{"error": "Открой игру через Telegram"}', content_type="application/json")

    @web.middleware
    async def api_mw(request: web.Request, handler):
        if not request.path.startswith("/api/"):
            return await handler(request)
        user = auth(request)
        now = time.monotonic()
        recent = [t for t in hits.get(user["id"], []) if now - t < 1]
        if len(recent) >= RATE_LIMIT:
            return web.json_response({"error": "Слишком часто, подожди секунду", "code": "rate"}, status=429)
        recent.append(now)
        hits[user["id"]] = recent
        if len(hits) > 200_000:
            hits.clear()
        request["user"] = user
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        request["body"] = body if isinstance(body, dict) else {}
        try:
            result = await handler(request)
        except GameError as e:
            return web.json_response({"error": e.message, "code": e.code, **e.extra}, status=400)
        except (KeyError, TypeError, ValueError) as e:
            log.info("bad request %s: %r", request.path, e)
            return web.json_response({"error": "Некорректный запрос"}, status=400)
        if game.outbox:
            asyncio.create_task(send_outbox(bot, game))
        return web.json_response(result) if not isinstance(result, web.StreamResponse) else result

    def uid(r: web.Request) -> int:
        return r["user"]["id"]

    def body(r: web.Request) -> dict:
        return r["body"]

    def ids(r: web.Request) -> list[int]:
        raw = body(r).get("ids") or []
        if not isinstance(raw, list) or len(raw) > 500:
            raise GameError("Некорректный список")
        return [int(x) for x in raw]

    routes = web.RouteTableDef()

    @routes.post("/api/state")
    async def state(r):
        u = r["user"]
        await game.ensure_user(u["id"], u["username"], u["first_name"], parse_ref(u["start_param"]))
        s = await game.state(u["id"])
        s["ref_link"] = await ref_link(bot, config, u["id"])
        return s

    @routes.post("/api/spin")
    async def spin(r):
        return await game.spin(uid(r), int(body(r).get("count", 1)), str(body(r).get("scale", "phone")))

    @routes.post("/api/country")
    async def country(r):
        await game.set_country(uid(r), str(body(r)["code"]))
        return {"ok": True}

    @routes.post("/api/settings")
    async def settings(r):
        return await game.update_settings(uid(r), body(r))

    @routes.post("/api/collection")
    async def collection(r):
        b = body(r)
        return await game.collection(uid(r), int(b.get("min_tier", 0)), str(b.get("q", ""))[:12],
                                     bool(b.get("favorites")))

    @routes.post("/api/seen")
    async def seen(r):
        await game.mark_seen(uid(r))
        return {"ok": True}

    @routes.post("/api/favorite")
    async def favorite(r):
        return {"favorite": await game.toggle_favorite(uid(r), int(body(r)["id"]))}

    @routes.post("/api/sell")
    async def sell(r):
        return await game.sell(uid(r), ids(r))

    @routes.post("/api/bulk_preview")
    async def bulk_preview(r):
        return await game.bulk_preview(uid(r), int(body(r).get("max_tier", 1)))

    @routes.post("/api/bulk_sell")
    async def bulk_sell(r):
        return await game.bulk_sell(uid(r), int(body(r).get("max_tier", 1)))

    @routes.post("/api/contract")
    async def contract(r):
        return await game.contract(uid(r), ids(r))

    @routes.post("/api/upgrade/quote")
    async def upgrade_quote(r):
        b = body(r)
        return await game.upgrade_quote(uid(r), ids(r), int(b.get("coins", 0)), int(b["target"]))

    @routes.post("/api/upgrade")
    async def upgrade(r):
        b = body(r)
        return await game.upgrade(uid(r), ids(r), int(b.get("coins", 0)), int(b["target"]))

    @routes.post("/api/market")
    async def market(r):
        b = body(r)
        return await game.market(uid(r), int(b.get("min_tier", 0)), str(b.get("country", "")),
                                 str(b.get("sort", "new")))

    @routes.post("/api/market/mine")
    async def market_mine(r):
        return await game.my_lots(uid(r))

    @routes.post("/api/market/list")
    async def market_list(r):
        return await game.list_lot(uid(r), int(body(r)["id"]), int(body(r)["price"]))

    @routes.post("/api/market/cancel")
    async def market_cancel(r):
        await game.cancel_lot(uid(r), int(body(r)["lot_id"]))
        return {"ok": True}

    @routes.post("/api/market/buy")
    async def market_buy(r):
        return await game.buy_lot(uid(r), int(body(r)["lot_id"]))

    @routes.post("/api/wheel")
    async def wheel(r):
        return await game.wheel_spin(uid(r))

    @routes.post("/api/gift")
    async def gift(r):
        return await game.gift_claim(uid(r))

    @routes.post("/api/task")
    async def task(r):
        return await game.task_claim(uid(r), str(body(r)["key"]))

    @routes.post("/api/friends")
    async def friends(r):
        data = await game.friends(uid(r))
        data["ref_link"] = await ref_link(bot, config, uid(r))
        return data

    @routes.post("/api/rating")
    async def rating(r):
        b = body(r)
        return await game.rating(uid(r), str(b.get("kind", "value")), str(b.get("scope", "all")))

    @routes.post("/api/history")
    async def history(r):
        return {"items": await game.history(uid(r))}

    @routes.post("/api/shop")
    async def shop(r):
        return await game.shop(uid(r))

    @routes.post("/api/shop/invoice")
    async def invoice(r):
        p = await game.check_purchase(uid(r), str(body(r)["key"]))
        link = await bot.create_invoice_link(
            title=p["title"], description=p["desc"], payload=f"{p['key']}:{uid(r)}",
            currency="XTR", prices=[LabeledPrice(label=p["title"], amount=p["stars"])])
        return {"link": link}

    async def index(_request):
        return web.FileResponse(WEBAPP_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app = web.Application(middlewares=[api_mw], client_max_size=64 * 1024)
    app.add_routes(routes)
    app.router.add_get("/", index)
    app.router.add_static("/app/", WEBAPP_DIR)
    return app
