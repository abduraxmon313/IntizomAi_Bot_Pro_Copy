from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from bot.config import TIMEZONE
from bot.services.user_service import get_user_by_telegram_id
from bot.services.plan_service import get_today_plans
from bot.services.admin_service import get_user_status
from bot.models.plan import Plan, PlanStatus
from bot.keyboards.plan_keys import back_to_home_keyboard

router = Router()


async def build_report_text(session, user) -> str:
    plans = await get_today_plans(session, user)

    done = [p for p in plans if p.status == PlanStatus.done]
    failed = [p for p in plans if p.status == PlanStatus.failed]
    pending = [p for p in plans if p.status == PlanStatus.pending]

    # Bugungi ball (Tashkent kuni): bajarilganlardan ball, bajarilmaganlardan -3.
    # ScoreLog yig'indisi qayta-belgilashlardan shishib ketardi — shuning uchun
    # bugungi rejalardan to'g'ridan-to'g'ri hisoblaymiz (aniq qiymat).
    today_score = sum(p.score_value or 0 for p in done) - 3 * len(failed)
    status = get_user_status(user.total_score, user.streak)

    today_str = datetime.now(TIMEZONE).strftime("%d.%m.%Y")

    text = f"📊 <b>Bugungi hisobot</b>\n"
    text += f"📅 {today_str}\n\n"

    if done:
        text += f"✅ <b>Bajarildi ({len(done)} ta):</b>\n"
        for p in done:
            text += f"  • {p.title} <i>(+{p.score_value}⭐️)</i>\n"
        text += "\n"

    if failed:
        text += f"❌ <b>Bajarilmadi ({len(failed)} ta):</b>\n"
        for p in failed:
            text += f"  • {p.title} <i>(-3⭐️)</i>\n"
        text += "\n"

    if pending:
        text += f"⏳ <b>Kutilmoqda ({len(pending)} ta):</b>\n"
        for p in pending:
            time_str = p.scheduled_time if p.scheduled_time else "vaqtsiz"
            text += f"  • {p.title} <i>({time_str})</i>\n"
        text += "\n"

    if not plans:
        text += "📭 Bugun hech qanday reja yo'q.\n\n"

    text += f"━━━━━━━━━━━━━━━\n"
    text += f"⭐️ Bugungi ball: <b>{today_score:+d}</b>\n"
    text += f"🏆 Umumiy ball: <b>{user.total_score}</b>\n"
    text += f"🔥 Streak: <b>{user.streak} kun</b>\n"
    text += f"📊 Status: <b>{status}</b>"

    return text


# Reply keyboard tugmasi va /hisobot buyrug'i — faqat DM'da (guruh uchun
# alohida `📊 Umumiy hisobot` handleri chat_events.py'da, u digest yuboradi).
# Decorator stacking: bir funksiya ikkala trigger ostida ham ishlaydi.
@router.message(Command("hisobot"), F.chat.type == ChatType.PRIVATE)
@router.message(F.text == "📈 Hisobot", F.chat.type == ChatType.PRIVATE)
async def report_message(message: Message, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)

    if not user:
        await message.answer("Iltimos /start bosing.")
        return

    text = await build_report_text(session, user)
    await message.answer(text, parse_mode="HTML")


# Inline callback
@router.callback_query(F.data == "report")
async def report_callback(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)

    if not user:
        await callback.answer("Xatolik!", show_alert=True)
        return

    text = await build_report_text(session, user)

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_to_home_keyboard()
    )
    await callback.answer()
