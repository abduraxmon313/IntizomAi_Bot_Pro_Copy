"""
Faza 3: Kunlik ritual (ertalabki reja / kechki refleksiya).

Callbacks:
  ritual_morning            — ertalabki marosim
  ritual_evening            — kechki marosim (kayfiyat tanlash)
  mood_<emoji>              — kayfiyatni saqlash → refleksiya so'rash
  ritual_reflect            — refleksiya matnini yozish (FSM)
  ritual_skip               — o'tkazib yuborish
"""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.user_service import get_user_by_telegram_id
from bot.services.ritual_service import (
    build_morning_ritual, build_evening_ritual, set_mood, save_reflection,
    MOOD_OPTIONS,
)

router = Router()


class RitualState(StatesGroup):
    waiting_reflection = State()


def _mood_keyboard() -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=e, callback_data=f"mood_{e}") for e, _ in MOOD_OPTIONS]
    return InlineKeyboardMarkup(inline_keyboard=[row, [
        InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="ritual_skip"),
    ]])


def _reflect_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Refleksiya yozish", callback_data="ritual_reflect")],
        [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="ritual_skip")],
    ])


@router.callback_query(F.data == "ritual_morning")
async def ritual_morning_cb(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    text = await build_morning_ritual(session, user)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Rejalarim", callback_data="my_plans")],
        [InlineKeyboardButton(text="➕ Reja qo'sh", callback_data="add_plan")],
    ])
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    try:
        from bot.services.analytics_service import track
        await track(callback.from_user.id, "ritual_morning", user_id=user.id)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "ritual_evening")
async def ritual_evening_cb(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    text = await build_evening_ritual(session, user)
    text += "\n\n<b>Bugungi kayfiyatingiz qanday?</b>"
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_mood_keyboard())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=_mood_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("mood_"))
async def mood_cb(callback: CallbackQuery, session: AsyncSession):
    mood = callback.data.replace("mood_", "")
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    await set_mood(session, user, mood)
    await callback.message.edit_text(
        f"Kayfiyat saqlandi: {mood}\n\n"
        "Bugungi <b>eng yaxshi yutug'ingiz</b> nima edi? Yozib qoldiring 👇",
        parse_mode="HTML",
        reply_markup=_reflect_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "ritual_reflect")
async def ritual_reflect_cb(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RitualState.waiting_reflection)
    await callback.message.answer(
        "✍️ Bugun haqida bir-ikki jumla yozing: nimadan faxrlanasiz, "
        "ertaga nimani yaxshilaysiz?",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RitualState.waiting_reflection, F.text)
async def ritual_reflection_input(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    user = await get_user_by_telegram_id(session, message.from_user.id)
    await save_reflection(session, user, reflection=message.text, win_of_day=message.text[:120])
    try:
        from bot.services.analytics_service import track
        await track(message.from_user.id, "ritual_evening", user_id=user.id)
    except Exception:
        pass
    await message.answer(
        "✅ <b>Saqlandi. Zo'r kun bo'ldi!</b>\n\n"
        "Bugungi refleksiyangiz AI Coach'ga ham yordam beradi — "
        "u sizni yaxshiroq tushunadi. Ertaga yana ko'rishamiz 🌙",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "ritual_skip")
async def ritual_skip_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("Mayli, ertaga davom etamiz 🌙")
