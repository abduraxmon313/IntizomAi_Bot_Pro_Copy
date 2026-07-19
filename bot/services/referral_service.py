"""
Referral (taklif) xizmati — do'st taklif qilib bepul premium olish.

Mantiq:
  • Har bir foydalanuvchining shaxsiy havolasi bor:
        https://t.me/<bot>?start=ref_<telegram_id>
  • Havola orqali kelgan YANGI foydalanuvchi birinchi marta /start bosganda
    taklif (Referral) yoziladi va taklif qiluvchining hisobi +1 bo'ladi.
  • Har REFERRAL_THRESHOLD (default 5) ta muvaffaqiyatli taklif uchun taklif
    qiluvchiga REFERRAL_REWARD_DAYS (default 7) kunlik premium sovg'a qilinadi.

Himoyalar:
  • O'z-o'zini taklif qilish hisoblanmaydi.
  • Bir foydalanuvchi faqat bir marta taklif qilingan deb sanaladi
    (referrals.referred_telegram_id unikal + users.referred_by).
  • Faqat YANGI (birinchi marta start bosgan) foydalanuvchilar sanaladi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime as _dt

from bot.config import (
    BOT_USERNAME,
    REFERRAL_INVITEE_REWARD_DAYS,
    REFERRAL_PAYLOAD_PREFIX,
    REFERRAL_REWARD_DAYS,
    REFERRAL_REWARD_SOURCE,
    REFERRAL_THRESHOLD,
)
from bot.models.referral import Referral
from bot.models.user import User
from bot.services.premium_service import days_left, grant_bonus_premium

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  HAVOLA YASASH / O'QISH
# ─────────────────────────────────────────────────────────────
async def get_bot_username(bot) -> str:
    """Bot username'ini (cache'langan) oladi; bo'lmasa config'dagini qaytaradi."""
    try:
        me = await bot.me()
        if me and me.username:
            return me.username
    except Exception:
        pass
    return BOT_USERNAME


def build_referral_link(username: str, telegram_id: int) -> str:
    """Shaxsiy taklif havolasini yasaydi."""
    username = (username or BOT_USERNAME).lstrip("@")
    return f"https://t.me/{username}?start={REFERRAL_PAYLOAD_PREFIX}{telegram_id}"


def parse_referrer_id(payload: Optional[str]) -> Optional[int]:
    """
    /start payload'idan taklif qiluvchining telegram_id sini ajratadi.
    Masalan: 'ref_12345' -> 12345. Mos kelmasa None.
    """
    if not payload:
        return None
    payload = payload.strip()
    if not payload.startswith(REFERRAL_PAYLOAD_PREFIX):
        return None
    raw = payload[len(REFERRAL_PAYLOAD_PREFIX):]
    if not raw.isdigit():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────
#  STATISTIKA
# ─────────────────────────────────────────────────────────────
@dataclass
class ReferralStats:
    total: int                 # jami muvaffaqiyatli takliflar
    threshold: int             # mukofot uchun kerakli taklif soni
    rewards_given: int         # berilgan mukofotlar uchun "ishlatilgan" takliflar
    progress: int              # joriy to'plamdagi taklif (0..threshold-1 yoki threshold)
    remaining: int             # mukofotga qolgan taklif soni
    rewards_count: int         # berilgan mukofotlar (premium) soni


def _stats_from_user(user: User) -> ReferralStats:
    total = int(user.referral_count or 0)
    rewards_given = int(user.referral_rewards_given or 0)
    threshold = REFERRAL_THRESHOLD or 5

    # Joriy (mukofotlanmagan) to'plamdagi taklif soni: 0..threshold-1
    cur_in_set = max(0, total - rewards_given) % threshold
    remaining = threshold - cur_in_set  # keyingi bepul premiumgacha qolgan

    return ReferralStats(
        total=total,
        threshold=threshold,
        rewards_given=rewards_given,
        progress=cur_in_set,
        remaining=remaining,
        rewards_count=rewards_given // threshold,
    )


async def get_referral_stats(session: AsyncSession, user: User) -> ReferralStats:
    """Foydalanuvchining taklif statistikasi (DB'dagi haqiqiy son bilan moslab)."""
    # Haqiqiy sonni referrals jadvalidan ham olib, user.referral_count bilan
    # nomuvofiqlik bo'lsa tuzatamiz (himoya).
    real = await session.scalar(
        select(func.count(Referral.id)).where(
            Referral.referrer_telegram_id == user.telegram_id
        )
    ) or 0
    if real != (user.referral_count or 0):
        user.referral_count = real
        try:
            await session.commit()
        except Exception:
            await session.rollback()
    return _stats_from_user(user)


# ─────────────────────────────────────────────────────────────
#  TAKLIFNI RO'YXATGA OLISH + MUKOFOT
# ─────────────────────────────────────────────────────────────
@dataclass
class RegisterResult:
    counted: bool = False          # taklif hisoblandi
    reason: str = ""               # hisoblanmasa sabab
    referrer: Optional[User] = None
    rewarded: bool = False         # mukofot (premium) berildi
    total: int = 0                 # taklif qiluvchining jami takliflari


async def register_referral(
    session: AsyncSession,
    referrer_telegram_id: int,
    new_user: User,
    bot=None,
) -> RegisterResult:
    """
    Yangi foydalanuvchi taklif havolasi orqali kelganini FAQAT ro'yxatga oladi.

    Muhim: /start bosishning o'zi mukofot BERMAYDI. Invitee birinchi reja/odat
    bajarganidan keyin `activate_referral()` chaqiriladi va shundagina:
      • invitee — bonus premium oladi
      • referrer — sanog'i ko'payadi va har `REFERRAL_THRESHOLD` uchun premium oladi

    Bu sifatsiz (bo'sh registratsiya) taklif fraud'ini oldini oladi.
    """
    # 1) O'z-o'zini taklif qilish — hisoblanmaydi
    if referrer_telegram_id == new_user.telegram_id:
        return RegisterResult(counted=False, reason="self")

    # 2) Bu foydalanuvchi allaqachon taklif qilinganmi
    if new_user.referred_by:
        return RegisterResult(counted=False, reason="already_referred")

    existing = await session.scalar(
        select(Referral).where(
            Referral.referred_telegram_id == new_user.telegram_id
        )
    )
    if existing:
        return RegisterResult(counted=False, reason="already_referred")

    # 3) Taklif qiluvchi mavjudmi
    referrer = await session.scalar(
        select(User).where(User.telegram_id == referrer_telegram_id)
    )
    if not referrer:
        return RegisterResult(counted=False, reason="referrer_not_found")

    # 4) Taklifni yozamiz — activated_at hozircha NULL. Mukofot invitee birinchi
    # item bajargandan keyin `activate_referral()` orqali beriladi.
    ref = Referral(
        referrer_telegram_id=referrer_telegram_id,
        referred_telegram_id=new_user.telegram_id,
    )
    session.add(ref)
    new_user.referred_by = referrer_telegram_id
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.warning(f"Referral yozishda xato: {e}")
        return RegisterResult(counted=False, reason="db_error")

    return RegisterResult(counted=True, referrer=referrer, total=int(referrer.referral_count or 0))


async def activate_referral(
    session: AsyncSession,
    invitee: User,
    bot=None,
) -> RegisterResult:
    """
    Invitee birinchi reja/odat bajargandan keyin chaqiriladi. Idempotent:
    faqat activated_at hali NULL bo'lgan referralni "activated" qiladi va
    mukofotlarni beradi. Bir marta bajarilgach, keyingi chaqiruvlarda no-op.

    Chaqirish joyi: reja `done` bo'lganda va odat `done` bo'lganda
    (callback.py va webapp/routes/plans.py, webapp/routes/habits.py).
    """
    if not invitee or not getattr(invitee, "referred_by", None):
        return RegisterResult(counted=False, reason="no_referrer")

    # Referral qatorini topamiz — hali aktivatsiya qilinmagan bo'lishi kerak.
    ref = await session.scalar(
        select(Referral).where(Referral.referred_telegram_id == invitee.telegram_id)
    )
    if ref is None:
        return RegisterResult(counted=False, reason="ref_not_found")
    if getattr(ref, "activated_at", None) is not None:
        return RegisterResult(counted=False, reason="already_activated")

    referrer = await session.scalar(
        select(User).where(User.telegram_id == ref.referrer_telegram_id)
    )
    if not referrer:
        # Referrer o'chirilgan bo'lsa faqat rowni belgilaymiz va chiqamiz.
        ref.activated_at = _dt.utcnow()
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        return RegisterResult(counted=False, reason="referrer_not_found")

    # Referralni "activated" deb belgilaymiz va referrer sanog'ini oshiramiz.
    ref.activated_at = _dt.utcnow()
    referrer.referral_count = int(referrer.referral_count or 0) + 1
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.warning(f"Referral activation yozishda xato: {e}")
        return RegisterResult(counted=False, reason="db_error")

    await session.refresh(referrer)
    total = int(referrer.referral_count or 0)

    # Invitee'ga bonus premium (ikki tomonlama mukofot).
    if REFERRAL_INVITEE_REWARD_DAYS > 0:
        try:
            await grant_bonus_premium(
                session, invitee, REFERRAL_INVITEE_REWARD_DAYS,
                source="referral_invitee",
            )
            if bot is not None:
                try:
                    await bot.send_message(
                        invitee.telegram_id,
                        (
                            "🎁 <b>Birinchi qadam uchun sovg'a!</b>\n\n"
                            f"Do'stingiz taklifi orqali qo'shilib, birinchi vazifangizni bajardingiz — "
                            f"sizga <b>{REFERRAL_INVITEE_REWARD_DAYS} kunlik Premium</b> berildi!\n\n"
                            "✨ Mini App va cheksiz imkoniyatlar ochiq."
                        ),
                        parse_mode="HTML",
                    )
                except TelegramForbiddenError:
                    pass
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Invitee mukofotini berishda xato: {e}")

    # Referrer uchun mukofot: har THRESHOLD ta faol do'st = REFERRAL_REWARD_DAYS kun.
    rewarded = False
    while (total - int(referrer.referral_rewards_given or 0)) >= REFERRAL_THRESHOLD:
        try:
            await grant_bonus_premium(
                session, referrer, REFERRAL_REWARD_DAYS,
                source=REFERRAL_REWARD_SOURCE,
            )
        except Exception as e:
            logger.error(f"Referrer mukofotini berishda xato: {e}")
            break
        referrer.referral_rewards_given = int(referrer.referral_rewards_given or 0) + REFERRAL_THRESHOLD
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        rewarded = True

    if bot is not None:
        await _notify_referrer(bot, referrer, total, rewarded)

    return RegisterResult(counted=True, referrer=referrer, rewarded=rewarded, total=total)


async def _notify_referrer(bot, referrer: User, total: int, rewarded: bool) -> None:
    """Taklif qiluvchiga faol taklif yoki mukofot haqida xabar yuboradi."""
    try:
        if rewarded:
            text = (
                "🎉 <b>Tabriklaymiz!</b>\n\n"
                f"Siz <b>{REFERRAL_THRESHOLD} ta</b> faol do'stingiz uchun "
                f"<b>{REFERRAL_REWARD_DAYS} kunlik Premium</b> qo'lga kiritdingiz! 🎁\n\n"
                f"💎 Premium faol — <b>{days_left(referrer)} kun</b> qoldi.\n\n"
                f"Davom eting — yana {REFERRAL_THRESHOLD} ta faol do'st = yana {REFERRAL_REWARD_DAYS} kun! 🚀"
            )
        else:
            remaining = REFERRAL_THRESHOLD - (
                (total - int(referrer.referral_rewards_given or 0)) % REFERRAL_THRESHOLD
            )
            if remaining == REFERRAL_THRESHOLD:
                remaining = REFERRAL_THRESHOLD
            text = (
                "🔥 <b>Do'stingiz faol!</b>\n\n"
                f"Taklif qilgan do'stingiz birinchi vazifasini bajardi va Premium oldi.\n"
                f"📊 Faol takliflar: <b>{total} ta</b>\n"
                f"🎁 Sizga {REFERRAL_REWARD_DAYS} kun Premiumgacha yana <b>{remaining} ta</b> faol do'st qoldi!"
            )
        await bot.send_message(referrer.telegram_id, text, parse_mode="HTML")
    except TelegramForbiddenError:
        pass
    except Exception as e:
        logger.debug(f"Referrer'ga xabar yuborilmadi: {e}")
