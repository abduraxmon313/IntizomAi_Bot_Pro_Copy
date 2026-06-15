"""
Qidiruv (search) — rejalar va maqsadlar bo'yicha. Faza 2.

Foydalanuvchi 200 ta reja to'plagach, kerakli narsani topa olmasligi — eski
mahsulotning zaif tomoni edi. Bu modul title/notes/tags bo'yicha qidiradi.
"""
from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.goal import Goal
from bot.models.plan import Plan
from bot.models.user import User


def _like(term: str) -> str:
    return f"%{term.strip().lower()}%"


async def search_plans(
    session: AsyncSession, user: User, query: str, limit: int = 20
) -> list[Plan]:
    """Reja sarlavhasi, izohi yoki teglari bo'yicha qidiradi (shablonlardan tashqari)."""
    q = (query or "").strip()
    if not q:
        return []
    pat = _like(q)
    from sqlalchemy import func
    res = await session.execute(
        select(Plan).where(
            and_(
                Plan.user_id == user.id,
                Plan.is_template == False,  # noqa: E712
                or_(
                    func.lower(Plan.title).like(pat),
                    func.lower(func.coalesce(Plan.notes, "")).like(pat),
                    func.lower(func.coalesce(Plan.tags, "")).like(pat),
                    func.lower(func.coalesce(Plan.category, "")).like(pat),
                ),
            )
        ).order_by(Plan.plan_date.desc()).limit(limit)
    )
    return res.scalars().all()


async def search_goals(
    session: AsyncSession, user: User, query: str, limit: int = 20
) -> list[Goal]:
    """Maqsad sarlavhasi, izohi yoki teglari bo'yicha qidiradi."""
    q = (query or "").strip()
    if not q:
        return []
    pat = _like(q)
    from sqlalchemy import func
    res = await session.execute(
        select(Goal).where(
            and_(
                Goal.user_id == user.id,
                or_(
                    func.lower(Goal.title).like(pat),
                    func.lower(func.coalesce(Goal.notes, "")).like(pat),
                    func.lower(func.coalesce(Goal.tags, "")).like(pat),
                    func.lower(func.coalesce(Goal.category, "")).like(pat),
                ),
            )
        ).order_by(Goal.created_at.desc()).limit(limit)
    )
    return res.scalars().all()


# ─────────────────────────────────────────────────────────────
#  KATEGORIYA / TEGLAR — avtomatik aniqlash
# ─────────────────────────────────────────────────────────────
# Reja sarlavhasidan kategoriya taxmin qilish (oddiy kalit so'z asosida).
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "sport":   ["sport", "yugur", "turnik", "mashq", "fitnes", "gym", "suzish", "velosiped"],
    "oqish":   ["kitob", "o'qi", "oqi", "dars", "imtihon", "konspekt", "mutolaa"],
    "ish":     ["ish", "loyiha", "proyekt", "vazifa", "deadline", "hisobot", "uchrashuv"],
    "salomatlik": ["suv", "uyqu", "uxla", "nonushta", "ovqat", "meditatsiya", "nafas", "dush"],
    "ibodat":  ["namoz", "ibodat", "qur'on", "quron", "zikr", "tahajjud"],
    "til":     ["ingliz", "english", "til", "so'z", "soz yodla", "grammatika"],
}

CATEGORY_LABELS = {
    "sport": "🏃 Sport",
    "oqish": "📚 O'qish",
    "ish": "💼 Ish",
    "salomatlik": "💚 Salomatlik",
    "ibodat": "🕌 Ibodat",
    "til": "🗣 Til",
    "boshqa": "📌 Boshqa",
}


def guess_category(title: str) -> str:
    """Sarlavhadan kategoriya taxmin qiladi. Topilmasa 'boshqa'."""
    t = (title or "").lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in t for w in words):
            return cat
    return "boshqa"


def normalize_tags(raw: str | None) -> str | None:
    """'#sport, kitob ;ertalab' -> 'sport,kitob,ertalab' (toza, vergulli)."""
    if not raw:
        return None
    import re
    parts = re.split(r"[,;#\s]+", raw.strip())
    tags = [p.lower() for p in parts if p]
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out[:10]) or None
