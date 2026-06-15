"""
Faza 2: Qidiruv — rejalar va maqsadlar bo'yicha.

/qidir buyrug'i yoki "🔎 Qidirish" → matn so'raydi → natijalarni ko'rsatadi.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.plan import PlanStatus
from bot.services.user_service import get_user_by_telegram_id
from bot.services.search_service import (
    search_plans, search_goals, CATEGORY_LABELS,
)

router = Router()


class SearchState(StatesGroup):
    waiting_query = State()


_STATUS_ICON = {PlanStatus.pending: "⏳", PlanStatus.done: "✅", PlanStatus.failed: "❌"}


def _plans_kb(plans) -> InlineKeyboardMarkup:
    rows = []
    for p in plans[:10]:
        icon = _STATUS_ICON.get(p.status, "⏳")
        rows.append([InlineKeyboardButton(
            text=f"{icon} {p.title[:34]}", callback_data=f"plan_{p.id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[
        InlineKeyboardButton(text="📋 Rejalarim", callback_data="my_plans")
    ]])


@router.message(Command("qidir"))
async def search_command(message: Message, state: FSMContext):
    await state.set_state(SearchState.waiting_query)
    await message.answer(
        "🔎 <b>Qidiruv</b>\n\nNimani izlayapsiz? Kalit so'z yoki teg yuboring.\n"
        "<i>Masalan: 'kitob', 'sport', 'imtihon'</i>",
        parse_mode="HTML",
    )


@router.message(SearchState.waiting_query, F.text)
async def do_search(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    query = (message.text or "").strip()
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("Iltimos /start bosing.")
        return

    plans = await search_plans(session, user, query)
    goals = await search_goals(session, user, query)

    try:
        from bot.services.analytics_service import track
        await track(message.from_user.id, "search", user_id=user.id,
                    results=len(plans) + len(goals))
    except Exception:
        pass

    if not plans and not goals:
        await message.answer(
            f"🔍 <b>«{query}»</b> bo'yicha hech narsa topilmadi.",
            parse_mode="HTML",
        )
        return

    lines = [f"🔍 <b>«{query}»</b> bo'yicha natijalar:\n"]
    if plans:
        lines.append(f"📋 <b>Rejalar ({len(plans)} ta):</b>")
        for p in plans[:10]:
            icon = _STATUS_ICON.get(p.status, "⏳")
            cat = CATEGORY_LABELS.get(p.category or "", "")
            d = p.plan_date.strftime("%d.%m") if p.plan_date else ""
            lines.append(f"  {icon} {p.title} <i>{d} {cat}</i>")
        lines.append("")
    if goals:
        lines.append(f"🎯 <b>Maqsadlar ({len(goals)} ta):</b>")
        for g in goals[:10]:
            mark = "✅" if g.completed else "⬜️"
            lines.append(f"  {mark} {g.title}")

    await message.answer(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=_plans_kb(plans) if plans else None,
    )
