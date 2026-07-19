"""
Do'stlar / Guruhlar (Groups) xizmati.

Guruh — foydalanuvchilar to'plami. A'zolar bir-birlarining bugungi rejalari,
maqsadlari va odatlarini ko'radi. A'zolar bir-biriga (grantor → grantee)
"mening reja/maqsad/odatlarimni yaratishga ruxsat" berishi mumkin — masalan,
xodim boshliqqa uning uchun reja yaratishga ruxsat berishi.

Guruhga qo'shilish:
  1. Ownership yaratgan `invite_code`.
  2. Deep-link `https://t.me/<bot>?start=grp_<invite_code>` orqali kelgan yangi
     foydalanuvchi bot start handleri orqali yoki Mini App'da `POST /friends/join/<code>`
     endpointi orqali qo'shiladi.
"""
from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.group import Group, GroupMember, GroupPermission
from bot.models.habit import Habit, HabitLog
from bot.models.plan import Plan, PlanStatus
from bot.models.goal import Goal
from bot.models.user import User
from bot.services.goal_service import ALLOWED_GOAL_TYPES

logger = logging.getLogger(__name__)


GROUP_INVITE_PREFIX = "grp_"
GROUP_INVITE_CODE_LEN = 10
GROUP_MAX_NAME_LEN = 80
GROUP_MAX_DESC_LEN = 300
GROUP_NAME_MIN = 1
# Bir foydalanuvchi ochishi mumkin bo'lgan maksimal guruhlar (spam himoyasi).
MAX_GROUPS_PER_OWNER = 20
# Bir guruhga sig'adigan maksimal a'zolar.
MAX_MEMBERS_PER_GROUP = 200


class GroupError(Exception):
    """Group service'ning umumiy xatosi (route 400 qaytaradi)."""


class GroupNotFound(GroupError):
    pass


class GroupForbidden(GroupError):
    pass


# ─────────────────────────────────────────────────────────────
#  INVITE CODE
# ─────────────────────────────────────────────────────────────
_INVITE_ALPHABET = string.ascii_lowercase + string.digits


def _generate_invite_code(length: int = GROUP_INVITE_CODE_LEN) -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(length))


async def _generate_unique_invite_code(session: AsyncSession) -> str:
    # Amaliyotda 10 belgili qatorlar to'qnashuvi ehtimoli juda past, lekin
    # xavfsizlik uchun bir necha marta urinamiz.
    for _ in range(8):
        code = _generate_invite_code()
        exists = await session.scalar(select(Group.id).where(Group.invite_code == code))
        if not exists:
            return code
    return _generate_invite_code(GROUP_INVITE_CODE_LEN + 2)


def parse_invite_code_from_payload(payload: Optional[str]) -> Optional[str]:
    """/start payload'idan guruh kodini ajratadi. Masalan 'grp_ab12cd' -> 'ab12cd'."""
    if not payload:
        return None
    p = payload.strip()
    if not p.startswith(GROUP_INVITE_PREFIX):
        return None
    code = p[len(GROUP_INVITE_PREFIX):].strip().lower()
    if not code or not all(c in _INVITE_ALPHABET for c in code):
        return None
    return code


# ─────────────────────────────────────────────────────────────
#  A'ZOLIK TEKSHIRUVI
# ─────────────────────────────────────────────────────────────
async def is_member(session: AsyncSession, group_id: int, user_id: int) -> bool:
    res = await session.scalar(
        select(GroupMember.id).where(
            and_(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        )
    )
    return bool(res)


async def require_member(
    session: AsyncSession, group_id: int, user_id: int
) -> GroupMember:
    res = await session.execute(
        select(GroupMember).where(
            and_(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        )
    )
    m = res.scalar_one_or_none()
    if not m:
        raise GroupForbidden("Siz bu guruhning a'zosi emassiz.")
    return m


async def get_group(session: AsyncSession, group_id: int) -> Group:
    g = await session.get(Group, group_id)
    if not g:
        raise GroupNotFound("Guruh topilmadi.")
    return g


# ─────────────────────────────────────────────────────────────
#  GURUH YARATISH / RO'YXATI / TAFSILOTI
# ─────────────────────────────────────────────────────────────
async def create_group(
    session: AsyncSession, owner: User, name: str, description: Optional[str] = None
) -> Group:
    name = (name or "").strip()[:GROUP_MAX_NAME_LEN]
    if len(name) < GROUP_NAME_MIN:
        raise GroupError("Guruh nomi bo'sh bo'lmasin.")
    desc = (description or "").strip()[:GROUP_MAX_DESC_LEN] or None

    # Spam himoyasi
    own_cnt = await session.scalar(
        select(func.count(Group.id)).where(Group.owner_user_id == owner.id)
    ) or 0
    if own_cnt >= MAX_GROUPS_PER_OWNER:
        raise GroupError(f"Siz ochishingiz mumkin bo'lgan guruh chegarasi tugadi (max {MAX_GROUPS_PER_OWNER}).")

    code = await _generate_unique_invite_code(session)
    g = Group(
        name=name, description=desc,
        owner_user_id=owner.id, invite_code=code,
    )
    session.add(g)
    await session.flush()
    # Owner avtomatik a'zo bo'ladi
    session.add(GroupMember(group_id=g.id, user_id=owner.id, role="owner"))
    await session.commit()
    await session.refresh(g)
    return g


async def list_my_groups(session: AsyncSession, user: User) -> list[dict]:
    """
    Foydalanuvchi a'zo bo'lgan barcha guruhlar (a'zolar soni bilan).
    Eng yangi yaratilgan tepada.
    """
    q = (
        select(
            Group,
            GroupMember.role,
            func.count(GroupMember.id).over(partition_by=Group.id).label("member_count"),
        )
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(
            Group.id.in_(
                select(GroupMember.group_id).where(GroupMember.user_id == user.id)
            )
        )
        .order_by(Group.created_at.desc())
    )
    seen: dict[int, dict] = {}
    for row in (await session.execute(q)).all():
        g, role, cnt = row
        if g.id in seen:
            continue
        # Joriy foydalanuvchining ushbu guruhdagi roli
        my_role = None
        for r2 in (await session.execute(
            select(GroupMember.role).where(
                and_(GroupMember.group_id == g.id, GroupMember.user_id == user.id)
            )
        )).scalars():
            my_role = r2
            break
        seen[g.id] = {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "invite_code": g.invite_code,
            "member_count": int(cnt),
            "is_owner": g.owner_user_id == user.id,
            "role": my_role or role or "member",
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
    return list(seen.values())


async def rename_group(
    session: AsyncSession, user: User, group_id: int,
    name: Optional[str] = None, description: Optional[str] = None,
) -> Group:
    g = await get_group(session, group_id)
    if g.owner_user_id != user.id:
        raise GroupForbidden("Faqat guruh egasi tahrirlashi mumkin.")
    if name is not None:
        nm = name.strip()[:GROUP_MAX_NAME_LEN]
        if not nm:
            raise GroupError("Guruh nomi bo'sh bo'lmasin.")
        g.name = nm
    if description is not None:
        g.description = (description.strip()[:GROUP_MAX_DESC_LEN] or None)
    await session.commit()
    await session.refresh(g)
    return g


async def delete_group(session: AsyncSession, user: User, group_id: int) -> None:
    g = await get_group(session, group_id)
    if g.owner_user_id != user.id:
        raise GroupForbidden("Faqat guruh egasi o'chirishi mumkin.")
    await session.delete(g)
    await session.commit()


async def leave_group(session: AsyncSession, user: User, group_id: int) -> None:
    g = await get_group(session, group_id)
    if g.owner_user_id == user.id:
        raise GroupError("Guruh egasi guruhni tark eta olmaydi — o'chiring.")
    await session.execute(
        GroupMember.__table__.delete().where(
            and_(GroupMember.group_id == group_id, GroupMember.user_id == user.id)
        )
    )
    # Ushbu a'zoga tegishli barcha permission yozuvlarini ham tozalaymiz
    # (ikkala yo'nalishda ham — grantor yoki grantee sifatida).
    await session.execute(
        GroupPermission.__table__.delete().where(
            and_(
                GroupPermission.group_id == group_id,
                (GroupPermission.grantor_user_id == user.id) |
                (GroupPermission.grantee_user_id == user.id),
            )
        )
    )
    await session.commit()


# ─────────────────────────────────────────────────────────────
#  QO'SHILISH (invite code orqali)
# ─────────────────────────────────────────────────────────────
async def join_by_code(session: AsyncSession, user: User, code: str) -> Group:
    code = (code or "").strip().lower()
    if not code:
        raise GroupError("Taklif kodi bo'sh.")
    g = await session.scalar(select(Group).where(Group.invite_code == code))
    if not g:
        raise GroupNotFound("Bunday taklif havolasi topilmadi.")

    already = await is_member(session, g.id, user.id)
    if already:
        return g

    # A'zolar soni chegarasi
    cnt = await session.scalar(
        select(func.count(GroupMember.id)).where(GroupMember.group_id == g.id)
    ) or 0
    if cnt >= MAX_MEMBERS_PER_GROUP:
        raise GroupError("Guruh to'lgan (a'zolar chegarasi).")

    session.add(GroupMember(group_id=g.id, user_id=user.id, role="member"))
    await session.commit()
    return g


# ─────────────────────────────────────────────────────────────
#  A'ZOLAR + BUGUNGI XULOSA (guruh sahifasi uchun)
# ─────────────────────────────────────────────────────────────
def _today_tashkent() -> date:
    return datetime.now(TIMEZONE).date()


async def _member_today_summary(session: AsyncSession, user_id: int) -> dict:
    """Bir a'zoning bugungi holati: reja, odat, oylik/yillik maqsad progresslari."""
    today = _today_tashkent()
    # Bugungi rejalar
    plans_res = await session.execute(
        select(Plan).where(and_(Plan.user_id == user_id, Plan.plan_date == today))
    )
    plans = plans_res.scalars().all()
    plans_total = len(plans)
    plans_done = sum(1 for p in plans if p.status == PlanStatus.done)

    # Aktiv (arxivlanmagan) odatlar + bugungi bajarilganlari
    habits_res = await session.execute(
        select(Habit).where(and_(Habit.user_id == user_id, Habit.archived == False))  # noqa: E712
    )
    habits = habits_res.scalars().all()
    habit_ids = [h.id for h in habits]
    habits_done_today = 0
    if habit_ids:
        habits_done_today = await session.scalar(
            select(func.count(HabitLog.id)).where(
                and_(HabitLog.habit_id.in_(habit_ids), HabitLog.log_date == today)
            )
        ) or 0
    habits_total = len(habits)

    # Yillik va oylik maqsadlar (jori davr)
    year_key = str(today.year)
    month_key = f"{today.year:04d}-{today.month:02d}"
    goals_res = await session.execute(
        select(Goal).where(
            and_(
                Goal.user_id == user_id,
                Goal.goal_type.in_(ALLOWED_GOAL_TYPES),
                Goal.period.in_([year_key, month_key]),
            )
        )
    )
    goals = goals_res.scalars().all()
    goals_total = len(goals)
    goals_done = sum(1 for g in goals if g.completed)

    return {
        "plans_total": int(plans_total),
        "plans_done": int(plans_done),
        "habits_total": int(habits_total),
        "habits_done_today": int(habits_done_today),
        "goals_total": int(goals_total),
        "goals_done": int(goals_done),
    }


def _empty_summary() -> dict:
    return {
        "plans_total": 0, "plans_done": 0,
        "habits_total": 0, "habits_done_today": 0,
        "goals_total": 0, "goals_done": 0,
    }


async def _bulk_today_summary(session: AsyncSession, user_ids: list[int]) -> dict:
    """
    BARCHA a'zolarning bugungi xulosasini FAQAT 4 ta guruhli (GROUP BY) so'rov
    bilan hisoblaydi — avvalgi N+1 (har a'zoga 3 ta so'rov) o'rniga. Katta
    guruhlarda (masalan 50 a'zo) 150+ so'rov → 4 so'rovga tushadi.
    Qaytaradi: {user_id: summary_dict}.
    """
    out = {uid: _empty_summary() for uid in user_ids}
    if not user_ids:
        return out

    today = _today_tashkent()
    year_key = str(today.year)
    month_key = f"{today.year:04d}-{today.month:02d}"

    done_case = func.sum(case((Plan.status == PlanStatus.done, 1), else_=0))
    # 1) Rejalar (bugun) — jami + bajarilgan, user bo'yicha
    for uid, total, done in (await session.execute(
        select(Plan.user_id, func.count(Plan.id), done_case)
        .where(and_(Plan.user_id.in_(user_ids), Plan.plan_date == today))
        .group_by(Plan.user_id)
    )).all():
        out[uid]["plans_total"] = int(total or 0)
        out[uid]["plans_done"] = int(done or 0)

    # 2) Aktiv odatlar soni, user bo'yicha
    for uid, total in (await session.execute(
        select(Habit.user_id, func.count(Habit.id))
        .where(and_(Habit.user_id.in_(user_ids), Habit.archived == False))  # noqa: E712
        .group_by(Habit.user_id)
    )).all():
        out[uid]["habits_total"] = int(total or 0)

    # 3) Bugun bajarilgan odatlar (HabitLog.user_id mavjud), user bo'yicha
    for uid, done in (await session.execute(
        select(HabitLog.user_id, func.count(HabitLog.id))
        .where(and_(HabitLog.user_id.in_(user_ids), HabitLog.log_date == today))
        .group_by(HabitLog.user_id)
    )).all():
        out[uid]["habits_done_today"] = int(done or 0)

    # 4) Joriy davr maqsadlari — jami + bajarilgan, user bo'yicha
    goal_done_case = func.sum(case((Goal.completed == True, 1), else_=0))  # noqa: E712
    for uid, total, done in (await session.execute(
        select(Goal.user_id, func.count(Goal.id), goal_done_case)
        .where(and_(
            Goal.user_id.in_(user_ids),
            Goal.goal_type.in_(ALLOWED_GOAL_TYPES),
            Goal.period.in_([year_key, month_key]),
        ))
        .group_by(Goal.user_id)
    )).all():
        out[uid]["goals_total"] = int(total or 0)
        out[uid]["goals_done"] = int(done or 0)

    return out


async def get_group_detail(
    session: AsyncSession, user: User, group_id: int
) -> dict:
    """Guruh + a'zolar ro'yxati + bugungi xulosa + joriy user permissions."""
    g = await get_group(session, group_id)
    await require_member(session, group_id, user.id)

    members_res = await session.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at)
    )
    rows = members_res.all()
    member_ids = [u.id for _gm, u in rows]

    # ── N+1 yo'q: barcha xulosalar 4 so'rov, ruxsatlar 1 so'rov ──
    summaries = await _bulk_today_summary(session, member_ids)
    # Bu foydalanuvchiga qaysi a'zolar can_manage bergan (bir so'rovda)
    granted_to_me: set[int] = set()
    if member_ids:
        for (grantor_id,) in (await session.execute(
            select(GroupPermission.grantor_user_id).where(and_(
                GroupPermission.group_id == group_id,
                GroupPermission.grantee_user_id == user.id,
                GroupPermission.can_manage == True,  # noqa: E712
            ))
        )).all():
            granted_to_me.add(int(grantor_id))

    members = []
    for gm, u in rows:
        summary = summaries.get(u.id, _empty_summary())
        can_i_manage = (u.id != user.id) and (u.id in granted_to_me)
        members.append({
            "user_id": u.id,
            "telegram_id": u.telegram_id,
            "name": (u.display_name or u.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi",
            "role": gm.role,
            "is_me": u.id == user.id,
            "streak": int(u.streak or 0),
            "summary": summary,
            "can_i_manage": can_i_manage,
        })

    return {
        "id": g.id,
        "name": g.name,
        "description": g.description,
        "invite_code": g.invite_code,
        "is_owner": g.owner_user_id == user.id,
        "owner_user_id": g.owner_user_id,
        "members": members,
    }


async def get_member_view(
    session: AsyncSession, user: User, group_id: int, target_user_id: int
) -> dict:
    """
    Guruhning bir a'zosining sahifasi: bugungi rejalari, aktiv odatlari va
    joriy davr maqsadlari. `can_manage` = joriy foydalanuvchi bu a'zo uchun
    yangi item yaratishga huquqli.
    """
    g = await get_group(session, group_id)
    await require_member(session, group_id, user.id)
    # Target ham a'zo bo'lishi kerak
    if not await is_member(session, group_id, target_user_id):
        raise GroupNotFound("Bunday a'zo bu guruhda yo'q.")

    target = await session.get(User, target_user_id)
    if not target:
        raise GroupNotFound("Foydalanuvchi topilmadi.")

    today = _today_tashkent()
    # Bugungi rejalar
    plans = (await session.execute(
        select(Plan).where(
            and_(Plan.user_id == target_user_id, Plan.plan_date == today)
        ).order_by(Plan.scheduled_time.nullslast(), Plan.id)
    )).scalars().all()

    # Odatlar (arxivlanmagan)
    habits = (await session.execute(
        select(Habit).where(and_(
            Habit.user_id == target_user_id, Habit.archived == False,  # noqa: E712
        )).order_by(Habit.sort_order, Habit.id)
    )).scalars().all()
    habit_ids = [h.id for h in habits]
    logged_today: set[int] = set()
    if habit_ids:
        rows = (await session.execute(
            select(HabitLog.habit_id).where(
                and_(HabitLog.habit_id.in_(habit_ids), HabitLog.log_date == today)
            )
        )).all()
        logged_today = {r[0] for r in rows}

    # Yillik + oylik maqsadlar (joriy davr)
    year_key = str(today.year)
    month_key = f"{today.year:04d}-{today.month:02d}"
    goals = (await session.execute(
        select(Goal).where(and_(
            Goal.user_id == target_user_id,
            Goal.goal_type.in_(ALLOWED_GOAL_TYPES),
            Goal.period.in_([year_key, month_key]),
        )).order_by(Goal.goal_type.desc(), Goal.created_at)
    )).scalars().all()

    # Joriy user shu a'zo uchun yozishga huquqlimi
    can_manage = False
    if target.id != user.id:
        can_manage = bool(await session.scalar(
            select(GroupPermission.can_manage).where(and_(
                GroupPermission.group_id == group_id,
                GroupPermission.grantor_user_id == target.id,
                GroupPermission.grantee_user_id == user.id,
            ))
        ))

    def _plan_dict(p):
        return {
            "id": p.id, "title": p.title, "description": p.description,
            "scheduled_time": p.scheduled_time,
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "created_by_user_id": p.created_by_user_id,
        }

    def _habit_dict(h):
        return {
            "id": h.id, "title": h.title, "icon": h.icon or "✅",
            "frequency": h.frequency, "done_today": h.id in logged_today,
            "created_by_user_id": h.created_by_user_id,
        }

    def _goal_dict(g):
        return {
            "id": g.id, "title": g.title, "description": g.description,
            "goal_type": g.goal_type, "period": g.period,
            "completed": bool(g.completed),
            "created_by_user_id": g.created_by_user_id,
        }

    return {
        "group_id": group_id,
        "member": {
            "user_id": target.id,
            "telegram_id": target.telegram_id,
            "name": (target.display_name or target.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi",
            "streak": int(target.streak or 0),
            "total_score": int(target.total_score or 0),
            "is_me": target.id == user.id,
        },
        "plans": [_plan_dict(p) for p in plans],
        "habits": [_habit_dict(h) for h in habits],
        "goals": [_goal_dict(g) for g in goals],
        "can_manage": can_manage,
    }


# ─────────────────────────────────────────────────────────────
#  RUXSATLAR (permissions)
# ─────────────────────────────────────────────────────────────
async def list_permissions(
    session: AsyncSession, user: User, group_id: int
) -> dict:
    """
    Joriy foydalanuvchiga tegishli ruxsatlar:
      • grants_out — Men KIMLARGA ruxsat berdim (grantor=me)
      • grants_in  — KIMLAR MENGA ruxsat berdi (grantee=me)
    """
    await require_member(session, group_id, user.id)
    # a'zolar ro'yxati (o'zim tashqari)
    members = (await session.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(and_(GroupMember.group_id == group_id, GroupMember.user_id != user.id))
    )).all()

    perms_out = {
        int(r[0]): bool(r[1]) for r in (await session.execute(
            select(GroupPermission.grantee_user_id, GroupPermission.can_manage).where(and_(
                GroupPermission.group_id == group_id,
                GroupPermission.grantor_user_id == user.id,
            ))
        )).all()
    }
    perms_in = {
        int(r[0]): bool(r[1]) for r in (await session.execute(
            select(GroupPermission.grantor_user_id, GroupPermission.can_manage).where(and_(
                GroupPermission.group_id == group_id,
                GroupPermission.grantee_user_id == user.id,
            ))
        )).all()
    }

    def _name(u: User) -> str:
        return (u.display_name or u.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi"

    grants_out = [
        {"user_id": u.id, "name": _name(u), "can_manage": perms_out.get(u.id, False)}
        for _, u in members
    ]
    grants_in = [
        {"user_id": u.id, "name": _name(u), "can_manage": perms_in.get(u.id, False)}
        for _, u in members
    ]
    return {"grants_out": grants_out, "grants_in": grants_in}


async def set_permission(
    session: AsyncSession, user: User, group_id: int,
    grantee_user_id: int, can_manage: bool,
) -> None:
    """Grantor = joriy user; grantee = boshqa a'zo. Ruxsat berish / bekor qilish."""
    await require_member(session, group_id, user.id)
    if grantee_user_id == user.id:
        raise GroupError("O'zingizga ruxsat berish shart emas.")
    if not await is_member(session, group_id, grantee_user_id):
        raise GroupNotFound("Bunday a'zo yo'q.")

    existing = await session.scalar(select(GroupPermission).where(and_(
        GroupPermission.group_id == group_id,
        GroupPermission.grantor_user_id == user.id,
        GroupPermission.grantee_user_id == grantee_user_id,
    )))
    if existing is None:
        if can_manage:
            session.add(GroupPermission(
                group_id=group_id, grantor_user_id=user.id,
                grantee_user_id=grantee_user_id, can_manage=True,
            ))
    else:
        existing.can_manage = bool(can_manage)
    await session.commit()


async def ensure_can_manage(
    session: AsyncSession, actor: User, group_id: int, target_user_id: int
) -> None:
    """
    Actor guruhda target uchun item yarata oladimi tekshiradi.
    Aks holda GroupForbidden qaytadi.
    """
    if actor.id == target_user_id:
        return  # o'zi uchun har doim mumkin
    await require_member(session, group_id, actor.id)
    if not await is_member(session, group_id, target_user_id):
        raise GroupNotFound("Bunday a'zo yo'q.")
    granted = await session.scalar(select(GroupPermission.can_manage).where(and_(
        GroupPermission.group_id == group_id,
        GroupPermission.grantor_user_id == target_user_id,
        GroupPermission.grantee_user_id == actor.id,
    )))
    if not granted:
        raise GroupForbidden("Bu a'zo sizga ruxsat bermagan.")
