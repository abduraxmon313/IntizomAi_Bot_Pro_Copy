"""
Analytics xizmati — mahsulot metrikalarini yozish va o'qish.

MAQSAD: retention (D1/D7/D30), activation (signup → first_win), funnel
(paywall_view → subscribe_success) ko'rinadigan bo'lsin. Avval kodda hech
qanday hodisa kuzatuvi yo'q edi — bu modul shu "ko'rlik"ni yopadi.

DIZAYN TAMOYILLARI:
  • track() HAR DOIM best-effort — o'z izolyatsiya qilingan sessiyasida ishlaydi
    va har qanday xatoni yutadi. Asosiy biznes-oqimni hech qachon to'xtatmaydi.
  • event_date Tashkent sanasi (string) — kunlik so'rovlar tez va sodda.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.analytics_event import AnalyticsEvent
from bot.models.user import User

logger = logging.getLogger(__name__)


def _today_str() -> str:
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────
#  YOZISH (best-effort, izolyatsiya qilingan sessiya)
# ─────────────────────────────────────────────────────────────
async def track(
    telegram_id: Optional[int],
    event: str,
    user_id: Optional[int] = None,
    **props,
) -> None:
    """
    Bitta hodisani yozadi. HECH QACHON xato ko'tarmaydi.

    Misol:
        await track(message.from_user.id, "plan_created", user_id=user.id, count=3)
    """
    from database.db import AsyncSessionLocal
    try:
        props_str = None
        if props:
            try:
                props_str = json.dumps(props, ensure_ascii=False)[:500]
            except Exception:
                props_str = None
        async with AsyncSessionLocal() as s:
            s.add(AnalyticsEvent(
                user_id=user_id,
                telegram_id=telegram_id,
                event=event[:48],
                props=props_str,
                event_date=_today_str(),
            ))
            await s.commit()
    except Exception as e:  # noqa: BLE001 — analitika hech narsani buzmasligi kerak
        logger.debug(f"analytics track skip ({event}): {e}")


async def track_once_per_day(
    session: AsyncSession,
    telegram_id: int,
    event: str,
    user_id: Optional[int] = None,
    **props,
) -> bool:
    """
    Kuniga bir marta yoziladigan hodisa (masalan "open" — DAU uchun).
    Bugun shu telegram_id uchun shu hodisa bo'lsa — qayta yozmaydi.
    Qaytaradi: yangi yozildimi (True) yoki bugun allaqachon bor edi (False).
    """
    try:
        today = _today_str()
        exists = await session.scalar(
            select(AnalyticsEvent.id).where(
                and_(
                    AnalyticsEvent.telegram_id == telegram_id,
                    AnalyticsEvent.event == event,
                    AnalyticsEvent.event_date == today,
                )
            ).limit(1)
        )
        if exists:
            return False
    except Exception:
        # Tekshira olmadik — baribir yozishga harakat qilamiz (best-effort).
        pass
    await track(telegram_id, event, user_id=user_id, **props)
    return True


# ─────────────────────────────────────────────────────────────
#  O'QISH — admin dashboard metrikalari
# ─────────────────────────────────────────────────────────────
@dataclass
class FunnelMetrics:
    signups: int
    first_plan: int
    first_win: int
    paywall_views: int
    subscribe_success: int
    activation_rate: float          # first_win / signups
    paywall_conversion: float       # subscribe_success / paywall_views


async def _count_distinct_users(session: AsyncSession, event: str,
                                date_from: str, date_to: str) -> int:
    return await session.scalar(
        select(func.count(distinct(AnalyticsEvent.telegram_id))).where(
            and_(
                AnalyticsEvent.event == event,
                AnalyticsEvent.event_date >= date_from,
                AnalyticsEvent.event_date <= date_to,
            )
        )
    ) or 0


async def get_funnel(session: AsyncSession, days: int = 30) -> FunnelMetrics:
    """Oxirgi `days` kun uchun activation/monetizatsiya funneli."""
    today = datetime.now(TIMEZONE).date()
    dfrom = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    dto = today.strftime("%Y-%m-%d")

    signups = await _count_distinct_users(session, "signup", dfrom, dto)
    first_plan = await _count_distinct_users(session, "first_plan", dfrom, dto)
    first_win = await _count_distinct_users(session, "first_win", dfrom, dto)
    paywall = await _count_distinct_users(session, "paywall_view", dfrom, dto)
    subs = await _count_distinct_users(session, "subscribe_success", dfrom, dto)

    return FunnelMetrics(
        signups=signups,
        first_plan=first_plan,
        first_win=first_win,
        paywall_views=paywall,
        subscribe_success=subs,
        activation_rate=(first_win / signups) if signups else 0.0,
        paywall_conversion=(subs / paywall) if paywall else 0.0,
    )


async def get_dau(session: AsyncSession, days: int = 7) -> list[tuple[str, int]]:
    """Kunlik faol foydalanuvchilar (DAU) — oxirgi `days` kun. [(date, count)]."""
    today = datetime.now(TIMEZONE).date()
    out: list[tuple[str, int]] = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt = await session.scalar(
            select(func.count(distinct(AnalyticsEvent.telegram_id))).where(
                AnalyticsEvent.event_date == d
            )
        ) or 0
        out.append((d, cnt))
    return out


async def get_retention(session: AsyncSession, cohort_days_ago: int = 7) -> dict:
    """
    Oddiy retention: `cohort_days_ago` kun oldin ro'yxatdan o'tganlardan
    nechtasi keyin (D1/D7) qaytib kelgan (har qanday hodisa).
    """
    today = datetime.now(TIMEZONE).date()
    cohort_day = today - timedelta(days=cohort_days_ago)
    cohort_str = cohort_day.strftime("%Y-%m-%d")

    # Kohort: shu kuni signup qilganlar
    cohort_ids = (await session.execute(
        select(distinct(AnalyticsEvent.telegram_id)).where(
            and_(
                AnalyticsEvent.event == "signup",
                AnalyticsEvent.event_date == cohort_str,
            )
        )
    )).scalars().all()
    cohort_set = {x for x in cohort_ids if x is not None}
    cohort_size = len(cohort_set)

    async def _retained(offset: int) -> int:
        if not cohort_set or cohort_days_ago < offset:
            return 0
        d = (cohort_day + timedelta(days=offset)).strftime("%Y-%m-%d")
        ret_ids = (await session.execute(
            select(distinct(AnalyticsEvent.telegram_id)).where(
                AnalyticsEvent.event_date == d
            )
        )).scalars().all()
        return len(cohort_set & {x for x in ret_ids if x is not None})

    d1 = await _retained(1)
    d7 = await _retained(7)

    return {
        "cohort_date": cohort_str,
        "cohort_size": cohort_size,
        "d1": d1,
        "d7": d7,
        "d1_rate": (d1 / cohort_size) if cohort_size else 0.0,
        "d7_rate": (d7 / cohort_size) if cohort_size else 0.0,
    }


async def top_events(session: AsyncSession, days: int = 7,
                     limit: int = 15) -> list[tuple[str, int]]:
    """Oxirgi `days` kundagi eng ko'p hodisalar (event, count)."""
    today = datetime.now(TIMEZONE).date()
    dfrom = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    rows = (await session.execute(
        select(AnalyticsEvent.event, func.count(AnalyticsEvent.id))
        .where(AnalyticsEvent.event_date >= dfrom)
        .group_by(AnalyticsEvent.event)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .limit(limit)
    )).all()
    return [(r[0], r[1]) for r in rows]


async def build_admin_analytics_text(session: AsyncSession) -> str:
    """Admin panel uchun tayyor matn (HTML)."""
    funnel = await get_funnel(session, days=30)
    dau = await get_dau(session, days=7)
    ret7 = await get_retention(session, cohort_days_ago=7)

    dau_line = " · ".join(str(c) for _, c in dau) if dau else "—"

    def pct(x: float) -> str:
        return f"{x * 100:.1f}%"

    return (
        "📈 <b>Analitika (30 kun)</b>\n\n"
        f"👥 Ro'yxatdan o'tdi: <b>{funnel.signups}</b>\n"
        f"✏️ Birinchi reja: <b>{funnel.first_plan}</b>\n"
        f"🏆 Birinchi g'alaba (activation): <b>{funnel.first_win}</b> "
        f"(<b>{pct(funnel.activation_rate)}</b>)\n\n"
        f"💳 Paywall ko'rdi: <b>{funnel.paywall_views}</b>\n"
        f"💎 Obuna oldi: <b>{funnel.subscribe_success}</b> "
        f"(konversiya <b>{pct(funnel.paywall_conversion)}</b>)\n\n"
        f"📊 DAU (oxirgi 7 kun):\n<code>{dau_line}</code>\n\n"
        f"🔁 Retention (7 kun oldingi kohort, {ret7['cohort_size']} kishi):\n"
        f"   D1: <b>{pct(ret7['d1_rate'])}</b> · D7: <b>{pct(ret7['d7_rate'])}</b>"
    )
