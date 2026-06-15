"""
Kunlik ritual — ertalabki rejalashtirish + kechki refleksiya. Faza 3.

Bu IntizomAI'ning eng kuchli retention "anchor"i: har kun bir xil marosim.
  • Ertalab: bugungi rejalarni ko'rib chiqish + niyat.
  • Kechqurun: kunni baholash (kayfiyat/energiya) + 1 ta yutuq + refleksiya.

Sunsama'ning butun biznesi shu marosim ustiga qurilgan — biz uni bepul beramiz.
Refleksiya DailyCheckin'ga yoziladi (reflection/win_of_day/gratitude ustunlari).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.checkin import DailyCheckin
from bot.models.plan import Plan, PlanStatus
from bot.models.user import User


def _today() -> date:
    return datetime.now(TIMEZONE).date()


MOOD_OPTIONS = [("🔥", "zo'r"), ("💪", "yaxshi"), ("😐", "o'rtacha"), ("😴", "charchagan"), ("😞", "qiyin")]


async def get_or_create_checkin(session: AsyncSession, user: User,
                                day: date | None = None) -> DailyCheckin:
    day = day or _today()
    res = await session.execute(
        select(DailyCheckin).where(
            and_(DailyCheckin.user_id == user.id, DailyCheckin.checkin_date == day)
        )
    )
    chk = res.scalar_one_or_none()
    if not chk:
        chk = DailyCheckin(user_id=user.id, checkin_date=day)
        session.add(chk)
        await session.commit()
        await session.refresh(chk)
    return chk


async def set_mood(session: AsyncSession, user: User, mood: str,
                   energy: int | None = None) -> DailyCheckin:
    chk = await get_or_create_checkin(session, user)
    chk.mood = mood
    if energy is not None:
        chk.energy = energy
    await session.commit()
    await session.refresh(chk)
    return chk


async def save_reflection(session: AsyncSession, user: User, *,
                          reflection: str | None = None,
                          win_of_day: str | None = None,
                          gratitude: str | None = None) -> DailyCheckin:
    chk = await get_or_create_checkin(session, user)
    if reflection is not None:
        chk.reflection = reflection.strip()[:2000]
    if win_of_day is not None:
        chk.win_of_day = win_of_day.strip()[:500]
    if gratitude is not None:
        chk.gratitude = gratitude.strip()[:500]
    await session.commit()
    await session.refresh(chk)
    return chk


async def build_morning_ritual(session: AsyncSession, user: User) -> str:
    """Ertalabki marosim matni — bugungi rejalar + niyat."""
    today = _today()
    res = await session.execute(
        select(Plan).where(
            and_(Plan.user_id == user.id, Plan.plan_date == today,
                 Plan.is_template == False)  # noqa: E712
        ).order_by(Plan.scheduled_time)
    )
    plans = res.scalars().all()

    lines = ["🌅 <b>Ertalabki marosim</b>\n"]
    if plans:
        lines.append(f"Bugun <b>{len(plans)} ta</b> rejangiz bor:")
        for p in plans[:12]:
            tm = f" 🕐{p.scheduled_time}" if p.scheduled_time else ""
            lines.append(f"  • {p.title}{tm}")
        lines.append("\n💪 Eng muhim 1 tasini tanlang va undan boshlang.")
    else:
        lines.append("Bugun hali reja yo'q.\nBitta kichik niyatdan boshlang — ovoz yoki matn yuboring.")
    return "\n".join(lines)


async def build_evening_ritual(session: AsyncSession, user: User) -> str:
    """Kechki marosim matni — bugungi natija + refleksiyaga taklif."""
    today = _today()
    res = await session.execute(
        select(Plan).where(
            and_(Plan.user_id == user.id, Plan.plan_date == today,
                 Plan.is_template == False)  # noqa: E712
        )
    )
    plans = res.scalars().all()
    done = sum(1 for p in plans if p.status == PlanStatus.done)
    total = len(plans)
    pct = int(done * 100 / total) if total else 0

    lines = ["🌙 <b>Kechki marosim</b>\n"]
    if total:
        lines.append(f"Bugun: <b>{done}/{total}</b> bajarildi ({pct}%)")
    lines.append(
        "\nBir daqiqa to'xtab, o'ylab ko'ring:\n"
        "• Bugun nimadan faxrlanasiz?\n"
        "• Ertaga nimani yaxshilaysiz?"
    )
    return "\n".join(lines)
