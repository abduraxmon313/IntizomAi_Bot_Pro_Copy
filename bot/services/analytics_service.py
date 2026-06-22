"""
Yengil analitika — funnel/retention o'lchovi.

`log_event` HECH QACHON xato ko'tarmaydi va ALOHIDA sessiyada ishlaydi —
shuning uchun analitika asosiy oqimni (reja yaratish, to'lov, ...) buzmaydi.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.analytics_event import AnalyticsEvent
from bot.models.habit import Habit
from bot.models.plan import Plan
from bot.models.subscription import Subscription
from bot.models.user import User

logger = logging.getLogger(__name__)


async def log_event(
    event: str,
    telegram_id: Optional[int] = None,
    user_id: Optional[int] = None,
    props: Optional[str] = None,
) -> None:
    """Hodisani yozadi (best-effort, izolyatsiya qilingan sessiya)."""
    try:
        from database.db import AsyncSessionLocal
        async with AsyncSessionLocal() as s:
            s.add(AnalyticsEvent(
                event=str(event)[:50],
                telegram_id=telegram_id,
                user_id=user_id,
                props=(str(props)[:300] if props is not None else None),
            ))
            await s.commit()
    except Exception as e:  # pragma: no cover
        logger.debug(f"analytics log skip ({event}): {e}")


async def _event_count(session: AsyncSession, event: str, since: datetime) -> int:
    return await session.scalar(
        select(func.count(AnalyticsEvent.id)).where(
            and_(AnalyticsEvent.event == event, AnalyticsEvent.created_at >= since)
        )
    ) or 0


async def get_funnel(session: AsyncSession) -> dict:
    """Asosiy funnel/retention ko'rsatkichlari (admin uchun)."""
    now = datetime.utcnow()
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)
    d1 = now - timedelta(days=1)

    total_users = await session.scalar(select(func.count(User.id))) or 0
    signups_7d = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= d7)
    ) or 0
    signups_30d = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= d30)
    ) or 0

    # Aktivatsiya: kamida 1 ta reja yoki odat yaratgan foydalanuvchilar
    plan_users = set((await session.execute(
        select(Plan.user_id).distinct()
    )).scalars().all())
    habit_users = set((await session.execute(
        select(Habit.user_id).distinct()
    )).scalars().all())
    activated = len(plan_users | habit_users)

    # Premium holati
    premium_active = await session.scalar(
        select(func.count(User.id)).where(
            and_(User.premium_until != None, User.premium_until > now)  # noqa: E711
        )
    ) or 0
    trial_granted = await session.scalar(
        select(func.count(User.id)).where(User.trial_used == True)  # noqa: E712
    ) or 0
    # Pullik obuna olganlar (trial/referral'dan tashqari manbalar)
    paid_users = await session.scalar(
        select(func.count(func.distinct(Subscription.user_id))).where(
            Subscription.source.in_(("paylov", "checkout", "promocode", "payment"))
        )
    ) or 0

    # Retention (last_active asosida)
    active_1 = await session.scalar(
        select(func.count(User.id)).where(
            and_(User.last_active != None, User.last_active >= d1)  # noqa: E711
        )
    ) or 0
    active_7 = await session.scalar(
        select(func.count(User.id)).where(
            and_(User.last_active != None, User.last_active >= d7)  # noqa: E711
        )
    ) or 0
    active_30 = await session.scalar(
        select(func.count(User.id)).where(
            and_(User.last_active != None, User.last_active >= d30)  # noqa: E711
        )
    ) or 0

    # Hodisalar (oxirgi 7 kun)
    events_7d = {}
    for ev in (
        "start", "signup", "plan_created", "habit_created", "goal_created",
        "ai_chat", "paywall_view", "miniapp_open", "checkout_started",
        "premium_activated", "trial_granted", "onboarding_done",
    ):
        events_7d[ev] = await _event_count(session, ev, d7)

    activation_rate = round(activated * 100 / total_users) if total_users else 0
    paid_rate = round(paid_users * 100 / total_users, 1) if total_users else 0

    return {
        "total_users": total_users,
        "signups_7d": signups_7d,
        "signups_30d": signups_30d,
        "activated": activated,
        "activation_rate": activation_rate,
        "premium_active": premium_active,
        "trial_granted": trial_granted,
        "paid_users": paid_users,
        "paid_rate": paid_rate,
        "active_1": active_1,
        "active_7": active_7,
        "active_30": active_30,
        "events_7d": events_7d,
    }
