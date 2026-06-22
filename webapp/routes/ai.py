"""
AI Coach suhbat (chat) API.

Foydalanuvchi savol bersa — AI uning BARCHA maqsad va rejalarini, streak/discipline
holatini ko'rib, shundan kelib chiqib javob beradi va u bilan suhbatlashadi.
Suhbatlar saqlanmaydi (ephemeral) — frontend tarixni o'zida yuritadi.
"""
import logging
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from webapp.security import resolve_telegram_id
from bot.models.checkin import DailyCheckin
from bot.models.plan import Plan, PlanStatus
from bot.services.ai_service import chat_with_coach
from bot.services.goal_service import get_user_goals
from bot.services.premium_service import check_and_consume_ai, user_is_premium
from bot.services.user_service import get_user_by_telegram_id
from database.db import AsyncSessionLocal

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessage]


class ChatOut(BaseModel):
    reply: str
    is_premium: bool
    remaining: int = -1
    limit: int = -1


class ContextOut(BaseModel):
    context: str


GOAL_TYPE_UZ = {
    "yearly": "Yillik",
    "monthly": "Oylik",
    "weekly": "Haftalik",
    "daily": "Kunlik",
}

UZ_WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


async def _build_context(session: AsyncSession, user) -> str:
    """
    Foydalanuvchining to'liq holatini AI uchun matn blokiga jamlaydi:
      • Daraja / XP / streak / discipline score
      • BARCHA maqsadlar (tur bo'yicha, bajarilgan/bajarilmagan)
      • Oxirgi 7 kunlik rejalar ro'yxati (kun bo'yicha, holati bilan)
      • Oxirgi 7 kunlik kayfiyat va energiya darajasi

    Har bir bo'lim ALOHIDA try bilan o'ralgan — bittasi xato bersa ham
    qolgan ma'lumotlar yo'qolmaydi (production'da bo'sh fallback bermaslik uchun).
    """
    today = datetime.now(TIMEZONE).date()
    week_ago = today - timedelta(days=6)
    lines = []

    # ── Shaxsiy progress (user ustunlaridan to'g'ridan-to'g'ri — xavfsiz) ──
    try:
        name = (getattr(user, "full_name", "") or "").split(" ")[0] or "Do'st"
        lines.append(f"FOYDALANUVCHI ISMI: {name}")
        lines.append(
            f"PROGRESS: Daraja {getattr(user, 'level', 1) or 1} | "
            f"{getattr(user, 'xp', 0) or 0} XP | "
            f"Streak {getattr(user, 'streak', 0) or 0} kun "
            f"(rekord {getattr(user, 'longest_streak', 0) or 0}) | "
            f"Discipline score {getattr(user, 'discipline_score', 50) or 50}/100"
        )
        lines.append(
            f"Premium: {'ha' if user_is_premium(user) else 'yoq (bepul)'}"
        )
    except Exception as e:
        logger.warning(f"ctx progress xato: {e}")

    # ── BARCHA MAQSADLAR ─────────────────────────────────────
    lines.append("\n=== BARCHA MAQSADLAR ===")
    try:
        goals = await get_user_goals(session, user)
        if goals:
            by_type: dict[str, list] = {}
            for g in goals:
                by_type.setdefault(g.goal_type, []).append(g)
            for gtype in ("yearly", "monthly", "weekly", "daily"):
                items = by_type.get(gtype, [])
                if not items:
                    continue
                done = sum(1 for g in items if g.completed)
                label = GOAL_TYPE_UZ.get(gtype, gtype)
                lines.append(f"{label} ({done}/{len(items)} bajarilgan):")
                for g in items[:20]:
                    mark = "✅ bajarilgan" if g.completed else "⬜️ jarayonda"
                    extra = f" — {g.description}" if getattr(g, "description", None) else ""
                    period = f" [{g.period}]" if getattr(g, "period", None) else ""
                    lines.append(f"  • {g.title}{period} — {mark}{extra}")
        else:
            lines.append("Hali maqsad qo'shilmagan.")
    except Exception as e:
        logger.warning(f"ctx goals xato: {e}")
        lines.append("(maqsadlarni o'qishda muammo)")

    # ── OXIRGI 7 KUNLIK REJALAR ──────────────────────────────
    lines.append("\n=== OXIRGI 7 KUNLIK REJALAR ===")
    try:
        res_plans = await session.execute(
            select(Plan).where(
                and_(
                    Plan.user_id == user.id,
                    Plan.plan_date >= week_ago,
                    Plan.plan_date <= today,
                )
            ).order_by(Plan.plan_date, Plan.scheduled_time)
        )
        week_plans = res_plans.scalars().all()
        if week_plans:
            by_date: dict = {}
            for p in week_plans:
                by_date.setdefault(p.plan_date, []).append(p)
            for d in sorted(by_date.keys(), reverse=True):
                wd = UZ_WEEKDAYS[d.weekday()]
                day_plans = by_date[d]
                done = sum(1 for p in day_plans if p.status == PlanStatus.done)
                tag = " (BUGUN)" if d == today else ""
                lines.append(f"{d.strftime('%d.%m')} {wd}{tag} — {done}/{len(day_plans)} bajarildi:")
                for p in day_plans[:12]:
                    if p.status == PlanStatus.done:
                        mark = "✅ bajarildi"
                    elif p.status == PlanStatus.failed:
                        mark = "❌ bajarilmadi"
                    else:
                        mark = "⬜️ kutilmoqda"
                    tm = f" {p.scheduled_time}" if p.scheduled_time else ""
                    lines.append(f"  • {p.title}{tm} — {mark}")
        else:
            lines.append("Oxirgi 7 kunda reja qo'shilmagan.")
    except Exception as e:
        logger.warning(f"ctx plans xato: {e}")
        lines.append("(rejalarni o'qishda muammo)")

    # ── OXIRGI 7 KUNLIK KAYFIYAT / ENERGIYA ──────────────────
    lines.append("\n=== OXIRGI 7 KUNLIK KAYFIYAT VA ENERGIYA ===")
    try:
        res_chk = await session.execute(
            select(DailyCheckin).where(
                and_(
                    DailyCheckin.user_id == user.id,
                    DailyCheckin.checkin_date >= week_ago,
                    DailyCheckin.checkin_date <= today,
                )
            ).order_by(DailyCheckin.checkin_date)
        )
        week_checkins = res_chk.scalars().all()
        wrote = False
        for c in week_checkins:
            wd = UZ_WEEKDAYS[c.checkin_date.weekday()]
            parts = []
            if c.mood:
                parts.append(f"kayfiyat {c.mood}")
            if c.energy:
                parts.append(f"energiya {c.energy}/5")
            if parts:
                lines.append(f"  {c.checkin_date.strftime('%d.%m')} {wd}: " + ", ".join(parts))
                wrote = True
        if not wrote:
            lines.append("Oxirgi 7 kunda kayfiyat belgilanmagan.")
    except Exception as e:
        logger.warning(f"ctx checkins xato: {e}")
        lines.append("(kayfiyatni o'qishda muammo)")

    return "\n".join(lines)


@router.get("/ai/context", response_model=ContextOut)
async def ai_context(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Foydalanuvchining maqsad/reja/kayfiyat ma'lumotlarini o'qiy oladigan
    matn ko'rinishida qaytaradi. Frontend buni chat input'iga oldindan
    yozib qo'yadi — foydalanuvchi uni jo'natib, keyin savolini beradi.
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi. Avval botda /start bosing.")
    try:
        ctx = await _build_context(session, user)
    except Exception as e:
        logger.error(f"⚠️ AI context endpoint xato: {type(e).__name__}: {e}", exc_info=True)
        ctx = "Ma'lumot vaqtincha mavjud emas."
    return ContextOut(context=ctx)


@router.post("/ai/chat", response_model=ChatOut)
async def ai_chat(
    body: ChatIn,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi. Avval botda /start bosing.")

    if not body.messages:
        raise HTTPException(400, "Bo'sh xabar")

    last = body.messages[-1]
    if last.role != "user" or not last.content.strip():
        raise HTTPException(400, "Oxirgi xabar foydalanuvchidan bo'lishi kerak")

    # Kunlik AI limiti (free) — premiumda cheksiz
    limit = await check_and_consume_ai(session, user)
    if not limit.allowed:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Bugungi bepul AI suhbat limiti tugadi ({limit.limit}/kun). "
                "Cheksiz AI Coach uchun Premium oling 💎"
            ),
        )

    # Kontekst qurish xato bersa ham suhbat to'xtamasligi kerak
    try:
        context_block = await _build_context(session, user)
    except Exception as e:
        logger.error(f"⚠️ AI kontekst qurishda xato: {type(e).__name__}: {e}", exc_info=True)
        context_block = "Ma'lumot vaqtincha mavjud emas."

    history = [{"role": m.role, "content": m.content} for m in body.messages]
    reply = await chat_with_coach(context_block, history)

    return ChatOut(
        reply=reply,
        is_premium=user_is_premium(user),
        remaining=limit.remaining,
        limit=limit.limit,
    )
