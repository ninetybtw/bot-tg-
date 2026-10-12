"""HTTP API мини-приложения (docs/API.md). Каждый запрос подписан Telegram (initData),
каждый POST несёт Idempotency-Key: повтор с тем же ключом возвращает сохранённый ответ."""
import asyncio
import json
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
INIT_DATA_TTL = 24 * 3600
RATE_LIMIT = 10        # запросов в секунду на игрока
SPIN_RATE_LIMIT = 2    # спинов в секунду


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


def _err(code: str, message: str, status: int = 400, **extra) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message, **extra}}, status=status)


def create_app(game: Game, bot: Bot, config: Config) -> web.Application:
    hits: dict[tuple[int, str], list[float]] = {}
    user_locks: dict[int, asyncio.Lock] = {}

    def auth(request: web.Request) -> dict:
        header = request.headers.get("Authorization", "")
        if header.startswith("tma "):
            try:
                data = safe_parse_webapp_init_data(config.bot_token, header[4:])
            except ValueError:
                raise web.HTTPUnauthorized(text=json.dumps({"error": {"code": "UNAUTHORIZED",
                                                                      "message": "Неверная подпись Telegram"}}),
                                           content_type="application/json")
            if time.time() - data.auth_date.timestamp() > INIT_DATA_TTL or not data.user:
                raise web.HTTPUnauthorized(text=json.dumps({"error": {"code": "UNAUTHORIZED",
                                                                      "message": "Сессия устарела. Перезапусти игру"}}),
                                           content_type="application/json")
            return {"id": data.user.id, "username": data.user.username, "first_name": data.user.first_name,
                    "language_code": data.user.language_code, "start_param": data.start_param}
        if config.dev_auth and header.startswith("dev "):
            uid = int(header[4:])
            return {"id": uid, "username": None, "first_name": f"Dev {uid}", "language_code": "ru",
                    "start_param": None}
        raise web.HTTPUnauthorized(text=json.dumps({"error": {"code": "UNAUTHORIZED",
                                                              "message": "Открой игру через Telegram"}}),
                                   content_type="application/json")

    def rate_ok(uid: int, bucket: str, limit: int) -> bool:
        now = time.monotonic()
        recent = [t for t in hits.get((uid, bucket), []) if now - t < 1]
        if len(recent) >= limit:
            return False
        recent.append(now)
        hits[(uid, bucket)] = recent
        if len(hits) > 200_000:
            hits.clear()
        return True

    @web.middleware
    async def api_mw(request: web.Request, handler):
        if not request.path.startswith("/api/"):
            return await handler(request)
        user = auth(request)
        uid = user["id"]
        if not rate_ok(uid, "all", RATE_LIMIT) or (request.path == "/api/spin" and not rate_ok(uid, "spin",
                                                                                                 SPIN_RATE_LIMIT)):
            return _err("RATE_LIMIT", "Слишком часто, подожди секунду", 429)
        request["user"] = user
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        request["body"] = body if isinstance(body, dict) else {}
        key = request.headers.get("Idempotency-Key", "")[:64]
        lock = user_locks.setdefault(uid, asyncio.Lock())
        async with lock:  # запросы одного игрока по очереди: повтор ключа видит сохранённый ответ
            if key:
                saved = await game.db.one("SELECT status, response FROM idempotency WHERE user_id = ? AND key = ?",
                                          uid, key)
                if saved:
                    return web.Response(text=saved["response"], status=saved["status"],
                                        content_type="application/json")
            try:
                result = await handler(request)
                status, payload = 200, json.dumps(result, ensure_ascii=False)
            except GameError as e:
                status = 400
                payload = json.dumps({"error": {"code": e.code, "message": e.message, **e.extra}}, ensure_ascii=False)
            except (KeyError, TypeError, ValueError) as e:
                log.info("bad request %s: %r", request.path, e)
                status, payload = 400, json.dumps({"error": {"code": "BAD_REQUEST", "message": "Некорректный запрос"}},
                                                  ensure_ascii=False)
            if key and status == 200:
                async with game.db.tx():
                    await game.db.run("INSERT OR IGNORE INTO idempotency (user_id, key, path, status, response, "
                                      "created_at) VALUES (?, ?, ?, ?, ?, ?)", uid, key, request.path, status, payload,
                                      time.time())
        if len(user_locks) > 50_000:
            user_locks.clear()
        if game.outbox:
            asyncio.create_task(send_outbox(bot, game))
        return web.Response(text=payload, status=status, content_type="application/json")

    def uid(r: web.Request) -> int:
        return r["user"]["id"]

    def body(r: web.Request) -> dict:
        return r["body"]

    def ids(r: web.Request, field: str = "ids") -> list[int]:
        raw = body(r).get(field) or []
        if not isinstance(raw, list) or len(raw) > 500:
            raise GameError("Некорректный список")
        return [int(x) for x in raw]

    routes = web.RouteTableDef()

    @routes.post("/api/config")
    async def config_(r):
        return game.public_config()

    @routes.post("/api/me")
    async def me(r):
        u = r["user"]
        await game.ensure_user(u["id"], u["username"], u["first_name"], u["language_code"], parse_ref(u["start_param"]))
        data = await game.me(u["id"])
        data["ref_link"] = await ref_link(bot, config, u["id"])
        return data

    @routes.post("/api/spin")
    async def spin(r):
        b = body(r)
        return await game.spin(uid(r), str(b.get("level", "common")), int(b.get("count", 1)), bool(b.get("confirmed")))

    @routes.post("/api/country")
    async def country(r):
        return await game.set_country(uid(r), str(body(r)["country"]))

    @routes.post("/api/settings")
    async def settings(r):
        return await game.update_settings(uid(r), body(r))

    @routes.post("/api/inventory")
    async def inventory(r):
        b = body(r)
        return await game.collection(uid(r), int(b.get("min_tier", 0)), str(b.get("q", ""))[:12],
                                     str(b.get("sort", "rare")), bool(b.get("favorites")), bool(b.get("overflow")))

    @routes.post("/api/item")
    async def item(r):
        return await game.item_card(uid(r), int(body(r)["id"]))

    @routes.post("/api/seen")
    async def seen(r):
        await game.mark_seen(uid(r))
        return {"ok": True}

    @routes.post("/api/favorite")
    async def favorite(r):
        return {"favorite": await game.toggle_favorite(uid(r), int(body(r)["id"]))}

    @routes.post("/api/lock")
    async def lock(r):
        b = body(r)
        return {"locked": await game.set_lock(uid(r), int(b["id"]), bool(b.get("locked", True)), bool(b.get("confirm")))}

    @routes.post("/api/showcase")
    async def showcase(r):
        return {"showcase": await game.set_showcase(uid(r), ids(r))}

    @routes.post("/api/sell")
    async def sell(r):
        return await game.sell(uid(r), ids(r), bool(body(r).get("confirmed")))

    @routes.post("/api/sell/quote")
    async def sell_quote(r):
        b = body(r)
        return await game.sell_quote(uid(r), str(b.get("mode", "below_rare")), int(b.get("max_cents", 0)))

    @routes.post("/api/sales/undo")
    async def undo(r):
        return await game.undo_sale(uid(r), int(body(r)["sale_id"]))

    @routes.post("/api/contract")
    async def contract(r):
        return await game.contract(uid(r), ids(r))

    @routes.post("/api/upgrade/quote")
    async def upgrade_quote(r):
        b = body(r)
        return await game.upgrade_quote(uid(r), ids(r), int(b.get("cents", 0)), int(b["target"]))

    @routes.post("/api/upgrade")
    async def upgrade(r):
        b = body(r)
        return await game.upgrade(uid(r), ids(r), int(b.get("cents", 0)), int(b["target"]), b.get("quote_chance"))

    @routes.post("/api/market")
    async def market(r):
        b = body(r)
        return await game.market(uid(r), int(b.get("min_tier", 0)), str(b.get("sort", "new")), str(b.get("q", ""))[:12])

    @routes.post("/api/market/mine")
    async def market_mine(r):
        return await game.my_lots(uid(r))

    @routes.post("/api/market/list")
    async def market_list(r):
        return await game.list_lot(uid(r), int(body(r)["id"]), int(body(r)["price_cents"]))

    @routes.post("/api/market/cancel")
    async def market_cancel(r):
        await game.cancel_lot(uid(r), int(body(r)["lot_id"]))
        return {"ok": True}

    @routes.post("/api/market/buy")
    async def market_buy(r):
        return await game.buy_lot(uid(r), int(body(r)["lot_id"]))

    @routes.post("/api/wheel")
    async def wheel(r):
        return await game.wheel(uid(r), "weekly" if body(r).get("kind") == "weekly" else "daily")

    @routes.post("/api/gift")
    async def gift(r):
        return await game.gift_claim(uid(r))

    @routes.post("/api/task")
    async def task(r):
        return await game.task_claim(uid(r), str(body(r)["key"]))

    @routes.post("/api/raffle")
    async def raffle(r):
        return await game.raffle(uid(r))

    @routes.post("/api/fair")
    async def fair_(r):
        return await game.fair_info(uid(r))

    @routes.post("/api/fair/rotate")
    async def fair_rotate(r):
        return await game.fair_rotate(uid(r), body(r).get("client_seed"))

    @routes.post("/api/friends")
    async def friends(r):
        data = await game.friends(uid(r))
        data["ref_link"] = await ref_link(bot, config, uid(r))
        return data

    @routes.post("/api/rating")
    async def rating(r):
        b = body(r)
        return await game.rating(uid(r), str(b.get("board", "collection")), str(b.get("scope", "friends")))

    @routes.post("/api/feed")
    async def feed(r):
        return {"items": await game.feed(uid(r))}

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
