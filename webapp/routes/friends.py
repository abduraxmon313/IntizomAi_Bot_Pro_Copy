"""
Do'stlar (Friends / Groups) API — jamoaviy intizom.

Barcha endpoint'lar `/api/webapp/friends/...` prefiksida yashaydi.

Xavfsizlik: har bir endpoint `resolve_telegram_id` orqali autentifikatsiya
qiladi. Guruh a'zoligi va ruxsat tekshiruvlari `group_service` ichida.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.goal_service import (
    ALLOWED_GOAL_TYPES,
    InvalidGoalTypeError,
    create_goal,
)
from bot.services.group_service import (
    GROUP_INVITE_PREFIX,
    GroupError,
    GroupForbidden,
    GroupNotFound,
    create_group,
    delete_group,
    ensure_can_manage,
    get_group_detail,
    get_member_view,
    join_by_code,
    leave_group,
    list_my_groups,
    list_permissions,
    rename_group,
    set_permission,
)
from bot.services.habit_service import create_habit
from bot.services.plan_service import create_plan_single
from bot.services.premium_service import (
    check_goal_limit,
    check_habit_limit,
    check_plan_limit,
)
from bot.services.user_service import get_user_by_telegram_id
from database.db import AsyncSessionLocal
from webapp.security import resolve_telegram_id

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


# ─────────────────────────────────────────────────────────────
#  DTOs
# ─────────────────────────────────────────────────────────────
class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


class GroupPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PermissionUpdate(BaseModel):
    can_manage: bool


class PlanCreateForMember(BaseModel):
    title: str
    description: Optional[str] = None
    scheduled_time: Optional[str] = None
    plan_date: Optional[str] = None


class GoalCreateForMember(BaseModel):
    title: str
    description: Optional[str] = None
    goal_type: str  # yearly | monthly
    period: str


class HabitCreateForMember(BaseModel):
    title: str
    description: Optional[str] = None
    icon: Optional[str] = None
    frequency: Optional[str] = None
    weekdays: Optional[list[int]] = None
    duration_type: Optional[str] = None
    target_days: Optional[int] = None
    reminder_time: Optional[str] = None


# ─────────────────────────────────────────────────────────────
#  ORQAGA XATO XARITASI
# ─────────────────────────────────────────────────────────────
def _map_group_error(e: Exception) -> HTTPException:
    if isinstance(e, GroupNotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, GroupForbidden):
        return HTTPException(status_code=403, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


async def _require_user(session: AsyncSession, telegram_id: int):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")
    return user


# ─────────────────────────────────────────────────────────────
#  GURUHLAR
# ─────────────────────────────────────────────────────────────
@router.get("/friends/groups")
async def list_groups(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    groups = await list_my_groups(session, user)
    return {"groups": groups, "invite_prefix": GROUP_INVITE_PREFIX}


@router.post("/friends/groups")
async def create_group_api(
    body: GroupCreate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        g = await create_group(session, user, body.name, body.description)
    except GroupError as e:
        raise _map_group_error(e)
    return {
        "id": g.id, "name": g.name, "description": g.description,
        "invite_code": g.invite_code, "is_owner": True,
    }


@router.get("/friends/groups/{group_id}")
async def group_detail_api(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        return await get_group_detail(session, user, group_id)
    except GroupError as e:
        raise _map_group_error(e)


@router.patch("/friends/groups/{group_id}")
async def rename_group_api(
    group_id: int,
    body: GroupPatch,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        g = await rename_group(session, user, group_id, body.name, body.description)
    except GroupError as e:
        raise _map_group_error(e)
    return {"id": g.id, "name": g.name, "description": g.description}


@router.delete("/friends/groups/{group_id}")
async def delete_group_api(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        await delete_group(session, user, group_id)
    except GroupError as e:
        raise _map_group_error(e)
    return {"ok": True}


@router.post("/friends/groups/{group_id}/leave")
async def leave_group_api(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        await leave_group(session, user, group_id)
    except GroupError as e:
        raise _map_group_error(e)
    return {"ok": True}


@router.post("/friends/join/{code}")
async def join_group_api(
    code: str,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        g = await join_by_code(session, user, code)
    except GroupError as e:
        raise _map_group_error(e)
    return {"id": g.id, "name": g.name}


# ─────────────────────────────────────────────────────────────
#  BIR A'ZO VIEW + RUXSATLAR
# ─────────────────────────────────────────────────────────────
@router.get("/friends/groups/{group_id}/members/{user_id}")
async def member_view_api(
    group_id: int, user_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        return await get_member_view(session, user, group_id, user_id)
    except GroupError as e:
        raise _map_group_error(e)


@router.get("/friends/groups/{group_id}/permissions")
async def permissions_api(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        return await list_permissions(session, user, group_id)
    except GroupError as e:
        raise _map_group_error(e)


@router.put("/friends/groups/{group_id}/permissions/{grantee_id}")
async def set_permission_api(
    group_id: int, grantee_id: int,
    body: PermissionUpdate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    try:
        await set_permission(session, user, group_id, grantee_id, body.can_manage)
    except GroupError as e:
        raise _map_group_error(e)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────
#  A'ZO UCHUN YANGI RESURS (cross-user create)
# ─────────────────────────────────────────────────────────────
async def _resolve_target(
    session: AsyncSession, actor, group_id: int, target_user_id: int
):
    """Actor+group+targetni tekshirib target User obyektini qaytaradi."""
    try:
        await ensure_can_manage(session, actor, group_id, target_user_id)
    except GroupError as e:
        raise _map_group_error(e)
    from bot.models.user import User
    tgt = await session.get(User, target_user_id)
    if not tgt:
        raise HTTPException(status_code=404, detail="A'zo topilmadi")
    return tgt


@router.post("/friends/groups/{group_id}/members/{user_id}/plans")
async def create_plan_for_member(
    group_id: int, user_id: int,
    body: PlanCreateForMember,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    actor = await _require_user(session, telegram_id)
    target = await _resolve_target(session, actor, group_id, user_id)

    # O'tib ketgan sana bo'lmasin
    if body.plan_date:
        from datetime import date as _date, datetime as _dt
        from bot.config import TIMEZONE
        try:
            _pd = _date.fromisoformat(body.plan_date)
        except Exception:
            _pd = None
        if _pd and _pd < _dt.now(TIMEZONE).date():
            raise HTTPException(status_code=409, detail="O'tib ketgan kun uchun reja qo'shib bo'lmaydi.")

    # Free-tier limit — TARGET foydalanuvchi limitiga qarab (uning hisobiga
    # yoziladi, uning limiti sarflansin).
    lim = await check_plan_limit(session, target, adding=1)
    if not lim.allowed:
        raise HTTPException(
            status_code=402,
            detail=f"A'zoning bepul kunlik limiti tugagan ({lim.used}/{lim.limit}).",
        )

    plan = await create_plan_single(
        session, target,
        title=body.title,
        description=body.description,
        scheduled_time=body.scheduled_time,
        plan_date_str=body.plan_date,
        score_value=5,
        created_by_user_id=actor.id,
    )
    return {
        "id": plan.id, "title": plan.title, "plan_date": str(plan.plan_date),
        "scheduled_time": plan.scheduled_time, "status": plan.status.value,
    }


@router.post("/friends/groups/{group_id}/members/{user_id}/goals")
async def create_goal_for_member(
    group_id: int, user_id: int,
    body: GoalCreateForMember,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    actor = await _require_user(session, telegram_id)
    target = await _resolve_target(session, actor, group_id, user_id)

    if (body.goal_type or "").strip().lower() not in ALLOWED_GOAL_TYPES:
        raise HTTPException(status_code=400, detail="Faqat yillik yoki oylik maqsad.")

    lim = await check_goal_limit(session, target, adding=1)
    if not lim.allowed:
        raise HTTPException(
            status_code=402,
            detail=f"A'zoning bepul maqsad limiti tugagan ({lim.used}/{lim.limit}).",
        )

    try:
        goal = await create_goal(
            session, target,
            title=body.title, description=body.description,
            goal_type=body.goal_type, period=body.period,
            created_by_user_id=actor.id,
        )
    except InvalidGoalTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "id": goal.id, "title": goal.title, "goal_type": goal.goal_type,
        "period": goal.period, "completed": bool(goal.completed),
    }


@router.post("/friends/groups/{group_id}/members/{user_id}/habits")
async def create_habit_for_member(
    group_id: int, user_id: int,
    body: HabitCreateForMember,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    actor = await _require_user(session, telegram_id)
    target = await _resolve_target(session, actor, group_id, user_id)

    lim = await check_habit_limit(session, target, adding=1)
    if not lim.allowed:
        raise HTTPException(
            status_code=402,
            detail=f"A'zoning bepul odat limiti tugagan ({lim.used}/{lim.limit}).",
        )

    habit = await create_habit(
        session, target,
        title=body.title, description=body.description, icon=body.icon,
        frequency=body.frequency, weekdays=body.weekdays,
        duration_type=body.duration_type, target_days=body.target_days,
        reminder_time=body.reminder_time,
        created_by_user_id=actor.id,
    )
    return {
        "id": habit.id, "title": habit.title, "icon": habit.icon,
        "frequency": habit.frequency,
    }
