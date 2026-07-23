"""
WebApp konfiguratsiyasi (global feature-flags).

Bu endpoint klientga (Mini App) admin panelidan boshqariladigan global
bayroqlarni beradi — masalan "Guruh ruxsatlar menyusi" yoqilganmi. Frontend
`#friendsPermsBtn` va shunga bog'liq UI elementlarini shu qiymatga qarab
yashiradi.

Endpoint jamoat uchun ochiq (autentifikatsiya `X-Telegram-Init-Data` orqali)
va faqat bir nechta bool bayroqni qaytaradi — hech qanday shaxsiy ma'lumot yo'q.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.app_settings import is_group_perms_menu_enabled
from database.db import AsyncSessionLocal
from webapp.security import resolve_telegram_id

router = APIRouter()


class AppConfig(BaseModel):
    # `True` (default) — Do'stlar sahifasida "🛡 Ruxsatlar" tugmasi ko'rinadi
    # va foydalanuvchilar o'z ma'lumotlarini kim ko'rishini boshqaradi.
    # `False` — admin panelidan o'chirilgan; tugma yashiriladi va guruh
    # a'zolari bir-birining reja va odatlarini avtomatik ko'radi.
    group_perms_menu_enabled: bool


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/config", response_model=AppConfig)
async def get_app_config(
    # Autentifikatsiya majburiy — bu bayroqlar shaxsiy bo'lmasa ham,
    # noma'lum ("anonim") mijozlarga API'ni ochib qo'ymaymiz.
    telegram_id: int = Depends(resolve_telegram_id),  # noqa: ARG001
    session: AsyncSession = Depends(get_session),
):
    return AppConfig(
        group_perms_menu_enabled=await is_group_perms_menu_enabled(session),
    )
