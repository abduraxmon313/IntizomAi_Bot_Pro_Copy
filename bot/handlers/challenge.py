"""
Faza 3: Coach challenges (murabbiy chaqiriqlari).

/challenge → faol chaqiriqlar + boshlash mumkin bo'lganlar.
Callbacks: chal_start_<code>
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.user_service import get_user_by_telegram_id
from bot.services.challenge_service import (
    list_active, start_challenge, available_to_start, CHALLENGE_CATALOG,
)

router = Router()


def _progress_bar(progress: int, target: int, length: int = 10) -> str:
    filled = max(0, min(length, round(progress / max(1, target) * length)))
    return "▰" * filled + "▱" * (length - filled)


async def _render(session: AsyncSession, user) -> tuple[str, InlineKeyboardMarkup]:
    active = await list_active(session, user.id)
    active_codes = {c.code for c in active}

    lines = ["🎯 <b>Chaqiriqlar (Challenges)</b>\n"]
    if active:
        lines.append("<b>Faol:</b>")
        for c in active:
            bar = _progress_bar(c.progress or 0, c.target)
            lines.append(f"{c.icon} {c.title}\n<code>{bar}</code> {c.progress}/{c.target}")
        lines.append("")
    else:
        lines.append("Hozircha faol chaqiruv yo'q.\n")

    rows = []
    avail = available_to_start(active_codes)
    if avail:
        lines.append("<b>Yangi chaqiruv boshlash:</b>")
        for code, spec in avail:
            lines.append(f"{spec['icon']} <b>{spec['title']}</b> — {spec['desc']} (🎁 +{spec['reward_credits']} AI kredit)")
            rows.append([InlineKeyboardButton(
                text=f"{spec['icon']} {spec['title']} boshlash",
                callback_data=f"chal_start_{code}",
            )])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows or [[
        InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="home")
    ]])


@router.message(Command("challenge"))
async def challenge_command(message: Message, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("Iltimos /start bosing.")
        return
    text, kb = await _render(session, user)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("mavsum"))
async def season_command(message: Message, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        await message.answer("Iltimos /start bosing.")
        return
    from bot.services.season_service import get_season_status, season_leaderboard
    st = await get_season_status(session, user)
    board = await season_leaderboard(session, limit=10)

    lines = [
        f"🏆 <b>Mavsum {st['season_id']}</b>\n",
        f"{st['tier_icon']} Sizning darajangiz: <b>{st['tier']}</b>",
        f"⭐️ Mavsum XP: <b>{st['season_xp']}</b>",
    ]
    if st["next_tier"]:
        lines.append(f"📈 <b>{st['next_tier']}</b> gacha: {st['to_next']} XP")
    lines.append("\n🥇 <b>Reyting (TOP-10):</b>")
    for i, u in enumerate(board, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = (u.full_name or "Foydalanuvchi").split(" ")[0]
        me = " ← siz" if u.id == user.id else ""
        lines.append(f"{medal} {name} — {u.season_xp or 0} XP{me}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data.startswith("chal_start_"))
async def challenge_start_cb(callback: CallbackQuery, session: AsyncSession):
    code = callback.data.replace("chal_start_", "")
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    ok, msg = await start_challenge(session, user, code)
    if not ok:
        await callback.answer(msg, show_alert=True)
        return
    try:
        from bot.services.analytics_service import track
        await track(callback.from_user.id, "challenge_start", user_id=user.id, code=code)
    except Exception:
        pass
    spec = CHALLENGE_CATALOG.get(code, {})
    await callback.answer("Chaqiruv boshlandi! 🎯")
    text, kb = await _render(session, user)
    try:
        await callback.message.edit_text(
            f"✅ <b>{spec.get('title', 'Chaqiruv')} boshlandi!</b>\n\n{msg}\n\n" + text,
            parse_mode="HTML", reply_markup=kb,
        )
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
