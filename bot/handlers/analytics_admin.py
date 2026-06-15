"""
Admin analitika — /stats buyrug'i.

Faqat adminlar uchun: retention (D1/D7), activation funnel va DAU ni ko'rsatadi.
Avval kodda hech qanday metrika ko'rinmasdi — bu "ko'rlik"ni yopadi.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.admin_service import is_admin
from bot.services.analytics_service import build_admin_analytics_text

router = Router()


@router.message(Command("stats"))
async def stats_command(message: Message, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return
    try:
        text = await build_admin_analytics_text(session)
    except Exception as e:
        text = f"⚠️ Analitikani hisoblashda xato: {e}"
    await message.answer(text, parse_mode="HTML")
