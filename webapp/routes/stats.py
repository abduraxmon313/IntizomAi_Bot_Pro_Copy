"""
Gamification + coach + quest API for the WebApp.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from webapp.security import resolve_telegram_id
from bot.models.checkin import DailyCheckin
from bot.models.plan import Plan, PlanStatus
from bot.services.coach_service import daily_quest, smart_coach_message
from bot.services.gamification_service import build_user_snapshot
from bot.services.user_service import get_user_by_telegram_id
from database.db import AsyncSessionLocal

router = APIRouter()


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


# ─────────────────────────────────────────────────────────────
class CheckinIn(BaseModel):
    mood: Optional[str] = None
    energy: Optional[int] = None


class CheckinOut(BaseModel):
    checkin_date: str
    mood: Optional[str] = None
    energy: Optional[int] = None


# ─────────────────────────────────────────────────────────────
@router.get("/stats")
async def get_stats(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return await build_user_snapshot(session, user)


@router.get("/coach")
async def get_coach(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return await smart_coach_message(session, user)


@router.get("/quest")
async def get_quest(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return await daily_quest(session, user)


# ─────────────────────────────────────────────────────────────
@router.get("/checkin", response_model=Optional[CheckinOut])
async def get_today_checkin(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    today = datetime.now(TIMEZONE).date()
    res = await session.execute(
        select(DailyCheckin).where(
            and_(
                DailyCheckin.user_id == user.id,
                DailyCheckin.checkin_date == today,
            )
        ).order_by(DailyCheckin.id)
    )
    # scalar_one_or_none() o'rniga first() — agar takror yozuvlar bo'lsa
    # MultipleResultsFound (500) bermasligi uchun.
    row = res.scalars().first()
    if not row:
        return None
    return CheckinOut(
        checkin_date=str(row.checkin_date),
        mood=row.mood, energy=row.energy,
    )


@router.post("/checkin", response_model=CheckinOut)
async def save_checkin(
    body: CheckinIn,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    today = datetime.now(TIMEZONE).date()

    res = await session.execute(
        select(DailyCheckin).where(
            and_(
                DailyCheckin.user_id == user.id,
                DailyCheckin.checkin_date == today,
            )
        ).order_by(DailyCheckin.id)
    )
    # Bir kunga bir nechta yozuv bo'lib qolgan bo'lsa (avvalgi parallel so'rovlar
    # natijasida) — birinchisini olib, qolganini tozalaymiz. Bu MultipleResultsFound
    # (500 "saqlashda xato") muammosini bartaraf etadi va o'zini-o'zi tuzatadi.
    rows = res.scalars().all()
    row = rows[0] if rows else None
    for extra in rows[1:]:
        await session.delete(extra)

    if row is None:
        row = DailyCheckin(user_id=user.id, checkin_date=today)
        session.add(row)

    if body.mood is not None:
        row.mood = body.mood
    if body.energy is not None:
        row.energy = body.energy

    await session.commit()
    await session.refresh(row)

    return CheckinOut(
        checkin_date=str(row.checkin_date),
        mood=row.mood, energy=row.energy,
    )



# ─────────────────────────────────────────────────────────────
#  REJALAR TARIXI — har kun uchun bajarilgan/jami (eng yangi tepada)
# ─────────────────────────────────────────────────────────────
@router.get("/history")
async def get_history(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Foydalanuvchining BUTUN reja tarixi — kun bo'yicha guruhlangan:
    har bir kun uchun jami reja soni va bajarilgan rejalar soni.
    Eng yangi kun birinchi (desc). Faqat reja bo'lgan kunlar qaytariladi.
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")

    done_expr = func.sum(
        case((Plan.status == PlanStatus.done, 1), else_=0)
    )
    res = await session.execute(
        select(Plan.plan_date, func.count(Plan.id), done_expr)
        .where(Plan.user_id == user.id)
        .group_by(Plan.plan_date)
        .order_by(Plan.plan_date.desc())
    )
    days = []
    for plan_date, total, done in res.all():
        if plan_date is None:
            continue
        days.append({
            "date": str(plan_date),
            "total": int(total or 0),
            "done": int(done or 0),
        })
    return {"days": days}
