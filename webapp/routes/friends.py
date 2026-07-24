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
    get_telegram_settings,
    join_by_code,
    leave_group,
    list_my_groups,
    list_permissions,
    remove_member,
    rename_group,
    set_member_active,
    set_permission,
    unlink_telegram,
    update_telegram_settings,
)
from bot.services.digest_service import (
    list_telegram_candidates,
    send_digest_for_group,
    send_per_user_plans_for_group,
    send_per_user_reports_for_group,
)
# Eslatma: Do'stlar guruhida MAQSAD bo'limi olib tashlandi. `create_goal` va
# `ALLOWED_GOAL_TYPES` importlari olib tashlandi — endi maqsadni faqat
# foydalanuvchi o'zi yaratishi mumkin (asosiy Mini App oqimi orqali).
from bot.services.habit_service import create_habit
from bot.services.plan_service import create_plan_single
from bot.services.premium_service import (
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
    # Ikkalasi ham ixtiyoriy — faqat berilgani yangilanadi. Ikkisini bir
    # so'rovda ham yuborish mumkin. `can_manage=True` bo'lsa `can_view`
    # avtomatik True qulflanadi (backend'da).
    can_manage: Optional[bool] = None
    can_view: Optional[bool] = None


class PlanCreateForMember(BaseModel):
    title: str
    description: Optional[str] = None
    scheduled_time: Optional[str] = None
    plan_date: Optional[str] = None


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

    # PREMIUM GATE: Do'stlar bo'limi faqat Premium foydalanuvchilar uchun
    from bot.services.premium_service import user_is_premium
    if not user_is_premium(user):
        raise HTTPException(
            status_code=402,
            detail=(
                "👥 Do'stlar bo'limi faqat Premium foydalanuvchilar uchun. "
                "💎 Premium oling va do'stlaringiz bilan birga intizomli bo'ling!"
            ),
        )
    groups = await list_my_groups(session, user)
    return {"groups": groups, "invite_prefix": GROUP_INVITE_PREFIX}


@router.post("/friends/groups")
async def create_group_api(
    body: GroupCreate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await _require_user(session, telegram_id)
    # PREMIUM GATE: guruh yaratish faqat Premium uchun
    from bot.services.premium_service import user_is_premium
    if not user_is_premium(user):
        raise HTTPException(
            status_code=402,
            detail="Do'stlar bo'limi faqat Premium foydalanuvchilar uchun.",
        )
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
    date: Optional[str] = None,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    # `date` (YYYY-MM-DD) — o'tgan davrni ko'rish uchun (ixtiyoriy).
    on_date = None
    if date:
        from datetime import date as _date
        try:
            on_date = _date.fromisoformat(date)
        except Exception:
            on_date = None
    user = await _require_user(session, telegram_id)
    try:
        return await get_member_view(session, user, group_id, user_id, on_date=on_date)
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
        await set_permission(
            session, user, group_id, grantee_id,
            can_manage=body.can_manage, can_view=body.can_view,
        )
    except GroupError as e:
        raise _map_group_error(e)
    return {"ok": True}


@router.delete("/friends/groups/{group_id}/members/{user_id}")
async def remove_member_api(
    group_id: int, user_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """Guruh egasi tomonidan a'zoni chiqarib yuborish."""
    user = await _require_user(session, telegram_id)
    try:
        await remove_member(session, user, group_id, user_id)
    except GroupError as e:
        raise _map_group_error(e)
    return {"ok": True}


class MemberActiveUpdate(BaseModel):
    """A'zoning 'aktiv' holatini yangilash uchun DTO (faqat guruh egasi)."""
    is_active: bool


@router.put("/friends/groups/{group_id}/members/{user_id}/active")
async def set_member_active_api(
    group_id: int, user_id: int,
    body: MemberActiveUpdate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Guruh egasi tomonidan a'zoni "pauza" (is_active=False) yoki qayta
    yoqish (is_active=True). O'chirilgan a'zoning ma'lumotlari webapp va
    Telegram guruh xabarlarida ko'rinmaydi (a'zolikni saqlab qoladi).
    """
    user = await _require_user(session, telegram_id)
    try:
        return await set_member_active(
            session, user, group_id, user_id, is_active=bool(body.is_active),
        )
    except GroupError as e:
        raise _map_group_error(e)


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


# A'zo uchun maqsad yaratish endpointi olib tashlandi (foydalanuvchi talabiga
# muvofiq). A'zolar bir-biriga maqsad qo'sha olmaydi. Yagona qolgan cross-user
# resurslar: reja va odat.


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



# ─────────────────────────────────────────────────────────────
#  TELEGRAM DIGEST — WebApp guruh statistikasini Telegram chatga yuborish
# ─────────────────────────────────────────────────────────────
class TelegramSettingsUpdate(BaseModel):
    # Barchasi ixtiyoriy — faqat berilgani yangilanadi.
    telegram_chat_id: Optional[int] = None
    telegram_chat_title: Optional[str] = None
    # ── Kunlik HISOBOT (report) sozlamalari
    digest_enabled: Optional[bool] = None
    digest_time: Optional[str] = None  # HH:MM Toshkent
    # ── Kunlik REJA (plans) sozlamalari (yangi)
    plans_enabled: Optional[bool] = None
    plans_time: Optional[str] = None  # HH:MM Toshkent
    # ── Backward compat — UI'da endi ko'rinmaydi (doim TRUE deb hisoblanadi)
    digest_show_zero: Optional[bool] = None
    digest_mention: Optional[bool] = None


class TelegramLink(BaseModel):
    telegram_chat_id: int
    telegram_chat_title: Optional[str] = None


@router.get("/friends/groups/{group_id}/telegram/settings")
async def telegram_settings_get(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """Digest sozlamalari (faqat guruh egasi)."""
    user = await _require_user(session, telegram_id)
    try:
        return await get_telegram_settings(session, user, group_id)
    except GroupError as e:
        raise _map_group_error(e)


@router.get("/friends/groups/{group_id}/telegram/candidates")
async def telegram_candidates(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Bot ham, guruh egasi ham a'zo bo'lgan Telegram chatlar ro'yxati.
    Guruh egasi UI'da shu ro'yxatdan tanlaydi.
    """
    user = await _require_user(session, telegram_id)
    # Egalikni tekshirish
    try:
        st = await get_telegram_settings(session, user, group_id)
    except GroupError as e:
        raise _map_group_error(e)

    candidates = await list_telegram_candidates(
        session, telegram_id,
        selected_chat_id=st.get("telegram_chat_id"),
    )
    return {
        "candidates": [
            {
                "chat_id": c.chat_id,
                "chat_title": c.chat_title,
                "chat_type": c.chat_type,
                "is_selected": c.is_selected,
                "can_send": c.can_send,
            }
            for c in candidates
        ],
    }


@router.put("/friends/groups/{group_id}/telegram/settings")
async def telegram_settings_update(
    group_id: int,
    body: TelegramSettingsUpdate,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """Digest sozlamalarini yangilash (partial). Faqat guruh egasi."""
    user = await _require_user(session, telegram_id)
    try:
        return await update_telegram_settings(
            session, user, group_id,
            telegram_chat_id=body.telegram_chat_id,
            telegram_chat_title=body.telegram_chat_title,
            digest_enabled=body.digest_enabled,
            digest_time=body.digest_time,
            plans_enabled=body.plans_enabled,
            plans_time=body.plans_time,
            digest_show_zero=body.digest_show_zero,
            digest_mention=body.digest_mention,
        )
    except GroupError as e:
        raise _map_group_error(e)


@router.post("/friends/groups/{group_id}/telegram/link")
async def telegram_link(
    group_id: int,
    body: TelegramLink,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Guruh egasi tanlagan Telegram chatga bog'lash — chat_id va title ni yozadi.
    `digest_enabled` avtomatik yoqilmaydi (foydalanuvchi keyingi qadamda yoqadi).
    """
    user = await _require_user(session, telegram_id)
    try:
        return await update_telegram_settings(
            session, user, group_id,
            telegram_chat_id=body.telegram_chat_id,
            telegram_chat_title=body.telegram_chat_title,
        )
    except GroupError as e:
        raise _map_group_error(e)


@router.post("/friends/groups/{group_id}/telegram/unlink")
async def telegram_unlink(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """Telegram bog'lanishni uzish (digestni ham o'chiradi)."""
    user = await _require_user(session, telegram_id)
    try:
        await unlink_telegram(session, user, group_id)
    except GroupError as e:
        raise _map_group_error(e)
    return {"ok": True}


async def _load_group_for_test(session, user, group_id: int):
    """Test tugmalar uchun umumiy helper: sozlamalarni tekshirib guruhni yuklaydi."""
    try:
        st = await get_telegram_settings(session, user, group_id)
    except GroupError as e:
        raise _map_group_error(e)
    if not st.get("telegram_chat_id"):
        raise HTTPException(status_code=400, detail="Avval Telegram guruhni tanlang.")
    from bot.services.group_service import get_group
    try:
        return await get_group(session, group_id)
    except GroupError as e:
        raise _map_group_error(e)


@router.post("/friends/groups/{group_id}/telegram/plans-test")
async def telegram_plans_test(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Kunlik REJA (plans) xabarlarini hoziroq test yuborish (per-user).
    Xabar tarkibida "test" yozuvi bo'lmaydi — real avtomatik yuborish bilan
    aynan bir xil ko'rinishda. `plans_enabled` FALSE bo'lsa ham ishlaydi.
    """
    user = await _require_user(session, telegram_id)
    g = await _load_group_for_test(session, user, group_id)
    result = await send_per_user_plans_for_group(session, g, is_test=True)
    return {"ok": result.ok, "reason": result.reason}


@router.post("/friends/groups/{group_id}/telegram/report-test")
async def telegram_report_test(
    group_id: int,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Kunlik HISOBOT (report) xabarlarini hoziroq test yuborish (per-user).
    Xabar tarkibida "test" yozuvi bo'lmaydi. `digest_enabled` FALSE bo'lsa ham
    ishlaydi (foydalanuvchi sinamoqchi).
    """
    user = await _require_user(session, telegram_id)
    g = await _load_group_for_test(session, user, group_id)
    result = await send_per_user_reports_for_group(session, g, is_test=True)
    return {"ok": result.ok, "reason": result.reason}
