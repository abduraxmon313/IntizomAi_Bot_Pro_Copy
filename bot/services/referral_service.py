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

from bot.config import (
    BOT_USERNAME,
    REFERRAL_PAYLOAD_PREFIX,
    REFERRAL_REWARD_DAYS,
    REFERRAL_REWARD_PLAN,
    REFERRAL_THRESHOLD,
    REFERRAL_INVITER_CREDITS,
    REFERRAL_INVITEE_CREDITS,
)
from bot.models.referral import Referral
from bot.models.user import User
from bot.services.premium_service import activate_subscription, days_left, grant_ai_credits

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
    Yangi foydalanuvchi taklif havolasi orqali kelganini ro'yxatga oladi.
    Kerak bo'lsa taklif qiluvchiga premium beradi va xabar yuboradi.
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

    # 4) Taklifni yozamiz
    ref = Referral(
        referrer_telegram_id=referrer_telegram_id,
        referred_telegram_id=new_user.telegram_id,
    )
    session.add(ref)
    new_user.referred_by = referrer_telegram_id
    referrer.referral_count = int(referrer.referral_count or 0) + 1
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.warning(f"Referral yozishda xato: {e}")
        return RegisterResult(counted=False, reason="db_error")

    await session.refresh(referrer)
    total = int(referrer.referral_count or 0)

    # ── Mutual mukofot — DARHOL ikki tomonga bonus AI kreditlari ──
    # (Audit: taklif qiluvchi VA yangi kelgan — ikkalasi ham mukofot olsin.)
    try:
        if REFERRAL_INVITEE_CREDITS > 0:
            await grant_ai_credits(session, new_user, REFERRAL_INVITEE_CREDITS)
        if REFERRAL_INVITER_CREDITS > 0:
            await grant_ai_credits(session, referrer, REFERRAL_INVITER_CREDITS)
    except Exception as e:
        logger.debug(f"mutual referral bonus skip: {e}")

    # Yangi kelgan foydalanuvchiga xabar (best-effort)
    if bot is not None and REFERRAL_INVITEE_CREDITS > 0:
        try:
            await bot.send_message(
                new_user.telegram_id,
                f"🎁 <b>Xush kelibsiz sovg'asi!</b>\n\n"
                f"Do'stingiz havolasi orqali keldingiz — sizga "
                f"<b>{REFERRAL_INVITEE_CREDITS} ta bonus AI suhbat</b> berildi! 🤖\n"
                "AI Coach bilan xohlagancha suhbatlashing.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    # 5) Mukofot tekshiruvi — har THRESHOLD ta uchun bir marta premium
    rewarded = False
    while (total - int(referrer.referral_rewards_given or 0)) >= REFERRAL_THRESHOLD:
        try:
            await activate_subscription(
                session, referrer,
                plan_key=REFERRAL_REWARD_PLAN,
                source="referral",
            )
        except Exception as e:
            logger.error(f"Referral mukofotini berishda xato: {e}")
            break
        referrer.referral_rewards_given = int(referrer.referral_rewards_given or 0) + REFERRAL_THRESHOLD
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        rewarded = True

    # 6) Taklif qiluvchiga xabar
    if bot is not None:
        await _notify_referrer(bot, referrer, total, rewarded)

    return RegisterResult(
        counted=True, referrer=referrer, rewarded=rewarded, total=total,
    )


async def _notify_referrer(bot, referrer: User, total: int, rewarded: bool) -> None:
    """Taklif qiluvchiga taraqqiyot yoki mukofot haqida xabar yuboradi."""
    try:
        if rewarded:
            text = (
                "🎉 <b>Tabriklaymiz!</b>\n\n"
                f"Siz <b>{REFERRAL_THRESHOLD} ta</b> do'stingizni taklif qildingiz va "
                f"<b>{REFERRAL_REWARD_DAYS} kunlik Premium</b> sovg'aga ega bo'ldingiz! 🎁\n\n"
                f"💎 Premium faol — <b>{days_left(referrer)} kun</b> qoldi.\n\n"
                "Davom eting — yana 5 ta do'st = yana 1 hafta Premium! 🚀"
            )
        else:
            remaining = REFERRAL_THRESHOLD - (
                (total - int(referrer.referral_rewards_given or 0)) % REFERRAL_THRESHOLD
            )
            if remaining == REFERRAL_THRESHOLD:
                remaining = REFERRAL_THRESHOLD
            text = (
                "👏 <b>Yangi do'st qo'shildi!</b>\n\n"
                f"Havolangiz orqali yana bir do'stingiz qo'shildi.\n"
                f"📊 Jami takliflar: <b>{total} ta</b>\n"
                f"🎁 Bepul premiumgacha yana <b>{remaining} ta</b> do'st qoldi!"
            )
        await bot.send_message(referrer.telegram_id, text, parse_mode="HTML")
    except TelegramForbiddenError:
        pass
    except Exception as e:
        logger.debug(f"Referrer'ga xabar yuborilmadi: {e}")
