from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import ADMIN_ID
from database.db import AsyncSessionLocal
from webapp.security import resolve_telegram_id
from bot.services.analytics_service import log_event, get_funnel
from bot.services.user_service import get_user_by_telegram_id

router = APIRouter()

# Klientdan qabul qilinadigan (ishonchli) hodisalar — abuse'ni cheklash uchun.
ALLOWED_CLIENT_EVENTS = {
    "miniapp_open", "paywall_view", "onboarding_done", "share_clicked",
}


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


class EventIn(BaseModel):
    event: str
    props: Optional[str] = None


@router.post("/event")
async def post_event(
    body: EventIn,
    telegram_id: int = Depends(resolve_telegram_id),
):
    ev = (body.event or "").strip()
    if ev not in ALLOWED_CLIENT_EVENTS:
        return {"ok": False}
    await log_event(ev, telegram_id=telegram_id, props=body.props)
    return {"ok": True}


@router.get("/admin/funnel")
async def admin_funnel(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    if not ADMIN_ID or telegram_id != ADMIN_ID:
        raise HTTPException(status_code=403, detail="Faqat admin uchun.")
    return await get_funnel(session)
