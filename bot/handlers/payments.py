"""Оплата в Telegram Stars (XTR). Покупка выдаётся только после successful_payment."""
import logging

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from bot.game.service import Game, GameError

log = logging.getLogger(__name__)
router = Router(name="payments")


def _parse(payload: str) -> tuple[str, int]:
    key, uid = payload.split(":")
    return key, int(uid)


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, game: Game) -> None:
    try:
        key, uid = _parse(query.invoice_payload)
        if uid != query.from_user.id:
            raise GameError("Счёт выписан другому игроку")
        product = await game.check_purchase(uid, key)
        if query.currency != "XTR" or query.total_amount != product["stars"]:
            raise GameError("Цена изменилась, открой магазин заново")
    except GameError as e:
        await query.answer(ok=False, error_message=e.message)
        return
    except ValueError:
        await query.answer(ok=False, error_message="Некорректный счёт")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, game: Game) -> None:
    pay = message.successful_payment
    key, uid = _parse(pay.invoice_payload)
    result = await game.grant_purchase(uid, key, pay.telegram_payment_charge_id, pay.total_amount)
    log.info("payment %s by %s: %s", pay.telegram_payment_charge_id, uid, result)
    if not result.get("duplicate"):
        await message.answer(f"✅ Получено: <b>{result['granted']}</b>. Возвращайся в игру!\n"
                             f"Чек: <code>{pay.telegram_payment_charge_id}</code>")
