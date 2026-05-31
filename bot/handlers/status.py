from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime

from bot.config import TIMEZONE
from bot.services.user_service import get_user_by_telegram_id
from bot.services.gamification_service import xp_progress, rank_for_level
from bot.services.score_service import get_today_score
from bot.models.plan import Plan, PlanStatus
from bot.models.achievement import Achievement

router = Router()


@router.message(F.text == "📊 Mening statusim")
async def my_status_handler(message: Message, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)

    if not user:
        await message.answer("Iltimos /start bosing.")
        return

    lvl, in_lvl, needed, pct = xp_progress(user.xp or 0)
    rank, emoji = rank_for_level(lvl)
    bar_filled = "▰" * round(pct / 10)
    bar_empty = "▱" * (10 - len(bar_filled))

    today = datetime.now(TIMEZONE).date()
    plans_result = await session.execute(
        select(Plan).where(
            and_(Plan.user_id == user.id, Plan.plan_date == today)
        )
    )
    plans = plans_result.scalars().all()

    done_today = len([p for p in plans if p.status == PlanStatus.done])
    total_today = len(plans)

    today_score = await get_today_score(session, user)

    all_done = await session.scalar(
        select(func.count(Plan.id)).where(
            and_(Plan.user_id == user.id, Plan.status == PlanStatus.done)
        )
    ) or 0

    ach_count = await session.scalar(
        select(func.count(Achievement.id)).where(Achievement.user_id == user.id)
    ) or 0

    text = (
        f"{emoji} <b>{user.full_name}</b>\n"
        f"📊 {rank} · {lvl}-daraja\n"
        f"<code>{bar_filled}{bar_empty}</code> {pct}%\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⭐️ Jami ball: <b>{user.total_score or 0}</b>\n"
        f"🔥 Streak: <b>{user.streak or 0} kun</b>"
        f"  (rekord {user.longest_streak or 0})\n"
        f"💎 Intizom kuchingiz: <b>{user.discipline_score or 50}/100</b>\n"
        f"✨ Mukammal kunlar: <b>{user.perfect_days or 0}</b>\n"
        f"🏅 Yutuqlar: <b>{ach_count} ta</b>\n"
        f"✅ Jami bajarilgan: <b>{all_done} ta</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📅 <b>Bugun:</b>\n"
        f"📋 Rejalar: <b>{total_today} ta</b>\n"
        f"✅ Bajarildi: <b>{done_today} ta</b>\n"
        f"⭐️ Bugungi ball: <b>{today_score:+d}</b>"
    )

    await message.answer(text, parse_mode="HTML")
