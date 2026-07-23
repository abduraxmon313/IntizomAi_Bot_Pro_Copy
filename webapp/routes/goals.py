from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel

from database.db import AsyncSessionLocal
from webapp.security import resolve_telegram_id
from bot.services.premium_service import user_is_premium
from bot.services.user_service import get_user_by_telegram_id
from bot.services.goal_service import (
    ALLOWED_GOAL_TYPES,
    InvalidGoalTypeError,
    get_user_goals,
    create_goal,
    update_goal,
    delete_goal,
)

router = APIRouter()


# Mini App'da BARCHA maqsad mutation'lari (qo'shish/tahrirlash/o'chirish/belgilash)
# Premium talab qiladi. Bepul foydalanuvchi maqsadlarni KO'RIShI mumkin,
# ammo yaratish uchun Premium olishi kerak.
_PREMIUM_GOAL_MSG = (
    "Maqsad qo'shish va tahrirlash faqat Premium foydalanuvchilar uchun. "
    "💎 Premium oling va cheksiz maqsadlaringizni qo'shing!"
)


class GoalOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    goal_type: str
    period: str
    completed: bool
    created_at: str


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    goal_type: str
    period: str


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


def _is_period_past(goal_type: str, period: str) -> bool:
    """
    Maqsad davri o'tib ketganmi? (o'tgan davrni belgilab bo'lmaydi)
      • yearly:  period = "2025"      -> joriy yildan kichik bo'lsa o'tgan
      • monthly: period = "2025-05"   -> joriy oydan oldin bo'lsa o'tgan
    Format noto'g'ri/aniqlanmasa — ruxsat beramiz (False), foydalanuvchini bloklamaymiz.
    """
    from datetime import datetime
    from bot.config import TIMEZONE
    try:
        today = datetime.now(TIMEZONE).date()
        gt = (goal_type or "").lower()
        p = (period or "").strip()
        if not p:
            return False

        if gt == "yearly":
            return int(p) < today.year

        if gt == "monthly":
            y, m = p.split("-")[:2]
            y, m = int(y), int(m)
            return (y, m) < (today.year, today.month)

        return False
    except Exception:
        return False


def _is_period_future(goal_type: str, period: str) -> bool:
    """
    Maqsad davri hali BOSHLANMAGANmi? (kelajakdagi davrni "bajarildi" deb
    belgilab bo'lmaydi — vaqti kelmagan).
      • yearly:  "2027"       -> joriy yildan katta bo'lsa kelajak
      • monthly: "2026-07"    -> joriy oydan keyin bo'lsa kelajak
    Format noto'g'ri/aniqlanmasa — bloklamaymiz (False).
    """
    from datetime import datetime
    from bot.config import TIMEZONE
    try:
        today = datetime.now(TIMEZONE).date()
        gt = (goal_type or "").lower()
        p = (period or "").strip()
        if not p:
            return False

        if gt == "yearly":
            return int(p) > today.year

        if gt == "monthly":
            y, m = p.split("-")[:2]
            y, m = int(y), int(m)
            return (y, m) > (today.year, today.month)

        return False
    except Exception:
        return False


@router.get("/goals", response_model=list[GoalOut])
async def get_goals(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    goals = await get_user_goals(session, user)
    return [
        GoalOut(
            id=g.id,
            title=g.title,
            description=g.description,
            goal_type=g.goal_type,
            period=g.period,
            completed=g.completed,
            created_at=g.created_at.isoformat(),
        )
        for g in goals
    ]


@router.post("/goals", response_model=GoalOut)
async def add_goal(
    body: GoalCreate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # PREMIUM GATE: Maqsad yaratish faqat Premium foydalanuvchilar uchun.
    if not user_is_premium(user):
        raise HTTPException(status_code=402, detail=_PREMIUM_GOAL_MSG)

    # Faqat yillik va oylik maqsadlar ruxsat etilgan.
    # Eski kunlik/haftalik turlari olib tashlandi — takroriy niyatlar Habits'ga,
    # bir martalik ishlar Plans'ga ko'chirilgan.
    if (body.goal_type or "").strip().lower() not in ALLOWED_GOAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Faqat yillik yoki oylik maqsad yaratish mumkin. "
                "Kunlik takroriy niyatni Odat (Habit), bir martalik ishni Reja (Plan) sifatida qo'shing."
            ),
        )
    try:
        goal = await create_goal(
            session, user, body.title, body.description, body.goal_type, body.period
        )
    except InvalidGoalTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return GoalOut(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        goal_type=goal.goal_type,
        period=goal.period,
        completed=goal.completed,
        created_at=goal.created_at.isoformat(),
    )


@router.put("/goals/{goal_id}", response_model=GoalOut)
async def edit_goal(
    goal_id: int,
    body: GoalUpdate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # PREMIUM GATE: Maqsad tahrirlash/belgilash faqat Premium foydalanuvchilar uchun.
    if not user_is_premium(user):
        raise HTTPException(status_code=402, detail=_PREMIUM_GOAL_MSG)

    # Hali boshlanmagan (kelajakdagi) davr maqsadini belgilab bo'lmaydi.
    # O'tib ketgan davr maqsadlarini esa belgilash MUMKIN.
    if body.completed:
        from bot.models.goal import Goal
        from sqlalchemy import and_, select
        res = await session.execute(
            select(Goal).where(and_(Goal.id == goal_id, Goal.user_id == user.id))
        )
        g0 = res.scalar_one_or_none()
        if g0 and _is_period_future(g0.goal_type, g0.period):
            raise HTTPException(
                status_code=409,
                detail="Bu maqsad davri hali boshlanmagan (vaqti kelmagan).",
            )

    goal = await update_goal(
        session, goal_id, user.id, body.title, body.description, body.completed
    )
    if not goal:
        raise HTTPException(status_code=404, detail="Maqsad topilmadi")
    return GoalOut(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        goal_type=goal.goal_type,
        period=goal.period,
        completed=goal.completed,
        created_at=goal.created_at.isoformat(),
    )


@router.delete("/goals/{goal_id}")
async def remove_goal(
    goal_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # PREMIUM GATE: Maqsadni o'chirish faqat Premium foydalanuvchilar uchun.
    if not user_is_premium(user):
        raise HTTPException(status_code=402, detail=_PREMIUM_GOAL_MSG)

    ok = await delete_goal(session, goal_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Maqsad topilmadi")
    return {"ok": True}
