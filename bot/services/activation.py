"""
Foydalanuvchi "aktivatsiyasi" — sotuv oqimida yagona nuqta.

"Aktivatsiya" — bu foydalanuvchining birinchi reja yoki odatni MUVAFFAQIYATLI
bajargani. Faqat shundagina biz:
  1. `3 kunlik Premium trial`ni sovg'a qilamiz (agar hali sovg'a qilmagan bo'lsak).
  2. Taklif havolasi bo'yicha kelgan bo'lsa — referral mukofotlarini beramiz
     (invitee'ga 3 kun, referrer sanog'iga +1, har 5 faol do'st uchun +7 kun).

Bu marketing va product mantiqning yadrosi: sovuq `/start` emas, real qiymat
kelganidan keyin sovg'a beriladi. Bu retention va conversion'ni oshiradi.

Chaqirilish joylari:
  • bot/handlers/callback.py — reja `done_handler` va odat `hbt_done` bosilganda
  • webapp/routes/plans.py — status "done"ga o'zgartirilganda
  • webapp/routes/habits.py — odat toggle-on qilinganda

Idempotent: bir marta bajarilgach, keyingi chaqiruvlarda no-op.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TRIAL_DAYS
from bot.models.user import User
from bot.services.premium_service import grant_bonus_premium, user_is_premium
from bot.services.referral_service import activate_referral

logger = logging.getLogger(__name__)


async def on_first_completion(
    session: AsyncSession,
    user: User,
    bot=None,
) -> None:
    """
    Foydalanuvchi biror reja/odatni bajarganidan keyin chaqiriladi.

    Idempotent:
      • Trial faqat `trial_used=False` bo'lganda bir marta beriladi.
      • Referral mukofoti faqat Referral.activated_at=NULL bo'lganda bir marta beriladi.
    """
    if user is None:
        return

    # 1) Referral aktivatsiyasi — invitee'ga bonus, referrer sanog'iga +1.
    try:
        await activate_referral(session, user, bot=bot)
    except Exception as e:
        logger.warning(f"activate_referral xato user={user.telegram_id}: {e}")

    # 2) 3 kunlik trial — faqat birinchi muvaffaqiyatdan keyin. Referral bonusi
    #    bilan aralashmaslik uchun `activate_referral`dan KEYIN chaqiramiz —
    #    ikkalasi ham additiv qo'shiladi (premium_until ustiga).
    try:
        if TRIAL_DAYS > 0 and not user.trial_used:
            granted = await grant_bonus_premium(
                session, user, TRIAL_DAYS, source="trial",
            )
            user.trial_used = True
            try:
                await session.commit()
            except Exception:
                await session.rollback()
            if granted and bot is not None:
                try:
                    await bot.send_message(
                        user.telegram_id,
                        (
                            "🎁 <b>Birinchi qadam uchun sovg'a!</b>\n\n"
                            f"Sizga <b>{TRIAL_DAYS} kunlik Premium</b> sinov ochildi.\n\n"
                            "✨ Cheksiz reja/maqsad/odat va Mini App'dan foydalaning.\n"
                            "Endi kuningizga intizom qo'shing! 🔥"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"trial berishda xato user={user.telegram_id}: {e}")


# Backward-compat sinonim — chaqiruvchi kod uchun toza nom.
mark_activation = on_first_completion
