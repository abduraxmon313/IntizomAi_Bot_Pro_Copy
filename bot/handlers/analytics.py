"""
Admin uchun funnel/retention statistikasi — /funnel buyrug'i.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.admin_service import is_admin
from bot.services.analytics_service import get_funnel

router = Router()


@router.message(Command("funnel"))
async def funnel_handler(message: Message, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    f = await get_funnel(session)
    e = f.get("events_7d", {})

    text = (
        "📊 <b>Funnel & Retention</b>\n\n"
        "👥 <b>Foydalanuvchilar</b>\n"
        f"• Jami: <b>{f['total_users']}</b>\n"
        f"• Yangi (7 kun): <b>{f['signups_7d']}</b> · (30 kun): <b>{f['signups_30d']}</b>\n\n"
        "⚡️ <b>Aktivatsiya</b>\n"
        f"• Kamida 1 reja/odat: <b>{f['activated']}</b> ({f['activation_rate']}%)\n\n"
        "🔁 <b>Retention (faol)</b>\n"
        f"• 1 kun: <b>{f['active_1']}</b> · 7 kun: <b>{f['active_7']}</b> · 30 kun: <b>{f['active_30']}</b>\n\n"
        "💎 <b>Monetizatsiya</b>\n"
        f"• Premium (faol): <b>{f['premium_active']}</b>\n"
        f"• Trial berilgan: <b>{f['trial_granted']}</b>\n"
        f"• Pullik obuna: <b>{f['paid_users']}</b> ({f['paid_rate']}%)\n\n"
        "📈 <b>Hodisalar (7 kun)</b>\n"
        f"• Reja: <b>{e.get('plan_created', 0)}</b> · Odat: <b>{e.get('habit_created', 0)}</b> · "
        f"Maqsad: <b>{e.get('goal_created', 0)}</b>\n"
        f"• AI suhbat: <b>{e.get('ai_chat', 0)}</b>\n"
        f"• Mini App ochildi: <b>{e.get('miniapp_open', 0)}</b> · Paywall: <b>{e.get('paywall_view', 0)}</b>\n"
        f"• Checkout: <b>{e.get('checkout_started', 0)}</b> · Premium faollashdi: <b>{e.get('premium_activated', 0)}</b>\n"
        f"• Onboarding tugatildi: <b>{e.get('onboarding_done', 0)}</b>"
    )
    await message.answer(text, parse_mode="HTML")
