from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel

from database.db import AsyncSessionLocal
from webapp.security import resolve_telegram_id
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


class HabitOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    icon: str = "✅"
    done_today: bool = False
    streak: int = 0
    total_done: int = 0
    created_at: Optional[str] = None


class HabitCreate(BaseModel):
    title: str
    description: Optional[str] = None
    icon: Optional[str] = None


class HabitUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None


class HabitToggle(BaseModel):
    done: Optional[bool] = None  # None -> toggle


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
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="Sarlavha bo'sh bo'lishi mumkin emas")
    habit = await create_habit(session, user, body.title, body.description, body.icon)
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
    habit = await update_habit(
        session, habit_id, user.id, body.title, body.description, body.icon
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
    snap = await toggle_habit_log(session, user, habit_id, on=body.done)
    if snap is None:
        raise HTTPException(status_code=404, detail="Odat topilmadi")
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
    ok = await delete_habit(session, habit_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Odat topilmadi")
    return {"ok": True}
