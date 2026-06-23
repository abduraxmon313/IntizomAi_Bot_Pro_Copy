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
    notifications_enabled: bool = True
    referral_link: Optional[str] = None
    referral_count: int = 0
    photo_url: Optional[str] = None


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    notifications_enabled: Optional[bool] = None
    photo_url: Optional[str] = None


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


def _effective_name(user) -> str:
    return (user.display_name or user.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi"


def _profile_payload(user) -> ProfileOut:
    from bot.config import BOT_USERNAME
    from bot.services.referral_service import build_referral_link
    return ProfileOut(
        telegram_id=user.telegram_id,
        full_name=_effective_name(user),
        username=user.username,
        notifications_enabled=bool(user.notifications_enabled),
        referral_link=build_referral_link(BOT_USERNAME, user.telegram_id),
        referral_count=int(user.referral_count or 0),
        photo_url=user.photo_url,
    )


@router.get("/profile", response_model=ProfileOut)
async def get_profile(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    return _profile_payload(user)


@router.put("/profile", response_model=ProfileOut)
async def update_profile(
    body: ProfileUpdate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    if body.full_name is not None:
        name = (body.full_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Ism bo'sh bo'lishi mumkin emas")
        if len(name) > 60:
            name = name[:60]
        # display_name — Telegram sinxronizatsiyasi o'chirib yubormaydigan maxsus ism.
        user.display_name = name

    if body.notifications_enabled is not None:
        user.notifications_enabled = bool(body.notifications_enabled)

    if body.photo_url is not None:
        pu = body.photo_url.strip()
        user.photo_url = pu[:512] if pu else None

    user.last_active = datetime.utcnow()
    await session.commit()
    await session.refresh(user)

    return _profile_payload(user)
