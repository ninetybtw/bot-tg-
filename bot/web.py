"""HTTP API мини-приложения (docs/API.md). Каждый запрос подписан Telegram (initData),
каждый POST несёт Idempotency-Key: повтор с тем же ключом возвращает сохранённый ответ."""
import asyncio
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
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


def admin_token(config: Config, uid: int, ttl: int = 24 * 3600, now: float | None = None) -> str:
    """Ключ входа в админку из браузера (команда /panel): id.срок.подпись токеном бота."""
    exp = int((now or time.time()) + ttl)
    sig = hmac.new(config.bot_token.encode(), f"admin:{uid}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return f"{uid}.{exp}.{sig}"


def check_admin_token(config: Config, token: str) -> int | None:
    try:
        uid_s, exp_s, sig = token.split(".")
        uid, exp = int(uid_s), int(exp_s)
    except ValueError:
        return None
    good = hmac.new(config.bot_token.encode(), f"admin:{uid}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    if not hmac.compare_digest(good, sig) or exp < time.time() or uid not in config.admin_ids:
        return None
    return uid


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

    def admin_auth(request: web.Request) -> dict:
        header = request.headers.get("Authorization", "")
        uid = check_admin_token(config, header[6:]) if header.startswith("admin ") else None
        if uid is None:
            user = auth(request)
            uid = user["id"] if user["id"] in config.admin_ids else None
        if uid is None:
            raise web.HTTPForbidden(text=json.dumps({"error": {"code": "FORBIDDEN", "message": "Нет доступа к админке"}}),
                                    content_type="application/json")
        return {"id": uid, "username": None, "first_name": "Админ", "language_code": "ru", "start_param": None}

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
        user = admin_auth(request) if request.path.startswith("/api/admin/") else auth(request)
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
    game_tasks: set[asyncio.Task] = set()

    @routes.post("/api/config")
    async def config_(r):
        return game.public_config()

    @routes.post("/api/me")
    async def me(r):
        u = r["user"]
        await game.ensure_user(u["id"], u["username"], u["first_name"], u["language_code"], parse_ref(u["start_param"]))
        data = await game.me(u["id"])
        data["ref_link"] = await ref_link(bot, config, u["id"])
        data["ads"] = [{k: a[k] for k in ("id", "title", "text", "url", "button", "icon")} for a in game.ads] or (
            [{"id": 0, "placeholder": True, "icon": "📣", "title": "Ваша реклама здесь", "text": "Её увидит каждый игрок",
              "button": "Связаться", "url": f"https://t.me/{config.ads_contact}"}] if config.ads_contact else [])
        data["is_admin"] = u["id"] in config.admin_ids
        return data

    @routes.post("/api/ad")
    async def ad(r):
        b = body(r)
        await game.ad_event(uid(r), int(b.get("id", 0)), str(b.get("kind", "")))
        return {"ok": True}

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
        return {"locked": await game.set_lock(uid(r), int(b["id"]), bool(b.get("locked", True)), bool(b.get("confirm")),
                                              str(b.get("kind", "number")))}

    @routes.post("/api/showcase")
    async def showcase(r):
        return {"showcase": await game.set_showcase(uid(r), ids(r))}

    @routes.post("/api/sell")
    async def sell(r):
        return await game.sell(uid(r), ids(r), bool(body(r).get("confirmed")), str(body(r).get("kind", "number")))

    @routes.post("/api/sell/quote")
    async def sell_quote(r):
        b = body(r)
        tier = b.get("tier")
        return await game.sell_quote(uid(r), str(b.get("mode", "below_rare")), int(b.get("max_cents", 0)),
                                     None if tier is None else int(tier), str(b.get("kind", "number")))

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

    @routes.post("/api/region")
    async def region(r):
        return await game.set_region(uid(r), str(body(r)["region"]))

    @routes.post("/api/case/spin")
    async def case_spin(r):
        b = body(r)
        return await game.device_spin(uid(r), str(b.get("case", "phones")), int(b.get("count", 1)), bool(b.get("confirmed")))

    @routes.post("/api/devices")
    async def devices_(r):
        b = body(r)
        return await game.device_collection(uid(r), int(b.get("min_tier", 0)), str(b.get("sort", "rare")))

    @routes.post("/api/devices/seen")
    async def devices_seen(r):
        await game.mark_devices_seen(uid(r))
        return {"ok": True}

    @routes.post("/api/luck/claim")
    async def luck_claim(r):
        ev = game.luck_event
        if not ev or ev["until"] < time.time():
            raise GameError("Акция удачи закончилась", "NOT_ALLOWED_YET")
        try:
            m = await bot.get_chat_member(ev["chat_id"], uid(r))
        except TelegramBadRequest as e:
            log.warning("luck subscription check failed: %s", e)
            raise GameError("Не получилось проверить подписку. Попробуй позже", "CHECK_FAILED")
        if m.status not in ("member", "administrator", "creator") and not getattr(m, "is_member", False):
            raise GameError("Сначала подпишись на канал, потом нажми «Проверить»", "NOT_SUBSCRIBED")
        return await game.claim_luck(uid(r))

    # ---------- админка (только ADMIN_IDS или ключ из /panel) ----------

    @routes.post("/api/admin/overview")
    async def a_overview(r):
        return {"stats": await game.admin_stats(), "series": await game.admin_series(14),
                "ads": await game.ads_stats(), "ads_max": game.cfg["ads_max"],
                "luck_event": await game.luck_event_stats(), "luck_mults": game.cfg["luck_event"]["mults"],
                "luck_max_spins": game.cfg["luck_event"]["max_spins"], "ads_contact": config.ads_contact,
                "tiers": [t for t in game.public_config()["tiers"]]}

    @routes.post("/api/admin/users")
    async def a_users(r):
        q = str(body(r).get("q", "")).strip()
        return {"users": await game.admin_find(q) if q else await game.admin_recent()}

    @routes.post("/api/admin/user")
    async def a_user(r):
        return await game.admin_user(int(body(r)["id"]))

    @routes.post("/api/admin/give")
    async def a_give(r):
        b = body(r)
        await game.admin_give(int(b["id"]), int(round(float(b.get("rubles", 0)) * 100)), int(b.get("attempts", 0)))
        return await game.admin_user(int(b["id"]))

    @routes.post("/api/admin/luck")
    async def a_luck(r):
        b = body(r)
        await game.admin_set_luck(int(b["id"]), float(b["mult"]), int(b["spins"]))
        return await game.admin_user(int(b["id"]))

    @routes.post("/api/admin/boost")
    async def a_boost(r):
        b = body(r)
        await game.admin_set_boost(int(b["id"]), None if b.get("tier") is None else int(b["tier"]))
        return await game.admin_user(int(b["id"]))

    @routes.post("/api/admin/ads/save")
    async def a_ad_save(r):
        b = body(r)
        await game.set_ad(str(b.get("title", "")), str(b.get("text", "")), str(b.get("url", "")),
                          str(b.get("button", "")), str(b.get("icon", "")), b.get("id"))
        return {"ads": await game.ads_stats()}

    @routes.post("/api/admin/ads/remove")
    async def a_ad_remove(r):
        await game.remove_ad(int(body(r)["id"]))
        return {"ads": await game.ads_stats()}

    @routes.post("/api/admin/luck_event/start")
    async def a_luck_start(r):
        b = body(r)
        ev = await game.start_luck_event(float(b["mult"]), int(b["spins"]), float(b["hours"]), str(b["channel"]),
                                         str(b.get("title", "")))
        try:  # бот должен видеть подписчиков канала, иначе игроки не получат удачу
            me = await bot.me()
            m = await bot.get_chat_member(ev["chat_id"], me.id)
            warn = None if m.status == "administrator" else "Добавь бота админом в канал — иначе подписку не проверить"
        except TelegramAPIError:
            warn = "Бот не видит канал. Добавь его админом в канал — иначе подписку не проверить"
        return {"luck_event": await game.luck_event_stats(), "warning": warn}

    @routes.post("/api/admin/luck_event/stop")
    async def a_luck_stop(r):
        await game.stop_luck_event()
        return {"luck_event": None}

    @routes.post("/api/admin/broadcast")
    async def a_broadcast(r):
        from bot.handlers.admin import broadcast_text
        b = body(r)
        text = str(b.get("text", "")).strip()
        if not 1 <= len(text) <= 3500:
            raise GameError("Текст рассылки от 1 до 3500 символов")
        total = await game.db.val("SELECT COUNT(*) FROM users WHERE is_blocked = 0")
        task = asyncio.create_task(broadcast_text(bot, game, config, text, bool(b.get("button")), uid(r)))
        game_tasks.add(task)
        task.add_done_callback(game_tasks.discard)
        return {"started": True, "recipients": total}

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

    async def admin_page(_request):
        return web.FileResponse(WEBAPP_DIR / "admin.html", headers={"Cache-Control": "no-cache"})
    app.router.add_get("/admin", admin_page)
    app.router.add_static("/app/", WEBAPP_DIR)
    return app
