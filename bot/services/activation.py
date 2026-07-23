"""
Foydalanuvchi "aktivatsiyasi" — sotuv oqimida yagona nuqta.

"Aktivatsiya" — bu foydalanuvchining birinchi reja yoki odatni MUVAFFAQIYATLI
bajargani. Shu paytda referral mukofotlari (invitee'ga bonus + referrer
sanog'iga +1, har 5 faol do'st uchun +7 kun) ochiladi.

TRIAL OLIB TASHLANDI: avval bu yerda 3 kunlik Premium trial ham berilar edi.
Endi trial hech qanday sharoitda berilmaydi — foydalanuvchi Premium'ni
sotib olishi, promokod ishlatishi yoki do'st taklif qilishi kerak.

Chaqirilish joylari:
  • bot/handlers/callback.py — reja `done_handler` va odat `hbt_done` bosilganda
  • webapp/routes/plans.py — status "done"ga o'zgartirilganda
  • webapp/routes/habits.py — odat toggle-on qilinganda

Idempotent: bir marta bajarilgach, keyingi chaqiruvlarda no-op (referral servisi
o'zi Referral.activated_at bayrog'i bilan takrorlanishni oldini oladi).
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.referral_service import activate_referral

logger = logging.getLogger(__name__)


async def on_first_completion(
    session: AsyncSession,
    user: User,
    bot=None,
) -> None:
    """
    Foydalanuvchi biror reja/odatni bajarganidan keyin chaqiriladi.

    Idempotent: referral aktivatsiyasi faqat Referral.activated_at=NULL bo'lganda
    bir marta ishlaydi. Trial funksiyasi butunlay olib tashlangan — bepul
    Premium sinov beriladigan hech qanday manzil yo'q.
    """
    if user is None:
        return

    # Referral aktivatsiyasi — invitee'ga bonus, referrer sanog'iga +1.
    # (Referrer'ning taklif qilgan do'stlari soni REFERRAL_THRESHOLD ga yetsa,
    # unga REFERRAL_REWARD_DAYS ta kun Premium beriladi — bu yagona bepul
    # Premium olish yo'li.)
    try:
        await activate_referral(session, user, bot=bot)
    except Exception as e:
        logger.warning(f"activate_referral xato user={user.telegram_id}: {e}")


# Backward-compat sinonim — chaqiruvchi kod uchun toza nom.
mark_activation = on_first_completion
