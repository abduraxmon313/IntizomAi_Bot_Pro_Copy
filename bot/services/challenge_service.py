"""
Coach challenges (murabbiy chaqiriqlari) — Faza 3 (task 12).

7-kunlik kabi qisqa, aniq chaqiriqlar foydalanuvchini har kuni qaytishga undaydi
("in-app challenge" — audit'dagi retention g'oyasi). Taraqqiyot kuniga bir marta
oshadi (o'sha kuni kamida 1 ta reja bajarilsa). Tugaganda bonus AI kredit beriladi.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.challenge import Challenge
from bot.models.user import User

logger = logging.getLogger(__name__)


# Mavjud chaqiriqlar katalogi.
CHALLENGE_CATALOG: dict[str, dict] = {
    "streak_7": {
        "title": "7 kun ketma-ket", "icon": "🔥", "target": 7, "days": 7,
        "reward_credits": 10,
        "desc": "7 kun davomida har kuni kamida 1 ta reja bajaring.",
    },
    "consistent_14": {
        "title": "14 kun izchillik", "icon": "💪", "target": 14, "days": 14,
        "reward_credits": 25,
        "desc": "14 kun davomida faol bo'ling.",
    },
    "sprint_3": {
        "title": "3 kunlik sprint", "icon": "⚡", "target": 3, "days": 3,
        "reward_credits": 5,
        "desc": "3 kun ketma-ket — kichik, lekin kuchli start.",
    },
}


def _today() -> date:
    return datetime.now(TIMEZONE).date()


async def list_active(session: AsyncSession, user_id: int) -> list[Challenge]:
    res = await session.execute(
        select(Challenge).where(
            and_(Challenge.user_id == user_id, Challenge.status == "active")
        ).order_by(Challenge.started_at.desc())
    )
    return res.scalars().all()


async def start_challenge(session: AsyncSession, user: User, code: str) -> tuple[bool, str]:
    spec = CHALLENGE_CATALOG.get(code)
    if not spec:
        return False, "Bunday chaqiruv yo'q."

    # Allaqachon faol shu chaqiruv bormi?
    existing = await session.scalar(
        select(Challenge.id).where(
            and_(Challenge.user_id == user.id, Challenge.code == code,
                 Challenge.status == "active")
        )
    )
    if existing:
        return False, "Bu chaqiruv allaqachon faol."

    ch = Challenge(
        user_id=user.id,
        code=code,
        title=spec["title"],
        icon=spec["icon"],
        target=spec["target"],
        progress=0,
        reward_xp=spec.get("reward_credits", 10),
        status="active",
        started_at=datetime.utcnow(),
        ends_at=datetime.utcnow() + timedelta(days=spec["days"]),
    )
    session.add(ch)
    await session.commit()
    return True, spec["desc"]


async def on_plan_completed(user_id: int, plan=None) -> list[Challenge]:
    """
    Reja bajarilganda chaqirilади (callback.done). Har faol chaqiruvning
    taraqqiyotini kuniga BIR marta oshiradi. Tugaganlarni 'done' qiladi va
    bonus AI kredit beradi. ALOHIDA sessiya — request oqimiga ta'sir qilmaydi.
    """
    from database.db import AsyncSessionLocal
    completed: list[Challenge] = []
    today = _today()
    async with AsyncSessionLocal() as s:
        res = await s.execute(
            select(Challenge).where(
                and_(Challenge.user_id == user_id, Challenge.status == "active")
            )
        )
        challenges = res.scalars().all()
        user = await s.get(User, user_id)
        for ch in challenges:
            # Muddati o'tdimi?
            if ch.ends_at and ch.ends_at < datetime.utcnow():
                ch.status = "failed"
                continue
            # Bugun allaqachon hisoblanganmi?
            if ch.last_progress_date == today:
                continue
            ch.progress = (ch.progress or 0) + 1
            ch.last_progress_date = today
            if ch.progress >= ch.target:
                ch.status = "done"
                ch.completed_at = datetime.utcnow()
                completed.append(ch)
                # Mukofot — bonus AI kreditlari
                if user:
                    user.ai_credits = (user.ai_credits or 0) + (ch.reward_xp or 0)
        try:
            await s.commit()
        except Exception:
            await s.rollback()
    return completed


def available_to_start(active_codes: set[str]) -> list[tuple[str, dict]]:
    """Hali boshlanmagan chaqiriqlar ro'yxati."""
    return [(c, spec) for c, spec in CHALLENGE_CATALOG.items() if c not in active_codes]
