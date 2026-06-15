"""
Seasons (mavsumiy reyting / battle-pass) — Faza 3 (task 12).

Har oy yangi "mavsum" boshlanadi. Foydalanuvchi mavsum davomida season_xp
yig'adi va mavsum darajasi (tier) oshadi. Oy oxirida natija arxivlanadi
(SeasonLog) va hammaning season_xp'i nolga tushadi — "fresh start effect"
lapslangan foydalanuvchilarni qaytaradi (audit'dagi monthly retention g'oyasi).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from bot.models.season_log import SeasonLog
from bot.models.user import User

logger = logging.getLogger(__name__)


# Mavsum darajalari (kümülativ season_xp bo'yicha).
SEASON_TIERS = [
    (0,    "Bronza",   "🥉"),
    (150,  "Kumush",   "🥈"),
    (400,  "Oltin",    "🥇"),
    (800,  "Platina",  "💠"),
    (1500, "Olmos",    "💎"),
    (3000, "Afsona",   "👑"),
]


def current_season_id(day: date | None = None) -> str:
    d = day or datetime.now(TIMEZONE).date()
    return d.strftime("%Y-%m")


def tier_for_xp(xp: int) -> tuple[str, str]:
    name, icon = SEASON_TIERS[0][1], SEASON_TIERS[0][2]
    for threshold, t, i in SEASON_TIERS:
        if xp >= threshold:
            name, icon = t, i
    return name, icon


def next_tier(xp: int) -> tuple[str, int] | None:
    for threshold, t, _ in SEASON_TIERS:
        if xp < threshold:
            return t, threshold - xp
    return None


async def add_season_xp(user_id: int, amount: int) -> None:
    """Foydalanuvchining mavsum XP'sini oshiradi (ALOHIDA sessiya, best-effort)."""
    if amount <= 0:
        return
    from database.db import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as s:
            u = await s.get(User, user_id)
            if not u:
                return
            cur = current_season_id()
            # Lazy reset: mavsum almashgan bo'lsa, nolga tushiramiz.
            if (u.season_id or "") != cur:
                u.season_id = cur
                u.season_xp = 0
            u.season_xp = (u.season_xp or 0) + amount
            await s.commit()
    except Exception as e:
        logger.debug(f"add_season_xp skip: {e}")


async def get_season_status(session: AsyncSession, user: User) -> dict:
    cur = current_season_id()
    xp = (user.season_xp or 0) if (user.season_id or "") == cur else 0
    name, icon = tier_for_xp(xp)
    nxt = next_tier(xp)
    return {
        "season_id": cur,
        "season_xp": xp,
        "tier": name,
        "tier_icon": icon,
        "next_tier": nxt[0] if nxt else None,
        "to_next": nxt[1] if nxt else 0,
    }


async def season_leaderboard(session: AsyncSession, limit: int = 10) -> list[User]:
    cur = current_season_id()
    res = await session.execute(
        select(User).where(User.season_id == cur)
        .order_by(desc(User.season_xp)).limit(limit)
    )
    return res.scalars().all()


def _is_last_day_of_month(d: date) -> bool:
    return (d + timedelta(days=1)).day == 1


async def rollover_if_month_end(bot=None) -> int:
    """
    Oyning oxirgi kuni bo'lsa: har bir foydalanuvchining mavsum natijasini
    arxivlaydi (SeasonLog) va season_xp'ni nolga tushiradi. Qaytaradi: arxivlangan.
    """
    today = datetime.now(TIMEZONE).date()
    if not _is_last_day_of_month(today):
        return 0

    from database.db import AsyncSessionLocal
    season = current_season_id(today)
    archived = 0
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(User).where(
                and_(User.season_id == season, User.season_xp > 0)
            )
        )
        users = res.scalars().all()
        for u in users:
            try:
                name, _ = tier_for_xp(u.season_xp or 0)
                session.add(SeasonLog(
                    user_id=u.id, season_id=season,
                    season_xp=u.season_xp or 0, season_tier=name,
                ))
                u.season_xp = 0
                u.season_id = current_season_id(today + timedelta(days=1))
                archived += 1
            except Exception:
                pass
        try:
            await session.commit()
        except Exception:
            await session.rollback()
    logger.info(f"🏁 Season rollover: {archived} ta foydalanuvchi arxivlandi ({season})")
    return archived
