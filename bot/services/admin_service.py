from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from bot.models.admin import Admin
from bot.models.user import User
from bot.models.plan import Plan, PlanStatus
from bot.config import ADMIN_ID


def get_user_status(total_score: int, streak: int) -> str:
    """Ball va streakga qarab user statusini qaytaradi"""
    if total_score >= 500 and streak >= 14:
        return "🏆 Ustoz"
    elif total_score >= 300 and streak >= 7:
        return "💎 Intizomli"
    elif total_score >= 150 and streak >= 3:
        return "🔥 Focused"
    elif total_score >= 50:
        return "📈 O'sishda"
    elif total_score > 0:
        return "🌱 Yangi boshlovchi"
    else:
        return "😴 Harakatsiz"


async def is_admin(session: AsyncSession, telegram_id: int) -> bool:
    """Userning admin ekanligini tekshiradi"""
    if telegram_id == ADMIN_ID:
        return True
    result = await session.execute(
        select(Admin).where(Admin.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none() is not None


def _bot_filter(bot_name: str | None = None):
    """Bot nomi bo'yicha filter shartini qaytaradi."""
    if bot_name == "main":
        return User.started_main_bot == True  # noqa: E712
    elif bot_name == "dilshodbek":
        return User.started_dilshodbek_bot == True  # noqa: E712
    return None


async def get_all_users(session: AsyncSession, bot_name: str | None = None) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc())
    flt = _bot_filter(bot_name)
    if flt is not None:
        stmt = stmt.where(flt)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_users_count(session: AsyncSession, bot_name: str | None = None) -> int:
    stmt = select(func.count(User.id))
    flt = _bot_filter(bot_name)
    if flt is not None:
        stmt = stmt.where(flt)
    result = await session.execute(stmt)
    return result.scalar()


async def get_all_admins(session: AsyncSession) -> list[Admin]:
    result = await session.execute(select(Admin).order_by(Admin.added_at.desc()))
    return result.scalars().all()


async def add_admin(session: AsyncSession, telegram_id: int, full_name: str = "Noma'lum") -> Admin | None:
    existing = await session.execute(select(Admin).where(Admin.telegram_id == telegram_id))
    if existing.scalar_one_or_none():
        return None
    admin = Admin(telegram_id=telegram_id, full_name=full_name)
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return admin


async def remove_admin(session: AsyncSession, telegram_id: int) -> bool:
    result = await session.execute(select(Admin).where(Admin.telegram_id == telegram_id))
    admin = result.scalar_one_or_none()
    if not admin:
        return False
    await session.delete(admin)
    await session.commit()
    return True


async def get_user_plan_stats(session: AsyncSession, user: User) -> dict:
    """User haqida to'liq statistika"""
    result = await session.execute(
        select(Plan).where(Plan.user_id == user.id)
    )
    plans = result.scalars().all()

    return {
        "total_plans": len(plans),
        "done": len([p for p in plans if p.status == PlanStatus.done]),
        "failed": len([p for p in plans if p.status == PlanStatus.failed]),
        "pending": len([p for p in plans if p.status == PlanStatus.pending]),
    }


async def get_detailed_users_stats(session: AsyncSession, bot_name: str | None = None) -> dict:
    """Userlar haqida to'liq statistika"""
    stmt = select(User)
    flt = _bot_filter(bot_name)
    if flt is not None:
        stmt = stmt.where(flt)
    users_result = await session.execute(stmt)
    users = users_result.scalars().all()

    total = len(users)

    # Active userlar — kamida 1 ta rejasi borlar
    active_ids_result = await session.execute(
        select(Plan.user_id).distinct()
    )
    active_ids = set(active_ids_result.scalars().all())
    active = len(active_ids)
    inactive = total - active

    # Statuslarga ko'ra ajratish
    status_counts = {
        "🏆 Ustoz": 0,
        "💎 Intizomli": 0,
        "🔥 Focused": 0,
        "📈 O'sishda": 0,
        "🌱 Yangi boshlovchi": 0,
        "😴 Harakatsiz": 0,
    }

    for user in users:
        status = get_user_status(user.total_score, user.streak)
        if status in status_counts:
            status_counts[status] += 1

    # Top 3 user (ball bo'yicha)
    top_users = sorted(users, key=lambda u: u.total_score, reverse=True)[:3]

    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "status_counts": status_counts,
        "top_users": top_users,
    }


async def get_activity_stats(session: AsyncSession) -> dict:
    """
    Faollik statistikasi:
      • Oxirgi 3 / 7 / 30 kun ichida kamida bir marta foydalanganlar
      • Oxirgi 7 kun davomida HAR KUNI foydalanib kelganlar

    "Foydalandi" belgisi sifatida ScoreLog (reja bajarish/bajarmaslik) va
    Plan yaratish kunlari, hamda users.last_active dan foydalanamiz.
    """
    from datetime import datetime, timedelta
    from bot.config import TIMEZONE
    from bot.models.score_log import ScoreLog

    now = datetime.now(TIMEZONE)
    today = now.date()

    # last_active asosida 3/7/30 kun
    cutoff_3 = datetime.utcnow() - timedelta(days=3)
    cutoff_7 = datetime.utcnow() - timedelta(days=7)
    cutoff_30 = datetime.utcnow() - timedelta(days=30)

    active_3 = await session.scalar(
        select(func.count(User.id)).where(
            and_(User.last_active != None, User.last_active >= cutoff_3)  # noqa: E711
        )
    ) or 0
    active_7 = await session.scalar(
        select(func.count(User.id)).where(
            and_(User.last_active != None, User.last_active >= cutoff_7)  # noqa: E711
        )
    ) or 0
    active_30 = await session.scalar(
        select(func.count(User.id)).where(
            and_(User.last_active != None, User.last_active >= cutoff_30)  # noqa: E711
        )
    ) or 0

    # Oxirgi 7 kun davomida HAR KUNI faol bo'lganlar.
    # ScoreLog yozuvlari kun bo'yicha guruhlangan: agar foydalanuvchida
    # oxirgi 7 kunning har birida kamida bitta yozuv bo'lsa — "har kuni faol".
    week_start = today - timedelta(days=6)
    rows = await session.execute(
        select(ScoreLog.user_id, func.date(ScoreLog.created_at)).where(
            func.date(ScoreLog.created_at) >= week_start
        ).distinct()
    )
    day_set: dict = {}
    for uid, d in rows.all():
        # d str yoki date bo'lishi mumkin — str ko'rinishida normalize qilamiz
        day_set.setdefault(uid, set()).add(str(d))
    daily_streak_7 = sum(1 for uid, days in day_set.items() if len(days) >= 7)

    return {
        "active_3": active_3,
        "active_7": active_7,
        "active_30": active_30,
        "daily_active_7": daily_streak_7,
    }