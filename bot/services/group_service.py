"""
Study groups / accountability circles — Faza 4 (task 13 & 14).

Bu IntizomAI'ning eng kuchli strategik ochilishi (audit Step 5): talabalar
tabiiy ravishda guruhlashadi (sinfdoshlar, imtihon guruhi). Guruh ichida umumiy
reyting va umumiy streak — ilova "do'stlaring bor"ligi sababli yopishqoq bo'ladi
(network effect + switching cost). Hech bir raqobatchi talaba-ijtimoiy burchakni
egallamagan.

Deep-link: https://t.me/<bot>?start=grp_<invite_code> orqali guruhga qo'shilish.
"""
from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.plan import Plan, PlanStatus
from bot.models.study_group import GroupMember, StudyGroup
from bot.models.user import User

logger = logging.getLogger(__name__)

GROUP_DEEPLINK_PREFIX = "grp_"
MAX_GROUPS_PER_USER = 1   # bir vaqtda bitta guruh (joriy)
_ALPHABET = string.ascii_uppercase + string.digits


def _today() -> date:
    return datetime.now(TIMEZONE).date()


def _gen_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


def build_group_link(username: str, code: str) -> str:
    username = (username or "intizomAi_bot").lstrip("@")
    return f"https://t.me/{username}?start={GROUP_DEEPLINK_PREFIX}{code}"


def parse_group_code(payload: str | None) -> str | None:
    if not payload:
        return None
    payload = payload.strip()
    if not payload.startswith(GROUP_DEEPLINK_PREFIX):
        return None
    code = payload[len(GROUP_DEEPLINK_PREFIX):].strip().upper()
    return code or None


async def create_group(session: AsyncSession, user: User, name: str) -> StudyGroup:
    """Yangi guruh tuzadi va tuzuvchini a'zo qiladi."""
    # Unikal kod yaratamiz
    code = _gen_code()
    for _ in range(5):
        exists = await session.scalar(
            select(StudyGroup.id).where(StudyGroup.invite_code == code)
        )
        if not exists:
            break
        code = _gen_code()

    group = StudyGroup(
        name=(name or "Mening guruhim").strip()[:80],
        invite_code=code,
        owner_telegram_id=user.telegram_id,
    )
    session.add(group)
    await session.commit()
    await session.refresh(group)

    await _add_member(session, group.id, user)
    return group


async def _add_member(session: AsyncSession, group_id: int, user: User) -> bool:
    """Foydalanuvchini guruhga a'zo qiladi (takror bo'lsa False)."""
    existing = await session.scalar(
        select(GroupMember.id).where(
            and_(GroupMember.group_id == group_id,
                 GroupMember.telegram_id == user.telegram_id)
        )
    )
    if existing:
        # joriy guruhni baribir yangilab qo'yamiz
        user.group_id = group_id
        await session.commit()
        return False
    session.add(GroupMember(group_id=group_id, telegram_id=user.telegram_id))
    user.group_id = group_id
    await session.commit()
    return True


async def join_by_code(session: AsyncSession, user: User, code: str) -> tuple[bool, str, StudyGroup | None]:
    code = (code or "").strip().upper()
    res = await session.execute(
        select(StudyGroup).where(
            and_(StudyGroup.invite_code == code, StudyGroup.is_active == True)  # noqa: E712
        )
    )
    group = res.scalar_one_or_none()
    if not group:
        return False, "Bunday guruh topilmadi.", None
    if group.owner_telegram_id == user.telegram_id:
        return False, "Bu sizning guruhingiz.", group
    added = await _add_member(session, group.id, user)
    if not added:
        return False, "Siz allaqachon shu guruhdasiz.", group
    return True, "ok", group


async def get_user_group(session: AsyncSession, user: User) -> StudyGroup | None:
    if not user.group_id:
        return None
    return await session.get(StudyGroup, user.group_id)


async def leave_group(session: AsyncSession, user: User) -> bool:
    if not user.group_id:
        return False
    await session.execute(
        GroupMember.__table__.delete().where(
            and_(GroupMember.group_id == user.group_id,
                 GroupMember.telegram_id == user.telegram_id)
        )
    )
    user.group_id = None
    await session.commit()
    return True


async def group_member_ids(session: AsyncSession, group_id: int) -> list[int]:
    rows = (await session.execute(
        select(GroupMember.telegram_id).where(GroupMember.group_id == group_id)
    )).scalars().all()
    return list(rows)


@dataclass
class MemberRank:
    telegram_id: int
    name: str
    weekly_done: int
    streak: int
    xp: int


async def group_leaderboard(session: AsyncSession, group_id: int) -> list[MemberRank]:
    """
    Guruh haftalik reytingi — oxirgi 7 kundagi bajarilgan rejalar bo'yicha.
    (audit task14: weekly leaderboard within group).
    """
    tids = await group_member_ids(session, group_id)
    if not tids:
        return []
    today = _today()
    week_ago = today - timedelta(days=6)

    ranks: list[MemberRank] = []
    for tid in tids:
        user = (await session.execute(
            select(User).where(User.telegram_id == tid)
        )).scalar_one_or_none()
        if not user:
            continue
        weekly_done = await session.scalar(
            select(func.count(Plan.id)).where(
                and_(
                    Plan.user_id == user.id,
                    Plan.plan_date >= week_ago,
                    Plan.plan_date <= today,
                    Plan.status == PlanStatus.done,
                    Plan.is_template == False,  # noqa: E712
                )
            )
        ) or 0
        ranks.append(MemberRank(
            telegram_id=tid,
            name=(user.full_name or "A'zo").split(" ")[0],
            weekly_done=weekly_done,
            streak=user.streak or 0,
            xp=user.xp or 0,
        ))
    ranks.sort(key=lambda r: (r.weekly_done, r.streak, r.xp), reverse=True)
    return ranks


async def group_summary_text(session: AsyncSession, group: StudyGroup) -> str:
    board = await group_leaderboard(session, group.id)
    total_weekly = sum(r.weekly_done for r in board)
    lines = [
        f"{group.emoji} <b>{group.name}</b>",
        f"🔑 Taklif kodi: <code>{group.invite_code}</code>",
        f"👥 A'zolar: <b>{len(board)}</b>",
        f"🔥 Shu hafta birgalikda: <b>{total_weekly} ta</b> reja bajarildi\n",
        "🏆 <b>Haftalik reyting:</b>",
    ]
    for i, r in enumerate(board[:15], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(f"{medal} {r.name} — {r.weekly_done} ta · 🔥{r.streak}")
    if not board:
        lines.append("Hali a'zo yo'q.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  DEEP-LINK orqali qo'shilish (start.py dan chaqiriladi)
# ─────────────────────────────────────────────────────────────
async def handle_group_deeplink(session: AsyncSession, user: User,
                                payload: str | None, bot=None) -> bool:
    """
    /start grp_<code> bo'lsa — foydalanuvchini guruhga qo'shadi va xabar beradi.
    Qaytaradi: qo'shildi (True) yoki yo'q.
    """
    code = parse_group_code(payload)
    if not code:
        return False
    ok, msg, group = await join_by_code(session, user, code)
    if ok and group and bot is not None:
        try:
            from bot.services.analytics_service import track
            await track(user.telegram_id, "group_join", user_id=user.id, code=code)
        except Exception:
            pass
        try:
            await bot.send_message(
                user.telegram_id,
                f"👥 <b>«{group.name}» guruhiga qo'shildingiz!</b>\n\n"
                "Endi birgalikda intizomli bo'lasiz. Har kuni reja bajaring — "
                "guruh reytingida yuqoriga chiqing!\n\n"
                "Guruhni ko'rish: /guruh",
                parse_mode="HTML",
            )
        except Exception:
            pass
        # Guruh egasiga xabar
        try:
            joiner_name = user.full_name or "Yangi a'zo"
            await bot.send_message(
                group.owner_telegram_id,
                f"🎉 <b>{joiner_name}</b> «{group.name}» guruhingizga qo'shildi!",
                parse_mode="HTML",
            )
        except Exception:
            pass
    return ok
