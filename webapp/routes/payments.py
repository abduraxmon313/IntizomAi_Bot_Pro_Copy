"""
Paylov to'lov webhooki.

Paylov to'lov holati o'zgarganda (to'landi/bekor) shu endpointga POST yuboradi.
To'lov muvaffaqiyatli bo'lsa — foydalanuvchiga premium ochiladi, soliq cheki
yaratiladi va xabar yuboriladi (payment_service.process_webhook ichida).

Eslatma: bu yo'l '/api/' ostida emas, shuning uchun rate-limitga tushmaydi
(Paylov serveri to'siqsiz chaqira oladi). Ishlash idempotent.
"""
import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook/paylov")
async def paylov_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        from bot.services.payment_service import process_webhook
        return await process_webhook(payload or {})
    except Exception as e:
        # Hech qachon 500 qaytarmaymiz — aks holda Paylov cheksiz qayta yuboradi.
        logger.error(f"❌ Paylov webhook xatosi: {type(e).__name__}: {e}", exc_info=True)
        return {"ok": True}
