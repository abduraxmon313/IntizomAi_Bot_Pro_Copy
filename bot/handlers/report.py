import html

from aiogram import Router, F
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

UZ_WEEKDAYS = [
    "Dushanba", "Seshanba", "Chorshanba", "Payshanba",
    "Juma", "Shanba", "Yakshanba",
]
UZ_MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
]


def _squares(pct: int, length: int = 10) -> str:
    """Rangli kvadrat progress: 🟩🟩🟩⬜️⬜️ ..."""
    filled = max(0, min(length, round(pct / 100 * length)))
    return "🟩" * filled + "⬜️" * (length - filled)


def _closing_line(done: int, total: int) -> str:
    """Holatga mos premium motivatsion yakun."""
    if total <= 0:
        return "🌱 <i>Bitta kichik reja qo'sh — kun shu yerdan boshlanadi.</i>"
    left = total - done
    if done >= total:
        return "🏆 <i>Mukammal kun! Bugun sen 100% bo'lding.</i>"
    if left == 1:
        return "🔥 <i>Yana atigi bittasi qoldi — yakuniga yetkaz!</i>"
    if done / total >= 0.5:
        return "💪 <i>Zo'r ketyapsan — oz qoldi!</i>"
    if done > 0:
        return "🌱 <i>Yaxshi boshlanish. Yana bittasini uddala.</i>"
    return "⏳ <i>Hali ulgurasan — bittadan boshla 🚀</i>"


async def build_report_text(session, user) -> str:
    plans = await get_today_plans(session, user)

    done = [p for p in plans if p.status == PlanStatus.done]

    status = get_user_status(user.total_score, user.streak)

    now = datetime.now(TIMEZONE)
    date_str = f"{now.day}-{UZ_MONTHS[now.month - 1]} · {UZ_WEEKDAYS[now.weekday()]}"

    total = len(plans)
    done_n = len(done)
    pct = round(done_n * 100 / total) if total else 0
    # Bugun haqiqatan ishlab topilgan XP (bajarilgan rejalardan) — ScoreLog
    # qayta-belgilashlaridan shishib ketmaydigan, aniq qiymat.
    today_xp = sum(p.score_value or 0 for p in done)

    # ── Sarlavha ────────────────────────────────────────────
    text = f"✨ <b>Kun yakuni</b>\n<i>{date_str}</i>\n\n"

    if total:
        text += f"{_squares(pct)}  <b>{pct}%</b>\n"
        text += f"✅ <b>{done_n} / {total}</b> reja bajarildi\n\n"

        # ── Vazifalar kartasi (blockquote) ──────────────────
        icon = {
            PlanStatus.done: "✅",
            PlanStatus.failed: "⚪️",
            PlanStatus.pending: "⬜️",
        }
        rows = []
        for p in plans:
            title = html.escape(p.title or "")
            line = f"{icon.get(p.status, '⬜️')} {title}"
            if p.status == PlanStatus.pending and p.scheduled_time:
                line += f"  <i>{p.scheduled_time}</i>"
            rows.append(line)
        body = "\n".join(rows)
        if len(rows) > 10:
            text += f"<blockquote expandable>{body}</blockquote>\n\n"
        else:
            text += f"<blockquote>{body}</blockquote>\n\n"
    else:
        text += "📭 <i>Bugun hali reja yo'q.</i>\n\n"

    # ── Statistika qatori ───────────────────────────────────
    text += (
        f"🔥 <b>{user.streak}</b> kun   "
        f"⭐️ <b>+{today_xp}</b> ball   "
        f"🏆 <b>{user.total_score}</b> umumiy\n"
    )
    text += f"{status}\n\n"
    text += _closing_line(done_n, total)

    return text


# Reply keyboard tugmasi
@router.message(F.text == "📈 Hisobot")
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