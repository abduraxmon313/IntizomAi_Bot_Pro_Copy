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
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/webhook/paylov")
async def paylov_webhook_verify(request: Request):
    """
    Webhook URL'ni TEKSHIRISH (verification) uchun GET handler.

    Ko'p to'lov tizimlari (jumladan WLCM) webhook URL'ni ro'yxatga olishdan oldin
    unga GET so'rov yuborib, manzil tirik va to'g'riligini tekshiradi. Avval bu
    yerda faqat POST bor edi va GET → 405 (Method Not Allowed) qaytarardi; bu
    tufayli URL "yaroqsiz" deb hisoblanib, ro'yxatga olinmasligi mumkin edi.

    Shu sabab GET'ga 200 OK qaytaramiz. Haqiqiy to'lov bildirishnomalari POST
    orqali keladi (pastdagi handler).
    """
    client = request.client.host if request.client else "?"
    logger.info(f"🔎 Webhook GET tekshiruvi: ip={client}")
    return {
        "ok": True,
        "service": "paylov-webhook",
        "note": "Endpoint live. Send payment notifications via POST.",
    }


@router.post("/webhook/paylov")
async def paylov_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # Diagnostika: WLCM webhookni chaqirayotganini ko'rish uchun log.
    # (To'lov nega avtomatik ochilmadi muammosini aniqlashga yordam beradi.)
    client = request.client.host if request.client else "?"
    logger.info(
        f"📥 Paylov webhook keldi: ip={client} "
        f"external_id={payload.get('external_id')} state={payload.get('state')} "
        f"payment_id={payload.get('payment_id')} amount={payload.get('amount')}"
    )

    # ── Imzo tekshiruvi (webhook haqiqatan WLCM'dan kelganini tasdiqlaydi) ──
    from bot.services.payment_service import process_webhook, verify_webhook_signature
    valid, reason = verify_webhook_signature(payload or {})
    if not valid:
        # Imzo noto'g'ri yoki secret sozlanmagan — bu soxta/buzilgan so'rov. Premium OCHILMAYDI.
        logger.warning(
            f"❌ Webhook imzo rad etildi ({reason}): "
            f"external_id={payload.get('external_id')} ip={client}"
        )
        if reason == "secret_not_set":
            # Admin uchun aniq xato — secret sozlanishi SHART
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "error": "webhook_secret_not_configured",
                    "detail": "PAYLOV_WEBHOOK_SECRET env sozlanmagan. Admin sozlashi kerak.",
                },
            )
        return JSONResponse(status_code=401, content={"ok": False, "error": "invalid_signature"})

    try:
        result = await process_webhook(payload or {})
        return result
    except Exception as e:
        # XAVFSIZLIK: Ichki xato bo'lsa 500 qaytaramiz — Paylov QAYTA YUBORADI.
        # Aks holda to'lov yo'qoladi (foydalanuvchi to'ladi lekin premium ochilmadi).
        logger.error(f"❌ Paylov webhook xatosi: {type(e).__name__}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "internal_error", "retry": True},
        )
