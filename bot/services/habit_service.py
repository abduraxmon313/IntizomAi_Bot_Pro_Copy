"""
Odat (habit) servisi — CRUD + takrorlanish/davomiylik + bugungi holat va streak.

Odat rejalardan va maqsadlardan alohida: u takrorlanadigan amal.
  • Takrorlanish (frequency): har kuni ("daily") yoki tanlangan hafta kunlari ("weekly").
  • Davomiylik (duration): doimiy ("permanent") yoki muddatli ("days" — N kun).

Foydalanuvchi odatni rejalashtirilgan kunlarda "bajardim" deb belgilaydi
(HabitLog), shu asosda joriy ketma-ketlik (streak) va bugungi holat hisoblanadi.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.habit import Habit, HabitLog
from bot.models.user import User


def _today() -> date:
    return datetime.now(TIMEZONE).date()


# ─────────────────────────────────────────────────────────────
#  Takrorlanish / davomiylik yordamchilari
# ─────────────────────────────────────────────────────────────
def _parse_weekdays(habit: Habit) -> set[int]:
    """Habit.weekdays ("0,2,4") -> {0,2,4}. Bo'sh bo'lsa — barcha kunlar."""
    raw = (habit.weekdays or "").strip()
    if not raw:
        return {0, 1, 2, 3, 4, 5, 6}
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            v = int(part)
            if 0 <= v <= 6:
                out.add(v)
    return out or {0, 1, 2, 3, 4, 5, 6}


def _start_date(habit: Habit) -> date:
    return habit.start_date or (habit.created_at.date() if habit.created_at else _today())


def _end_date(habit: Habit) -> Optional[date]:
    """Muddatli odat tugash sanasi (inclusive). Doimiy bo'lsa None."""
    if (habit.duration_type or "permanent") != "days":
        return None
    td = habit.target_days or 0
    if td <= 0:
        return None
    return _start_date(habit) + timedelta(days=td - 1)


def is_finished(habit: Habit, today: Optional[date] = None) -> bool:
    """Muddatli odat muddati tugaganmi?"""
    today = today or _today()
    end = _end_date(habit)
    return bool(end and today > end)


def is_due_on(habit: Habit, d: date) -> bool:
    """Odat shu kuni rejalashtirilganmi (bajarilishi kerakmi)?"""
    start = _start_date(habit)
    if d < start:
        return False
    end = _end_date(habit)
    if end and d > end:
        return False
    if (habit.frequency or "daily") == "weekly":
        return d.weekday() in _parse_weekdays(habit)
    return True


async def get_user_habits(session: AsyncSession, user: User) -> list[Habit]:
    result = await session.execute(
        select(Habit)
        .where(and_(Habit.user_id == user.id, Habit.archived == False))  # noqa: E712
        .order_by(Habit.sort_order, Habit.created_at)
    )
    return result.scalars().all()


async def _log_dates_for(session: AsyncSession, habit_id: int) -> set[date]:
    """Odatning barcha bajarilgan kunlari (oxirgi ~400 kun bilan cheklab)."""
    since = _today() - timedelta(days=400)
    res = await session.execute(
        select(HabitLog.log_date).where(
            and_(HabitLog.habit_id == habit_id, HabitLog.log_date >= since)
        )
    )
    return {row[0] for row in res.all() if row[0] is not None}


def _current_streak(habit: Habit, dates: set[date], today: date) -> int:
    """
    Joriy ketma-ketlik — FAQAT rejalashtirilgan (due) kunlar bo'yicha.
      • Bugun due va hali belgilanmagan bo'lsa — uzilmaydi (kun tugamagan).
      • O'tgan due kun belgilanmagan bo'lsa — streak uziladi.
      • Due bo'lmagan kunlar (masalan haftalik odatda dam kunlari) o'tkazib yuboriladi.
    """
    if not dates:
        return 0
    streak = 0
    d = today
    guard = 0
    while guard < 500:
        guard += 1
        if is_due_on(habit, d):
            if d in dates:
                streak += 1
            elif d == today:
                pass  # bugun hali belgilanmagan — toq emas
            else:
                break
        # start_date dan oldinga o'tib ketmaymiz
        if d <= _start_date(habit):
            break
        d -= timedelta(days=1)
    return streak


async def habit_snapshot(session: AsyncSession, habit: Habit) -> dict:
    """Bitta odat uchun frontendga yuboriladigan ma'lumot."""
    today = _today()
    dates = await _log_dates_for(session, habit.id)
    end = _end_date(habit)
    finished = bool(end and today > end)
    wd = sorted(_parse_weekdays(habit)) if (habit.frequency or "daily") == "weekly" else []
    days_left = None
    if end:
        days_left = max(0, (end - today).days + 1) if not finished else 0
    # Tracker uchun: oxirgi ~45 kun ichida bajarilgan sanalar (ISO)
    recent = sorted(d.isoformat() for d in dates if d >= today - timedelta(days=45))
    return {
        "id": habit.id,
        "title": habit.title,
        "description": habit.description,
        "icon": habit.icon or "✅",
        "reminder_time": habit.reminder_time,
        "frequency": habit.frequency or "daily",
        "weekdays": wd,
        "duration_type": habit.duration_type or "permanent",
        "target_days": habit.target_days,
        "start_date": _start_date(habit).isoformat(),
        "end_date": end.isoformat() if end else None,
        "days_left": days_left,
        "finished": finished,
        "due_today": (not finished) and is_due_on(habit, today),
        "done_today": today in dates,
        "streak": _current_streak(habit, dates, today),
        "total_done": len(dates),
        "log_dates": recent,
        "created_at": habit.created_at.isoformat() if habit.created_at else None,
    }


async def list_habit_snapshots(session: AsyncSession, user: User) -> list[dict]:
    habits = await get_user_habits(session, user)
    return [await habit_snapshot(session, h) for h in habits]


def _normalize_weekdays(weekdays) -> Optional[str]:
    """list[int] yoki "0,2,4" -> tartiblangan vergulli string (yoki None)."""
    if weekdays is None:
        return None
    if isinstance(weekdays, str):
        parts = [p.strip() for p in weekdays.split(",")]
    else:
        parts = [str(p) for p in weekdays]
    vals = sorted({int(p) for p in parts if str(p).strip().isdigit() and 0 <= int(p) <= 6})
    return ",".join(str(v) for v in vals) if vals else None


def _normalize_time(t) -> Optional[str]:
    """"7:5" / "07:05" -> "07:05"; yaroqsiz bo'lsa None."""
    if not t:
        return None
    s = str(t).strip()
    if ":" not in s:
        return None
    try:
        hh, mm = s.split(":")[:2]
        hh, mm = int(hh), int(mm)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"
    except Exception:
        pass
    return None


async def create_habit(
    session: AsyncSession,
    user: User,
    title: str,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    frequency: Optional[str] = None,
    weekdays=None,
    duration_type: Optional[str] = None,
    target_days: Optional[int] = None,
    reminder_time: Optional[str] = None,
    created_by_user_id: Optional[int] = None,
) -> Habit:
    res = await session.execute(
        select(func.coalesce(func.max(Habit.sort_order), 0)).where(Habit.user_id == user.id)
    )
    max_order = res.scalar() or 0

    freq = frequency if frequency in ("daily", "weekly") else "daily"
    dur = duration_type if duration_type in ("permanent", "days") else "permanent"
    tdays = int(target_days) if (dur == "days" and target_days and int(target_days) > 0) else None

    habit = Habit(
        user_id=user.id,
        title=title.strip()[:200],
        description=(description or None),
        icon=(icon or "✅")[:8],
        reminder_time=_normalize_time(reminder_time),
        frequency=freq,
        weekdays=_normalize_weekdays(weekdays) if freq == "weekly" else None,
        duration_type=dur,
        target_days=tdays,
        start_date=_today(),
        sort_order=max_order + 1,
        archived=False,
        created_by_user_id=created_by_user_id,
    )
    session.add(habit)
    await session.commit()
    await session.refresh(habit)
    return habit


async def update_habit(
    session: AsyncSession,
    habit_id: int,
    user_id: int,
    title: Optional[str] = None,
    description: Optional[str] = None,
    icon: Optional[str] = None,
    frequency: Optional[str] = None,
    weekdays=None,
    duration_type: Optional[str] = None,
    target_days: Optional[int] = None,
    reminder_time: Optional[str] = None,
    clear_reminder: bool = False,
) -> Optional[Habit]:
    res = await session.execute(
        select(Habit).where(and_(Habit.id == habit_id, Habit.user_id == user_id))
    )
    habit = res.scalar_one_or_none()
    if not habit:
        return None
    if title is not None:
        habit.title = title.strip()[:200]
    if description is not None:
        habit.description = description or None
    if icon is not None:
        habit.icon = (icon or "✅")[:8]
    if clear_reminder:
        habit.reminder_time = None
    elif reminder_time is not None:
        habit.reminder_time = _normalize_time(reminder_time)
    if frequency is not None and frequency in ("daily", "weekly"):
        habit.frequency = frequency
        if frequency == "daily":
            habit.weekdays = None
    if weekdays is not None and (frequency == "weekly" or habit.frequency == "weekly"):
        habit.weekdays = _normalize_weekdays(weekdays)
    if duration_type is not None and duration_type in ("permanent", "days"):
        habit.duration_type = duration_type
        if duration_type == "permanent":
            habit.target_days = None
    if target_days is not None and (habit.duration_type == "days"):
        habit.target_days = int(target_days) if int(target_days) > 0 else None
    await session.commit()
    await session.refresh(habit)
    return habit


async def delete_habit(session: AsyncSession, habit_id: int, user_id: int) -> bool:
    """Odatni o'chirish — aslida ARXIVLASH.

    Odat o'chirilganda uning barcha tarixiy log'lari (HabitLog) saqlanib qoladi.
    Bu foydalanuvchining umumiy statistikasi (jami ball, XP, streak tarixi)
    o'zgarmasligini kafolatlaydi. Arxivlangan odat foydalanuvchiga ko'rinmaydi
    lekin backend hisobotlarda mavjud bo'lib qoladi.
    """
    res = await session.execute(
        select(Habit).where(and_(Habit.id == habit_id, Habit.user_id == user_id))
    )
    habit = res.scalar_one_or_none()
    if not habit:
        return False
    habit.archived = True
    await session.commit()
    return True


async def toggle_habit_log(
    session: AsyncSession,
    user: User,
    habit_id: int,
    on: Optional[bool] = None,
    target_date: Optional[date] = None,
) -> Optional[dict]:
    """
    Odatni belgilangan kun uchun "bajarildi/bekor" qiladi (toggle).
    Yangilangan odat snapshot'ini qaytaradi (yoki odat topilmasa None).
    """
    res = await session.execute(
        select(Habit).where(and_(Habit.id == habit_id, Habit.user_id == user.id))
    )
    habit = res.scalar_one_or_none()
    if not habit:
        return None

    d = target_date or _today()
    res2 = await session.execute(
        select(HabitLog).where(
            and_(HabitLog.habit_id == habit_id, HabitLog.log_date == d)
        )
    )
    existing = res2.scalars().first()

    if on is None:
        on = existing is None  # toggle

    became_done = False
    changed = False
    if on and existing is None:
        session.add(HabitLog(habit_id=habit_id, user_id=user.id, log_date=d))
        await session.commit()
        became_done = True
        changed = True
    elif not on and existing is not None:
        await session.delete(existing)
        await session.commit()
        changed = True

    # Har qanday o'zgarishdan keyin ball/daraja/discipline qayta hisoblanadi
    # (odat reja/maqsad kabi ball beradi). Done bo'lsa streak ham uzayadi.
    if changed:
        try:
            from bot.services.gamification_service import (
                _update_streak_on_complete, recompute_user_points,
            )
            u = await session.get(User, user.id)
            if u is not None:
                if became_done and d == _today():
                    _update_streak_on_complete(u)
                u.last_active = datetime.utcnow()
                await recompute_user_points(session, u)
                await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass

    return await habit_snapshot(session, habit)


# ─────────────────────────────────────────────────────────────
#  ESLATMALAR UCHUN: bugun rejalashtirilgan, lekin belgilanmagan odatlar
# ─────────────────────────────────────────────────────────────
async def get_due_unchecked_habits(session: AsyncSession, user: User) -> list[Habit]:
    """Bugun bajarilishi kerak (due) bo'lib, hali belgilanmagan odatlar."""
    today = _today()
    habits = await get_user_habits(session, user)
    out = []
    for h in habits:
        if not is_due_on(h, today):
            continue
        done = await session.scalar(
            select(func.count(HabitLog.id)).where(
                and_(HabitLog.habit_id == h.id, HabitLog.log_date == today)
            )
        )
        if not done:
            out.append(h)
    return out


async def get_habits_to_remind_at(session: AsyncSession, hhmm: str) -> list[tuple[Habit, int]]:
    """
    Eslatma vaqti (reminder_time) HOZIRGI vaqtga (HH:MM) teng bo'lgan, bugun due
    va hali belgilanmagan odatlar ro'yxati: (habit, user_id).
    """
    today = _today()
    res = await session.execute(
        select(Habit).where(
            and_(Habit.archived == False, Habit.reminder_time == hhmm)  # noqa: E712
        )
    )
    out = []
    for h in res.scalars().all():
        if not is_due_on(h, today):
            continue
        done = await session.scalar(
            select(func.count(HabitLog.id)).where(
                and_(HabitLog.habit_id == h.id, HabitLog.log_date == today)
            )
        )
        if not done:
            out.append((h, h.user_id))
    return out
