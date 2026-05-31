"""
Daily retention loop — morning, midday, evening, late-night, inactivity.

All times are Tashkent. Each job is wrapped so a single user's failure
never blocks the rest.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import and_, select

from bot.config import (
    PENDING_CHECK_HOUR,
    PENDING_CHECK_MINUTE,
    PREMIUM_EXPIRY_REMINDER_DAYS,
    SUMMARY_HOUR,
    SUMMARY_MINUTE,
    TIMEZONE,
)
from bot.models.plan import Plan, PlanStatus
from bot.models.subscription import Subscription
from bot.models.user import User
from bot.services.coach_service import (
    message_for_comeback,
    message_for_evening,
    message_for_morning,
    message_for_streak_warning,
)
from bot.services.premium_service import days_left, get_expired_premium_users
from database.db import AsyncSessionLocal

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone=str(TIMEZONE))


# ─────────────────────────────────────────────────────────────
async def send_plan_notifications(bot):
    """Every minute — fire reminders for plans whose time has come."""
    async with AsyncSessionLocal() as session:
        from bot.services.plan_service import get_pending_plans_to_notify
        plans = await get_pending_plans_to_notify(session)

        for plan in plans:
            user = (await session.execute(
                select(User).where(User.id == plan.user_id)
            )).scalar_one_or_none()
            if not user:
                continue

            from bot.keyboards.plan_keys import done_failed_keyboard

            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"⏰ <b>Vaqt bo'ldi!</b>\n\n"
                        f"📌 <b>{plan.title}</b>\n"
                        f"🕐 {plan.scheduled_time}\n\n"
                        f"✅ Bajarsangiz <b>+{plan.score_value} ball</b>\n"
                        f"❌ Bajarmasangiz <b>-3 ball</b>"
                    ),
                    parse_mode="HTML",
                    reply_markup=done_failed_keyboard(plan.id),
                )
                plan.notified_at = datetime.now(TIMEZONE).replace(tzinfo=None)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.warning(f"Notification error: {e}")


# ─────────────────────────────────────────────────────────────
async def send_morning_nudge(bot):
    """07:00 — energising, identity-affirming."""
    async with AsyncSessionLocal() as session:
        users = (await session.execute(
            select(User).where(User.is_active == True)
        )).scalars().all()

        for user in users:
            try:
                msg = message_for_morning()
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📋 Bugungi rejam", callback_data="my_plans")],
                    [InlineKeyboardButton(text="➕ Reja qo'sh", callback_data="add_plan")],
                ])
                await bot.send_message(
                    user.telegram_id, msg, parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                logger.debug(f"Morning nudge skip {user.telegram_id}: {e}")


# ─────────────────────────────────────────────────────────────
async def send_streak_warning(bot):
    """20:00 — warn users with active streak who haven't completed yet today."""
    async with AsyncSessionLocal() as session:
        today = datetime.now(TIMEZONE).date()

        users = (await session.execute(
            select(User).where(
                and_(User.is_active == True, User.streak > 1)
            )
        )).scalars().all()

        for user in users:
            if user.last_completed_date == today:
                continue
            try:
                msg = message_for_streak_warning(user.streak)
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔥 Streakni saqlash", callback_data="my_plans")],
                ])
                await bot.send_message(
                    user.telegram_id, msg, parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                logger.debug(f"Streak warn skip {user.telegram_id}: {e}")


# ─────────────────────────────────────────────────────────────
async def send_inactivity_comeback(bot):
    """Daily 11:00 — reach out to users idle for 3+ days."""
    async with AsyncSessionLocal() as session:
        today = datetime.now(TIMEZONE).date()

        users = (await session.execute(
            select(User).where(User.is_active == True)
        )).scalars().all()

        for user in users:
            last = user.last_completed_date
            if last is None:
                continue
            days_idle = (today - last).days
            # Only nudge at exact 3-day and 7-day marks (avoid spamming)
            if days_idle not in (3, 7, 14):
                continue
            try:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Qaytib boshlash", callback_data="add_plan")],
                ])
                await bot.send_message(
                    user.telegram_id,
                    message_for_comeback() +
                    f"\n\n💎 Sening eng yaxshi streaking: <b>{user.longest_streak} kun</b>",
                    parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                logger.debug(f"Comeback skip {user.telegram_id}: {e}")


# ─────────────────────────────────────────────────────────────
async def send_evening_reflection(bot):
    """21:00 — invite reflection."""
    async with AsyncSessionLocal() as session:
        users = (await session.execute(
            select(User).where(User.is_active == True)
        )).scalars().all()

        for user in users:
            try:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📊 Bugungi hisobot", callback_data="report")],
                ])
                await bot.send_message(
                    user.telegram_id,
                    message_for_evening(),
                    parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                logger.debug(f"Evening skip {user.telegram_id}: {e}")


# ─────────────────────────────────────────────────────────────
async def send_daily_summary(bot):
    """23:59 — daily summary + streak settlement."""
    async with AsyncSessionLocal() as session:
        today = datetime.now(TIMEZONE).date()

        users = (await session.execute(
            select(User).where(User.is_active == True)
        )).scalars().all()

        for user in users:
            plans = (await session.execute(
                select(Plan).where(
                    and_(Plan.user_id == user.id, Plan.plan_date == today)
                )
            )).scalars().all()

            if not plans:
                continue

            done = [p for p in plans if p.status == PlanStatus.done]
            failed = [p for p in plans if p.status == PlanStatus.failed]
            pending = [p for p in plans if p.status == PlanStatus.pending]

            # Streak loss only if user did literally nothing today AND had plans
            had_zero_done = len(done) == 0
            if had_zero_done and (failed or pending):
                # auto-burn freeze if available, else reset
                if (user.streak_freezes or 0) > 0 and (user.streak or 0) > 0:
                    user.streak_freezes -= 1
                else:
                    user.streak = 0

            # Reset weekly_xp on Sunday
            if today.weekday() == 6:
                user.weekly_xp = 0

            try:
                await session.commit()
            except Exception:
                await session.rollback()

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📊 Batafsil hisobot", callback_data="report")]
            ])

            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"🌙 <b>Kunlik hisobot</b>\n\n"
                        f"✅ Bajarildi: <b>{len(done)} ta</b>\n"
                        f"❌ Bajarilmadi: <b>{len(failed)} ta</b>\n"
                        f"⏳ Eslatilmadi: <b>{len(pending)} ta</b>\n\n"
                        f"⭐️ Jami ball: <b>{user.total_score or 0}</b>\n"
                        f"🔥 Streak: <b>{user.streak} kun</b>\n"
                        f"💎 Intizom kuchingiz: <b>{user.discipline_score or 50}/100</b>\n\n"
                        f"<i>Ertaga yana davom etamiz!</i>"
                    ),
                    parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                logger.debug(f"Summary skip {user.telegram_id}: {e}")


# ─────────────────────────────────────────────────────────────
async def check_pending_plans(bot):
    """23:00 — last call for pending plans (har foydalanuvchiga BITTA xabar)."""
    async with AsyncSessionLocal() as session:
        today = datetime.now(TIMEZONE).date()
        pending_plans = (await session.execute(
            select(Plan).where(
                and_(
                    Plan.status == PlanStatus.pending,
                    Plan.plan_date == today,
                )
            )
        )).scalars().all()

        if not pending_plans:
            return

        # Foydalanuvchi bo'yicha guruhlash — spam'ning oldini olish uchun
        by_user: dict[int, list[Plan]] = {}
        for plan in pending_plans:
            by_user.setdefault(plan.user_id, []).append(plan)

        for user_id, plans in by_user.items():
            user = (await session.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
            if not user:
                continue

            lines = []
            for p in plans[:15]:
                tm = f" 🕐 {p.scheduled_time}" if p.scheduled_time else ""
                lines.append(f"• <b>{p.title}</b>{tm}")
            extra = f"\n…va yana {len(plans) - 15} ta" if len(plans) > 15 else ""

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Rejalarni belgilash", callback_data="my_plans")],
            ])

            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"🌙 <b>Kun tugayapti</b>\n\n"
                        f"Quyidagi <b>{len(plans)} ta</b> reja hali belgilanmagan:\n\n"
                        + "\n".join(lines) + extra +
                        "\n\nBugun nimalarni bajardingiz? Belgilab qo'ying 👇"
                    ),
                    parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                logger.debug(f"Pending check skip {user.telegram_id}: {e}")


# ─────────────────────────────────────────────────────────────
async def downgrade_expired_premium(bot):
    """09:30 — muddati tugagan premiumlarni bepulga o'tkazadi va xabar beradi."""
    async with AsyncSessionLocal() as session:
        users = await get_expired_premium_users(session)
        for user in users:
            user.is_premium = False
            subs = (await session.execute(
                select(Subscription).where(
                    and_(
                        Subscription.user_id == user.id,
                        Subscription.is_active == True,  # noqa: E712
                    )
                )
            )).scalars().all()
            for s in subs:
                s.is_active = False
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                continue

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Obunani yangilash", callback_data="open_subscription")],
            ])
            try:
                await bot.send_message(
                    user.telegram_id,
                    "⌛️ <b>Premium obunangiz tugadi.</b>\n\n"
                    "Mini App va cheksiz imkoniyatlar yopildi.\n"
                    "Streakingizni va natijalaringizni yo'qotmaslik uchun "
                    "obunani yangilang 👇",
                    parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                logger.debug(f"Downgrade notify skip {user.telegram_id}: {e}")


# ─────────────────────────────────────────────────────────────
async def premium_expiry_reminder(bot):
    """10:30 — obuna tugashiga 3 va 1 kun qolganda eslatma."""
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()
        users = (await session.execute(
            select(User).where(
                and_(
                    User.premium_until != None,  # noqa: E711
                    User.premium_until > now,
                )
            )
        )).scalars().all()

        for user in users:
            left = days_left(user)
            if left not in PREMIUM_EXPIRY_REMINDER_DAYS:
                continue
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Obunani uzaytirish", callback_data="open_subscription")],
            ])
            try:
                await bot.send_message(
                    user.telegram_id,
                    f"⏳ <b>Premium obunangizga {left} kun qoldi.</b>\n\n"
                    "Uzluksiz davom etish uchun obunani oldindan uzaytiring — "
                    "shunda qolgan kunlar yo'qolmaydi 👇",
                    parse_mode="HTML", reply_markup=kb,
                )
            except Exception as e:
                logger.debug(f"Expiry reminder skip {user.telegram_id}: {e}")


# ─────────────────────────────────────────────────────────────
def start_scheduler(bot):
    tz = str(TIMEZONE)

    # every minute — fire due reminders
    scheduler.add_job(
        send_plan_notifications,
        trigger=CronTrigger(minute="*", timezone=tz),
        args=[bot], id="plan_notifications",
    )
    # 07:00 — morning nudge
    scheduler.add_job(
        send_morning_nudge,
        trigger=CronTrigger(hour=7, minute=0, timezone=tz),
        args=[bot], id="morning_nudge",
    )
    # 11:00 — comeback nudge for idle users
    scheduler.add_job(
        send_inactivity_comeback,
        trigger=CronTrigger(hour=11, minute=0, timezone=tz),
        args=[bot], id="comeback_nudge",
    )
    # 20:00 — streak warning
    scheduler.add_job(
        send_streak_warning,
        trigger=CronTrigger(hour=20, minute=0, timezone=tz),
        args=[bot], id="streak_warning",
    )
    # 21:00 — evening reflection prompt
    scheduler.add_job(
        send_evening_reflection,
        trigger=CronTrigger(hour=21, minute=0, timezone=tz),
        args=[bot], id="evening_reflection",
    )
    # 23:00 — pending plan check
    scheduler.add_job(
        check_pending_plans,
        trigger=CronTrigger(
            hour=PENDING_CHECK_HOUR, minute=PENDING_CHECK_MINUTE, timezone=tz,
        ),
        args=[bot], id="pending_check",
    )
    # 23:59 — daily summary + streak settlement
    scheduler.add_job(
        send_daily_summary,
        trigger=CronTrigger(
            hour=SUMMARY_HOUR, minute=SUMMARY_MINUTE, timezone=tz,
        ),
        args=[bot], id="daily_summary",
    )
    # 09:30 — muddati tugagan premiumlarni downgrade qilish
    scheduler.add_job(
        downgrade_expired_premium,
        trigger=CronTrigger(hour=9, minute=30, timezone=tz),
        args=[bot], id="downgrade_expired_premium",
    )
    # 10:30 — premium tugashi haqida eslatma
    scheduler.add_job(
        premium_expiry_reminder,
        trigger=CronTrigger(hour=10, minute=30, timezone=tz),
        args=[bot], id="premium_expiry_reminder",
    )
    scheduler.start()
