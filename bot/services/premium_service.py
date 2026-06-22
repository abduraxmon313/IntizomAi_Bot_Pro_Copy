"""
Premium / obuna xizmati — monetizatsiya yadrosi.

Mas'uliyat doirasi:
  • Obuna planlari katalogi (1/3/6/12 oy)
  • Foydalanuvchining premium holatini hisoblash (premium_until asosida)
  • Promokod orqali obunani faollashtirish (sinov bosqichi)
  • Obuna tarixini (Subscription) yozish
  • Free (bepul) foydalanuvchi limitlari (kunlik reja soni)
  • Obuna muddati tugaganlarni downgrade qilish va eslatma uchun ro'yxat

Barcha vaqtlar UTC-naive (datetime.utcnow) bilan saqlanadi va solishtiriladi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import (
    FREE_AI_DAILY_LIMIT,
    FREE_DAILY_PLAN_LIMIT,
    SUBSCRIPTION_PLANS,
)
from bot.models.plan import Plan
from bot.models.subscription import Promocode, Subscription
from bot.models.user import User

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  PLAN KATALOGI
# ─────────────────────────────────────────────────────────────
def get_plans() -> dict:
    """Barcha obuna planlari: {key: {title, days, price}}."""
    return SUBSCRIPTION_PLANS


def get_plan(plan_key: str) -> Optional[dict]:
    return SUBSCRIPTION_PLANS.get(plan_key)


def format_price(price: int) -> str:
    """9900 -> '9 900' (so'm uchun)."""
    return f"{price:,}".replace(",", " ")


# ─────────────────────────────────────────────────────────────
#  PREMIUM HOLAT
# ─────────────────────────────────────────────────────────────
def user_is_premium(user: User) -> bool:
    """premium_until asosida joriy holatni hisoblaydi (UTC)."""
    if not user:
        return False
    until = user.premium_until
    if until is None:
        return False
    return until > datetime.utcnow()


def days_left(user: User) -> int:
    """Premium tugashiga necha kun qolgani (0 yoki musbat)."""
    if not user_is_premium(user):
        return 0
    delta = user.premium_until - datetime.utcnow()
    return max(0, delta.days + (1 if delta.seconds > 0 else 0))


@dataclass
class SubStatus:
    is_premium: bool
    premium_until: Optional[datetime]
    days_left: int
    plan: Optional[str]
    plan_title: Optional[str]


async def get_status(session: AsyncSession, user: User) -> SubStatus:
    """Foydalanuvchining joriy obuna holatini qaytaradi (oxirgi faol obuna bilan)."""
    active_sub = None
    if user_is_premium(user):
        res = await session.execute(
            select(Subscription)
            .where(
                and_(
                    Subscription.user_id == user.id,
                    Subscription.is_active == True,  # noqa: E712
                )
            )
            .order_by(Subscription.expires_at.desc())
        )
        active_sub = res.scalars().first()

    return SubStatus(
        is_premium=user_is_premium(user),
        premium_until=user.premium_until,
        days_left=days_left(user),
        plan=active_sub.plan if active_sub else None,
        plan_title=(
            SUBSCRIPTION_PLANS.get(active_sub.plan, {}).get("title")
            if active_sub else None
        ),
    )


# ─────────────────────────────────────────────────────────────
#  OBUNANI FAOLLASHTIRISH
# ─────────────────────────────────────────────────────────────
async def activate_subscription(
    session: AsyncSession,
    user: User,
    plan_key: str,
    source: str = "promocode",
    promocode: Optional[str] = None,
    bonus_days: int = 0,
) -> Subscription:
    """
    Obunani faollashtiradi yoki uzaytiradi.

    Agar foydalanuvchida hali faol obuna bo'lsa — yangi muddat mavjud
    `premium_until` ustiga qo'shiladi (uzaytirish). Aks holda hozirdan boshlanadi.
    """
    plan = SUBSCRIPTION_PLANS.get(plan_key)
    if not plan:
        raise ValueError(f"Noma'lum plan: {plan_key}")

    now = datetime.utcnow()
    total_days = plan["days"] + max(0, bonus_days)

    # Uzaytirish: agar hali premium bo'lsa, mavjud tugash vaqtidan davom etadi
    base = user.premium_until if (user.premium_until and user.premium_until > now) else now
    expires_at = base + timedelta(days=total_days)

    # Eski faol obunalarni nofaol qilamiz (joriy bittasi bo'lsin)
    old = (await session.execute(
        select(Subscription).where(
            and_(Subscription.user_id == user.id, Subscription.is_active == True)  # noqa: E712
        )
    )).scalars().all()
    for s in old:
        s.is_active = False

    sub = Subscription(
        user_id=user.id,
        plan=plan_key,
        days=total_days,
        price=plan.get("price", 0),
        source=source,
        promocode=promocode,
        started_at=now,
        expires_at=expires_at,
        is_active=True,
    )
    session.add(sub)

    user.is_premium = True
    user.premium_until = expires_at

    await session.commit()
    await session.refresh(sub)
    logger.info(
        f"✅ Obuna faollashdi: user={user.telegram_id} plan={plan_key} "
        f"until={expires_at} source={source}"
    )
    return sub


async def revoke_premium(session: AsyncSession, user: User) -> None:
    """Premiumni bekor qiladi (admin yoki muddati tugaganda)."""
    user.is_premium = False
    user.premium_until = None
    subs = (await session.execute(
        select(Subscription).where(
            and_(Subscription.user_id == user.id, Subscription.is_active == True)  # noqa: E712
        )
    )).scalars().all()
    for s in subs:
        s.is_active = False
    await session.commit()


# ─────────────────────────────────────────────────────────────
#  PROMOKOD
# ─────────────────────────────────────────────────────────────
@dataclass
class PromoResult:
    valid: bool
    reason: str = ""
    plan_override: Optional[str] = None
    bonus_days: int = 0
    promo: Optional[Promocode] = None


async def validate_promocode(session: AsyncSession, code: str) -> PromoResult:
    """
    Promokodni tekshiradi. Faqat DB'dagi (admin yaratgan) promokodlar ishlaydi.

    Eslatma: kuchsizlantirilgan (is_active=False) promokod YANGI foydalanuvchilar
    uchun ishlamaydi; ammo avval undan foydalanib olganlarning obunasiga ta'sir
    qilmaydi (Subscription yozuvlari tegilmaydi).
    """
    if not code:
        return PromoResult(valid=False, reason="Promokod bo'sh")

    norm = code.strip().lower()

    res = await session.execute(
        select(Promocode).where(func.lower(Promocode.code) == norm)
    )
    promo = res.scalar_one_or_none()
    if not promo:
        return PromoResult(valid=False, reason="Bunday promokod topilmadi")
    if not promo.is_active:
        return PromoResult(valid=False, reason="Promokod kuchsizlantirilgan")
    if promo.expires_at and promo.expires_at < datetime.utcnow():
        return PromoResult(valid=False, reason="Promokod muddati tugagan")
    if promo.max_uses and promo.used_count >= promo.max_uses:
        return PromoResult(valid=False, reason="Promokod limiti tugagan")

    return PromoResult(
        valid=True,
        reason="db_code",
        plan_override=promo.plan,
        bonus_days=promo.bonus_days or 0,
        promo=promo,
    )


async def list_promocodes(session: AsyncSession) -> list[Promocode]:
    """Barcha promokodlar (eng yangisi birinchi)."""
    res = await session.execute(
        select(Promocode).order_by(Promocode.created_at.desc())
    )
    return res.scalars().all()


async def delete_promocode(session: AsyncSession, promo_id: int) -> Optional[str]:
    """
    Promokodni BUTUNLAY o'chiradi (DB dan yo'q qiladi).
    Bu faqat YANGI foydalanuvchilar uchun amal qiladi — avval foydalanib
    olganlarning obunasi (Subscription) saqlanib qoladi, chunki ular alohida
    jadvalda. O'chirilgach kod boshqa ishlamaydi.
    Qaytaradi: o'chirilgan promokod matni (yoki None).
    """
    promo = await session.get(Promocode, promo_id)
    if not promo:
        return None
    code = promo.code
    await session.delete(promo)
    await session.commit()
    return code


async def increment_promocode_use(session: AsyncSession, code: str) -> None:
    """Promokod ishlatilganini (used_count) bittaga oshiradi."""
    if not code:
        return
    res = await session.execute(
        select(Promocode).where(func.lower(Promocode.code) == code.strip().lower())
    )
    promo = res.scalar_one_or_none()
    if promo is not None:
        promo.used_count = (promo.used_count or 0) + 1
        await session.commit()


async def redeem_with_promocode(
    session: AsyncSession,
    user: User,
    plan_key: str,
    code: str,
) -> tuple[bool, str, Optional[Subscription]]:
    """
    Promokod orqali obunani faollashtiradi.
    Qaytaradi: (muvaffaqiyat, xabar, Subscription|None)
    """
    result = await validate_promocode(session, code)
    if not result.valid:
        return False, result.reason, None

    # DB promokod plan'ni majburlashi mumkin
    final_plan = result.plan_override or plan_key
    if final_plan not in SUBSCRIPTION_PLANS:
        final_plan = plan_key

    sub = await activate_subscription(
        session,
        user,
        plan_key=final_plan,
        source="promocode",
        promocode=code.strip(),
        bonus_days=result.bonus_days,
    )

    # DB promokod ishlatilishini hisoblaymiz
    if result.promo is not None:
        result.promo.used_count = (result.promo.used_count or 0) + 1
        await session.commit()

    return True, "ok", sub


async def create_promocode(
    session: AsyncSession,
    code: str,
    plan: Optional[str] = None,
    bonus_days: int = 0,
    max_uses: int = 0,
    created_by: Optional[int] = None,
    expires_at: Optional[datetime] = None,
) -> Optional[Promocode]:
    """Yangi promokod yaratadi (admin). Mavjud bo'lsa None qaytaradi."""
    norm = code.strip()
    existing = await session.execute(
        select(Promocode).where(func.lower(Promocode.code) == norm.lower())
    )
    if existing.scalar_one_or_none():
        return None
    promo = Promocode(
        code=norm,
        plan=plan if plan in SUBSCRIPTION_PLANS else None,
        bonus_days=bonus_days,
        max_uses=max_uses,
        created_by=created_by,
        expires_at=expires_at,
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


# ─────────────────────────────────────────────────────────────
#  FREE-TIER LIMITLAR
# ─────────────────────────────────────────────────────────────
async def count_today_plans(session: AsyncSession, user: User) -> int:
    from bot.config import TIMEZONE
    today = datetime.now(TIMEZONE).date()
    cnt = await session.scalar(
        select(func.count(Plan.id)).where(
            and_(Plan.user_id == user.id, Plan.plan_date == today)
        )
    )
    return cnt or 0


@dataclass
class LimitCheck:
    allowed: bool
    used: int
    limit: int
    remaining: int


async def check_plan_limit(
    session: AsyncSession, user: User, adding: int = 1
) -> LimitCheck:
    """
    Free foydalanuvchi uchun kunlik reja limitini tekshiradi.
    Premium foydalanuvchilarga limit yo'q (cheksiz).
    """
    if user_is_premium(user):
        return LimitCheck(allowed=True, used=0, limit=-1, remaining=-1)

    used = await count_today_plans(session, user)
    limit = FREE_DAILY_PLAN_LIMIT
    remaining = max(0, limit - used)
    allowed = (used + adding) <= limit
    return LimitCheck(allowed=allowed, used=used, limit=limit, remaining=remaining)


async def check_goal_limit(session: AsyncSession, user: User, adding: int = 1) -> LimitCheck:
    """Free foydalanuvchi uchun jami maqsad limiti (premium — cheksiz)."""
    if user_is_premium(user):
        return LimitCheck(allowed=True, used=0, limit=-1, remaining=-1)
    from bot.config import FREE_GOAL_LIMIT
    from bot.models.goal import Goal
    used = await session.scalar(
        select(func.count(Goal.id)).where(Goal.user_id == user.id)
    ) or 0
    limit = FREE_GOAL_LIMIT
    remaining = max(0, limit - used)
    return LimitCheck(allowed=(used + adding) <= limit, used=used, limit=limit, remaining=remaining)


async def check_habit_limit(session: AsyncSession, user: User, adding: int = 1) -> LimitCheck:
    """Free foydalanuvchi uchun faol odat limiti (premium — cheksiz)."""
    if user_is_premium(user):
        return LimitCheck(allowed=True, used=0, limit=-1, remaining=-1)
    from bot.config import FREE_HABIT_LIMIT
    from bot.models.habit import Habit
    used = await session.scalar(
        select(func.count(Habit.id)).where(
            and_(Habit.user_id == user.id, Habit.archived == False)  # noqa: E712
        )
    ) or 0
    limit = FREE_HABIT_LIMIT
    remaining = max(0, limit - used)
    return LimitCheck(allowed=(used + adding) <= limit, used=used, limit=limit, remaining=remaining)


async def check_and_consume_ai(session: AsyncSession, user: User) -> LimitCheck:
    """
    AI Coach suhbati uchun kunlik limitni tekshiradi va (free bo'lsa) 1 ta sarflaydi.
    Premium — cheksiz (limit=-1). Free — FREE_AI_DAILY_LIMIT/kun.
    Kun almashsa hisoblagich avtomatik nolga tushadi.
    """
    if user_is_premium(user):
        return LimitCheck(allowed=True, used=0, limit=-1, remaining=-1)

    from bot.config import TIMEZONE
    today = datetime.now(TIMEZONE).date()

    if user.ai_msgs_date != today:
        user.ai_msgs_date = today
        user.ai_msgs_count = 0

    limit = FREE_AI_DAILY_LIMIT
    used = user.ai_msgs_count or 0

    if used >= limit:
        await session.commit()  # kun reset bo'lgan bo'lsa saqlaymiz
        return LimitCheck(allowed=False, used=used, limit=limit, remaining=0)

    user.ai_msgs_count = used + 1
    await session.commit()
    return LimitCheck(
        allowed=True,
        used=user.ai_msgs_count,
        limit=limit,
        remaining=max(0, limit - user.ai_msgs_count),
    )


# ─────────────────────────────────────────────────────────────
#  SCHEDULER UCHUN YORDAMCHILAR
# ─────────────────────────────────────────────────────────────
async def get_expired_premium_users(session: AsyncSession) -> list[User]:
    """premium_until o'tib ketgan, lekin hali is_premium=True bo'lganlar."""
    now = datetime.utcnow()
    res = await session.execute(
        select(User).where(
            and_(
                User.is_premium == True,  # noqa: E712
                User.premium_until != None,  # noqa: E711
                User.premium_until < now,
            )
        )
    )
    return res.scalars().all()


async def get_premium_count(session: AsyncSession) -> int:
    now = datetime.utcnow()
    cnt = await session.scalar(
        select(func.count(User.id)).where(
            and_(
                User.premium_until != None,  # noqa: E711
                User.premium_until > now,
            )
        )
    )
    return cnt or 0
