"""
To'lov biznes-mantiqi (Paylov ustida).

  • create_checkout_order — PaymentOrder yaratadi + Paylov checkout oladi.
  • process_webhook       — Paylov webhookini qayta ishlaydi: to'lov muvaffaqiyatli
                            bo'lsa premium ochadi, soliq cheki yaratadi va
                            foydalanuvchini xabardor qiladi (idempotent).

Xavfsizlik: external_id kriptografik tasodifiy qism o'z ichiga oladi, shu sabab
soxta webhook bilan premium ochib bo'lmaydi. Qo'shimcha: summa, holat (state) va
idempotentlik (pending → paid) tekshiriladi.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from datetime import datetime

from sqlalchemy import select

from bot.config import (
    BOT_TOKEN,
    SUBSCRIPTION_PLANS,
    PAYLOV_PROVIDER,
    PAYLOV_WEBHOOK_SECRET,
    PAYLOV_FISCAL_ENABLED,
    PAYLOV_FISCAL_MXIK,
    PAYLOV_FISCAL_PACKAGE_CODE,
    PAYLOV_FISCAL_VAT_PERCENT,
)
from bot.models.payment_order import PaymentOrder
from bot.models.user import User
from bot.services import paylov
from bot.services.premium_service import (
    activate_subscription,
    increment_promocode_use,
)

logger = logging.getLogger(__name__)

STATE_SUCCESS = 2
STATE_CANCELLED = -2


def verify_webhook_signature(payload: dict) -> tuple[bool, str]:
    """
    WLCM webhook imzosini tekshiradi (HMAC-SHA256) — webhook haqiqatan WLCM'dan
    kelganini tasdiqlaydi.

    WLCM bergan formula:
        message  = "{order_id}:{payment_id}:{state}:{timestamp}"
        expected = HMAC_SHA256(key=PAYLOV_WEBHOOK_SECRET, msg=message).hexdigest()
        valid    = compare_digest(expected, payload["signature"])

    Qaytaradi: (valid, reason).
      • PAYLOV_WEBHOOK_SECRET sozlanmagan bo'lsa → (True, "secret_not_set")
        (secret kelguncha ishlash to'xtamasligi uchun; chaqiruvchi ogohlantiradi).
      • signature yo'q bo'lsa → (False, "no_signature").
      • mos kelmasa → (False, "mismatch").
    """
    if not PAYLOV_WEBHOOK_SECRET:
        return True, "secret_not_set"

    received = str(payload.get("signature") or "")
    if not received:
        return False, "no_signature"

    # Qiymatlar payloaddan AYNAN olinadi (WLCM ham xuddi shu qiymatlar ustida
    # imzolaydi). Format: order_id:payment_id:state:timestamp
    message = (
        f'{payload.get("order_id")}:{payload.get("payment_id")}:'
        f'{payload.get("state")}:{payload.get("timestamp")}'
    )
    expected = hmac.new(
        PAYLOV_WEBHOOK_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    valid = hmac.compare_digest(expected, received)
    return valid, ("ok" if valid else "mismatch")


def _gen_external_id(user_id: int) -> str:
    """Taxmin qilib bo'lmaydigan external_id (random token bilan)."""
    return f"iz{user_id}t{int(time.time())}r{secrets.token_hex(6)}"


async def create_checkout_order(session, user, plan_key: str,
                                bonus_days: int = 0, promo_code: str | None = None,
                                provider: str | None = None):
    """
    PaymentOrder (pending) yaratadi va Paylov checkout URL oladi.
    provider — to'lov provayderi (payme/click/uzum/paylov). None bo'lsa default.
    Qaytaradi: (order, checkout_url). checkout_url None bo'lsa — xato.
    """
    # Effective narx — admin o'zgartirgan narx ustuvor.
    # `SUBSCRIPTION_PLANS` — tarif kaliti va meta (kunlar/emoji/teg) uchun,
    # narx `plan_pricing` xizmatidan olinadi.
    from bot.services.plan_pricing import get_effective_plan
    plan = get_effective_plan(plan_key) or SUBSCRIPTION_PLANS.get(plan_key)
    if not plan:
        raise ValueError(f"Noma'lum tarif: {plan_key}")

    prov = (provider or PAYLOV_PROVIDER).strip().lower()
    amount_tiyin = int(plan["price"]) * 100  # so'm -> tiyin (order yaratilgan paytdagi narx qulflanadi)
    external_id = _gen_external_id(user.id)

    order = PaymentOrder(
        user_id=user.id,
        external_id=external_id,
        plan_key=plan_key,
        bonus_days=int(bonus_days or 0),
        promocode=promo_code,
        amount=amount_tiyin,
        provider=prov,
        status="pending",
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    resp = await paylov.create_checkout(external_id, amount_tiyin, provider=prov)
    checkout_url = resp.get("checkout_url")
    order.provider_order_id = str(resp.get("order_id") or "") or None
    await session.commit()

    return order, checkout_url


async def _notify(telegram_id: int, text: str) -> None:
    """Foydalanuvchiga xabar yuboradi (qisqa muddatli Bot — pollingга ta'sir qilmaydi)."""
    if not BOT_TOKEN:
        return
    from aiogram import Bot
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_message(telegram_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"To'lov xabarini yuborishda xato {telegram_id}: {e}")
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


async def _notify_admin(text: str) -> None:
    """
    BARCHA adminlarni xabardor qiladi: ADMIN_ID (bosh admin) + /admin orqali
    qo'shilgan adminlar. Shu tariqa to'lov bildirishnomalari har bir adminga
    yetib boradi (adminlar darajasi teng).
    """
    from bot.config import ADMIN_ID

    admin_ids: set[int] = set()
    if ADMIN_ID:
        admin_ids.add(int(ADMIN_ID))

    # Bazadagi qo'shimcha adminlar.
    try:
        from database.db import AsyncSessionLocal
        from bot.models.admin import Admin
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(Admin.telegram_id))).scalars().all()
            for tid in rows:
                if tid:
                    admin_ids.add(int(tid))
    except Exception as e:
        logger.warning(f"Adminlar ro'yxatini olishda xato: {e}")

    for tid in admin_ids:
        await _notify(tid, text)


async def _delete_message(telegram_id: int, message_id: int) -> None:
    """Berilgan xabarni o'chiradi (xato bo'lsa jim o'tadi — masalan xabar eski bo'lsa)."""
    if not BOT_TOKEN or not message_id:
        return
    from aiogram import Bot
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.delete_message(chat_id=telegram_id, message_id=message_id)
    except Exception as e:
        logger.info(f"To'lov xabarini o'chirib bo'lmadi {telegram_id}/{message_id}: {e}")
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


def _amounts_match(webhook_amount, order_amount_tiyin: int) -> bool:
    """Webhook summasi buyurtma summasiga (so'm yoki tiyin talqinida) aniq mosmi."""
    try:
        paid = float(str(webhook_amount).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return False
    expected_som = order_amount_tiyin / 100.0
    expected_tiyin = float(order_amount_tiyin)
    return abs(paid - expected_som) < 1.0 or abs(paid - expected_tiyin) < 1.0


async def process_webhook(payload: dict) -> dict:
    """
    Paylov webhookini qayta ishlaydi. Har doim {'ok': True} qaytaradi (Paylov
    qayta-qayta yubormasligi uchun) — idempotent.
    """
    external_id = payload.get("external_id")
    state = payload.get("state")
    payment_id = payload.get("payment_id")

    if not external_id:
        logger.warning("Webhook: external_id yo'q")
        return {"ok": True}

    try:
        state_int = int(state)
    except (TypeError, ValueError):
        logger.warning(f"Webhook: noto'g'ri state={state!r}")
        return {"ok": True}

    from database.db import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        order = (await session.execute(
            select(PaymentOrder).where(PaymentOrder.external_id == external_id)
        )).scalar_one_or_none()

        if order is None:
            logger.warning(f"Webhook: buyurtma topilmadi external_id={external_id}")
            return {"ok": True}

        # ── Bekor qilingan ──────────────────────────────────
        if state_int == STATE_CANCELLED:
            if order.status == "pending":
                order.status = "cancelled"
                await session.commit()
            return {"ok": True}

        if state_int != STATE_SUCCESS:
            return {"ok": True}

        # ── Muvaffaqiyatli to'lov ───────────────────────────
        if order.status == "paid":
            return {"ok": True}  # idempotent — allaqachon ishlangan
        if order.status != "pending":
            return {"ok": True}

        # User'ni oldindan yuklaymiz — summa mos kelmasa admin xabarida kerak.
        user = (await session.execute(
            select(User).where(User.id == order.user_id)
        )).scalar_one_or_none()
        user_tg = user.telegram_id if user else "—"

        if "amount" in payload and not _amounts_match(payload.get("amount"), order.amount):
            # Summa mos emas — premiumni AVTOMATIK ochmaymiz (komissiyani provayder
            # to'g'rilaydi). Adminni xabardor qilamiz — u qo'lda faollashtiradi.
            logger.warning(
                f"Webhook: summa mos emas — adminga yuborildi. external_id={external_id} "
                f"keldi={payload.get('amount')} kutilgan_tiyin={order.amount}"
            )
            plan_t = SUBSCRIPTION_PLANS.get(order.plan_key, {}).get("title", order.plan_key)
            await _notify_admin(
                "⚠️ <b>To'lov summasi mos kelmadi</b>\n\n"
                f"👤 User TG ID: <code>{user_tg}</code>\n"
                f"🆔 external_id: <code>{external_id}</code>\n"
                f"🧾 payment_id: <code>{payment_id}</code>\n"
                f"📦 Tarif: <b>{plan_t}</b>\n"
                f"💰 To'langan: <b>{payload.get('amount')}</b> so'm\n"
                f"📌 Kutilgan: <b>{order.amount // 100}</b> so'm\n\n"
                "Tekshirib, kerak bo'lsa <b>/admin → 💳 To'lovni faollashtirish</b> orqali oching."
            )
            return {"ok": True}

        if user is None:
            logger.warning(f"Webhook: user topilmadi order={order.id}")
            return {"ok": True}

        # Summa mos — premiumni ochamiz (idempotent, qayta ishlatiladigan helper).
        await activate_order(session, order, payment_id)

        logger.info(
            f"✅ To'lov: user={user.telegram_id} plan={order.plan_key} "
            f"payment_id={order.payment_id} order={order.provider_order_id}"
        )
        return {"ok": True}


async def _try_fiscalization(session, order, user, plan: dict, plan_title: str) -> None:
    """Soliq chekini yaratadi va foydalanuvchiga yuboradi (xato bo'lsa jim o'tadi)."""
    if not PAYLOV_FISCAL_ENABLED:
        return
    if order.fiscal_done or not order.payment_id:
        return
    try:
        item = {
            "title": f"IntizomAI — {plan_title} obuna",
            "price": int(plan.get("price", 0)),
            "count": 1,
            "vat_percent": PAYLOV_FISCAL_VAT_PERCENT,
        }
        # IKPU/MXIK va qadoq kodi — O'zbekiston OFD uchun majburiy bo'lishi mumkin.
        if PAYLOV_FISCAL_MXIK:
            item["code"] = PAYLOV_FISCAL_MXIK
        if PAYLOV_FISCAL_PACKAGE_CODE:
            item["package_code"] = PAYLOV_FISCAL_PACKAGE_CODE
        items = [item]
        result = await paylov.register_fiscalization(order.payment_id, items)

        order.fiscal_done = True
        await session.commit()

        qr = result.get("qr_code_url")
        fiscal_number = result.get("fiscal_number")
        lines = ["🧾 <b>Soliq cheki tayyor</b>"]
        if fiscal_number:
            lines.append(f"№ <code>{fiscal_number}</code>")
        if qr:
            lines.append(f'<a href="{qr}">Chekni ko\'rish (QR)</a>')
        if len(lines) > 1:
            await _notify(user.telegram_id, "\n".join(lines))
    except Exception as e:
        logger.warning(f"Fiscalization xato order={order.id}: {e}")



async def activate_order(session, order, payment_id=None) -> bool:
    """
    Buyurtmani faollashtiradi (premium ochadi, user'ga xabar, soliq cheki).
    Idempotent: allaqachon 'paid' bo'lsa False qaytaradi. Muvaffaqiyatda True.
    """
    if order.status == "paid":
        return False
    user = (await session.execute(
        select(User).where(User.id == order.user_id)
    )).scalar_one_or_none()
    if user is None:
        return False
    order.status = "paid"
    if payment_id is not None:
        order.payment_id = str(payment_id)
    order.paid_at = datetime.utcnow()
    await session.commit()
    sub = await activate_subscription(
        session, user, plan_key=order.plan_key, source="paylov",
        promocode=order.promocode, bonus_days=order.bonus_days or 0,
    )
    if order.promocode:
        try:
            await increment_promocode_use(session, order.promocode)
        except Exception:
            pass
    plan = SUBSCRIPTION_PLANS.get(order.plan_key, {})
    plan_title = plan.get("title", order.plan_key)
    until = sub.expires_at.strftime("%d.%m.%Y") if sub and sub.expires_at else "—"
    await _notify(
        user.telegram_id,
        "🎉 <b>To'lov muvaffaqiyatli! Premium ochildi.</b>\n\n"
        f"📦 Tarif: <b>{plan_title}</b>\n"
        f"📅 Amal qiladi: <b>{until} gacha</b>\n"
        f"⏳ Davomiylik: <b>{sub.days if sub else '—'} kun</b>\n\n"
        "✨ Endi Mini App va barcha premium imkoniyatlar ochiq. Rahmat! 🔥",
    )
    if getattr(order, "pay_message_id", None):
        await _delete_message(user.telegram_id, order.pay_message_id)
    await _try_fiscalization(session, order, user, plan, plan_title)
    logger.info(f"✅ Faollashtirildi: user={user.telegram_id} plan={order.plan_key} order={order.id}")
    return True


async def find_order(session, ref: str):
    """external_id yoki payment_id bo'yicha buyurtmani topadi (eng oxirgisi)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    from sqlalchemy import or_
    res = await session.execute(
        select(PaymentOrder).where(
            or_(PaymentOrder.external_id == ref, PaymentOrder.payment_id == ref)
        ).order_by(PaymentOrder.id.desc())
    )
    return res.scalars().first()
