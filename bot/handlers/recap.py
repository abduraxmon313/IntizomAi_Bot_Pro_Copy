"""
Faza 3: Haftalik recap / oylik hisobot kartasi / AI insights.

Commands:
  /hafta   — haftalik hisobot
  /oy      — oylik hisobot kartasi (ulashsa bo'ladi)
Callbacks:
  ai_insights  — AI tahlil (14 kun)
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.user_service import get_user_by_telegram_id
from bot.services.recap_service import (
    build_weekly_recap, build_monthly_card, build_ai_insights,
)

router = Router()


@router.message(Command("hafta"))
async def weekly_command(message: Message, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("Iltimos /start bosing.")
        return
    text = await build_weekly_recap(session, user)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("oy"))
async def monthly_command(message: Message, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("Iltimos /start bosing.")
        return
    text = await build_monthly_card(session, user)
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "ai_insights")
async def ai_insights_cb(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("Iltimos /start bosing.", show_alert=True)
        return
    await callback.answer("Tahlil tayyorlanmoqda...")
    text = await build_ai_insights(session, user)
    try:
        from bot.services.analytics_service import track
        await track(callback.from_user.id, "ai_insights", user_id=user.id)
    except Exception:
        pass
    await callback.message.answer(text, parse_mode="HTML")
