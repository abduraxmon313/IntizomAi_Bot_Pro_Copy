"""
Emotional AI coach — rotating, mood-aware messages.

Tone: supportive, grounded, identity-affirming.
Never toxic. Never shaming. Always points forward.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.checkin import DailyCheckin
from bot.models.plan import Plan, PlanStatus
from bot.models.user import User


# ── Templates ────────────────────────────────────────────────
MORNING = [
    "☀️ Xayrli tong! Yangi kun — yangi imkoniyat. Bugun nimadan boshlaymiz?",
    "🌅 Erta turdingizmi? Bu allaqachon kichik g'alaba.",
    "🔥 Bugungi siz — kechagi sizdan bir qadam oldinda.",
    "🌱 Har kichik qadam katta natijaga olib boradi. Bugun ham davom etamiz.",
    "💎 Intizom — bu kayfiyat emas, qaror. Bugun ham to'g'ri qaror qabul qiling.",
    "🎯 Kuningizni rejalashtiring — shunda kun sizni boshqaradi emas, siz kunni.",
]

STREAK_WARNING = [
    "🔥 Streakingizni saqlang — {streak} kunlik mehnatingiz xavf ostida.",
    "⚠️ Bugun bitta reja ham bajarmasangiz, {streak} kunlik olov o'chadi.",
    "💪 Yana atigi 1 ta reja — va kun saqlanadi. Buni keyinga qoldirmang.",
    "🛡 Streak — bu o'zingizga bergan va'da. Uni buzmang.",
]

LEVEL_UP = [
    "🚀 Yangi daraja — yangi siz!",
    "🎉 Daraja oshdi! Keyingi cho'qqi allaqachon ko'rinmoqda.",
    "🏆 Bu shunchaki raqam emas — bu sizning o'sganingiz isboti.",
]

PERFECT_DAY = [
    "✨ Mukammal kun! Bironta reja ham o'tkazib yuborilmadi.",
    "🌟 Bugun siz 100% bo'ldingiz. Bunday kunlar sizni ajratib turadi.",
    "💎 Bu kun tarixingizda oltin sahifa bo'lib qoladi.",
]

COMEBACK = [
    "🔄 Qaytib keldingiz — bu eng muhim qadam edi.",
    "💪 Tushish — mag'lubiyat emas. To'xtab qolish — mag'lubiyat. Davom etamiz.",
    "🌱 Yana boshlash — eng kuchli odatlardan biri. Bugun toza varaqdan boshlaymiz.",
]

LOW_DISCIPLINE = [
    "🎯 Intizom kuchingiz biroz pasaydi. Bitta kichik yutuq — va u tiklanadi.",
    "📈 Hammasi sizning qo'lingizda. Bugun bitta narsani uddalab ko'ring.",
]

HIGH_DISCIPLINE = [
    "🏆 Intizom kuchingiz cho'qqida! Siz o'z xarakteringizni qurmoqdasiz.",
    "💎 Siz endi shunchaki 'qilaman' deydigan emas — qiluvchisiz.",
]

EVENING = [
    "🌙 Kun yakuni. Bugun qaysi ishingiz bilan faxrlanasiz?",
    "✨ Esda tuting: bugungi tanlovlaringiz — ertangi poydevoringiz.",
    "🌌 Yaxshi dam oling. Ertaga yana yangi imkoniyat bor.",
]

EMPTY_DAY = [
    "📋 Bugun reja yo'q. Bitta kichik niyatdan boshlang.",
    "🌱 Eng kichik reja — eng kuchli boshlanish.",
    "✍️ Bo'sh sahifa — imkoniyat. Bugun nimani uddalashni xohlaysiz?",
]


def _pick(pool: list[str], **fmt) -> str:
    return random.choice(pool).format(**fmt)


# ─────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────
def message_for_level_up(level: int) -> str:
    return f"{_pick(LEVEL_UP)}\n\n💎 Daraja: <b>{level}</b>"


def message_for_perfect_day() -> str:
    return _pick(PERFECT_DAY)


def message_for_streak_warning(streak: int) -> str:
    return _pick(STREAK_WARNING, streak=streak)


def message_for_comeback() -> str:
    return _pick(COMEBACK)


def message_for_morning() -> str:
    return _pick(MORNING)


def message_for_evening() -> str:
    return _pick(EVENING)


def message_for_empty_day() -> str:
    return _pick(EMPTY_DAY)


# ─────────────────────────────────────────────────────────────
#  Smart contextual coach (used by webapp /api/webapp/coach)
# ─────────────────────────────────────────────────────────────
async def smart_coach_message(session: AsyncSession, user: User) -> dict:
    """
    Returns a contextual, mood-aware message + tone label.
    Decision tree (priority order):
      1. Comeback (≥2 days inactive)
      2. Streak at risk (today not yet completed, has streak)
      3. Low discipline (<35)
      4. High discipline (≥75)
      5. Perfect day standing
      6. Morning vs evening time-of-day
    """
    now = datetime.now(TIMEZONE)
    today = now.date()
    last = user.last_completed_date
    streak = user.streak or 0
    ds = user.discipline_score or 50

    days_idle = (today - last).days if last else 999

    if days_idle >= 2 and streak == 0:
        return {"tone": "comeback", "icon": "🔄", "text": _pick(COMEBACK)}

    if streak >= 2 and last != today:
        return {
            "tone": "warning",
            "icon": "⚠️",
            "text": _pick(STREAK_WARNING, streak=streak),
        }

    if ds < 35:
        return {"tone": "encourage", "icon": "📈", "text": _pick(LOW_DISCIPLINE)}

    # Today has plans but none done?
    today_plans = await session.execute(
        select(Plan).where(
            and_(Plan.user_id == user.id, Plan.plan_date == today)
        )
    )
    today_plans = today_plans.scalars().all()
    today_total = len(today_plans)
    today_done = sum(1 for p in today_plans if p.status == PlanStatus.done)

    if today_total == 0:
        return {"tone": "neutral", "icon": "📋", "text": _pick(EMPTY_DAY)}

    if today_total > 0 and today_done == today_total:
        return {"tone": "celebrate", "icon": "✨", "text": _pick(PERFECT_DAY)}

    if ds >= 75:
        return {"tone": "elite", "icon": "💎", "text": _pick(HIGH_DISCIPLINE)}

    if 5 <= now.hour < 12:
        return {"tone": "morning", "icon": "🌅", "text": _pick(MORNING)}
    if now.hour >= 19:
        return {"tone": "evening", "icon": "🌙", "text": _pick(EVENING)}

    return {"tone": "neutral", "icon": "🌱", "text": _pick(MORNING)}


# ─────────────────────────────────────────────────────────────
#  Daily quest — a single "do this now" focus
# ─────────────────────────────────────────────────────────────
async def daily_quest(session: AsyncSession, user: User) -> dict:
    """Returns a single concrete quest with progress."""
    today = datetime.now(TIMEZONE).date()
    res = await session.execute(
        select(Plan).where(
            and_(Plan.user_id == user.id, Plan.plan_date == today)
        )
    )
    plans = res.scalars().all()
    total = len(plans)
    done = sum(1 for p in plans if p.status == PlanStatus.done)

    if total == 0:
        return {
            "title": "Bugungi 1-rejangni qo'sh",
            "subtitle": "Boshlanish — eng qiyin va eng muhim qadam",
            "progress": 0,
            "target": 1,
            "reward_xp": 5,
            "icon": "✏️",
            "completed": False,
        }

    if done < total:
        return {
            "title": "Bugungi rejalarni yakunla",
            "subtitle": f"{total - done} ta qoldi — har biri seni kuchaytiradi",
            "progress": done,
            "target": total,
            "reward_xp": 10,
            "icon": "🎯",
            "completed": False,
        }

    # All done — perfect day quest already won
    streak = user.streak or 0
    return {
        "title": f"{streak}-kunlik streak saqlandi",
        "subtitle": "Mukammal kun. Ertaga ham kel.",
        "progress": 1,
        "target": 1,
        "reward_xp": 0,
        "icon": "✨",
        "completed": True,
    }
