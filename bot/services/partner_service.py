"""
Mobil ilova backend'i uchun obuna sotish ko'prigi (partner API).

Oqim:
  1. Ilova backend'i `POST /partner/v1/orders` (imzolangan) → shu yerda
     `PartnerOrder` yaratiladi va Paylov checkout olinadi.
  2. Paylov webhooki `/webhook/paylov` ga keladi. `payment_service.process_webhook`
     buyurtmani `payment_orders` da topa olmasa — shu modulga uzatadi.
  3. To'langach ilova backend'iga imzolangan callback yuboriladi
     (`PARTNER_APP_CALLBACK_URL`). Yetib bormasa — fon siklida qayta urinadi.
     Ilova backend'i `GET /partner/v1/orders/{external_id}` bilan o'zi ham so'raydi.

Imzo (ikki tomonda bir xil):
    signature = HMAC_SHA256(secret, f"{METHOD}\\n{PATH}\\n{TIMESTAMP_MS}\\n{sha256(body).hexdigest()}")
    sarlavhalar: X-Partner-Key, X-Timestamp, X-Signature
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import logging
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import func, or_, select

from bot.config import (
    PARTNER_APP_CALLBACK_URL,
    PARTNER_APP_KEY,
    PARTNER_APP_SECRET,
    PAYLOV_ENABLED,
    PAYLOV_FISCAL_ENABLED,
    PAYLOV_FISCAL_MXIK,
    PAYLOV_FISCAL_PACKAGE_CODE,
    PAYLOV_FISCAL_VAT_PERCENT,
    PAYLOV_PROVIDER,
    PAYLOV_PROVIDERS,
    SUBSCRIPTION_PLANS,
)
from bot.models.partner_order import PartnerOrder, PartnerPromoRedemption
from bot.models.subscription import Promocode

logger = logging.getLogger(__name__)

MAX_SKEW_MS = 5 * 60 * 1000
MAX_NOTIFY_ATTEMPTS = 60
# Ilova o'zi narx belgilaganda ruxsat etilgan oraliq (tiyin): 1 000 … 100 000 000 so'm.
MIN_APP_AMOUNT_TIYIN = 1_000 * 100
MAX_APP_AMOUNT_TIYIN = 100_000_000 * 100
_PLAN_KEY_RE = re.compile(r"^[a-z0-9_]{1,16}$")


class PartnerError(Exception):
    """Ilova backend'iga qaytariladigan xato: (http status, kod, o'zbekcha matn)."""

    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


# ─────────────────────────────────────────────────────────────
#  Imzo
# ─────────────────────────────────────────────────────────────
def sign(method: str, path: str, timestamp: str, body: bytes) -> str:
    msg = f"{method.upper()}\n{path}\n{timestamp}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(PARTNER_APP_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()


def verify_request(method: str, path: str, headers, body: bytes) -> bool:
    if not (PARTNER_APP_KEY and PARTNER_APP_SECRET):
        return False
    if not hmac.compare_digest(headers.get("x-partner-key", ""), PARTNER_APP_KEY):
        return False
    ts = headers.get("x-timestamp", "")
    try:
        if abs(int(time.time() * 1000) - int(ts)) > MAX_SKEW_MS:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(sign(method, path, ts, body), headers.get("x-signature", ""))


# ─────────────────────────────────────────────────────────────
#  Tariflar va promokodlar
# ─────────────────────────────────────────────────────────────
_PROMO_REASON_CODES = {
    "Bunday promokod topilmadi": "promo_not_found",
    "Promokod kuchsizlantirilgan": "promo_inactive",
    "Promokod muddati tugagan": "promo_expired",
    "Promokod limiti tugagan": "promo_exhausted",
    "Promokod bo'sh": "promo_not_found",
}


def _plans_list(discount_percent: int = 0) -> list[dict]:
    from bot.services.plan_pricing import get_discounted_plans, get_effective_plans

    data = get_discounted_plans(discount_percent) if discount_percent > 0 else get_effective_plans()
    out = []
    for key, p in data.items():
        orig = p.get("original_price")
        out.append({
            "key": key,
            "title": p.get("title") or key,
            "days": int(p.get("days") or 0),
            "price": int(p.get("price") or 0),
            "emoji": p.get("emoji"),
            "tag": p.get("tag") or None,
            "original_price": int(orig) if orig and int(orig) != int(p.get("price") or 0) else None,
        })
    return out


async def _validate_promo(session, code: str):
    from bot.services.premium_service import validate_promocode

    res = await validate_promocode(session, code)
    if not res.valid:
        raise PartnerError(422, _PROMO_REASON_CODES.get(res.reason, "promo_not_found"), res.reason)
    return res


async def catalog(session, promo_code: str | None) -> dict:
    promo = None
    discount = 0
    if promo_code:
        try:
            res = await _validate_promo(session, promo_code)
            discount = int(res.discount_percent or 0)
            promo = {
                "code": promo_code.strip(),
                "valid": True,
                "is_free": bool(res.is_free),
                "discount_percent": discount,
                "bonus_days": int(res.bonus_days or 0),
            }
        except PartnerError as e:
            promo = {"code": promo_code.strip(), "valid": False, "reason_code": e.code}
    return {
        "plans": _plans_list(discount),
        "providers": list(PAYLOV_PROVIDERS),
        "promo": promo,
        "payments_enabled": PAYLOV_ENABLED,
    }


def _order_title(order: PartnerOrder) -> str:
    return order.title or SUBSCRIPTION_PLANS.get(order.plan_key, {}).get("title", order.plan_key)


def _external_id(order_id_hint: int) -> str:
    return f"izapp{order_id_hint}t{int(time.time())}r{secrets.token_hex(6)}"


def _public(o: PartnerOrder) -> dict:
    return {
        "external_id": o.external_id,
        "client_ref": o.client_ref,
        "status": o.status,
        "plan_key": o.plan_key,
        "days": o.days,
        "amount": int(o.amount),
        "checkout_url": o.checkout_url if o.status == "pending" else None,
        "paid_at": o.paid_at.isoformat() + "Z" if o.paid_at else None,
    }


# ─────────────────────────────────────────────────────────────
#  Buyurtma yaratish
# ─────────────────────────────────────────────────────────────
async def create_order(session, body: dict) -> dict:
    from bot.services import paylov
    from bot.services.plan_pricing import get_discounted_plan, get_effective_plan

    client_ref = str(body.get("client_ref") or "").strip()[:64]
    plan_key = str(body.get("plan_key") or "")
    try:
        app_user_id = int(body.get("app_user_id"))
    except (TypeError, ValueError):
        raise PartnerError(422, "bad_request", "app_user_id noto'g'ri")
    if not client_ref:
        raise PartnerError(422, "bad_request", "client_ref yo'q")

    # Ilova backend'i tarif, narx va promokodni o'zi boshqaradi (o'z bazasida) —
    # imzolangan so'rovda tayyor summa va kunlarni yuboradi. Bot faqat Paylov ko'prigi.
    app_priced = body.get("amount_tiyin") is not None
    if app_priced:
        try:
            amount = int(body.get("amount_tiyin"))
            days = int(body.get("days"))
        except (TypeError, ValueError):
            raise PartnerError(422, "bad_request", "amount_tiyin/days noto'g'ri")
        if not (MIN_APP_AMOUNT_TIYIN <= amount <= MAX_APP_AMOUNT_TIYIN):
            raise PartnerError(422, "bad_amount", "Summa ruxsat etilgan oraliqda emas")
        if not (1 <= days <= 3650):
            raise PartnerError(422, "bad_request", "days 1..3650 bo'lishi kerak")
        if not _PLAN_KEY_RE.match(plan_key):
            raise PartnerError(422, "plan_unknown", "Noma'lum tarif")
        title = " ".join(str(body.get("title") or "").split())[:64] or None
    elif plan_key not in SUBSCRIPTION_PLANS:
        raise PartnerError(422, "plan_unknown", "Noma'lum tarif")
    provider = str(body.get("provider") or PAYLOV_PROVIDER).strip().lower()
    if provider not in PAYLOV_PROVIDERS:
        raise PartnerError(422, "provider_unknown", "Noma'lum to'lov usuli")
    if not PAYLOV_ENABLED:
        raise PartnerError(503, "payments_disabled", "To'lov tizimi sozlanmagan")

    # Idempotent: bir xil client_ref qayta kelsa — o'sha buyurtma.
    existing = (await session.execute(
        select(PartnerOrder).where(PartnerOrder.client_ref == client_ref)
    )).scalar_one_or_none()
    if existing is not None:
        if app_priced and (int(existing.amount) != amount or int(existing.days) != days):
            raise PartnerError(409, "client_ref_conflict", "Bu client_ref boshqa summa bilan band")
        return _public(existing)

    if app_priced:
        # Promokod ilova bazasida hisoblangan — bot promokodlariga tegmaymiz.
        promo_code = None
        bonus_days = max(0, int(body.get("bonus_days") or 0))
    else:
        title = None
        promo_code = (body.get("promo_code") or "").strip() or None
        bonus_days, discount = 0, 0
        if promo_code:
            res = await _validate_promo(session, promo_code)
            if res.is_free:
                raise PartnerError(422, "promo_free_at_checkout", "Bu promokod bepul Premium beradi")
            bonus_days = int(res.bonus_days or 0)
            discount = int(res.discount_percent or 0)

        plan = None
        if discount > 0 and plan_key in ("1m", "3m"):
            plan = get_discounted_plan(plan_key, discount)
        plan = plan or get_effective_plan(plan_key) or SUBSCRIPTION_PLANS[plan_key]
        amount = int(plan["price"]) * 100
        days = int(SUBSCRIPTION_PLANS[plan_key]["days"]) + bonus_days

    next_id = int(await session.scalar(select(func.coalesce(func.max(PartnerOrder.id), 0))) or 0) + 1
    order = PartnerOrder(
        partner="app",
        external_id=_external_id(next_id),
        client_ref=client_ref,
        app_user_id=app_user_id,
        app_user_label=str(body.get("app_user_label") or "")[:64] or None,
        plan_key=plan_key,
        title=title,
        days=days,
        bonus_days=bonus_days,
        promocode=promo_code,
        amount=amount,
        provider=provider,
        status="pending",
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    return_url = str(body.get("return_url") or "").strip() or None
    if return_url and not return_url.startswith("https://"):
        return_url = None
    try:
        resp = await paylov.create_checkout(order.external_id, amount, return_url=return_url, provider=provider)
    except Exception as e:
        order.status = "cancelled"
        await session.commit()
        logger.error(f"❌ Partner checkout xato order={order.id}: {e}")
        raise PartnerError(502, "paylov_error", "Paylov checkout yaratilmadi")
    order.provider_order_id = str(resp.get("order_id") or "") or None
    order.checkout_url = resp.get("checkout_url")
    if not order.checkout_url:
        order.status = "cancelled"
        await session.commit()
        raise PartnerError(502, "paylov_error", "Paylov checkout_url qaytarmadi")
    await session.commit()
    logger.info(f"📱 Ilova buyurtmasi: {order.external_id} user={order.app_user_label} plan={plan_key} amount={amount}")
    return _public(order)


async def get_order(session, external_id: str) -> dict:
    o = (await session.execute(
        select(PartnerOrder).where(PartnerOrder.external_id == external_id)
    )).scalar_one_or_none()
    if o is None:
        raise PartnerError(404, "order_not_found", "Buyurtma topilmadi")
    return _public(o)


# ─────────────────────────────────────────────────────────────
#  Bepul promokod
# ─────────────────────────────────────────────────────────────
async def redeem_promo(session, body: dict) -> dict:
    code = str(body.get("code") or "").strip()[:64]
    customer_ref = str(body.get("customer_ref") or "").strip()[:80]
    if not code or not customer_ref:
        raise PartnerError(422, "promo_not_found", "Promokod bo'sh")
    res = await _validate_promo(session, code)
    if not res.is_free:
        raise PartnerError(422, "promo_not_free", "Bu chegirma promokodi")
    days = int(res.bonus_days or 0)
    if days <= 0:
        raise PartnerError(422, "promo_not_found", "Promokod kunlari yo'q")
    norm = code.lower()
    used = await session.scalar(select(PartnerPromoRedemption.id).where(
        PartnerPromoRedemption.code == norm, PartnerPromoRedemption.customer_ref == customer_ref,
    ))
    if used:
        raise PartnerError(409, "promo_already_used", "Promokod allaqachon ishlatilgan")
    session.add(PartnerPromoRedemption(
        code=norm, customer_ref=customer_ref, days=days,
        app_user_id=int(body["app_user_id"]) if str(body.get("app_user_id") or "").isdigit() else None,
    ))
    promo = res.promo or (await session.execute(
        select(Promocode).where(func.lower(Promocode.code) == norm)
    )).scalar_one_or_none()
    if promo is not None:
        promo.used_count = (promo.used_count or 0) + 1
    await session.commit()
    return {"days": days, "code": norm}


async def export_promocodes(session) -> dict:
    """Ilova admin paneli promokodlarni bir marta o'z bazasiga ko'chirishi uchun (faqat o'qish)."""
    rows = (await session.execute(select(Promocode).order_by(Promocode.created_at))).scalars().all()
    return {
        "promocodes": [
            {
                "code": p.code,
                "is_free": bool(p.is_free),
                "bonus_days": int(p.bonus_days or 0),
                "discount_percent": int(getattr(p, "discount_percent", 0) or 0),
                "max_uses": int(p.max_uses or 0),
                "used_count": int(p.used_count or 0),
                "is_active": bool(p.is_active),
                "expires_at": p.expires_at.isoformat() + "Z" if p.expires_at else None,
            }
            for p in rows
        ]
    }


# ─────────────────────────────────────────────────────────────
#  Paylov webhooki (payment_service.process_webhook dan chaqiriladi)
# ─────────────────────────────────────────────────────────────
async def find_order(session, ref: str):
    ref = (ref or "").strip()
    if not ref:
        return None
    return (await session.execute(
        select(PartnerOrder).where(or_(
            PartnerOrder.external_id == ref,
            PartnerOrder.payment_id == ref,
            PartnerOrder.client_ref == ref,
        )).order_by(PartnerOrder.id.desc())
    )).scalars().first()


async def handle_paylov_webhook(session, payload: dict, state: int) -> bool:
    """True — buyurtma partner buyurtmasi edi va qayta ishlandi."""
    from bot.services.payment_service import STATE_CANCELLED, STATE_SUCCESS, _amounts_match, _notify_admin

    external_id = payload.get("external_id")
    order = (await session.execute(
        select(PartnerOrder).where(PartnerOrder.external_id == external_id)
    )).scalar_one_or_none()
    if order is None:
        return False

    if state == STATE_CANCELLED:
        if order.status == "pending":
            order.status = "cancelled"
            _queue_notify(order)
            await session.commit()
            _spawn_delivery(order.id)
        return True
    if state != STATE_SUCCESS or order.status != "pending":
        return True

    if "amount" in payload and not _amounts_match(payload.get("amount"), order.amount):
        await _notify_admin(
            "⚠️ <b>Ilova to'lovi: summa mos kelmadi</b>\n\n"
            f"👤 Ilova foydalanuvchisi: <code>{order.app_user_label or order.app_user_id}</code>\n"
            f"🆔 external_id: <code>{order.external_id}</code>\n"
            f"💰 To'langan: <b>{payload.get('amount')}</b>, kutilgan: <b>{order.amount // 100}</b> so'm\n\n"
            "Tekshirib, kerak bo'lsa /admin → 💳 To'lovni faollashtirish orqali oching."
        )
        return True

    await mark_paid(session, order, payload.get("payment_id"))
    return True


async def mark_paid(session, order: PartnerOrder, payment_id=None) -> bool:
    """Webhook va admin qo'lda faollashtirish uchun umumiy. Idempotent."""
    if order.status == "paid":
        return False
    order.status = "paid"
    order.paid_at = datetime.utcnow()
    if payment_id is not None:
        order.payment_id = str(payment_id)
    _queue_notify(order)
    await session.commit()
    _spawn_delivery(order.id)

    if order.promocode:
        try:
            from bot.services.premium_service import increment_promocode_use
            await increment_promocode_use(session, order.promocode)
        except Exception:
            pass
    try:
        from bot.services.payment_service import _notify_admin
        title = _order_title(order)
        await _notify_admin(
            "📱 <b>Ilovadan to'lov</b>\n\n"
            f"👤 {order.app_user_label or order.app_user_id}\n"
            f"📦 {title} · {order.days} kun\n"
            f"💰 {order.amount // 100:,} so'm".replace(",", " ")
        )
    except Exception:
        pass
    await _try_fiscalization(session, order)
    logger.info(f"✅ Ilova to'lovi: {order.external_id} user={order.app_user_id} plan={order.plan_key}")
    return True


async def _try_fiscalization(session, order: PartnerOrder) -> None:
    if not PAYLOV_FISCAL_ENABLED or order.fiscal_done or not order.payment_id:
        return
    try:
        from bot.services import paylov
        title = _order_title(order)
        item = {
            "title": f"IntizomAI — {title} obuna",
            "price": int(order.amount // 100),
            "count": 1,
            "vat_percent": PAYLOV_FISCAL_VAT_PERCENT,
        }
        if PAYLOV_FISCAL_MXIK:
            item["code"] = PAYLOV_FISCAL_MXIK
        if PAYLOV_FISCAL_PACKAGE_CODE:
            item["package_code"] = PAYLOV_FISCAL_PACKAGE_CODE
        await paylov.register_fiscalization(order.payment_id, [item])
        order.fiscal_done = True
        await session.commit()
    except Exception as e:
        logger.warning(f"Partner fiscalization xato {order.external_id}: {e}")


# ─────────────────────────────────────────────────────────────
#  Ilova backend'iga natijani yetkazish (callback)
# ─────────────────────────────────────────────────────────────
def _queue_notify(order: PartnerOrder) -> None:
    order.notify_status = "pending"
    order.notify_next_at = datetime.utcnow()


def _spawn_delivery(order_id: int) -> None:
    try:
        asyncio.get_running_loop().create_task(deliver(order_id))
    except RuntimeError:
        pass


async def deliver(order_id: int) -> bool:
    if not (PARTNER_APP_CALLBACK_URL and PARTNER_APP_SECRET):
        return False
    from database.db import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        order = await session.get(PartnerOrder, order_id)
        if order is None or order.notify_status in ("sent", "none"):
            return False
        event = "order.paid" if order.status == "paid" else "order.cancelled"
        body = json.dumps({
            "event": event,
            "external_id": order.external_id,
            "client_ref": order.client_ref,
            "app_user_id": order.app_user_id,
            "plan_key": order.plan_key,
            "days": order.days,
            "amount": int(order.amount),
            "payment_id": order.payment_id,
            "paid_at": order.paid_at.isoformat() + "Z" if order.paid_at else None,
        }, separators=(",", ":")).encode()
        ts = str(int(time.time() * 1000))
        path = urlsplit(PARTNER_APP_CALLBACK_URL).path or "/"
        headers = {
            "Content-Type": "application/json",
            "X-Partner-Key": PARTNER_APP_KEY,
            "X-Timestamp": ts,
            "X-Signature": sign("POST", path, ts, body),
        }
        error = None
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(PARTNER_APP_CALLBACK_URL, content=body, headers=headers)
            if 200 <= r.status_code < 300:
                order.notify_status = "sent"
                order.notified_at = datetime.utcnow()
                order.notify_error = None
                await session.commit()
                return True
            error = f"HTTP {r.status_code}: {r.text[:200]}"
        except httpx.HTTPError as e:
            error = f"{type(e).__name__}: {e}"[:300]
        order.notify_attempts = (order.notify_attempts or 0) + 1
        order.notify_error = error
        if order.notify_attempts >= MAX_NOTIFY_ATTEMPTS:
            order.notify_status = "failed"
        else:
            delay = min(3600, 15 * (2 ** min(order.notify_attempts, 8)))
            order.notify_next_at = datetime.utcnow() + timedelta(seconds=delay)
        await session.commit()
        logger.warning(f"Partner callback yetmadi {order.external_id}: {error}")
        return False


async def retry_loop(interval: int = 60) -> None:
    """Web jarayonida ishlaydi: yetib bormagan callback'larni qayta yuboradi."""
    from database.db import AsyncSessionLocal
    await asyncio.sleep(10)
    while True:
        try:
            async with AsyncSessionLocal() as session:
                ids = (await session.execute(
                    select(PartnerOrder.id).where(
                        PartnerOrder.notify_status == "pending",
                        or_(PartnerOrder.notify_next_at.is_(None), PartnerOrder.notify_next_at <= datetime.utcnow()),
                    ).limit(50)
                )).scalars().all()
            for oid in ids:
                await deliver(oid)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Partner retry loop xato: {e}")
        await asyncio.sleep(interval)
