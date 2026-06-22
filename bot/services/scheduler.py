"""
Daily retention loop — morning, midday, evening, late-night, inactivity.

All times are Tashkent. Each job is wrapped so a single user's failure
never blocks the rest.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import and_, or_, select

from bot.config import (
    HABIT_REMINDER_HOUR,
    HABIT_REMINDER_MINUTE,
    PENDING_CHECK_HOUR,
    PENDING_CHECK_MINUTE,
    PREMIUM_EXPIRY_REMINDER_DAYS,
    SUMMARY_HOUR,
    SUMMARY_MINUTE,
    TIMEZONE,
    WEBAPP_URL,
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

# Telegram global limiti ~30 msg/sek. Xavfsizlik uchun har yuborish orasida
# kichik pauza qo'yamiz (~20 msg/sek).
SEND_DELAY = 0.05

# Bildirishnoma yoqilgan foydalanuvchilar filtri (NULL ham yoqilgan deb hisoblanadi).
NOTIF_ON = or_(User.notifications_enabled == True, User.notifications_enabled.is_(None))  # noqa: E712


async def _deliver(bot, user, text, reply_markup=None) -> str:
    """
    Bitta foydalanuvchiga xabar yuboradi — flood-control bilan.
    Qaytaradi: 'ok' | 'blocked' | 'failed'.
      • TelegramRetryAfter — ko'rsatilgan vaqt kutib, bir marta qayta urinadi.
      • TelegramForbiddenError — user botni bloklagan/to'xtatgan ('blocked').
    """
    try:
        await bot.send_message(
            user.telegram_id, text, parse_mode="HTML", reply_markup=reply_markup
        )
        return "ok"
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(
                user.telegram_id, text, parse_mode="HTML", reply_markup=reply_markup
            )
            return "ok"
        except Exception:
            return "failed"
    except TelegramForbiddenError:
        return "blocked"
    except Exception as e:
        logger.debug(f"send skip {user.telegram_id}: {e}")
        return "failed"


# ─────────────────────────────────────────────────────────────
async def send_plan_notifications(bot):
    """Every minute — fire reminders for plans whose time has come."""
    async with AsyncSessionLocal() as session:
        from bot.services.plan_service import get_pending_plans_to_notify
        from bot.keyboards.plan_keys import done_failed_keyboard
        plans = await get_pending_plans_to_notify(session)

        for plan in plans:
            user = (await session.execute(
                select(User).where(User.id == plan.user_id)
            )).scalar_one_or_none()
            if not user:
                continue

            st = await _deliver(
                bot, user,
                (
                    f"⏰ <b>Vaqt bo'ldi!</b>\n\n"
                    f"📌 <b>{plan.title}</b>\n"
                    f"🕐 {plan.scheduled_time}\n\n"
                    f"✅ Bajarsangiz <b>+{plan.score_value} ball</b>\n"
                    f"❌ Bajarmasangiz <b>-3 ball</b>"
                ),
                done_failed_keyboard(plan.id),
            )
            if st == "blocked":
                user.is_active = False
            # Qayta yubormaslik uchun belgilab qo'yamiz
            plan.notified_at = datetime.now(TIMEZONE).replace(tzinfo=None)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
            await asyncio.sleep(SEND_DELAY)


# ─────────────────────────────────────────────────────────────
async def send_morning_nudge(bot):
    """07:00 — energising, identity-affirming."""
    async with AsyncSessionLocal() as session:
        users = (await session.execute(
            select(User).where(and_(User.is_active == True, NOTIF_ON))
        )).scalars().all()

        blocked = False
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Bugungi rejam", callback_data="my_plans")],
            [InlineKeyboardButton(text="➕ Reja qo'sh", callback_data="add_plan")],
        ])
        for user in users:
            st = await _deliver(bot, user, message_for_morning(), kb)
            if st == "blocked":
                user.is_active = False
                blocked = True
            await asyncio.sleep(SEND_DELAY)
        if blocked:
            try:
                await session.commit()
            except Exception:
                await session.rollback()


# ─────────────────────────────────────────────────────────────
async def send_streak_warning(bot):
    """20:00 — warn users with active streak who haven't completed yet today."""
    async with AsyncSessionLocal() as session:
        today = datetime.now(TIMEZONE).date()

        users = (await session.execute(
            select(User).where(
                and_(User.is_active == True, User.streak > 1, NOTIF_ON)
            )
        )).scalars().all()

        blocked = False
        for user in users:
            if user.last_completed_date == today:
                continue
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔥 Streakni saqlash", callback_data="my_plans")],
            ])
            st = await _deliver(bot, user, message_for_streak_warning(user.streak), kb)
            if st == "blocked":
                user.is_active = False
                blocked = True
            await asyncio.sleep(SEND_DELAY)
        if blocked:
            try:
                await session.commit()
            except Exception:
                await session.rollback()


# ─────────────────────────────────────────────────────────────
async def send_inactivity_comeback(bot):
    """Daily 11:00 — reach out to users idle for 3+ days."""
    async with AsyncSessionLocal() as session:
        today = datetime.now(TIMEZONE).date()

        users = (await session.execute(
            select(User).where(and_(User.is_active == True, NOTIF_ON))
        )).scalars().all()

        blocked = False
        for user in users:
            last = user.last_completed_date
            if last is None:
                continue
            days_idle = (today - last).days
            # Only nudge at exact 3-day and 7-day marks (avoid spamming)
            if days_idle not in (3, 7, 14):
                continue
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Qaytib boshlash", callback_data="add_plan")],
            ])
            st = await _deliver(
                bot, user,
                message_for_comeback() +
                f"\n\n💎 Sening eng yaxshi streaking: <b>{user.longest_streak} kun</b>",
                kb,
            )
            if st == "blocked":
                user.is_active = False
                blocked = True
            await asyncio.sleep(SEND_DELAY)
        if blocked:
            try:
                await session.commit()
            except Exception:
                await session.rollback()


# ─────────────────────────────────────────────────────────────
async def send_evening_reflection(bot):
    """21:00 — invite reflection."""
    async with AsyncSessionLocal() as session:
        users = (await session.execute(
            select(User).where(User.is_active == True)
        )).scalars().all()

        blocked = False
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Bugungi hisobot", callback_data="report")],
        ])
        for user in users:
            st = await _deliver(bot, user, message_for_evening(), kb)
            if st == "blocked":
                user.is_active = False
                blocked = True
            await asyncio.sleep(SEND_DELAY)
        if blocked:
            try:
                await session.commit()
            except Exception:
                await session.rollback()


# ─────────────────────────────────────────────────────────────
async def send_daily_summary(bot):
    """23:59 — daily summary + streak settlement."""
    async with AsyncSessionLocal() as session:
        today = datetime.now(TIMEZONE).date()

        users = (await session.execute(
            select(User).where(User.is_active == True)
        )).scalars().all()

        for user in users:
            # ── Oylik "grace": oyning 1-kunida har bir faol foydalanuvchiga
            #    1 ta streak freeze beriladi (maks. 2 ta to'planadi). Bu engaged
            #    foydalanuvchining bitta yomon kunini kechiradi (P1).
            if today.day == 1 and (user.streak_freezes or 0) < 2:
                user.streak_freezes = (user.streak_freezes or 0) + 1
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()

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

            # Streak settlement har doim bajariladi; xabar esa faqat bildirishnoma
            # yoqilgan bo'lsa yuboriladi (P1 notification budget).
            if user.notifications_enabled is False:
                continue

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📊 Batafsil hisobot", callback_data="report")]
            ])

            st = await _deliver(
                bot, user,
                (
                    f"🌙 <b>Kunlik hisobot</b>\n\n"
                    f"✅ Bajarildi: <b>{len(done)} ta</b>\n"
                    f"❌ Bajarilmadi: <b>{len(failed)} ta</b>\n"
                    f"⏳ Eslatilmadi: <b>{len(pending)} ta</b>\n\n"
                    f"⭐️ Jami ball: <b>{user.total_score or 0}</b>\n"
                    f"🔥 Streak: <b>{user.streak} kun</b>\n"
                    f"💎 Intizom kuchingiz: <b>{user.discipline_score or 50}/100</b>\n\n"
                    f"<i>Ertaga yana davom etamiz!</i>"
                ),
                kb,
            )
            if st == "blocked":
                user.is_active = False
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
            await asyncio.sleep(SEND_DELAY)


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

        blocked = False
        for user_id, plans in by_user.items():
            user = (await session.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
            if not user:
                continue
            if user.notifications_enabled is False:
                continue

            lines = []
            for p in plans[:15]:
                tm = f" 🕐 {p.scheduled_time}" if p.scheduled_time else ""
                lines.append(f"• <b>{p.title}</b>{tm}")
            extra = f"\n…va yana {len(plans) - 15} ta" if len(plans) > 15 else ""

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Rejalarni belgilash", callback_data="my_plans")],
            ])

            st = await _deliver(
                bot, user,
                (
                    f"🌙 <b>Kun tugayapti</b>\n\n"
                    f"Quyidagi <b>{len(plans)} ta</b> reja hali belgilanmagan:\n\n"
                    + "\n".join(lines) + extra +
                    "\n\nBugun nimalarni bajardingiz? Belgilab qo'ying 👇"
                ),
                kb,
            )
            if st == "blocked":
                user.is_active = False
                blocked = True
            await asyncio.sleep(SEND_DELAY)
        if blocked:
            try:
                await session.commit()
            except Exception:
                await session.rollback()


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
            st = await _deliver(
                bot, user,
                "⌛️ <b>Premium obunangiz tugadi.</b>\n\n"
                "Mini App va cheksiz imkoniyatlar yopildi.\n"
                "Streakingizni va natijalaringizni yo'qotmaslik uchun "
                "obunani yangilang 👇",
                kb,
            )
            if st == "blocked":
                user.is_active = False
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()
            await asyncio.sleep(SEND_DELAY)


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

        blocked = False
        for user in users:
            left = days_left(user)
            if left not in PREMIUM_EXPIRY_REMINDER_DAYS:
                continue
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💎 Obunani uzaytirish", callback_data="open_subscription")],
            ])
            st = await _deliver(
                bot, user,
                f"⏳ <b>Premium obunangizga {left} kun qoldi.</b>\n\n"
                "Uzluksiz davom etish uchun obunani oldindan uzaytiring — "
                "shunda qolgan kunlar yo'qolmaydi 👇",
                kb,
            )
            if st == "blocked":
                user.is_active = False
                blocked = True
            await asyncio.sleep(SEND_DELAY)
        if blocked:
            try:
                await session.commit()
            except Exception:
                await session.rollback()


# ─────────────────────────────────────────────────────────────
async def send_habit_reminders(bot):
    """19:00 — bugun rejalashtirilgan, lekin hali belgilanmagan odatlar eslatmasi."""
    from bot.services.habit_service import get_due_unchecked_habits
    async with AsyncSessionLocal() as session:
        users = (await session.execute(
            select(User).where(and_(User.is_active == True, NOTIF_ON))
        )).scalars().all()

        blocked = False
        for user in users:
            try:
                due = await get_due_unchecked_habits(session, user)
            except Exception:
                due = []
            if not due:
                continue

            lines = []
            for h in due[:12]:
                lines.append(f"{h.icon or '✅'} <b>{h.title}</b>")
            extra = f"\n…va yana {len(due) - 12} ta" if len(due) > 12 else ""

            kb = None
            if WEBAPP_URL:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Odatlarni belgilash",
                        web_app=WebAppInfo(url=WEBAPP_URL),
                    )],
                ])
            st = await _deliver(
                bot, user,
                (
                    f"✅ <b>Bugungi odatlaring</b>\n\n"
                    f"Quyidagi <b>{len(due)} ta</b> odat hali belgilanmagan:\n\n"
                    + "\n".join(lines) + extra +
                    "\n\nKichik qadam — katta natija. Streakingni saqla 🔥"
                ),
                kb,
            )
            if st == "blocked":
                user.is_active = False
                blocked = True
            await asyncio.sleep(SEND_DELAY)
        if blocked:
            try:
                await session.commit()
            except Exception:
                await session.rollback()


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
    # 19:00 — odat (habit) eslatmasi (bugun belgilanmaganlar)
    scheduler.add_job(
        send_habit_reminders,
        trigger=CronTrigger(
            hour=HABIT_REMINDER_HOUR, minute=HABIT_REMINDER_MINUTE, timezone=tz,
        ),
        args=[bot], id="habit_reminders",
    )
    # Eslatma: 21:00 "evening_reflection" jo'natmasi olib tashlandi — kunlik
    # bildirishnoma yukini kamaytirish uchun (20:00 streak + 23:00 pending yetarli).
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
