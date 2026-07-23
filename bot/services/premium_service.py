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
    """
    Barcha obuna planlari: {key: {title, days, price}}.

    Bu — DB'dagi admin override'lari config default'lari ustiga qo'yilgan
    "effective" katalogi (bot/services/plan_pricing.py). Shu yerdan
    keyboardlar, checkout va admin oynasi bir xil narxni ko'radi.
    """
    # Lazy import — plan_pricing modulida `bot.models.plan_override` ni import
    # qiladigan aylanma bog'lanish (circular import) bo'lmasligi uchun.
    from bot.services.plan_pricing import get_effective_plans
    return get_effective_plans()


def get_plan(plan_key: str) -> Optional[dict]:
    from bot.services.plan_pricing import get_effective_plan
    return get_effective_plan(plan_key)


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


async def grant_bonus_premium(
    session: AsyncSession,
    user: User,
    days: int,
    source: str = "trial",
    label: str = "Bonus",
    promocode: Optional[str] = None,
) -> Optional[Subscription]:
    """
    Tarif katalogiga bog'lanmagan bonus premium beradi (trial, referral invitee
    yoki `-` turidagi bepul promokod).
    Premium muddatini ADDITIV uzaytiradi (mavjud premium ustiga qo'shiladi).
    """
    if days <= 0:
        return None
    now = datetime.utcnow()
    base = user.premium_until if (user.premium_until and user.premium_until > now) else now
    expires_at = base + timedelta(days=days)

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
        plan=source,            # "trial" | "referral_invitee" | "promo_free"
        days=days,
        price=0,
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
    logger.info(f"🎁 Bonus premium: user={user.telegram_id} +{days}d source={source}")
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


async def revoke_all_trial_subscriptions() -> int:
    """
    Bir martalik CLEANUP: hozirda faol bo'lgan barcha `source="trial"` obunalarni
    bekor qiladi va shunga bog'liq user'larning Premium holatini olib tashlaydi.

    NEGA KERAK: 3 kunlik trial funksiyasi loyihadan butunlay olib tashlangan.
    Ammo baza'da hali ham `is_active=True` bo'lgan trial obunalar bo'lishi
    mumkin (avval berilgan). Bu funksiya ularni tozalaydi.

    INVARIANT: har bir foydalanuvchida ayni paytda AT MOST BITTA faol obuna
    bo'ladi (`activate_subscription` va `grant_bonus_premium` yangi obuna
    yaratganda eskilarini nofaol qiladi). Shu sabab agar user'ning faol obunasi
    trial bo'lsa — u user'da BOSHQA faol obuna YO'Q. Trial bekor qilingach,
    Premium holati (`is_premium=False`, `premium_until=None`) tozalanadi.

    IDEMPOTENT: birinchi ishga tushishda tozalab qo'yadi; keyingi safarda hech
    qanday faol trial qolmaydi va funksiya darhol 0 qaytaradi. Har startup'da
    xavfsiz chaqirish mumkin.

    Qaytaradi: bekor qilingan obunalar soni (int).
    """
    from database.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        trial_subs = (await session.execute(
            select(Subscription).where(
                and_(
                    Subscription.source == "trial",
                    Subscription.is_active == True,  # noqa: E712
                )
            )
        )).scalars().all()

        if not trial_subs:
            return 0

        affected_user_ids: set[int] = set()
        for s in trial_subs:
            s.is_active = False
            affected_user_ids.add(s.user_id)

        # Har bir affected user'ning Premium holatini tozalaymiz.
        # Invariant tufayli ularda boshqa faol obuna yo'q — Premium OLIB TASHLANADI.
        # (Zamonaviyroq himoya uchun: boshqa `is_active=True` obuna bor-yo'qligini
        # tekshirmaymiz — bo'lsa ham premium_until endi trial ta'siridan tashqari
        # boshqa obunaga tegishli emas, chunki `grant_bonus_premium` uni mavjud
        # `premium_until` ustiga qo'shgan bo'lardi. Xavfsiz choraga: real boshqa
        # faol obuna bor bo'lsa uni tekshirib, premium_until'ni saqlaymiz.)
        for uid in affected_user_ids:
            # Boshqa faol obunalar bor-yo'qligini tekshiramiz (yuqoridagi commit'siz
            # — trial_subs.is_active hali eski qiymatda emas, session ichida
            # o'zgartirildi va _identity map orqali bir xil obyekt).
            other_active = (await session.execute(
                select(Subscription).where(
                    and_(
                        Subscription.user_id == uid,
                        Subscription.is_active == True,  # noqa: E712
                        Subscription.source != "trial",
                    )
                )
            )).scalars().first()
            user = await session.get(User, uid)
            if user is None:
                continue
            if other_active is not None:
                # Boshqa faol obuna bor — premium_until'ni saqlaymiz.
                # (Nazariy holat; invariant buni oldini oladi, ammo defence-in-depth.)
                continue
            user.is_premium = False
            user.premium_until = None

        await session.commit()
        logger.info(
            f"🧹 Trial cleanup: {len(trial_subs)} ta trial obuna bekor qilindi, "
            f"{len(affected_user_ids)} ta userdan Premium olib tashlandi"
        )
        return len(trial_subs)


# ─────────────────────────────────────────────────────────────
#  PROMOKOD
# ─────────────────────────────────────────────────────────────
@dataclass
class PromoResult:
    valid: bool
    reason: str = ""
    plan_override: Optional[str] = None
    bonus_days: int = 0
    is_free: bool = False          # True (`-`) = to'lovsiz avtomatik; False (`+`) = sotib olish + bonus
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
        is_free=bool(promo.is_free),
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
    is_free: bool = False,
) -> Optional[Promocode]:
    """Yangi promokod yaratadi (admin). Mavjud bo'lsa None qaytaradi.

    `is_free=True` (`-`) → to'lovsiz avtomatik `bonus_days` kun premium.
    `is_free=False` (`+`) → foydalanuvchi obuna sotib oladi, `bonus_days` bonus.
    """
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
        is_free=is_free,
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
