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
from bot.models.user import User
from bot.services.app_settings import is_group_perms_menu_enabled
from bot.services.habit_service import is_due_on as _habit_is_due_on, is_finished as _habit_is_finished
# Eslatma: Do'stlar guruhida MAQSAD (goal) bo'limi olib tashlandi.
# A'zolar bir-birining maqsadini ko'rmaydi va bir-biriga maqsad qo'sha olmaydi
# (foydalanuvchi talabi). Faqat reja + odat guruh kontekstida ko'rinadi.

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
    """Bir a'zoning bugungi holati: reja va odat sanoqlari.

    Maqsad (goal) bo'limi olib tashlandi — guruh kontekstida ko'rinmaydi.
    """
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

    return {
        "plans_total": int(plans_total),
        "plans_done": int(plans_done),
        "habits_total": int(habits_total),
        "habits_done_today": int(habits_done_today),
    }


async def _effective_visible(
    session: AsyncSession, group_id: int, owner_id: int, viewer_id: int,
    *,
    target_is_active: bool = True,
    viewer_is_group_owner: bool = False,
) -> bool:
    """
    Viewer, guruhda owner'ning (bu funksiyada "data owner" — a'zoning ma'lumoti
    egasi) ma'lumotlarini ko'ra oladimi?

    Qoidalar:
      • O'ziga har doim ko'rinadi.
      • Target `is_active=False` bo'lsa (guruh egasi vaqtincha o'chirgan): faqat
        target o'zi va guruh egasi ko'ra oladi. Boshqa a'zolar → False.
      • Global "guruh ruxsatlar menyusi" o'chirilgan bo'lsa → hamma birdek
        ko'radi (admin foydalanuvchilarga ruxsatlar tanlash imkonini o'chirib
        qo'ygan, natijada default hamma ochiq).
      • Aks holda owner viewer'ga `can_view` yoki `can_manage` bergan bo'lsa → True.
      • Bo'lmasa → False (default yashirin).
    """
    if owner_id == viewer_id:
        return True
    # A'zo egasi tomonidan o'chirilgan (is_active=False) → faqat guruh egasi
    # ko'ra oladi (target'ni yoqib qo'yish imkoniyati uchun).
    if not target_is_active:
        return viewer_is_group_owner
    # Admin panelidan ruxsatlar menyusi o'chirilgan bo'lsa qulflarni chetlab
    # o'tamiz — bu holatda hamma bir-birini avtomatik ko'radi.
    if not await is_group_perms_menu_enabled(session):
        return True
    row = await session.scalar(
        select(GroupPermission).where(and_(
            GroupPermission.group_id == group_id,
            GroupPermission.grantor_user_id == owner_id,
            GroupPermission.grantee_user_id == viewer_id,
        ))
    )
    if not row:
        return False
    return bool(row.can_view) or bool(row.can_manage)


def _empty_summary() -> dict:
    return {
        "plans_total": 0, "plans_done": 0,
        "habits_total": 0, "habits_done_today": 0,
    }


async def _bulk_today_summary(session: AsyncSession, user_ids: list[int]) -> dict:
    """
    BARCHA (ko'rinadigan) a'zolarning bugungi xulosasini 3 ta guruhli (GROUP BY)
    so'rov bilan hisoblaydi — reja jami, odat jami, odat bugun. Maqsad bo'limi
    olib tashlandi (guruh kontekstida ko'rinmaydi). {user_id: summary}.
    """
    out = {uid: _empty_summary() for uid in user_ids}
    if not user_ids:
        return out

    today = _today_tashkent()

    done_case = func.sum(case((Plan.status == PlanStatus.done, 1), else_=0))
    for uid, total, done in (await session.execute(
        select(Plan.user_id, func.count(Plan.id), done_case)
        .where(and_(Plan.user_id.in_(user_ids), Plan.plan_date == today))
        .group_by(Plan.user_id)
    )).all():
        out[uid]["plans_total"] = int(total or 0)
        out[uid]["plans_done"] = int(done or 0)

    for uid, total in (await session.execute(
        select(Habit.user_id, func.count(Habit.id))
        .where(and_(Habit.user_id.in_(user_ids), Habit.archived == False))  # noqa: E712
        .group_by(Habit.user_id)
    )).all():
        out[uid]["habits_total"] = int(total or 0)

    for uid, done in (await session.execute(
        select(HabitLog.user_id, func.count(HabitLog.id))
        .where(and_(HabitLog.user_id.in_(user_ids), HabitLog.log_date == today))
        .group_by(HabitLog.user_id)
    )).all():
        out[uid]["habits_done_today"] = int(done or 0)

    return out


async def get_group_detail(
    session: AsyncSession, user: User, group_id: int
) -> dict:
    """Guruh + a'zolar ro'yxati + bugungi xulosa (visibility bilan) + permissions.

    is_active=False bo'lgan a'zolar:
      • Guruh egasi — barcha a'zolarni ko'radi (jumladan o'chirilganlarini),
        `is_active` bayrog'i bilan (UI toggle ko'rsatishi uchun).
      • Boshqalar — o'chirilgan a'zolar ro'yxatga umuman qo'shilmaydi (ular
        guruhdan chiqarilgandek bo'ladi).
    """
    g = await get_group(session, group_id)
    await require_member(session, group_id, user.id)

    is_group_owner = (g.owner_user_id == user.id)

    members_res = await session.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at)
    )
    rows = members_res.all()

    # is_active mapping — a'zo id → aktiv (True/False).
    active_map: dict[int, bool] = {u.id: bool(gm.is_active) for gm, u in rows}

    # Egadan boshqalar uchun o'chirilgan a'zolarni ro'yxatdan olib tashlaymiz.
    if not is_group_owner:
        rows = [
            (gm, u) for gm, u in rows
            if bool(gm.is_active) or u.id == user.id
        ]

    member_ids = [u.id for _gm, u in rows]

    # Admin panelidan "Guruh ruxsatlar menyusi" o'chirilgan bo'lsa — barcha
    # a'zolar bir-birini ko'radi (default hamma ochiq). Bu holatda perms
    # so'rovi umuman kerak emas.
    perms_menu_on = await is_group_perms_menu_enabled(session)

    # ── N+1 yo'q: barcha ruxsatlar BITTA so'rovda (visible + can_i_manage) ──
    # Bu a'zolar MENGA (grantee=user.id) qanday ruxsat bergan: {grantor_id: (view, manage)}
    perms: dict[int, tuple[bool, bool]] = {}
    if member_ids and perms_menu_on:
        for gid, cv, cm in (await session.execute(
            select(
                GroupPermission.grantor_user_id,
                GroupPermission.can_view,
                GroupPermission.can_manage,
            ).where(and_(
                GroupPermission.group_id == group_id,
                GroupPermission.grantee_user_id == user.id,
                GroupPermission.grantor_user_id.in_(member_ids),
            ))
        )).all():
            perms[int(gid)] = (bool(cv), bool(cm))

    def _is_visible(uid: int) -> bool:
        if uid == user.id:
            return True
        # is_active=False a'zoni faqat guruh egasi ko'ra oladi.
        if not active_map.get(uid, True):
            return is_group_owner
        # Ruxsatlar menyusi global o'chirilgan bo'lsa hamma ko'rinadi.
        if not perms_menu_on:
            return True
        cv, cm = perms.get(uid, (False, False))
        return cv or cm

    # Faqat KO'RINADIGAN a'zolar uchun xulosa hisoblaymiz (4 guruhli so'rov).
    visible_ids = [uid for uid in member_ids if _is_visible(uid)]
    summaries = await _bulk_today_summary(session, visible_ids)

    members = []
    for gm, u in rows:
        vis = _is_visible(u.id)
        summary = summaries.get(u.id, _empty_summary()) if vis else _empty_summary()
        _cv, cm = perms.get(u.id, (False, False))
        can_i_manage = (u.id != user.id) and cm
        members.append({
            "user_id": u.id,
            "telegram_id": u.telegram_id,
            "name": (u.display_name or u.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi",
            "role": gm.role,
            "is_me": u.id == user.id,
            "streak": int(u.streak or 0),
            "summary": summary,
            "can_i_manage": can_i_manage,
            "visible": vis,
            # Guruh egasi UI toggle uchun ishlatadi. Boshqalar uchun bu qiymat
            # ma'nosiz (ular is_active=False a'zolarni ko'rmaydi umuman).
            "is_active": bool(gm.is_active),
        })

    return {
        "id": g.id,
        "name": g.name,
        "description": g.description,
        "invite_code": g.invite_code,
        "is_owner": is_group_owner,
        "owner_user_id": g.owner_user_id,
        "members": members,
    }


async def get_member_view(
    session: AsyncSession, user: User, group_id: int, target_user_id: int,
    on_date: Optional[date] = None,
) -> dict:
    """
    Guruhning bir a'zosining sahifasi. `visible` — target o'z ma'lumotlarini
    joriy foydalanuvchiga ochganmi:
      • False → ism va streak (leaderboard'da baribir ochiq) qaytariladi,
                lekin plans/habits/goals bo'sh ro'yxatlar. Frontend
                "🔒 Yashirin" xabarini ko'rsatadi.
      • True  → to'liq ma'lumot.

    `on_date` — ko'riladigan sana (o'tgan davrni ham ko'rish uchun). None bo'lsa
    bugun. Rejalar shu kunga, odatlar shu kunda bajarilgan-yo'qligiga,
    maqsadlar shu kunning yil+oy davriga tegishli qaytariladi.
    Kelajak sana so'ralsa — bugungacha cheklaymiz.
    """
    g = await get_group(session, group_id)
    await require_member(session, group_id, user.id)
    if not await is_member(session, group_id, target_user_id):
        raise GroupNotFound("Bunday a'zo bu guruhda yo'q.")

    target = await session.get(User, target_user_id)
    if not target:
        raise GroupNotFound("Foydalanuvchi topilmadi.")

    # Target'ning aktiv holati — is_active=False bo'lsa faqat ega yoki target
    # o'zi ko'ra oladi.
    target_membership = (await session.execute(
        select(GroupMember).where(and_(
            GroupMember.group_id == group_id,
            GroupMember.user_id == target_user_id,
        ))
    )).scalar_one_or_none()
    target_is_active = bool(target_membership.is_active) if target_membership else True
    is_group_owner = (g.owner_user_id == user.id)

    visible = await _effective_visible(
        session, group_id, target.id, user.id,
        target_is_active=target_is_active,
        viewer_is_group_owner=is_group_owner,
    )

    # Joriy user shu a'zo uchun yozishga huquqlimi (can_manage → visible ham True)
    can_manage = False
    if target.id != user.id:
        can_manage = bool(await session.scalar(
            select(GroupPermission.can_manage).where(and_(
                GroupPermission.group_id == group_id,
                GroupPermission.grantor_user_id == target.id,
                GroupPermission.grantee_user_id == user.id,
            ))
        ))

    # Ko'riladigan sana. `on_date` berilmasa bugun. Kelajak va o'tgan kunlar
    # ham qo'llaniladi — plan/habit/goal 'shu kun/davr' uchun qaytariladi.
    real_today = _today_tashkent()
    today = on_date or real_today
    is_today = today == real_today
    is_future = today > real_today
    is_past = today < real_today

    # Ko'rinmaydigan a'zo — bo'sh ro'yxatlar bilan qaytariladi.
    if not visible:
        return {
            "group_id": group_id,
            "member": {
                "user_id": target.id,
                "telegram_id": target.telegram_id,
                "name": (target.display_name or target.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi",
                "streak": int(target.streak or 0),
                "total_score": int(target.total_score or 0),
                "is_me": False,
                "is_active": target_is_active,
            },
            # Maqsad guruh kontekstida ko'rinmaydi. Frontend uchun to'liq
            # backward-compat saqlash uchun bo'sh ro'yxatni qaytarmaymiz.
            "plans": [], "habits": [],
            "can_manage": False,  # ko'rinmasa yaratish ham yo'q (aslida bunday yozuv ham bo'lmasligi kerak)
            "visible": False,
            "date": today.isoformat(),
            "is_today": is_today,
            "is_future": is_future,
            "is_past": is_past,
        }

    plans = (await session.execute(
        select(Plan).where(
            and_(Plan.user_id == target_user_id, Plan.plan_date == today)
        ).order_by(Plan.scheduled_time.nullslast(), Plan.id)
    )).scalars().all()

    # Odatlarni yuklab olamiz; keyin `on_date` ga qarab shu kunda bajarilishi
    # kerak (due) va tugamagan (finished emas) bo'lganlarini qoldiramiz.
    # Saralash: eslatma vaqti erta bo'lganlar TEPADA, vaqtsizlar OXIRDA.
    all_habits = (await session.execute(
        select(Habit).where(and_(
            Habit.user_id == target_user_id, Habit.archived == False,  # noqa: E712
        ))
    )).scalars().all()

    def _habit_sort_key(h: Habit):
        # ("HH:MM" yoki None) — None ni oxirga qo'yamiz.
        rt = (h.reminder_time or "").strip()
        return (0, rt) if rt else (1, "")

    habits = [
        h for h in all_habits
        if not _habit_is_finished(h, today) and _habit_is_due_on(h, today)
    ]
    habits.sort(key=_habit_sort_key)

    # Faqat ko'rilayotgan sana odatlarining loglarini olamiz.
    habit_ids = [h.id for h in habits]
    logged_today: set[int] = set()
    if habit_ids:
        rows = (await session.execute(
            select(HabitLog.habit_id).where(
                and_(HabitLog.habit_id.in_(habit_ids), HabitLog.log_date == today)
            )
        )).all()
        logged_today = {r[0] for r in rows}

    # Maqsad (goal) bo'limi guruh kontekstida umuman ko'rinmaydi — foydalanuvchi
    # talabiga muvofiq. Bu yerda goals so'rovi bajarilmaydi.

    def _plan_dict(p):
        return {
            "id": p.id, "title": p.title, "description": p.description,
            "scheduled_time": p.scheduled_time,
            "status": p.status.value if hasattr(p.status, "value") else str(p.status),
            "created_by_user_id": p.created_by_user_id,
        }

    def _habit_dict(h):
        # Weekdays "0,2,4" → [0,2,4] (haftalik uchun).
        wd = []
        if (h.frequency or "daily") == "weekly" and h.weekdays:
            try:
                wd = sorted({int(x) for x in str(h.weekdays).split(",") if x.strip().isdigit() and 0 <= int(x) <= 6})
            except Exception:
                wd = []
        return {
            "id": h.id, "title": h.title, "icon": h.icon or "✅",
            "frequency": h.frequency or "daily",
            "reminder_time": h.reminder_time,
            "weekdays": wd,
            "done_today": h.id in logged_today,
            "created_by_user_id": h.created_by_user_id,
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
            "is_active": target_is_active,
        },
        "plans": [_plan_dict(p) for p in plans],
        "habits": [_habit_dict(h) for h in habits],
        # Maqsad guruh kontekstida ko'rinmaydi.
        "can_manage": can_manage,
        "visible": True,
        "date": today.isoformat(),
        "is_today": is_today,
        "is_future": is_future,
        "is_past": is_past,
    }


# ─────────────────────────────────────────────────────────────
#  RUXSATLAR (permissions)
# ─────────────────────────────────────────────────────────────
async def list_permissions(
    session: AsyncSession, user: User, group_id: int
) -> dict:
    """
    Joriy foydalanuvchiga tegishli ruxsatlar (endi ikki bayroq):
      • grants_out — Men KIMLARGA berdim (grantor=me): can_manage + can_view
      • grants_in  — KIMLAR MENGA berdi (grantee=me): can_manage + can_view
    """
    await require_member(session, group_id, user.id)
    # a'zolar ro'yxati (o'zim tashqari)
    members = (await session.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(and_(GroupMember.group_id == group_id, GroupMember.user_id != user.id))
    )).all()

    perms_out: dict[int, tuple[bool, bool]] = {
        int(r[0]): (bool(r[1]), bool(r[2])) for r in (await session.execute(
            select(
                GroupPermission.grantee_user_id,
                GroupPermission.can_manage,
                GroupPermission.can_view,
            ).where(and_(
                GroupPermission.group_id == group_id,
                GroupPermission.grantor_user_id == user.id,
            ))
        )).all()
    }
    perms_in: dict[int, tuple[bool, bool]] = {
        int(r[0]): (bool(r[1]), bool(r[2])) for r in (await session.execute(
            select(
                GroupPermission.grantor_user_id,
                GroupPermission.can_manage,
                GroupPermission.can_view,
            ).where(and_(
                GroupPermission.group_id == group_id,
                GroupPermission.grantee_user_id == user.id,
            ))
        )).all()
    }

    def _name(u: User) -> str:
        return (u.display_name or u.full_name or "Foydalanuvchi").strip() or "Foydalanuvchi"

    grants_out = []
    for _, u in members:
        cm, cv = perms_out.get(u.id, (False, False))
        grants_out.append({
            "user_id": u.id,
            "name": _name(u),
            "can_manage": cm,
            "can_view": bool(cv or cm),  # can_manage → auto view
        })
    grants_in = []
    for _, u in members:
        cm, cv = perms_in.get(u.id, (False, False))
        grants_in.append({
            "user_id": u.id,
            "name": _name(u),
            "can_manage": cm,
            "can_view": bool(cv or cm),
        })
    return {"grants_out": grants_out, "grants_in": grants_in}


async def set_permission(
    session: AsyncSession, user: User, group_id: int,
    grantee_user_id: int,
    can_manage: Optional[bool] = None,
    can_view: Optional[bool] = None,
) -> None:
    """
    Grantor = joriy user; grantee = boshqa a'zo.
    `can_manage` va `can_view` ixtiyoriy — faqat berilganlari yangilanadi.
    Qoidalar:
      • can_manage=True bo'lsa can_view avtomatik True qilib qulflanadi
        (chunki yaratish uchun ko'ra olish shart).
      • can_manage=False qilinsa can_view saqlanadi (foydalanuvchi ilgari o'zi
        yoqib qo'ygan bo'lishi mumkin).
      • Ikkisi ham False bo'lsa qatorni saqlab qolamiz (tarixiy).
    """
    await require_member(session, group_id, user.id)
    if grantee_user_id == user.id:
        raise GroupError("O'zingizga ruxsat berish shart emas.")
    if not await is_member(session, group_id, grantee_user_id):
        raise GroupNotFound("Bunday a'zo yo'q.")
    if can_manage is None and can_view is None:
        return  # hech narsa berilmagan

    existing = await session.scalar(select(GroupPermission).where(and_(
        GroupPermission.group_id == group_id,
        GroupPermission.grantor_user_id == user.id,
        GroupPermission.grantee_user_id == grantee_user_id,
    )))
    new_manage = bool(can_manage) if can_manage is not None else (
        bool(existing.can_manage) if existing else False
    )
    new_view = bool(can_view) if can_view is not None else (
        bool(existing.can_view) if existing else False
    )
    # can_manage bo'lsa can_view majburiy True
    if new_manage:
        new_view = True

    if existing is None:
        if new_manage or new_view:
            session.add(GroupPermission(
                group_id=group_id, grantor_user_id=user.id,
                grantee_user_id=grantee_user_id,
                can_manage=new_manage, can_view=new_view,
            ))
    else:
        existing.can_manage = new_manage
        existing.can_view = new_view
    await session.commit()


async def remove_member(
    session: AsyncSession, actor: User, group_id: int, target_user_id: int
) -> None:
    """
    Guruh egasi tomonidan a'zoni chiqarib yuborish.
    Ega o'zini bu tarzda chiqarolmaydi — u faqat guruhni o'chira oladi.
    """
    g = await get_group(session, group_id)
    if g.owner_user_id != actor.id:
        raise GroupForbidden("Faqat guruh egasi a'zoni chiqarib yuborishi mumkin.")
    if target_user_id == actor.id:
        raise GroupError("Ega o'zini chiqarolmaydi — guruhni o'chiring.")
    if not await is_member(session, group_id, target_user_id):
        raise GroupNotFound("Bunday a'zo bu guruhda yo'q.")

    # A'zolikni va u bilan bog'liq barcha permissionlarni tozalaymiz.
    await session.execute(
        GroupMember.__table__.delete().where(
            and_(GroupMember.group_id == group_id, GroupMember.user_id == target_user_id)
        )
    )
    await session.execute(
        GroupPermission.__table__.delete().where(
            and_(
                GroupPermission.group_id == group_id,
                (GroupPermission.grantor_user_id == target_user_id) |
                (GroupPermission.grantee_user_id == target_user_id),
            )
        )
    )
    await session.commit()


async def set_member_active(
    session: AsyncSession, actor: User, group_id: int, target_user_id: int,
    is_active: bool,
) -> dict:
    """
    Guruh egasi tomonidan a'zoning "aktiv" holatini o'zgartirish (jumladan
    o'zining ham — ega o'zining ma'lumotlarini boshqalardan yashira oladi).

    is_active=False bo'lsa:
      • Target'ning reja/odatlari webapp'da boshqa a'zolarga ko'rinmaydi
      • Telegram guruh xabarlarida (kunlik reja, kunlik hisobot, aggregate
        /hisobot digest) target umuman ko'rinmaydi va hisoblanmaydi
      • Target o'zi ma'lumotini ko'ra oladi (self-visibility har doim ochiq)

    Ega bo'lmagan actor uchun — GroupForbidden.
    """
    g = await get_group(session, group_id)
    if g.owner_user_id != actor.id:
        raise GroupForbidden("Faqat guruh egasi a'zoni yoqish/o'chirishi mumkin.")

    row = (await session.execute(
        select(GroupMember).where(and_(
            GroupMember.group_id == group_id,
            GroupMember.user_id == target_user_id,
        ))
    )).scalar_one_or_none()
    if row is None:
        raise GroupNotFound("Bunday a'zo bu guruhda yo'q.")

    row.is_active = bool(is_active)
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise GroupError(f"Saqlashda xato: {e}")

    return {
        "group_id": group_id,
        "user_id": target_user_id,
        "is_active": bool(row.is_active),
    }


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



# ─────────────────────────────────────────────────────────────
#  TELEGRAM DIGEST — sozlamalar (faqat guruh egasi uchun)
# ─────────────────────────────────────────────────────────────
_ALLOWED_DIGEST_HOURS = tuple(f"{h:02d}:00" for h in range(6, 24))
"""Tayyor vaqt tanlovlari (06:00..23:00). Har soatda, 24 ta variant."""


def is_valid_digest_time(hhmm: str) -> bool:
    """
    Digest_time HH:MM formatida bo'lishi va oqilona diapazonda (06:00..23:59)
    tushishi kerak. Yarim tunda yuborilishi mumkin, ammo default katalog
    soatlar bilan cheklangan (foydalanuvchi UI'da tanlaydi).
    """
    if not isinstance(hhmm, str) or len(hhmm) != 5 or hhmm[2] != ":":
        return False
    try:
        h = int(hhmm[:2])
        m = int(hhmm[3:])
    except ValueError:
        return False
    if not (0 <= h <= 23) or not (0 <= m <= 59):
        return False
    return True


async def get_telegram_settings(
    session: AsyncSession, user: User, group_id: int,
) -> dict:
    """
    Guruh egasi uchun joriy Telegram sozlamalari:
      • digest (kunlik HISOBOT) — enabled, time, last_sent, last_error
      • plans  (kunlik REJA)   — enabled, time, last_sent, last_error
    A'zo ega bo'lmasa GroupForbidden.

    Eslatma: eski `digest_show_zero` va `digest_mention` maydonlari endi UI'da
    ko'rinmaydi (doim TRUE). Backward compat uchun API javobida hali qaytariladi.
    """
    g = await get_group(session, group_id)
    if g.owner_user_id != user.id:
        raise GroupForbidden("Faqat guruh egasi sozlamalarni ko'ra oladi.")
    return {
        "group_id": g.id,
        "telegram_chat_id": g.telegram_chat_id,
        "telegram_chat_title": g.telegram_chat_title,
        # ── Kunlik HISOBOT
        "digest_enabled": bool(g.digest_enabled),
        "digest_time": g.digest_time or "21:00",
        "digest_last_sent_at": g.digest_last_sent_at.isoformat() if g.digest_last_sent_at else None,
        "digest_last_error": g.digest_last_error,
        # ── Kunlik REJA
        "plans_enabled": bool(getattr(g, "plans_enabled", False)),
        "plans_time": getattr(g, "plans_time", None) or "07:00",
        "plans_last_sent_at": g.plans_last_sent_at.isoformat() if getattr(g, "plans_last_sent_at", None) else None,
        "plans_last_error": getattr(g, "plans_last_error", None),
        # ── Backward compat (UI'da endi ko'rinmaydi)
        "digest_show_zero": bool(g.digest_show_zero),
        "digest_mention": bool(g.digest_mention),
        "allowed_times": list(_ALLOWED_DIGEST_HOURS),
    }


async def update_telegram_settings(
    session: AsyncSession, user: User, group_id: int,
    *,
    telegram_chat_id: Optional[int] = None,
    telegram_chat_title: Optional[str] = None,
    digest_enabled: Optional[bool] = None,
    digest_time: Optional[str] = None,
    plans_enabled: Optional[bool] = None,
    plans_time: Optional[str] = None,
    # Backward compat — hozircha qabul qilinadi (frontend'da yo'q).
    digest_show_zero: Optional[bool] = None,
    digest_mention: Optional[bool] = None,
) -> dict:
    """
    Guruh egasi digest/plans sozlamalarini yangilaydi.
    None qiymatli maydonlar tegilmaydi (partial update).
    """
    g = await get_group(session, group_id)
    if g.owner_user_id != user.id:
        raise GroupForbidden("Faqat guruh egasi sozlamalarni o'zgartira oladi.")

    if telegram_chat_id is not None:
        try:
            g.telegram_chat_id = int(telegram_chat_id)
        except (TypeError, ValueError):
            raise GroupError("Noto'g'ri Telegram chat id.")
    if telegram_chat_title is not None:
        g.telegram_chat_title = (telegram_chat_title or "")[:200] or None

    # ── Kunlik HISOBOT
    if digest_enabled is not None:
        if bool(digest_enabled) and not g.telegram_chat_id:
            raise GroupError("Avval Telegram guruhni tanlang.")
        g.digest_enabled = bool(digest_enabled)
        if g.digest_enabled:
            g.digest_last_error = None

    if digest_time is not None:
        if not is_valid_digest_time(digest_time):
            raise GroupError("Vaqt formati noto'g'ri (HH:MM).")
        g.digest_time = digest_time

    # ── Kunlik REJA
    if plans_enabled is not None:
        if bool(plans_enabled) and not g.telegram_chat_id:
            raise GroupError("Avval Telegram guruhni tanlang.")
        g.plans_enabled = bool(plans_enabled)
        if g.plans_enabled:
            g.plans_last_error = None

    if plans_time is not None:
        if not is_valid_digest_time(plans_time):
            raise GroupError("Vaqt formati noto'g'ri (HH:MM).")
        g.plans_time = plans_time

    # Backward compat — endi UI'da ko'rinmaydi
    if digest_show_zero is not None:
        g.digest_show_zero = bool(digest_show_zero)
    if digest_mention is not None:
        g.digest_mention = bool(digest_mention)

    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise GroupError(f"Saqlashda xato: {e}")
    await session.refresh(g)
    return await get_telegram_settings(session, user, group_id)


async def unlink_telegram(
    session: AsyncSession, user: User, group_id: int,
) -> None:
    """
    Telegram chat bog'lanishini uzadi va digestni o'chiradi.
    """
    g = await get_group(session, group_id)
    if g.owner_user_id != user.id:
        raise GroupForbidden("Faqat guruh egasi bog'lanishni uza oladi.")
    g.telegram_chat_id = None
    g.telegram_chat_title = None
    g.digest_enabled = False
    g.digest_last_error = None
    g.plans_enabled = False
    g.plans_last_error = None
    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise GroupError(f"Saqlashda xato: {e}")
