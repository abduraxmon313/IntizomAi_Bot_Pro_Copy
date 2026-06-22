from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel

from database.db import AsyncSessionLocal
from webapp.security import resolve_telegram_id
from bot.services.user_service import get_user_by_telegram_id
from bot.services.goal_service import (
    get_user_goals,
    create_goal,
    update_goal,
    delete_goal,
)

router = APIRouter()


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
      • yearly:  period = "2025"           -> joriy yildan kichik bo'lsa o'tgan
      • monthly: period = "2025-05"        -> joriy oydan oldin bo'lsa o'tgan
      • weekly:  period = "2025-W22"        -> joriy haftadan oldin bo'lsa o'tgan
      • daily:   period = "2025-05-29"      -> bugundan oldin bo'lsa o'tgan
    Format noto'g'ri/aniqlanmasa — ruxsat beramiz (False), foydalanuvchini bloklamaymiz.
    """
    from datetime import datetime, date
    from bot.config import TIMEZONE
    try:
        now = datetime.now(TIMEZONE)
        today = now.date()
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

        if gt == "weekly":
            # ISO hafta: "YYYY-Www"
            y_str, w_str = p.upper().split("-W")
            y, w = int(y_str), int(w_str)
            iso = today.isocalendar()
            return (y, w) < (iso[0], iso[1])

        if gt == "daily":
            d = date.fromisoformat(p)
            return d < today

        return False
    except Exception:
        return False


def _is_period_future(goal_type: str, period: str) -> bool:
    """
    Maqsad davri hali BOSHLANMAGANmi? (kelajakdagi davrni "bajarildi" deb
    belgilab bo'lmaydi — vaqti kelmagan).
      • yearly:  "2027"          -> joriy yildan katta bo'lsa kelajak
      • monthly: "2026-07"       -> joriy oydan keyin bo'lsa kelajak
      • weekly:  "2026-W30"      -> joriy haftadan keyin bo'lsa kelajak
      • daily:   "2026-06-10"    -> bugundan keyin bo'lsa kelajak
    Format noto'g'ri/aniqlanmasa — bloklamaymiz (False).
    """
    from datetime import datetime, date
    from bot.config import TIMEZONE
    try:
        now = datetime.now(TIMEZONE)
        today = now.date()
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

        if gt == "weekly":
            y_str, w_str = p.upper().split("-W")
            y, w = int(y_str), int(w_str)
            iso = today.isocalendar()
            return (y, w) > (iso[0], iso[1])

        if gt == "daily":
            d = date.fromisoformat(p)
            return d > today

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
    # Free-tier maqsad limiti (premium — cheksiz)
    from bot.services.premium_service import check_goal_limit
    lim = await check_goal_limit(session, user, adding=1)
    if not lim.allowed:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Bepul maqsad limiti tugadi ({lim.used}/{lim.limit}). "
                "Cheksiz maqsadlar uchun Premium oling."
            ),
        )
    goal = await create_goal(
        session, user, body.title, body.description, body.goal_type, body.period
    )
    try:
        from bot.services.analytics_service import log_event
        await log_event("goal_created", telegram_id=user.telegram_id, user_id=user.id)
    except Exception:
        pass
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
    ok = await delete_goal(session, goal_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Maqsad topilmadi")
    return {"ok": True}
