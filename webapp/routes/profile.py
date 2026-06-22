from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import AsyncSessionLocal
from webapp.security import resolve_telegram_id
from bot.services.user_service import get_user_by_telegram_id

router = APIRouter()


class ProfileOut(BaseModel):
    telegram_id: int
    full_name: str
    username: Optional[str] = None


class ProfileUpdate(BaseModel):
    full_name: str


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


def _effective_name(user) -> str:
    return (user.display_name or user.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi"


@router.get("/profile", response_model=ProfileOut)
async def get_profile(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    return ProfileOut(
        telegram_id=user.telegram_id,
        full_name=_effective_name(user),
        username=user.username,
    )


@router.put("/profile", response_model=ProfileOut)
async def update_profile(
    body: ProfileUpdate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    name = (body.full_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Ism bo'sh bo'lishi mumkin emas")
    if len(name) > 60:
        name = name[:60]

    # display_name — Telegram sinxronizatsiyasi o'chirib yubormaydigan maxsus ism.
    user.display_name = name
    user.last_active = datetime.utcnow()
    await session.commit()
    await session.refresh(user)

    return ProfileOut(
        telegram_id=user.telegram_id,
        full_name=_effective_name(user),
        username=user.username,
    )
