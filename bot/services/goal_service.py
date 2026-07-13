from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from bot.models.goal import Goal
from bot.models.user import User
from typing import Optional


# Yagona ruxsat etilgan maqsad turlari (backend hamma joyda shu to'plamdan foydalanadi).
# Eski `weekly` va `daily` DB'da saqlanib qolishi mumkin — o'qishda filtrlab tashlanadi,
# yozishda ruxsat berilmaydi.
ALLOWED_GOAL_TYPES: frozenset[str] = frozenset({"yearly", "monthly"})


class InvalidGoalTypeError(ValueError):
    """Ruxsat etilmagan goal_type kiritilganda ko'tariladi (400 → API'ga)."""


async def get_user_goals(session: AsyncSession, user: User) -> list[Goal]:
    """
    Foydalanuvchining barcha AMALDAGI maqsadlarini qaytaradi.

    Eslatma: DB'da eski `weekly` yoki `daily` yozuvlar bo'lishi mumkin (rollout'dan
    oldingi). Ularni foydalanuvchiga ko'rsatmaymiz — API darajasida filtrlaymiz,
    lekin DB dan o'chirmaymiz (ma'lumot yo'qolmasligi va rollback imkoniyati uchun).
    """
    result = await session.execute(
        select(Goal)
        .where(and_(
            Goal.user_id == user.id,
            Goal.goal_type.in_(ALLOWED_GOAL_TYPES),
        ))
        .order_by(Goal.created_at)
    )
    return result.scalars().all()


async def create_goal(
    session: AsyncSession,
    user: User,
    title: str,
    description: Optional[str],
    goal_type: str,
    period: str,
) -> Goal:
    """
    Yangi maqsad yaratadi. Faqat `yearly` va `monthly` turlari ruxsat etilgan.
    Boshqasi kelsa `InvalidGoalTypeError` ko'tariladi (route 400 qaytaradi).
    """
    gt = (goal_type or "").strip().lower()
    if gt not in ALLOWED_GOAL_TYPES:
        raise InvalidGoalTypeError(
            f"Maqsad turi noto'g'ri: {goal_type!r}. Faqat yillik yoki oylik maqsad yaratish mumkin."
        )
    goal = Goal(
        user_id=user.id,
        title=title,
        description=description,
        goal_type=gt,
        period=period,
        completed=False,
    )
    session.add(goal)
    await session.commit()
    await session.refresh(goal)
    return goal


async def update_goal(
    session: AsyncSession,
    goal_id: int,
    user_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    completed: Optional[bool] = None,
) -> Optional[Goal]:
    """
    Maqsadni yangilaydi. Eski (yashirilgan `weekly`/`daily`) yozuvlar ustida
    ham ishlaydi — chunki `update_goal` faqat matn/holatni o'zgartiradi,
    turini emas.
    """
    result = await session.execute(
        select(Goal).where(and_(Goal.id == goal_id, Goal.user_id == user_id))
    )
    goal = result.scalar_one_or_none()
    if not goal:
        return None
    if title is not None:
        goal.title = title
    if description is not None:
        goal.description = description
    if completed is not None:
        goal.completed = completed
    await session.commit()
    await session.refresh(goal)
    return goal


async def delete_goal(session: AsyncSession, goal_id: int, user_id: int) -> bool:
    result = await session.execute(
        select(Goal).where(and_(Goal.id == goal_id, Goal.user_id == user_id))
    )
    goal = result.scalar_one_or_none()
    if not goal:
        return False
    await session.delete(goal)
    await session.commit()
    return True
