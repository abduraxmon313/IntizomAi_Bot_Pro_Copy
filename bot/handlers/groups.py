"""
Faza 4: Study groups / accountability circles + guruh reytingi (leaderboard).

/guruh → guruhingiz (yoki tuzish/qo'shilish). Network effect + switching cost.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.user_service import get_user_by_telegram_id
from bot.services.group_service import (
    create_group, join_by_code, get_user_group, leave_group,
    group_summary_text, build_group_link,
)
from bot.services.referral_service import get_bot_username

router = Router()


class GroupState(StatesGroup):
    naming = State()
    joining = State()


def _no_group_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Guruh tuzish", callback_data="grp_create")],
        [InlineKeyboardButton(text="🔑 Kod bilan qo'shilish", callback_data="grp_join")],
    ])


def _group_kb(group) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Do'st taklif qilish", callback_data="grp_invite")],
        [InlineKeyboardButton(text="🏆 Reyting (yangilash)", callback_data="grp_board")],
        [InlineKeyboardButton(text="🚪 Guruhdan chiqish", callback_data="grp_leave")],
    ])


async def _show_group(target, session: AsyncSession, user):
    group = await get_user_group(session, user)
    if not group:
        text = (
            "👥 <b>Study Group</b>\n\n"
            "Do'stlaringiz bilan birgalikda intizomli bo'ling! Guruhda umumiy "
            "reyting bo'ladi — kim ko'proq reja bajaradi?\n\n"
            "Guruh tuzing yoki taklif kodi bilan qo'shiling 👇"
        )
        kb = _no_group_kb()
    else:
        text = await group_summary_text(session, group)
        kb = _group_kb(group)
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await target.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("guruh"))
async def group_command(message: Message, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("Iltimos /start bosing.")
        return
    await _show_group(message, session, user)


@router.callback_query(F.data == "grp_open")
async def group_open_cb(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    await _show_group(callback, session, user)


@router.callback_query(F.data == "grp_create")
async def group_create_cb(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GroupState.naming)
    await callback.message.answer(
        "➕ <b>Guruh tuzish</b>\n\nGuruhingizga nom bering "
        "(masalan: «Bizning sinf», «IELTS guruhi»).",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(GroupState.naming, F.text)
async def group_naming(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    user = await get_user_by_telegram_id(session, message.from_user.id)
    group = await create_group(session, user, message.text)
    try:
        from bot.services.analytics_service import track
        await track(message.from_user.id, "group_create", user_id=user.id)
    except Exception:
        pass
    username = await get_bot_username(message.bot)
    link = build_group_link(username, group.invite_code)
    await message.answer(
        f"✅ <b>«{group.name}» guruhi tuzildi!</b>\n\n"
        f"🔑 Taklif kodi: <code>{group.invite_code}</code>\n\n"
        "Do'stlaringizni quyidagi havola orqali taklif qiling 👇\n"
        f"<code>{link}</code>",
        parse_mode="HTML",
    )
    await _show_group(message, session, user)


@router.callback_query(F.data == "grp_join")
async def group_join_cb(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GroupState.joining)
    await callback.message.answer(
        "🔑 <b>Qo'shilish</b>\n\nGuruhning 6 xonali taklif kodini yuboring "
        "(masalan: <code>A1B2C3</code>).",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(GroupState.joining, F.text)
async def group_joining(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    user = await get_user_by_telegram_id(session, message.from_user.id)
    ok, msg, group = await join_by_code(session, user, message.text)
    if not ok:
        await message.answer(f"❌ {msg}")
        return
    try:
        from bot.services.analytics_service import track
        await track(message.from_user.id, "group_join", user_id=user.id, code=message.text.strip())
    except Exception:
        pass
    await message.answer(f"✅ «{group.name}» guruhiga qo'shildingiz!")
    await _show_group(message, session, user)


@router.callback_query(F.data == "grp_invite")
async def group_invite_cb(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    group = await get_user_group(session, user)
    if not group:
        await callback.answer("Avval guruhga qo'shiling.", show_alert=True)
        return
    username = await get_bot_username(callback.bot)
    link = build_group_link(username, group.invite_code)
    await callback.message.answer(
        f"🔗 <b>«{group.name}» ga taklif</b>\n\n"
        f"Kod: <code>{group.invite_code}</code>\n"
        f"Havola:\n<code>{link}</code>\n\n"
        "Do'stlaringizga yuboring — birga intizomli bo'lasiz! 🚀\n\n"
        "🎁 Do'stingiz qo'shilsa, ikkalangiz ham bonus olasiz.",
        parse_mode="HTML",
    )
    await callback.answer("Havola tayyor! 🔗")


@router.callback_query(F.data == "grp_board")
async def group_board_cb(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    await _show_group(callback, session, user)


@router.callback_query(F.data == "grp_leave")
async def group_leave_cb(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    await leave_group(session, user)
    await callback.answer("Guruhdan chiqdingiz.")
    await _show_group(callback, session, user)
