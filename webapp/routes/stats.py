"""
Gamification + coach + quest API for the WebApp.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import TIMEZONE
from webapp.security import resolve_telegram_id
from bot.models.checkin import DailyCheckin
from bot.models.plan import Plan, PlanStatus
from bot.models.user import User
from bot.services.coach_service import daily_quest, smart_coach_message
from bot.services.gamification_service import build_user_snapshot
from bot.services.user_service import get_user_by_telegram_id
from database.db import AsyncSessionLocal

router = APIRouter()


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


# ─────────────────────────────────────────────────────────────
class CheckinIn(BaseModel):
    mood: Optional[str] = None
    energy: Optional[int] = None


class CheckinOut(BaseModel):
    checkin_date: str
    mood: Optional[str] = None
    energy: Optional[int] = None


# ─────────────────────────────────────────────────────────────
@router.get("/stats")
async def get_stats(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Foydalanuvchining shaxsiy statistika snapshot'i (streak, XP, ball, yutuqlar).

    PREMIUM GATE OLIB TASHLANDI: bu endpoint HAR BIR foydalanuvchining o'z
    shaxsiy ma'lumotini qaytaradi (Premium'ga xos maxsus tahlil emas).
    Home sahifasi startup'da avtomatik chaqiradi va bepul user'larga ham
    o'z streak/XP raqamlari ko'rinishi kerak.

    Dedicated "Statistika" (charts + tarix) sahifasi frontend'da gated —
    Statistika tugmasini bosgan bepul user inline dialog ko'radi
    (webapp/static/app.js ichida premiumGate).
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return await build_user_snapshot(session, user)


@router.get("/coach")
async def get_coach(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    # PREMIUM GATE: Coach faqat Premium uchun
    from bot.services.premium_service import user_is_premium
    if not user_is_premium(user):
        raise HTTPException(
            status_code=402,
            detail="🧠 Coach faqat Premium foydalanuvchilar uchun.",
        )
    return await smart_coach_message(session, user)


@router.get("/quest")
async def get_quest(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Bugungi kunlik topshiriq (kartaga tayyor kunlik motivatsion cel).

    PREMIUM GATE OLIB TASHLANDI: kunlik topshiriq home sahifasidagi motivatsion
    element bo'lib, bepul user'larga ham foydali. Startup'da avtomatik yuklanadi
    va agar bu 402 qaytarsa foydalanuvchi Mini App'ni ochishi bilan darhol
    dialog ochilar edi (foydalanuvchi hech nima bosmaganda ham).
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return await daily_quest(session, user)


# ─────────────────────────────────────────────────────────────
#  REYTING (leaderboard) — eng ko'p ball / haftalik / streak
# ─────────────────────────────────────────────────────────────
_LB_COL = {"all": User.total_score, "week": User.weekly_xp, "streak": User.streak}
_LB_ATTR = {"all": "total_score", "week": "weekly_xp", "streak": "streak"}


def _first_name(u: User) -> str:
    raw = (u.display_name or u.full_name or "Foydalanuvchi").strip()
    return (raw.split()[0] if raw.split() else "Foydalanuvchi")[:20]


@router.get("/leaderboard")
async def leaderboard(
    period: str = "all",
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    if period not in _LB_COL:
        period = "all"
    col = _LB_COL[period]
    attr = _LB_ATTR[period]

    user = await get_user_by_telegram_id(session, telegram_id)

    # PREMIUM GATE: Reyting faqat Premium foydalanuvchilar uchun
    from bot.services.premium_service import user_is_premium
    if user and not user_is_premium(user):
        raise HTTPException(
            status_code=402,
            detail=(
                "🏆 Reyting faqat Premium foydalanuvchilar uchun. "
                "💎 Premium oling va o'zingizni boshqalar bilan solishtiring!"
            ),
        )

    rows = (await session.execute(
        select(User).order_by(col.desc().nullslast(), User.id).limit(20)
    )).scalars().all()

    # Har bir foydalanuvchi rasmini BOT orqali yuklab beruvchi proksi (avatar.py).
    # Mini App'ni ochmagan (faqat botni ishga tushirgan) foydalanuvchilar rasmi
    # ham shu yerdan yuklanadi — reytingda hamma rasmi bilan ko'rinadi.
    def _avatar_url(u: User) -> str:
        return f"/api/webapp/avatar/{u.telegram_id}"

    top = []
    for i, u in enumerate(rows):
        top.append({
            "rank": i + 1,
            "name": _first_name(u),
            "emoji": u.avatar_emoji or "🌱",
            "photo_url": _avatar_url(u),
            "value": int(getattr(u, attr) or 0),
            "is_me": bool(user and u.telegram_id == user.telegram_id),
        })

    me = None
    if user:
        my_val = int(getattr(user, attr) or 0)
        greater = await session.scalar(
            select(func.count(User.id)).where(col > my_val)
        ) or 0
        me = {
            "rank": int(greater) + 1,
            "name": _first_name(user),
            "emoji": user.avatar_emoji or "🌱",
            "photo_url": _avatar_url(user),
            "value": my_val,
            "in_top": any(t["is_me"] for t in top),
        }

    total_users = await session.scalar(select(func.count(User.id))) or 0
    return {"period": period, "top": top, "me": me, "total_users": int(total_users)}


# ─────────────────────────────────────────────────────────────
@router.get("/checkin", response_model=Optional[CheckinOut])
async def get_today_checkin(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    today = datetime.now(TIMEZONE).date()
    res = await session.execute(
        select(DailyCheckin).where(
            and_(
                DailyCheckin.user_id == user.id,
                DailyCheckin.checkin_date == today,
            )
        ).order_by(DailyCheckin.id)
    )
    # scalar_one_or_none() o'rniga first() — agar takror yozuvlar bo'lsa
    # MultipleResultsFound (500) bermasligi uchun.
    row = res.scalars().first()
    if not row:
        return None
    return CheckinOut(
        checkin_date=str(row.checkin_date),
        mood=row.mood, energy=row.energy,
    )


@router.post("/checkin", response_model=CheckinOut)
async def save_checkin(
    body: CheckinIn,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    today = datetime.now(TIMEZONE).date()

    res = await session.execute(
        select(DailyCheckin).where(
            and_(
                DailyCheckin.user_id == user.id,
                DailyCheckin.checkin_date == today,
            )
        ).order_by(DailyCheckin.id)
    )
    # Bir kunga bir nechta yozuv bo'lib qolgan bo'lsa (avvalgi parallel so'rovlar
    # natijasida) — birinchisini olib, qolganini tozalaymiz. Bu MultipleResultsFound
    # (500 "saqlashda xato") muammosini bartaraf etadi va o'zini-o'zi tuzatadi.
    rows = res.scalars().all()
    row = rows[0] if rows else None
    for extra in rows[1:]:
        await session.delete(extra)

    if row is None:
        row = DailyCheckin(user_id=user.id, checkin_date=today)
        session.add(row)

    if body.mood is not None:
        row.mood = body.mood
    if body.energy is not None:
        row.energy = body.energy

    await session.commit()
    await session.refresh(row)

    return CheckinOut(
        checkin_date=str(row.checkin_date),
        mood=row.mood, energy=row.energy,
    )



# ─────────────────────────────────────────────────────────────
#  REJALAR TARIXI — har kun uchun bajarilgan/jami (eng yangi tepada)
# ─────────────────────────────────────────────────────────────
@router.get("/history")
async def get_history(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Foydalanuvchining BUTUN reja tarixi — kun bo'yicha guruhlangan:
    har bir kun uchun jami reja soni va bajarilgan rejalar soni.
    Eng yangi kun birinchi (desc). Eng erta reja sanasidan to BUGUNgacha
    (Toshkent vaqti) BARCHA sanalar qaytariladi — reja yo'q kunlar 0/0,
    rejasi bor lekin bajarilmagan kunlar done:0.
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Foydalanuvchi topilmadi")

    # PREMIUM GATE: Tarix/kalendar faqat Premium foydalanuvchilar uchun
    from bot.services.premium_service import user_is_premium
    if not user_is_premium(user):
        raise HTTPException(
            status_code=402,
            detail=(
                "📅 Tarix va kalendar faqat Premium foydalanuvchilar uchun. "
                "💎 Premium oling va kunlik tarixingizni ko'ring!"
            ),
        )

    done_expr = func.sum(
        case((Plan.status == PlanStatus.done, 1), else_=0)
    )
    # Kunlar bo'yicha guruhlangan jami/bajarilgan — SQL'da tartiblash shart emas
    res = await session.execute(
        select(Plan.plan_date, func.count(Plan.id), done_expr)
        .where(Plan.user_id == user.id)
        .group_by(Plan.plan_date)
    )
    by_date = {}
    earliest = None
    for plan_date, total, done in res.all():
        if plan_date is None:
            continue
        by_date[plan_date] = (int(total or 0), int(done or 0))
        if earliest is None or plan_date < earliest:
            earliest = plan_date

    # Umuman reja bo'lmasa — bo'sh ro'yxat (frontend bo'sh holatni ko'rsatadi)
    if earliest is None:
        return {"days": []}

    # BUGUNdan boshlab eng erta sanagacha teskari yuramiz (eng yangi tepada).
    # 365 kunlik xavfsizlik chegarasi — ro'yxat haddan tashqari uzayib ketmasligi uchun.
    today = datetime.now(TIMEZONE).date()
    start = max(earliest, today - timedelta(days=365))
    days = []
    cur = today
    while cur >= start:
        t, dn = by_date.get(cur, (0, 0))
        days.append({"date": str(cur), "total": t, "done": dn})
        cur -= timedelta(days=1)
    return {"days": days}
