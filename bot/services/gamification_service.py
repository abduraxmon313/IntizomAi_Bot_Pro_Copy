"""
Gamification engine — XP, levels, streaks, discipline score, achievements.

This module is the single source of truth for everything that
makes IntizomAI psychologically sticky:

  • XP curve (sub-quadratic — early wins feel fast, mastery feels earned)
  • Streak update with grace day & freeze tokens
  • Discipline Score (0-100) — emotional "identity" metric
  • Achievement unlock check
  • Rank titles
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.achievement import Achievement
from bot.models.habit import HabitLog
from bot.models.plan import Plan, PlanStatus
from bot.models.score_log import ScoreLog
from bot.models.user import User


async def _done_points_total(session: AsyncSession, user: User) -> int:
    """Jami ball: bajarilgan rejalar ballari + bajarilgan odatlar (har biri uchun
    HABIT_DONE_SCORE). Odatlar ham reja/maqsad kabi ball beradi."""
    from bot.config import HABIT_DONE_SCORE
    plan_total = await session.scalar(
        select(func.coalesce(func.sum(Plan.score_value), 0)).where(
            and_(Plan.user_id == user.id, Plan.status == PlanStatus.done)
        )
    ) or 0
    habit_logs = await session.scalar(
        select(func.count(HabitLog.id)).where(HabitLog.user_id == user.id)
    ) or 0
    return int(plan_total) + int(habit_logs) * int(HABIT_DONE_SCORE)


# ─────────────────────────────────────────────────────────────
#  XP CURVE
# ─────────────────────────────────────────────────────────────
def xp_for_level(level: int) -> int:
    """Total XP required to reach `level` from 1.
    Curve: level 2 = 100, lvl 5 ≈ 700, lvl 10 ≈ 2700, lvl 20 ≈ 10800."""
    if level <= 1:
        return 0
    return int(50 * (level - 1) * level)


def level_for_xp(xp: int) -> int:
    lvl = 1
    while xp >= xp_for_level(lvl + 1):
        lvl += 1
        if lvl > 200:
            break
    return lvl


def xp_progress(xp: int) -> tuple[int, int, int, int]:
    """Returns (level, xp_in_level, xp_needed_for_next, percent_0_100)."""
    lvl = level_for_xp(xp)
    base = xp_for_level(lvl)
    nxt = xp_for_level(lvl + 1)
    in_lvl = xp - base
    needed = max(1, nxt - base)
    pct = max(0, min(100, int(in_lvl * 100 / needed)))
    return lvl, in_lvl, needed, pct


# ─────────────────────────────────────────────────────────────
#  RANK TITLES — identity attachment
# ─────────────────────────────────────────────────────────────
RANKS = [
    (1,  "Boshlovchi",   "🌱"),
    (3,  "O'rganuvchi",  "🔰"),
    (5,  "Faol",         "⚡"),
    (8,  "Izchil",       "🔥"),
    (12, "Intizomli",    "💎"),
    (18, "Ustoz",        "🏆"),
    (25, "Afsona",       "👑"),
    (35, "Mifik",        "🌌"),
]


def rank_for_level(level: int) -> tuple[str, str]:
    title, emoji = RANKS[0][1], RANKS[0][2]
    for lvl_min, t, e in RANKS:
        if level >= lvl_min:
            title, emoji = t, e
    return title, emoji


# ─────────────────────────────────────────────────────────────
#  ACHIEVEMENTS catalogue
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AchDef:
    code: str
    title: str
    icon: str
    rarity: str = "common"  # common | rare | epic | legendary


ACHIEVEMENTS: list[AchDef] = [
    AchDef("first_step",   "Birinchi qadam",  "🌱", "common"),
    AchDef("streak_3",     "Olov yondi",      "🔥", "common"),
    AchDef("streak_7",     "Bir hafta",       "⚡", "rare"),
    AchDef("streak_14",    "Ikki hafta",      "💪", "rare"),
    AchDef("streak_30",    "Bir oy",          "💎", "epic"),
    AchDef("streak_100",   "Yuz kun",         "🌌", "legendary"),
    AchDef("level_5",      "5-daraja",        "⭐", "common"),
    AchDef("level_10",     "10-daraja",       "🌟", "rare"),
    AchDef("level_25",     "25-daraja",       "👑", "epic"),
    AchDef("perfect_day",  "Mukammal kun",    "✨", "rare"),
    AchDef("early_bird",   "Erta qush",       "🌅", "common"),
    AchDef("night_owl",    "Tungi ishchi",    "🌙", "common"),
    AchDef("100_done",     "100 ta bajarildi","🎯", "rare"),
    AchDef("500_done",     "500 ta bajarildi","🏆", "epic"),
    AchDef("comeback",     "Qaytdim",         "🔄", "rare"),
]
ACH_INDEX = {a.code: a for a in ACHIEVEMENTS}


# ─────────────────────────────────────────────────────────────
#  Result type
# ─────────────────────────────────────────────────────────────
@dataclass
class CompletionReward:
    xp_gained: int = 0
    score_change: int = 0
    leveled_up: bool = False
    new_level: int = 1
    streak_extended: bool = False
    new_streak: int = 0
    new_unlocks: list[Achievement] = field(default_factory=list)
    discipline_score: int = 50
    perfect_day: bool = False


# ─────────────────────────────────────────────────────────────
#  STREAK
# ─────────────────────────────────────────────────────────────
def _today() -> date:
    return datetime.now(TIMEZONE).date()


def _update_streak_on_complete(user: User) -> bool:
    """Returns True when the streak was extended (i.e. first complete today)."""
    today = _today()
    last = user.last_completed_date

    if last == today:
        return False  # already counted today

    if last is None:
        user.streak = 1
    elif last == today - timedelta(days=1):
        user.streak += 1
    elif last == today - timedelta(days=2) and user.streak_freezes > 0:
        # auto-burn one freeze for a single missed day
        user.streak_freezes -= 1
        user.streak += 1
    else:
        user.streak = 1

    user.last_completed_date = today
    if user.streak > (user.longest_streak or 0):
        user.longest_streak = user.streak
    return True


# ─────────────────────────────────────────────────────────────
#  DISCIPLINE SCORE 0..100
# ─────────────────────────────────────────────────────────────
async def _recompute_discipline_score(session: AsyncSession, user: User) -> int:
    """
    Discipline score = weighted blend of:
      • 30-day completion rate (50%)
      • current streak vs 30 cap (25%)
      • 7-day activity intensity (15%)
      • inactivity penalty (10%)
    """
    today = _today()
    window_start = today - timedelta(days=29)

    res = await session.execute(
        select(Plan).where(
            and_(
                Plan.user_id == user.id,
                Plan.plan_date >= window_start,
                Plan.plan_date <= today,
            )
        )
    )
    plans = res.scalars().all()

    total = len(plans)
    done = sum(1 for p in plans if p.status == PlanStatus.done)
    completion_rate = (done / total) if total else 0.0

    streak_norm = min(1.0, (user.streak or 0) / 30.0)

    last7 = today - timedelta(days=6)
    last7_done = sum(
        1 for p in plans if p.plan_date >= last7 and p.status == PlanStatus.done
    )
    intensity = min(1.0, last7_done / 14.0)  # 2/day saturates

    # Inactivity penalty
    if user.last_completed_date is None:
        inactivity = 0.0
    else:
        days_idle = (today - user.last_completed_date).days
        inactivity = max(0.0, 1.0 - (days_idle / 7.0))

    score = (
        completion_rate * 50
        + streak_norm * 25
        + intensity * 15
        + inactivity * 10
    )
    score_int = int(round(max(0, min(100, score))))
    user.discipline_score = score_int
    return score_int


# ─────────────────────────────────────────────────────────────
#  ACHIEVEMENTS unlock detection
# ─────────────────────────────────────────────────────────────
async def _user_unlocked_codes(session: AsyncSession, user: User) -> set[str]:
    res = await session.execute(
        select(Achievement.code).where(Achievement.user_id == user.id)
    )
    return set(res.scalars().all())


async def _check_unlocks(session: AsyncSession, user: User) -> list[Achievement]:
    today = _today()
    unlocked = await _user_unlocked_codes(session, user)
    new: list[AchDef] = []

    if user.streak >= 1 and "first_step" not in unlocked:
        new.append(ACH_INDEX["first_step"])
    if user.streak >= 3 and "streak_3" not in unlocked:
        new.append(ACH_INDEX["streak_3"])
    if user.streak >= 7 and "streak_7" not in unlocked:
        new.append(ACH_INDEX["streak_7"])
    if user.streak >= 14 and "streak_14" not in unlocked:
        new.append(ACH_INDEX["streak_14"])
    if user.streak >= 30 and "streak_30" not in unlocked:
        new.append(ACH_INDEX["streak_30"])
    if user.streak >= 100 and "streak_100" not in unlocked:
        new.append(ACH_INDEX["streak_100"])

    if user.level >= 5 and "level_5" not in unlocked:
        new.append(ACH_INDEX["level_5"])
    if user.level >= 10 and "level_10" not in unlocked:
        new.append(ACH_INDEX["level_10"])
    if user.level >= 25 and "level_25" not in unlocked:
        new.append(ACH_INDEX["level_25"])

    # Total done plans
    done_total = await session.scalar(
        select(func.count(Plan.id)).where(
            and_(Plan.user_id == user.id, Plan.status == PlanStatus.done)
        )
    ) or 0
    if done_total >= 100 and "100_done" not in unlocked:
        new.append(ACH_INDEX["100_done"])
    if done_total >= 500 and "500_done" not in unlocked:
        new.append(ACH_INDEX["500_done"])

    # Time-of-day cosmetic
    hour = datetime.now(TIMEZONE).hour
    if hour < 7 and "early_bird" not in unlocked:
        new.append(ACH_INDEX["early_bird"])
    if hour >= 22 and "night_owl" not in unlocked:
        new.append(ACH_INDEX["night_owl"])

    rows: list[Achievement] = []
    for d in new:
        row = Achievement(
            user_id=user.id,
            code=d.code, title=d.title, icon=d.icon, rarity=d.rarity,
        )
        session.add(row)
        rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────
#  XP recompute (deterministic — no drift across toggles)
# ─────────────────────────────────────────────────────────────
async def _recompute_xp_and_score(session: AsyncSession, user: User) -> None:
    """XP va total_score ni BARCHA bajarilgan reja va odatlardan deterministik
    tiklaydi. Shu tufayli done<->failed<->pending o'zgarishlarida drift bo'lmaydi."""
    total = await _done_points_total(session, user)
    user.xp = total
    user.total_score = total
    user.level = level_for_xp(total)
    title, emoji = rank_for_level(user.level)
    user.rank_title = title
    user.avatar_emoji = emoji


async def recompute_user_points(session: AsyncSession, user: User) -> None:
    """Odat belgilangach (yoki bekor qilingach) ball/daraja/discipline'ni qayta hisoblaydi."""
    await _recompute_xp_and_score(session, user)
    await _recompute_discipline_score(session, user)


# ─────────────────────────────────────────────────────────────
#  PUBLIC: set plan status (toggle/re-mark) — RELIABLE
# ─────────────────────────────────────────────────────────────
async def _run_gamification(user_id: int, became_done: bool) -> CompletionReward:
    """
    Gamification hisob-kitobi — ALOHIDA, izolyatsiya qilingan sessiyada.
    Bu yerda har qanday xato bo'lsa, u request sessiyasiga ta'sir qilmaydi.
    """
    out = CompletionReward()
    from database.db import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        u = await s.get(User, user_id)
        if u is None:
            return out
        out.new_level = u.level or 1
        out.new_streak = u.streak or 0
        prev_level = u.level or 1

        if became_done:
            out.streak_extended = _update_streak_on_complete(u)
            out.new_streak = u.streak
        u.last_active = datetime.utcnow()

        # ── XP/streak/discipline — ENG MUHIM, alohida commit ──
        await _recompute_xp_and_score(s, u)
        out.new_level = u.level
        out.leveled_up = u.level > prev_level
        out.discipline_score = await _recompute_discipline_score(s, u)
        await s.commit()

        # ── Perfect day + achievements — best-effort, alohida commit ──
        # (Bu yerda xato bo'lsa ham yuqoridagi XP/streak saqlanib qoladi.)
        if became_done:
            try:
                today = _today()
                pending_today = await s.scalar(
                    select(func.count(Plan.id)).where(
                        and_(
                            Plan.user_id == u.id,
                            Plan.plan_date == today,
                            Plan.status == PlanStatus.pending,
                        )
                    )
                ) or 0
                total_today = await s.scalar(
                    select(func.count(Plan.id)).where(
                        and_(Plan.user_id == u.id, Plan.plan_date == today)
                    )
                ) or 0
                if total_today >= 1 and pending_today == 0:
                    out.perfect_day = True
                    u.perfect_days = (u.perfect_days or 0) + 1
                    existing = await s.scalar(
                        select(Achievement).where(
                            and_(Achievement.user_id == u.id,
                                 Achievement.code == "perfect_day")
                        )
                    )
                    if not existing:
                        s.add(Achievement(
                            user_id=u.id, code="perfect_day",
                            title="Mukammal kun", icon="✨", rarity="rare",
                        ))
                more = await _check_unlocks(s, u)
                out.new_unlocks.extend(more)
                await s.commit()
            except Exception:
                await s.rollback()
    return out


async def set_plan_status(
    session: AsyncSession,
    user: User,
    plan: Plan,
    new_status: PlanStatus,
) -> CompletionReward:
    """
    Rejani istalgan holatga o'tkazadi (pending/done/failed) — toggle/qayta belgilash.

    MAQSADLAR (update_goal) bilan bir xil ishonchli struktura:
      1-QADAM: statusni o'zgartirish + ScoreLog — request sessiyasida BITTA commit.
               (sodda va ishonchli, doim muvaffaqiyatli, huddi maqsadlardagidek.)
      2-QADAM: XP/streak/discipline/achievements — ALOHIDA izolyatsiya qilingan
               sessiyada. U yerdagi xato request sessiyasiga ta'sir qilmaydi,
               shuning uchun toggle/belgilash HAR DOIM ishlaydi.
    """
    out = CompletionReward()
    out.new_level = user.level or 1
    out.new_streak = user.streak or 0
    out.discipline_score = user.discipline_score or 50

    if plan.status == new_status:
        return out

    became_done = (new_status == PlanStatus.done)
    base = max(1, plan.score_value or 5)

    # ── 1-QADAM: sodda status o'zgarishi (update_goal kabi) ──────────────
    plan.status = new_status
    if new_status == PlanStatus.done:
        out.xp_gained = base
        out.score_change = base
        session.add(ScoreLog(
            user_id=user.id, plan_id=plan.id, score_change=base,
            reason=f"✅ '{plan.title}' bajarildi",
        ))
    elif new_status == PlanStatus.failed:
        out.score_change = -3
        session.add(ScoreLog(
            user_id=user.id, plan_id=plan.id, score_change=-3,
            reason=f"❌ '{plan.title}' bajarilmadi",
        ))
    await session.commit()
    await session.refresh(plan)

    # ── 2-QADAM: gamification — alohida sessiyada (xato bo'lsa yutiladi) ──
    try:
        reward = await _run_gamification(user.id, became_done)
        out.xp_gained = out.xp_gained or reward.xp_gained
        out.new_level = reward.new_level
        out.leveled_up = reward.leveled_up
        out.streak_extended = reward.streak_extended
        out.new_streak = reward.new_streak
        out.new_unlocks = reward.new_unlocks
        out.discipline_score = reward.discipline_score
        out.perfect_day = reward.perfect_day
        # request sessiyadagi user'ni yangilab qo'yamiz
        try:
            await session.refresh(user)
        except Exception:
            pass
    except Exception:
        pass

    return out


async def reward_completion(
    session: AsyncSession,
    user: User,
    plan: Plan,
    is_done: bool,
) -> CompletionReward:
    """Backward-compat shim — har qanday holat o'tishini set_plan_status bajaradi."""
    return await set_plan_status(
        session, user, plan,
        PlanStatus.done if is_done else PlanStatus.failed,
    )


# ─────────────────────────────────────────────────────────────
#  BACKFILL — eski (gamification'dan oldingi) aktivlikni tiklash
# ─────────────────────────────────────────────────────────────
async def _backfill_user_stats(session: AsyncSession, user: User) -> None:
    """
    Agar foydalanuvchining bajarilgan rejalari bo'lsa-yu, lekin XP hali
    hisoblanmagan bo'lsa (0), mavjud bajarilgan rejalardan XP, daraja,
    total_score, streak va discipline score'ni qayta tiklaydi.

    Bu faqat bir marta ishlaydi (XP > 0 bo'lgach qayta hisoblamaydi),
    shuning uchun har bir foydalanuvchining qiymati o'ziga mos bo'ladi.
    """
    if (user.xp or 0) > 0:
        return  # allaqachon hisoblangan — tegmaymiz

    # Barcha bajarilgan rejalar
    res = await session.execute(
        select(Plan).where(
            and_(Plan.user_id == user.id, Plan.status == PlanStatus.done)
        )
    )
    done_plans = res.scalars().all()
    if not done_plans:
        # bajarilgan reja yo'q — faqat discipline'ni yangilab qo'yamiz
        await _recompute_discipline_score(session, user)
        return

    # XP va total_score ni bajarilgan rejalardan tiklaymiz
    total_xp = sum(max(1, p.score_value or 5) for p in done_plans)
    user.xp = total_xp
    user.total_score = max(user.total_score or 0, total_xp)
    user.level = level_for_xp(user.xp)

    title, emoji = rank_for_level(user.level)
    user.rank_title = title
    user.avatar_emoji = emoji

    # Streak'ni bajarilgan kunlardan tiklaymiz
    done_dates = sorted({p.plan_date for p in done_plans if p.plan_date})
    if done_dates:
        user.last_completed_date = done_dates[-1]
        # ketma-ket kunlar bo'yicha eng uzun joriy streak
        today = _today()
        streak = 0
        cursor = done_dates[-1]
        date_set = set(done_dates)
        # faqat oxirgi kun bugun yoki kecha bo'lsa joriy streak hisoblanadi
        if cursor >= today - timedelta(days=1):
            d = cursor
            while d in date_set:
                streak += 1
                d = d - timedelta(days=1)
        user.streak = streak
        user.longest_streak = max(user.longest_streak or 0, streak)

    await session.flush()
    await _recompute_discipline_score(session, user)
    await session.commit()


# ─────────────────────────────────────────────────────────────
#  PUBLIC: snapshot for webapp
# ─────────────────────────────────────────────────────────────
async def _backfill_user_stats_isolated(user_id: int) -> None:
    """Backfill ALOHIDA sessiyada — request sessiyasini buzmasligi uchun."""
    from database.db import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as s:
            u = await s.get(User, user_id)
            if u is None or (u.xp or 0) > 0:
                return
            res = await s.execute(
                select(Plan).where(
                    and_(Plan.user_id == u.id, Plan.status == PlanStatus.done)
                )
            )
            done_plans = res.scalars().all()
            if not done_plans:
                await _recompute_discipline_score(s, u)
                await s.commit()
                return
            total_xp = sum(max(1, p.score_value or 5) for p in done_plans)
            u.xp = total_xp
            u.total_score = max(u.total_score or 0, total_xp)
            u.level = level_for_xp(u.xp)
            title, emoji = rank_for_level(u.level)
            u.rank_title = title
            u.avatar_emoji = emoji
            done_dates = sorted({p.plan_date for p in done_plans if p.plan_date})
            if done_dates:
                u.last_completed_date = done_dates[-1]
                today = _today()
                streak = 0
                date_set = set(done_dates)
                if done_dates[-1] >= today - timedelta(days=1):
                    d = done_dates[-1]
                    while d in date_set:
                        streak += 1
                        d = d - timedelta(days=1)
                u.streak = streak
                u.longest_streak = max(u.longest_streak or 0, streak)
            await _recompute_discipline_score(s, u)
            await s.commit()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
#  PUBLIC: snapshot for webapp
# ─────────────────────────────────────────────────────────────
async def _reconcile_user_stats(session: AsyncSession, user: User) -> None:
    """
    Foydalanuvchi statistikasini HAQIQIY manbadan (bajarilgan rejalar) qayta
    hisoblab, request sessiyasida saqlaydi. Bu funksiya snapshot har chaqirilganda
    ishlaydi va xp/total_score/level/discipline ni doim moslashtiradi — shu tufayli
    "xp=0 lekin total_score=55" kabi nomuvofiqliklar bo'lmaydi.

    Avvalgi versiyada bu ALOHIDA sessiyada (`_backfill_user_stats_isolated`) va faqat
    `xp==0` bo'lganda bajarilardi; nested sessiya/skip mantig'i ba'zan snapshot'ni
    buzib, frontendda default qiymatlar (0 XP, 50 discipline, 0/0) ko'rinardi.
    """
    # XP / total_score / level / rank — bajarilgan reja va odatlar yig'indisidan
    total = await _done_points_total(session, user)
    total = int(total)
    user.xp = total
    user.total_score = total
    user.level = level_for_xp(total)
    title, emoji = rank_for_level(user.level)
    user.rank_title = title
    user.avatar_emoji = emoji

    # Streak — agar hech qachon hisoblanmagan bo'lsa (last_completed_date None),
    # bajarilgan rejalar sanalaridan joriy streak'ni tiklaymiz.
    if user.last_completed_date is None:
        res = await session.execute(
            select(Plan.plan_date).where(
                and_(Plan.user_id == user.id, Plan.status == PlanStatus.done)
            )
        )
        done_dates = sorted({d for d in res.scalars().all() if d})
        if done_dates:
            today = _today()
            user.last_completed_date = done_dates[-1]
            date_set = set(done_dates)
            streak = 0
            if done_dates[-1] >= today - timedelta(days=1):
                d = done_dates[-1]
                while d in date_set:
                    streak += 1
                    d = d - timedelta(days=1)
            user.streak = streak
            user.longest_streak = max(user.longest_streak or 0, streak)

    await _recompute_discipline_score(session, user)


async def build_user_snapshot(session: AsyncSession, user: User) -> dict:
    """
    Webapp uchun foydalanuvchi holatini qaytaradi.

    MUHIM: bu funksiya HECH QACHON xato ko'tarmasligi kerak — aks holda
    frontend hero default qiymatlarni (0 XP, 50 discipline, 0/0 bugun)
    ko'rsatib qoladi. Shuning uchun har bir bosqich himoyalangan.
    """
    # 1) Statistikani moslashtirish (xp/score/level/discipline) — best-effort.
    try:
        await _reconcile_user_stats(session, user)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        try:
            await session.refresh(user)
        except Exception:
            pass

    lvl, in_lvl, needed, pct = xp_progress(user.xp or 0)
    title, emoji = rank_for_level(lvl)

    today = _today()

    # 2) Bugungi rejalar — alohida himoyalangan (xato bo'lsa ham snapshot qaytadi).
    today_done = 0
    today_total = 0
    try:
        res = await session.execute(
            select(Plan).where(
                and_(Plan.user_id == user.id, Plan.plan_date == today)
            )
        )
        today_plans = res.scalars().all()
        today_total = len(today_plans)
        today_done = sum(1 for p in today_plans if p.status == PlanStatus.done)
    except Exception:
        pass

    # 3) Yutuqlar — alohida himoyalangan.
    achievements = []
    try:
        achs_res = await session.execute(
            select(Achievement)
            .where(Achievement.user_id == user.id)
            .order_by(Achievement.unlocked_at.desc())
        )
        achievements = [
            {
                "code": a.code,
                "title": a.title,
                "icon": a.icon,
                "rarity": a.rarity,
                "unlocked_at": a.unlocked_at.isoformat() if a.unlocked_at else None,
            }
            for a in achs_res.scalars().all()
        ]
    except Exception:
        pass

    # Streak status: at_risk if last completed wasn't today
    risk = (
        user.last_completed_date is None
        or user.last_completed_date < today
    )

    return {
        "level": lvl,
        "xp": user.xp or 0,
        "total_score": user.total_score or 0,
        "xp_in_level": in_lvl,
        "xp_needed": needed,
        "xp_percent": pct,
        "streak": user.streak or 0,
        "longest_streak": user.longest_streak or 0,
        "streak_at_risk": risk,
        "streak_freezes": user.streak_freezes or 0,
        "discipline_score": user.discipline_score or 50,
        "rank_title": title,
        "rank_emoji": emoji,
        "is_premium": bool(user.premium_until and user.premium_until > datetime.utcnow()),
        "perfect_days": user.perfect_days or 0,
        "today_done": today_done,
        "today_total": today_total,
        "today_completion_pct": (
            int(today_done * 100 / today_total) if today_total else 0
        ),
        "achievements": achievements,
    }
