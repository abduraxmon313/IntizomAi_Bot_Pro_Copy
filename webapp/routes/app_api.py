"""
Mobil ilova (Flutter) uchun REST API endpointlari.

Barcha endpoint'lar JWT token bilan autentifikatsiya qilinadi.
Token bot /start app_login orqali olinadi.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from bot.models.goal import Goal
from bot.models.habit import Habit, HabitLog
from bot.models.plan import Plan, PlanStatus
from bot.models.user import User
from bot.services.app_auth import verify_app_token
from database.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Mobile App API"])


# ── Auth dependency ───────────────────────────────────────
async def get_app_user_id(authorization: str = Header(default="")) -> int:
    """Bearer token'dan user_id ajratib oladi."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Token kerak")
    payload = verify_app_token(token)
    if payload is None:
        raise HTTPException(401, "Token noto'g'ri yoki muddati o'tgan")
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Token noto'g'ri")
    return int(user_id)


async def get_app_db():
    async with AsyncSessionLocal() as session:
        yield session


# ── Pydantic sxemalar ────────────────────────────────────
class PlanCreate(BaseModel):
    title: str
    description: Optional[str] = None
    scheduled_time: Optional[str] = None
    plan_date: str


class PlanStatusUpdate(BaseModel):
    status: str


class HabitCreate(BaseModel):
    title: str
    description: Optional[str] = None
    icon: str = "✅"
    frequency: str = "daily"
    weekdays: Optional[str] = None
    reminder_time: Optional[str] = None


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    goal_type: str = "yearly"
    period: Optional[str] = None


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    notifications_enabled: Optional[bool] = None


# ── Helpers ───────────────────────────────────────────────
def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "telegram_id": u.telegram_id,
        "full_name": u.full_name,
        "display_name": u.display_name,
        "username": u.username,
        "photo_url": u.photo_url,
        "custom_photo_url": u.custom_photo_url,
        "streak": u.streak or 0,
        "total_score": u.total_score or 0,
        "xp": u.xp or 0,
        "level": u.level or 1,
        "longest_streak": u.longest_streak or 0,
        "streak_freezes": u.streak_freezes or 0,
        "discipline_score": u.discipline_score or 50,
        "weekly_xp": u.weekly_xp or 0,
        "perfect_days": u.perfect_days or 0,
        "is_premium": u.is_premium or False,
        "premium_until": str(u.premium_until) if u.premium_until else None,
        "onboarded": u.onboarded or False,
        "rank_title": u.rank_title,
        "avatar_emoji": u.avatar_emoji or "🌱",
        "referral_count": u.referral_count or 0,
        "is_active": u.is_active if u.is_active is not None else True,
        "notifications_enabled": u.notifications_enabled if u.notifications_enabled is not None else True,
        "created_at": str(u.created_at) if u.created_at else None,
    }


def _plan_dict(p: Plan) -> dict:
    return {
        "id": p.id,
        "user_id": p.user_id,
        "title": p.title,
        "description": p.description,
        "scheduled_time": p.scheduled_time,
        "plan_date": str(p.plan_date),
        "status": p.status.value if hasattr(p.status, 'value') else str(p.status or "pending"),
        "score_value": p.score_value or 5,
        "created_by_user_id": p.created_by_user_id,
    }


def _habit_dict(h: Habit) -> dict:
    return {
        "id": h.id,
        "user_id": h.user_id,
        "title": h.title,
        "description": h.description,
        "icon": h.icon or "✅",
        "reminder_time": h.reminder_time,
        "frequency": h.frequency or "daily",
        "weekdays": h.weekdays,
        "duration_type": h.duration_type or "permanent",
        "target_days": h.target_days,
        "start_date": str(h.start_date) if h.start_date else None,
        "sort_order": h.sort_order or 0,
        "archived": h.archived or False,
    }


def _goal_dict(g: Goal) -> dict:
    return {
        "id": g.id,
        "user_id": g.user_id,
        "title": g.title,
        "description": g.description,
        "goal_type": g.goal_type or "yearly",
        "period": g.period,
        "completed": g.completed or False,
    }


def _smart_message(user: User) -> str:
    """Foydalanuvchi holatiga qarab motivatsion xabar."""
    streak = user.streak or 0
    disc = user.discipline_score or 50
    if streak == 0:
        return "Bugun birinchi qadamni qo'ying! Har bir sayohat bitta qadam bilan boshlanadi 🌱"
    if streak >= 30:
        return f"Ajoyib! {streak} kunlik streak — siz haqiqiy intizom namunasisiz! 💎🔥"
    if streak >= 7:
        return f"{streak} kun ketma-ket — zo'r natija! Davom eting! 🔥"
    if disc >= 70:
        return "Intizom darajangiz yuqori — shu ruhda davom eting! ⚡"
    if disc < 40:
        return "Kichik qadamlar katta natija beradi. Bugun bitta ish bajaring! 💪"
    return f"Streak: {streak} kun. Bugun ham davom eting! 🎯"


# ══════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════

# ── User / Profile ──
@router.get("/user/profile")
async def get_profile(
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return _user_dict(user)


@router.patch("/user/profile")
async def update_profile(
    body: ProfileUpdate,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.notifications_enabled is not None:
        user.notifications_enabled = body.notifications_enabled
    await db.commit()
    return _user_dict(user)


@router.get("/user/dashboard")
async def get_dashboard(
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    today = date.today()
    plans_q = await db.execute(
        select(Plan).where(and_(Plan.user_id == user_id, Plan.plan_date == today))
    )
    plans = plans_q.scalars().all()
    done = sum(1 for p in plans if p.status == PlanStatus.done)
    return {
        "user": _user_dict(user),
        "today_plans_done": done,
        "today_plans_total": len(plans),
    }


# ── Plans ──
@router.get("/plans/today")
async def get_today_plans(
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    today = date.today()
    res = await db.execute(
        select(Plan)
        .where(and_(Plan.user_id == user_id, Plan.plan_date == today))
        .order_by(Plan.scheduled_time.asc().nullslast(), Plan.id)
    )
    return [_plan_dict(p) for p in res.scalars().all()]


@router.get("/plans")
async def get_plans_by_date(
    date: str = "",
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    from datetime import date as dt_date
    target = dt_date.fromisoformat(date) if date else dt_date.today()
    res = await db.execute(
        select(Plan)
        .where(and_(Plan.user_id == user_id, Plan.plan_date == target))
        .order_by(Plan.scheduled_time.asc().nullslast(), Plan.id)
    )
    return [_plan_dict(p) for p in res.scalars().all()]


@router.post("/plans")
async def create_plan(
    body: PlanCreate,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    from datetime import date as dt_date
    plan = Plan(
        user_id=user_id,
        title=body.title,
        description=body.description,
        scheduled_time=body.scheduled_time,
        plan_date=dt_date.fromisoformat(body.plan_date),
        status=PlanStatus.pending,
        score_value=5,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return _plan_dict(plan)


@router.patch("/plans/{plan_id}/status")
async def set_plan_status(
    plan_id: int,
    body: PlanStatusUpdate,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    plan = await db.get(Plan, plan_id)
    if not plan or plan.user_id != user_id:
        raise HTTPException(404, "Reja topilmadi")
    if body.status not in ("done", "pending", "failed"):
        raise HTTPException(400, "Noto'g'ri status")

    # Gamification: status done bo'lganda ball yangilash
    became_done = body.status == "done" and plan.status != PlanStatus.done
    plan.status = PlanStatus(body.status)
    await db.commit()

    if became_done:
        try:
            from bot.services.gamification_service import _run_gamification
            await _run_gamification(user_id, True)
        except Exception:
            logger.warning(f"gamification xato (plan {plan_id})", exc_info=True)

    await db.refresh(plan)
    return _plan_dict(plan)


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: int,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    plan = await db.get(Plan, plan_id)
    if not plan or plan.user_id != user_id:
        raise HTTPException(404, "Reja topilmadi")
    await db.delete(plan)
    await db.commit()
    return {"ok": True}


@router.post("/plans/{plan_id}/move-tomorrow")
async def move_plan_tomorrow(
    plan_id: int,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    plan = await db.get(Plan, plan_id)
    if not plan or plan.user_id != user_id:
        raise HTTPException(404, "Reja topilmadi")
    plan.plan_date = plan.plan_date + timedelta(days=1)
    plan.status = PlanStatus.pending
    await db.commit()
    return _plan_dict(plan)


# ── Habits ──
@router.get("/habits")
async def get_habits(
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    today = date.today()
    res = await db.execute(
        select(Habit).where(Habit.user_id == user_id).order_by(Habit.sort_order, Habit.id)
    )
    habits = res.scalars().all()
    logs_res = await db.execute(
        select(HabitLog.habit_id).where(
            and_(HabitLog.user_id == user_id, HabitLog.log_date == today)
        )
    )
    done_ids = {row[0] for row in logs_res.all()}

    result = []
    for h in habits:
        d = _habit_dict(h)
        d["today_done"] = h.id in done_ids
        # Odat streak hisoblash (oddiy)
        d["current_streak"] = 0
        result.append(d)
    return result


@router.post("/habits")
async def create_habit(
    body: HabitCreate,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    habit = Habit(
        user_id=user_id,
        title=body.title,
        description=body.description,
        icon=body.icon,
        frequency=body.frequency,
        weekdays=body.weekdays,
        reminder_time=body.reminder_time,
    )
    db.add(habit)
    await db.commit()
    await db.refresh(habit)
    d = _habit_dict(habit)
    d["today_done"] = False
    d["current_streak"] = 0
    return d


@router.post("/habits/{habit_id}/toggle")
async def toggle_habit(
    habit_id: int,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    habit = await db.get(Habit, habit_id)
    if not habit or habit.user_id != user_id:
        raise HTTPException(404, "Odat topilmadi")

    today = date.today()
    existing = await db.execute(
        select(HabitLog).where(
            and_(HabitLog.habit_id == habit_id, HabitLog.log_date == today)
        )
    )
    log = existing.scalar_one_or_none()
    if log:
        await db.delete(log)
        today_done = False
    else:
        db.add(HabitLog(habit_id=habit_id, user_id=user_id, log_date=today))
        today_done = True
    await db.commit()

    # Gamification yangilash
    if today_done:
        try:
            from bot.services.gamification_service import recompute_user_points
            user = await db.get(User, user_id)
            if user:
                await recompute_user_points(db, user)
                await db.commit()
        except Exception:
            logger.warning(f"gamification xato (habit {habit_id})", exc_info=True)

    d = _habit_dict(habit)
    d["today_done"] = today_done
    d["current_streak"] = 0
    return d


@router.patch("/habits/{habit_id}")
async def update_habit(
    habit_id: int,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    habit = await db.get(Habit, habit_id)
    if not habit or habit.user_id != user_id:
        raise HTTPException(404, "Odat topilmadi")
    habit.archived = True
    await db.commit()
    d = _habit_dict(habit)
    d["today_done"] = False
    d["current_streak"] = 0
    return d


@router.delete("/habits/{habit_id}")
async def delete_habit(
    habit_id: int,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    habit = await db.get(Habit, habit_id)
    if not habit or habit.user_id != user_id:
        raise HTTPException(404, "Odat topilmadi")
    await db.delete(habit)
    await db.commit()
    return {"ok": True}


# ── Goals ──
@router.get("/goals")
async def get_goals(
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    res = await db.execute(
        select(Goal).where(Goal.user_id == user_id).order_by(Goal.id.desc())
    )
    return [_goal_dict(g) for g in res.scalars().all()]


@router.post("/goals")
async def create_goal(
    body: GoalCreate,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    goal = Goal(
        user_id=user_id,
        title=body.title,
        description=body.description,
        goal_type=body.goal_type,
        period=body.period,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return _goal_dict(goal)


@router.post("/goals/{goal_id}/toggle")
async def toggle_goal(
    goal_id: int,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    goal = await db.get(Goal, goal_id)
    if not goal or goal.user_id != user_id:
        raise HTTPException(404, "Maqsad topilmadi")
    goal.completed = not goal.completed
    await db.commit()
    return _goal_dict(goal)


@router.delete("/goals/{goal_id}")
async def delete_goal(
    goal_id: int,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    goal = await db.get(Goal, goal_id)
    if not goal or goal.user_id != user_id:
        raise HTTPException(404, "Maqsad topilmadi")
    await db.delete(goal)
    await db.commit()
    return {"ok": True}


# ── Coach ──
@router.get("/coach/smart-message")
async def get_smart_message(
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    return {"message": _smart_message(user)}


@router.post("/coach/message")
async def send_coach_message(
    body: dict,
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    """AI Coach'ga xabar yuborish."""
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "Xabar bo'sh")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)

    try:
        from bot.services.ai_service import ai_coach_reply
        reply = await ai_coach_reply(db, user, message)
        return {"reply": reply, "remaining": 99 if user.is_premium else max(0, 3 - (user.ai_msgs_count or 0))}
    except Exception as e:
        logger.warning(f"AI coach xato: {e}", exc_info=True)
        return {"reply": _smart_message(user), "remaining": 0}


@router.get("/coach/history")
async def get_coach_history(
    user_id: int = Depends(get_app_user_id),
    db: AsyncSession = Depends(get_app_db),
):
    # Hozircha bo'sh — kelajakda suhbat tarixini saqlash mumkin
    return []
