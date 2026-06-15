"""
Haftalik recap + oylik hisobot kartasi + AI insights. Faza 3 (task 9 & 10).

  • Weekly recap  — har yakshanba 20:00 (bajarilgan, streak, XP, eng faol kun).
  • Monthly card  — har oyning 1-kuni 10:00 (oldingi oy bo'yicha "report card").
  • AI insights   — bajarilish pattern'idan AI yordamida shaxsiy xulosa.

Bularning hammasi retention'ni oshiradi: davriy yakunlar foydalanuvchini
qaytishga undaydi va "men intizomli odamman" degan o'zlikni mustahkamlaydi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.plan import Plan, PlanStatus
from bot.models.user import User

logger = logging.getLogger(__name__)

UZ_WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
UZ_MONTHS = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
             "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]


def _today() -> date:
    return datetime.now(TIMEZONE).date()


@dataclass
class PeriodStats:
    total: int
    done: int
    failed: int
    completion_pct: int
    best_day: str | None
    best_day_done: int
    by_category: dict[str, int]
    xp_gained: int


async def _period_stats(session: AsyncSession, user: User,
                        start: date, end: date) -> PeriodStats:
    res = await session.execute(
        select(Plan).where(
            and_(
                Plan.user_id == user.id,
                Plan.plan_date >= start,
                Plan.plan_date <= end,
                Plan.is_template == False,  # noqa: E712
            )
        )
    )
    plans = res.scalars().all()
    total = len(plans)
    done = sum(1 for p in plans if p.status == PlanStatus.done)
    failed = sum(1 for p in plans if p.status == PlanStatus.failed)

    by_day: dict[date, int] = {}
    by_cat: dict[str, int] = {}
    xp = 0
    for p in plans:
        if p.status == PlanStatus.done:
            by_day[p.plan_date] = by_day.get(p.plan_date, 0) + 1
            xp += p.score_value or 0
            cat = p.category or "boshqa"
            by_cat[cat] = by_cat.get(cat, 0) + 1

    best_day, best_done = None, 0
    if by_day:
        bd = max(by_day, key=by_day.get)
        best_day = UZ_WEEKDAYS[bd.weekday()]
        best_done = by_day[bd]

    return PeriodStats(
        total=total, done=done, failed=failed,
        completion_pct=int(done * 100 / total) if total else 0,
        best_day=best_day, best_day_done=best_done,
        by_category=by_cat, xp_gained=xp,
    )


# ─────────────────────────────────────────────────────────────
#  HAFTALIK RECAP
# ─────────────────────────────────────────────────────────────
async def build_weekly_recap(session: AsyncSession, user: User) -> str:
    today = _today()
    start = today - timedelta(days=6)
    s = await _period_stats(session, user, start, today)

    from bot.services.search_service import CATEGORY_LABELS
    lines = [
        "📅 <b>Haftalik hisobot</b>",
        f"<i>{start.strftime('%d.%m')} – {today.strftime('%d.%m')}</i>\n",
        f"✅ Bajarildi: <b>{s.done}/{s.total}</b> ({s.completion_pct}%)",
        f"⭐️ Yig'ilgan XP: <b>{s.xp_gained}</b>",
        f"🔥 Streak: <b>{user.streak or 0} kun</b>",
        f"💎 Intizom kuchingiz: <b>{user.discipline_score or 50}/100</b>",
    ]
    if s.best_day:
        lines.append(f"🏆 Eng faol kun: <b>{s.best_day}</b> ({s.best_day_done} ta)")
    if s.by_category:
        top = sorted(s.by_category.items(), key=lambda x: -x[1])[:3]
        cats = ", ".join(f"{CATEGORY_LABELS.get(c, c)} ({n})" for c, n in top)
        lines.append(f"🏷 Asosiy yo'nalishlar: {cats}")

    if s.completion_pct >= 80:
        lines.append("\n🌟 Ajoyib hafta! Shu sur'atda davom eting.")
    elif s.completion_pct >= 50:
        lines.append("\n💪 Yaxshi hafta. Keyingi hafta yana yuqoriroq!")
    else:
        lines.append("\n🌱 Har hafta — yangi imkoniyat. Keling, kichikroq, lekin aniq rejalar bilan boshlaymiz.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  OYLIK HISOBOT KARTASI (shareable)
# ─────────────────────────────────────────────────────────────
async def build_monthly_card(session: AsyncSession, user: User,
                             ref_day: date | None = None) -> str:
    """Oldingi oy bo'yicha "report card" — ulashsa bo'ladigan, faxr uyg'otadigan."""
    ref = ref_day or _today()
    first_this = ref.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    s = await _period_stats(session, user, first_prev, last_prev)

    grade = (
        "S 🏆" if s.completion_pct >= 90 else
        "A 🌟" if s.completion_pct >= 75 else
        "B 💪" if s.completion_pct >= 60 else
        "C 🌱" if s.completion_pct >= 40 else "D 🔄"
    )
    month_name = f"{UZ_MONTHS[last_prev.month]} {last_prev.year}"
    name = (user.full_name or "Do'st").split(" ")[0]

    return (
        f"🎖 <b>{month_name} — Hisobot kartasi</b>\n"
        f"<i>{name}</i>\n"
        "━━━━━━━━━━━━━━━\n"
        f"📊 Baho: <b>{grade}</b>\n"
        f"✅ Bajarildi: <b>{s.done}/{s.total}</b> ({s.completion_pct}%)\n"
        f"⭐️ XP: <b>{s.xp_gained}</b>\n"
        f"🔥 Eng uzun streak: <b>{user.longest_streak or 0} kun</b>\n"
        f"💎 Intizom kuchi: <b>{user.discipline_score or 50}/100</b>\n"
        + (f"🏆 Eng faol kun: <b>{s.best_day}</b>\n" if s.best_day else "")
        + "━━━━━━━━━━━━━━━\n"
        "📲 <b>IntizomAI</b> bilan o'z intizomingizni quring.\n"
        "Bu kartani do'stlaringiz bilan bo'lishing! 🚀"
    )


# ─────────────────────────────────────────────────────────────
#  AI WEEKLY INSIGHTS (task 10)
# ─────────────────────────────────────────────────────────────
async def build_ai_insights(session: AsyncSession, user: User) -> str:
    """
    Foydalanuvchining oxirgi 14 kunlik bajarilish pattern'idan AI yordamida
    shaxsiy, amaliy xulosa chiqaradi (masalan "ertalabki rejalarni 80% bajarasiz,
    kechqurun 30%"). AI bo'lmasa — qoidaga asoslangan fallback.
    """
    today = _today()
    start = today - timedelta(days=13)
    res = await session.execute(
        select(Plan).where(
            and_(
                Plan.user_id == user.id,
                Plan.plan_date >= start,
                Plan.plan_date <= today,
                Plan.is_template == False,  # noqa: E712
            )
        )
    )
    plans = res.scalars().all()
    if not plans:
        return "📊 Hali yetarli ma'lumot yo'q. Bir necha kun reja qo'shing — keyin shaxsiy tahlil beraman."

    # Vaqt oralig'i bo'yicha bajarilish (ertalab/kunduzi/kechqurun)
    buckets = {"ertalab": [0, 0], "kunduzi": [0, 0], "kechqurun": [0, 0], "vaqtsiz": [0, 0]}
    cat_stats: dict[str, list[int]] = {}
    for p in plans:
        done = 1 if p.status == PlanStatus.done else 0
        b = "vaqtsiz"
        if p.scheduled_time:
            try:
                hh = int(str(p.scheduled_time).split(":")[0])
                b = "ertalab" if hh < 12 else ("kunduzi" if hh < 18 else "kechqurun")
            except Exception:
                b = "vaqtsiz"
        buckets[b][0] += done
        buckets[b][1] += 1
        cat = p.category or "boshqa"
        cs = cat_stats.setdefault(cat, [0, 0])
        cs[0] += done
        cs[1] += 1

    # Pattern matni (AI uchun kontekst)
    parts = []
    for b, (d, t) in buckets.items():
        if t:
            parts.append(f"{b}: {int(d*100/t)}% ({d}/{t})")
    pattern = "; ".join(parts)

    from bot.services.ai_service import chat_with_coach, OPENAI_API_KEY
    if OPENAI_API_KEY:
        try:
            ctx = (
                f"Foydalanuvchi oxirgi 14 kunlik bajarilish pattern'i (vaqt oralig'i bo'yicha): {pattern}. "
                f"Streak {user.streak or 0} kun, discipline {user.discipline_score or 50}/100."
            )
            history = [{"role": "user", "content":
                        "Mening oxirgi 2 haftalik natijalarimni qisqa tahlil qil va "
                        "1 ta aniq, amaliy tavsiya ber. 3-4 jumla, o'zbekcha."}]
            reply = await chat_with_coach(ctx, history)
            return "🧠 <b>AI tahlil (14 kun)</b>\n\n" + reply
        except Exception as e:
            logger.debug(f"ai insights fallback: {e}")

    # Fallback — qoidaga asoslangan
    best = max((b for b in buckets if buckets[b][1]), key=lambda b: buckets[b][0] / max(1, buckets[b][1]), default=None)
    worst = min((b for b in buckets if buckets[b][1]), key=lambda b: buckets[b][0] / max(1, buckets[b][1]), default=None)
    tip = ""
    if best and worst and best != worst:
        tip = f"\n\n💡 Eng yaxshi <b>{best}</b> vaqtida ishlaysiz. <b>{worst}</b> rejalarini kamroq qiling yoki vaqtini o'zgartiring."
    return f"🧠 <b>Tahlil (14 kun)</b>\n\n📊 {pattern}{tip}"


# ─────────────────────────────────────────────────────────────
#  SCHEDULER JOBLARI
# ─────────────────────────────────────────────────────────────
async def send_weekly_recap(bot):
    """Yakshanba 20:30 — barcha faol foydalanuvchilarga haftalik recap."""
    from database.db import AsyncSessionLocal
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from aiogram.exceptions import TelegramForbiddenError
    import asyncio
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧠 AI tahlilim", callback_data="ai_insights")],
        ])
        for user in users:
            try:
                text = await build_weekly_recap(session, user)
                await bot.send_message(user.telegram_id, text, parse_mode="HTML", reply_markup=kb)
            except TelegramForbiddenError:
                user.is_active = False
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
            except Exception:
                pass
            await asyncio.sleep(0.05)


async def send_monthly_card(bot):
    """Oyning 1-kuni 10:00 — oldingi oy hisobot kartasi."""
    from database.db import AsyncSessionLocal
    from aiogram.exceptions import TelegramForbiddenError
    import asyncio
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712
        for user in users:
            try:
                text = await build_monthly_card(session, user)
                await bot.send_message(user.telegram_id, text, parse_mode="HTML")
            except TelegramForbiddenError:
                user.is_active = False
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
            except Exception:
                pass
            await asyncio.sleep(0.05)
