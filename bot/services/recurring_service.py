"""
Takrorlanuvchi rejalar (recurring habits) — Faza 2.

MUHIM: timezone'ga TEGMAYMIZ. Eski string vaqt modeli ("HH:MM") saqlanadi.
Takrorlanish "shablon" (is_template=True, ko'rinmas) Plan yozuvi orqali ishlaydi:
har kuni 00:10 da scheduler bugungi sanaga mos shablonlardan haqiqiy (ko'rinadigan)
reja nusxalarini yaratadi. Shu tariqa "har kuni 6 da turish" rejasi qo'lda
nusxalanmaydi — avtomatik paydo bo'ladi.

recurrence qiymatlari:
  • daily     — har kuni
  • weekdays  — Du–Ju (0..4)
  • weekly    — recurrence_days dagi kunlar ("0,2,4" = Du,Cho,Ju; Du=0)
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.plan import Plan, PlanStatus
from bot.models.user import User

logger = logging.getLogger(__name__)

VALID_RECURRENCE = {"none", "daily", "weekdays", "weekly"}

# Shablon (template) Plan yozuvi uchun "sun'iy" o'tmish sanasi. Shu tufayli
# u HECH QANDAY "bugungi rejalar" / 30-kunlik discipline so'roviga tushmaydi
# (qo'shimcha is_template filtri bo'lmasa ham xavfsiz).
TEMPLATE_DATE = date(2000, 1, 1)


def _today() -> date:
    return datetime.now(TIMEZONE).date()


def parse_days(spec: str | None) -> list[int]:
    """'0,2,4' -> [0,2,4]. Noto'g'ri qiymatlar tashlanadi."""
    if not spec:
        return []
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if part.isdigit():
            d = int(part)
            if 0 <= d <= 6:
                out.append(d)
    return sorted(set(out))


def occurs_on(plan: Plan, day: date) -> bool:
    """Shablon reja `day` kuni uchun nusxa yaratishi kerakmi?"""
    rec = (plan.recurrence or "none")
    if rec == "daily":
        return True
    if rec == "weekdays":
        return day.weekday() < 5  # Du..Ju
    if rec == "weekly":
        return day.weekday() in parse_days(plan.recurrence_days)
    return False


async def create_recurring_template(
    session: AsyncSession,
    user: User,
    title: str,
    scheduled_time: str | None,
    recurrence: str,
    recurrence_days: str | None = None,
    score_value: int = 5,
    category: str | None = None,
) -> Plan:
    """Takrorlanuvchi shablon yaratadi va darhol bugungi nusxasini ham qo'shadi."""
    if recurrence not in VALID_RECURRENCE or recurrence == "none":
        recurrence = "daily"

    template = Plan(
        user_id=user.id,
        title=title,
        scheduled_time=scheduled_time,
        plan_date=TEMPLATE_DATE,
        score_value=score_value,
        category=category,
        recurrence=recurrence,
        recurrence_days=recurrence_days,
        is_template=True,
        status=PlanStatus.pending,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)

    # Bugun uchun amal qilsa — darhol ko'rinadigan nusxa yaratamiz.
    today = _today()
    if occurs_on(template, today):
        await _materialize_one(session, template, today)

    return template


async def list_templates(session: AsyncSession, user: User) -> list[Plan]:
    res = await session.execute(
        select(Plan).where(
            and_(Plan.user_id == user.id, Plan.is_template == True)  # noqa: E712
        ).order_by(Plan.scheduled_time)
    )
    return res.scalars().all()


async def stop_recurrence(session: AsyncSession, template_id: int, user_id: int) -> bool:
    """Takrorlanishni to'xtatadi (shablonni o'chiradi). Yaratilgan nusxalar qoladi."""
    res = await session.execute(
        select(Plan).where(
            and_(Plan.id == template_id, Plan.user_id == user_id,
                 Plan.is_template == True)  # noqa: E712
        )
    )
    tpl = res.scalar_one_or_none()
    if not tpl:
        return False
    await session.delete(tpl)
    await session.commit()
    return True


async def _materialize_one(session: AsyncSession, template: Plan, day: date) -> Plan | None:
    """Bitta shablondan `day` uchun nusxa yaratadi (agar hali yo'q bo'lsa)."""
    exists = await session.scalar(
        select(Plan.id).where(
            and_(
                Plan.user_id == template.user_id,
                Plan.recurrence_parent_id == template.id,
                Plan.plan_date == day,
            )
        ).limit(1)
    )
    if exists:
        return None
    clone = Plan(
        user_id=template.user_id,
        title=template.title,
        description=template.description,
        scheduled_time=template.scheduled_time,
        plan_date=day,
        score_value=template.score_value or 5,
        category=template.category,
        tags=template.tags,
        recurrence="none",
        recurrence_parent_id=template.id,
        is_template=False,
        status=PlanStatus.pending,
    )
    session.add(clone)
    await session.commit()
    await session.refresh(clone)
    return clone


async def materialize_for_day(day: date | None = None) -> int:
    """
    BARCHA foydalanuvchilarning takrorlanuvchi shablonlaridan `day` (default bugun)
    uchun nusxalar yaratadi. Scheduler har kuni 00:10 da chaqiradi.
    Qaytaradi: yaratilgan nusxalar soni.
    """
    from database.db import AsyncSessionLocal
    target = day or _today()
    created = 0
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(Plan).where(Plan.is_template == True)  # noqa: E712
        )
        templates = res.scalars().all()
        for tpl in templates:
            try:
                if occurs_on(tpl, target):
                    clone = await _materialize_one(session, tpl, target)
                    if clone is not None:
                        created += 1
            except Exception as e:
                logger.debug(f"materialize skip tpl={tpl.id}: {e}")
    logger.info(f"♻️ Recurring: {created} ta nusxa yaratildi ({target})")
    return created
