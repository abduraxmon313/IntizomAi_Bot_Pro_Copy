from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel

from database.db import AsyncSessionLocal
from webapp.security import resolve_telegram_id
from bot.services.premium_service import user_is_premium
from bot.services.user_service import get_user_by_telegram_id
from bot.services.habit_service import (
    list_habit_snapshots,
    create_habit,
    update_habit,
    delete_habit,
    toggle_habit_log,
    habit_snapshot,
)

router = APIRouter()


# Mini App'da BARCHA odat mutation'lari (qo'shish/tahrirlash/o'chirish/toggle)
# Premium talab qiladi. Bepul foydalanuvchi odatlarini ko'ra oladi ammo
# ular ustida ish qilolmaydi.
_PREMIUM_HABIT_MSG = (
    "Odat qo'shish va belgilash faqat Premium foydalanuvchilar uchun. "
    "💎 Premium oling va cheksiz odatlaringizni kuzating!"
)


class HabitOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    icon: str = "✅"
    reminder_time: Optional[str] = None
    frequency: str = "daily"
    weekdays: list[int] = []
    duration_type: str = "permanent"
    target_days: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    days_left: Optional[int] = None
    finished: bool = False
    due_today: bool = True
    done_today: bool = False
    streak: int = 0
    total_done: int = 0
    log_dates: list[str] = []
    created_at: Optional[str] = None


class HabitCreate(BaseModel):
    title: str
    description: Optional[str] = None
    icon: Optional[str] = None
    reminder_time: Optional[str] = None       # "HH:MM" yoki bo'sh
    frequency: Optional[str] = None          # "daily" | "weekly"
    weekdays: Optional[list[int]] = None      # 0=Mon .. 6=Sun
    duration_type: Optional[str] = None       # "permanent" | "days"
    target_days: Optional[int] = None


class HabitUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    reminder_time: Optional[str] = None
    clear_reminder: Optional[bool] = None
    frequency: Optional[str] = None
    weekdays: Optional[list[int]] = None
    duration_type: Optional[str] = None
    target_days: Optional[int] = None


class HabitToggle(BaseModel):
    done: Optional[bool] = None  # None -> toggle
    date: Optional[str] = None   # "YYYY-MM-DD" — bo'lmasa bugun


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/habits", response_model=list[HabitOut])
async def get_habits(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    return await list_habit_snapshots(session, user)


@router.post("/habits", response_model=HabitOut)
async def add_habit(
    body: HabitCreate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # PREMIUM GATE: Odat yaratish faqat Premium foydalanuvchilar uchun.
    if not user_is_premium(user):
        raise HTTPException(status_code=402, detail=_PREMIUM_HABIT_MSG)

    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="Sarlavha bo'sh bo'lishi mumkin emas")
    habit = await create_habit(
        session, user, body.title, body.description, body.icon,
        frequency=body.frequency, weekdays=body.weekdays,
        duration_type=body.duration_type, target_days=body.target_days,
        reminder_time=body.reminder_time,
    )
    return await habit_snapshot(session, habit)


@router.put("/habits/{habit_id}", response_model=HabitOut)
async def edit_habit(
    habit_id: int,
    body: HabitUpdate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # PREMIUM GATE: Odat tahrirlash faqat Premium foydalanuvchilar uchun.
    if not user_is_premium(user):
        raise HTTPException(status_code=402, detail=_PREMIUM_HABIT_MSG)

    habit = await update_habit(
        session, habit_id, user.id, body.title, body.description, body.icon,
        frequency=body.frequency, weekdays=body.weekdays,
        duration_type=body.duration_type, target_days=body.target_days,
        reminder_time=body.reminder_time, clear_reminder=bool(body.clear_reminder),
    )
    if not habit:
        raise HTTPException(status_code=404, detail="Odat topilmadi")
    return await habit_snapshot(session, habit)


@router.post("/habits/{habit_id}/toggle", response_model=HabitOut)
async def toggle_habit(
    habit_id: int,
    body: HabitToggle,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # PREMIUM GATE: Odatni belgilash faqat Premium foydalanuvchilar uchun.
    if not user_is_premium(user):
        raise HTTPException(status_code=402, detail=_PREMIUM_HABIT_MSG)

    target_date = None
    if body.date:
        from datetime import date as _date
        try:
            target_date = _date.fromisoformat(body.date)
        except Exception:
            raise HTTPException(status_code=400, detail="Sana formati noto'g'ri.")
        from datetime import datetime as _dt
        from bot.config import TIMEZONE
        if target_date > _dt.now(TIMEZONE).date():
            raise HTTPException(status_code=409, detail="Kelajak kunni belgilab bo'lmaydi.")
    snap = await toggle_habit_log(session, user, habit_id, on=body.done, target_date=target_date)
    if snap is None:
        raise HTTPException(status_code=404, detail="Odat topilmadi")

    # Odat bajarilgan (done_today=True) bo'lsa — referral aktivatsiyasi.
    # (Trial olib tashlangan; referral bonusi idempotent.)
    if snap.get("done_today"):
        try:
            from bot.services.activation import on_first_completion
            await on_first_completion(session, user, bot=None)
        except Exception:
            pass
    return snap


@router.delete("/habits/{habit_id}")
async def remove_habit(
    habit_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    # PREMIUM GATE: Odatni o'chirish faqat Premium foydalanuvchilar uchun.
    if not user_is_premium(user):
        raise HTTPException(status_code=402, detail=_PREMIUM_HABIT_MSG)

    ok = await delete_habit(session, habit_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Odat topilmadi")
    return {"ok": True}
