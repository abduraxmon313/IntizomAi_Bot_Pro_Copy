"""
Odat (habit) servisi — CRUD + bugungi holat va joriy streak hisobi.

Odat rejalardan va maqsadlardan alohida: u har kuni takrorlanadigan amal.
Foydalanuvchi odatni har kuni "bajardim" deb belgilaydi (HabitLog), shu asosda
joriy ketma-ketlik (streak) va bugungi holat hisoblanadi.
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.habit import Habit, HabitLog
from bot.models.user import User
from datetime import datetime


def _today() -> date:
    return datetime.now(TIMEZONE).date()


async def get_user_habits(session: AsyncSession, user: User) -> list[Habit]:
    result = await session.execute(
        select(Habit)
        .where(and_(Habit.user_id == user.id, Habit.archived == False))  # noqa: E712
        .order_by(Habit.sort_order, Habit.created_at)
    )
    return result.scalars().all()


async def _log_dates_for(session: AsyncSession, habit_id: int) -> set[date]:
    """Odatning barcha bajarilgan kunlari (oxirgi ~120 kun bilan cheklab)."""
    since = _today() - timedelta(days=120)
    res = await session.execute(
        select(HabitLog.log_date).where(
            and_(HabitLog.habit_id == habit_id, HabitLog.log_date >= since)
        )
    )
    return {row[0] for row in res.all() if row[0] is not None}


def _current_streak(dates: set[date], today: date) -> int:
    """
    Joriy ketma-ketlik: bugundan (yoki bugun belgilanmagan bo'lsa kechadan)
    boshlab orqaga qarab nechta kun uzluksiz bajarilgan.
    """
    if not dates:
        return 0
    cur = today if today in dates else today - timedelta(days=1)
    streak = 0
    while cur in dates:
        streak += 1
        cur -= timedelta(days=1)
    return streak


async def habit_snapshot(session: AsyncSession, habit: Habit) -> dict:
    """Bitta odat uchun frontendga yuboriladigan ma'lumot."""
    today = _today()
    dates = await _log_dates_for(session, habit.id)
    return {
        "id": habit.id,
        "title": habit.title,
        "description": habit.description,
        "icon": habit.icon or "✅",
        "done_today": today in dates,
        "streak": _current_streak(dates, today),
        "total_done": len(dates),
        "created_at": habit.created_at.isoformat() if habit.created_at else None,
    }


async def list_habit_snapshots(session: AsyncSession, user: User) -> list[dict]:
    habits = await get_user_habits(session, user)
    return [await habit_snapshot(session, h) for h in habits]


async def create_habit(
    session: AsyncSession,
    user: User,
    title: str,
    description: Optional[str] = None,
    icon: Optional[str] = None,
) -> Habit:
    # Yangi odat ro'yxat oxiriga qo'shiladi
    res = await session.execute(
        select(func.coalesce(func.max(Habit.sort_order), 0)).where(Habit.user_id == user.id)
    )
    max_order = res.scalar() or 0
    habit = Habit(
        user_id=user.id,
        title=title.strip()[:200],
        description=(description or None),
        icon=(icon or "✅")[:8],
        sort_order=max_order + 1,
        archived=False,
    )
    session.add(habit)
    await session.commit()
    await session.refresh(habit)
    return habit


async def update_habit(
    session: AsyncSession,
    habit_id: int,
    user_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    icon: Optional[str] = None,
) -> Optional[Habit]:
    res = await session.execute(
        select(Habit).where(and_(Habit.id == habit_id, Habit.user_id == user_id))
    )
    habit = res.scalar_one_or_none()
    if not habit:
        return None
    if title is not None:
        habit.title = title.strip()[:200]
    if description is not None:
        habit.description = description or None
    if icon is not None:
        habit.icon = (icon or "✅")[:8]
    await session.commit()
    await session.refresh(habit)
    return habit


async def delete_habit(session: AsyncSession, habit_id: int, user_id: int) -> bool:
    res = await session.execute(
        select(Habit).where(and_(Habit.id == habit_id, Habit.user_id == user_id))
    )
    habit = res.scalar_one_or_none()
    if not habit:
        return False
    await session.delete(habit)
    await session.commit()
    return True


async def toggle_habit_log(
    session: AsyncSession,
    user: User,
    habit_id: int,
    on: Optional[bool] = None,
    target_date: Optional[date] = None,
) -> Optional[dict]:
    """
    Odatni belgilangan kun uchun "bajarildi/bekor" qiladi (toggle).
      • on=None  -> hozirgi holatni teskarisiga o'zgartiradi (toggle)
      • on=True  -> bajarildi qiladi (yozuv yaratadi)
      • on=False -> bekor qiladi (yozuvni o'chiradi)
    Yangilangan odat snapshot'ini qaytaradi (yoki odat topilmasa None).
    """
    res = await session.execute(
        select(Habit).where(and_(Habit.id == habit_id, Habit.user_id == user.id))
    )
    habit = res.scalar_one_or_none()
    if not habit:
        return None

    d = target_date or _today()
    res2 = await session.execute(
        select(HabitLog).where(
            and_(HabitLog.habit_id == habit_id, HabitLog.log_date == d)
        )
    )
    existing = res2.scalars().first()

    if on is None:
        on = existing is None  # toggle

    if on and existing is None:
        session.add(HabitLog(habit_id=habit_id, user_id=user.id, log_date=d))
        await session.commit()
    elif not on and existing is not None:
        await session.delete(existing)
        await session.commit()

    return await habit_snapshot(session, habit)
