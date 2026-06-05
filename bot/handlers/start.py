import os

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiogram.filters import CommandStart, CommandObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main_menu import main_menu_keyboard
from bot.keyboards.reply_keys import main_reply_keyboard
from bot.keyboards.subscribe_keys import contact_keyboard, premium_promo_keyboard
from bot.services.gamification_service import xp_progress, rank_for_level
from bot.services.user_service import get_or_create_user, get_user_by_telegram_id
from bot.services.premium_service import user_is_premium, days_left
from bot.services.referral_service import parse_referrer_id, register_referral

router = Router()


WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()


def _webapp_kb(is_premium: bool) -> InlineKeyboardMarkup | None:
    if not is_premium:
        # Obunasiz — 2 tugmali promo (Obuna sotib olish + Premium haqida).
        return premium_promo_keyboard()
    rows = []
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(
            text="✨ Mini App ochish",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject, session: AsyncSession):
    # Foydalanuvchi avval mavjudmidi? (referral faqat YANGI userlar uchun)
    existing = await get_user_by_telegram_id(session, message.from_user.id)
    is_new = existing is None

    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username or "",
    )

    # ── Referral (taklif havolasi) — yangi foydalanuvchini taklif qiluvchiga bog'lash
    if is_new:
        referrer_id = parse_referrer_id(command.args)
        if referrer_id:
            try:
                await register_referral(
                    session, referrer_id, user, bot=message.bot,
                )
            except Exception:
                # Referral xatosi /start oqimini to'xtatmasin
                pass

    if not user.onboarded:
        text = (
            "🎯 <b>Intizom AI</b> ga xush kelibsiz!\n\n"
            "Men sizning shaxsiy intizom yordamchingizman.\n\n"
            "📌 <b>Nima qila olaman:</b>\n"
            "• Ovoz yoki matn orqali reja tuzish\n"
            "• Vaqti kelganda eslatish\n"
            "• Bajargan ishlaringiz uchun ball berish\n"
            "• Streak, daraja va kunlik hisobot yuritish\n\n"
            "💡 <b>Boshlash uchun</b> — bugun nima qilmoqchi ekanligingizni "
            "ovozli xabar yoki matn yuboring!\n\n"
            "<i>Masalan: 'Soat 6 da turaman, 9 da kitob o'qiyman'</i>"
        )
    else:
        lvl, in_lvl, needed, pct = xp_progress(user.xp or 0)
        rank, emoji = rank_for_level(lvl)
        bar_filled = "▰" * round(pct / 10)
        bar_empty = "▱" * (10 - len(bar_filled))
        name = user.full_name or "do'st"
        text = (
            f"🎯 <b>Xush kelibsiz, {name}!</b>\n\n"
            f"{emoji} <b>{rank}</b> · {lvl}-daraja\n"
            f"<code>{bar_filled}{bar_empty}</code> {pct}%\n\n"
            f"🔥 Streak: <b>{user.streak or 0} kun</b>\n"
            f"💎 Intizom kuchingiz: <b>{user.discipline_score or 50}/100</b>\n"
            f"⭐️ Jami ball: <b>{user.total_score or 0}</b>\n\n"
            "Bugun nima qilamiz? 👇"
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_reply_keyboard(),
    )

    is_premium = user_is_premium(user)
    webapp_kb = _webapp_kb(is_premium)
    if webapp_kb:
        if is_premium:
            promo_text = (
                "🚀 <b>Mini App</b> — kalendar, statistika va shaxsiy AI Coach.\n"
                f"💎 Premium faol — <b>{days_left(user)} kun</b> qoldi. Bahridan to'liq foydalaning!"
            )
        else:
            promo_text = (
                "🚀 <b>Mini App</b> — kalendar, statistika va AI Coach bir joyda.\n\n"
                "💎 Bu <b>Premium</b> imkoniyat. Quyidagidan tanlang 👇"
            )
        await message.answer(
            promo_text,
            parse_mode="HTML",
            reply_markup=webapp_kb,
        )

    if not user.onboarded:
        user.onboarded = True
        await session.commit()


@router.message(F.text == "📞 Bog'lanish")
async def contact_admin(message: Message):
    await message.answer(
        "📞 <b>Bog'lanish</b>\n\nQuyidagidan birini tanlang 👇",
        parse_mode="HTML",
        reply_markup=contact_keyboard(),
    )


@router.callback_query(F.data == "home")
async def home_handler(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)

    lvl, in_lvl, needed, pct = xp_progress(user.xp or 0)
    rank, emoji = rank_for_level(lvl)
    bar_filled = "▰" * round(pct / 10)
    bar_empty = "▱" * (10 - len(bar_filled))

    await callback.message.edit_text(
        f"🏠 <b>Bosh sahifa</b>\n\n"
        f"{emoji} <b>{user.full_name}</b>\n"
        f"📊 {rank} · {lvl}-daraja\n"
        f"<code>{bar_filled}{bar_empty}</code> {pct}%\n\n"
        f"🔥 Streak: <b>{user.streak or 0} kun</b>\n"
        f"💎 Intizom kuchingiz: <b>{user.discipline_score or 50}/100</b>\n"
        f"⭐️ Jami ball: <b>{user.total_score or 0}</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()
