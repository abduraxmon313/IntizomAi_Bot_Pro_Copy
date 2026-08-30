"""
WebApp obuna (premium) holati API.

Frontend ushbu endpoint orqali foydalanuvchining premium ekanini tekshiradi.
Premium bo'lmasa — Mini App'da paywall (ogohlantirish) ko'rsatiladi.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import BOT_USERNAME, FREE_DAILY_PLAN_LIMIT
from webapp.security import resolve_telegram_id
from bot.services.premium_service import get_status, format_price, get_plans
from bot.services.user_service import get_user_by_telegram_id
from database.db import AsyncSessionLocal

router = APIRouter()


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


class PlanOut(BaseModel):
    key: str
    title: str
    days: int
    price: int
    price_label: str
    emoji: Optional[str] = None
    tag: Optional[str] = None
    original_price: Optional[int] = None
    original_price_label: Optional[str] = None


class SubscriptionOut(BaseModel):
    is_premium: bool
    premium_until: Optional[str] = None
    days_left: int = 0
    plan: Optional[str] = None
    plan_title: Optional[str] = None
    free_daily_plan_limit: int
    plans: list[PlanOut]
    # Bot username — frontend'da "botga o'tkazish" deep-link yasash uchun.
    # `t.me/<bot_username>?start=premium` ko'rinishida ishlatiladi.
    bot_username: str


def _plans_catalog(discount_percent: int = 0) -> list[PlanOut]:
    """
    Mini App katalogi — bot bilan bir xil "effective" (admin override qilgan)
    tariflardan olinadi. Shu tariqa foydalanuvchi ko'rgan narx checkout paytida
    to'lanadigan narxga aynan mos keladi (bot/webapp mismatch bo'lmaydi).

    discount_percent > 0 bo'lsa — 1m va 3m tariflarga chegirma qo'llanadi.
    """
    if discount_percent > 0:
        from bot.services.plan_pricing import get_discounted_plans
        plans_data = get_discounted_plans(discount_percent)
    else:
        plans_data = get_plans()

    result = []
    for key, p in plans_data.items():
        original_price = p.get("original_price")
        result.append(PlanOut(
            key=key,
            title=p["title"],
            days=p["days"],
            price=p["price"],
            price_label=format_price(p["price"]),
            emoji=p.get("emoji"),
            tag=p.get("tag") or None,
            original_price=original_price if original_price and original_price != p["price"] else None,
            original_price_label=format_price(original_price) if original_price and original_price != p["price"] else None,
        ))
    return result


@router.get("/subscription", response_model=SubscriptionOut)
async def get_subscription(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
    promo_code: Optional[str] = None,
):
    bot_username = (BOT_USERNAME or "intizomAi_bot").lstrip("@")

    # Promokod bo'lsa — chegirma foizini aniqlaymiz
    discount_percent = 0
    if promo_code:
        from bot.services.premium_service import validate_promocode
        result = await validate_promocode(session, promo_code)
        if result.valid and result.discount_percent > 0:
            discount_percent = result.discount_percent

    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        # Foydalanuvchi hali botda /start bosmagan — premium emas
        return SubscriptionOut(
            is_premium=False,
            days_left=0,
            free_daily_plan_limit=FREE_DAILY_PLAN_LIMIT,
            plans=_plans_catalog(discount_percent=discount_percent),
            bot_username=bot_username,
        )

    status = await get_status(session, user)
    return SubscriptionOut(
        is_premium=status.is_premium,
        premium_until=status.premium_until.isoformat() if status.premium_until else None,
        days_left=status.days_left,
        plan=status.plan,
        plan_title=status.plan_title,
        free_daily_plan_limit=FREE_DAILY_PLAN_LIMIT,
        plans=_plans_catalog(discount_percent=discount_percent),
        bot_username=bot_username,
    )



class CheckoutIn(BaseModel):
    plan: str


class CheckoutOut(BaseModel):
    # DIQQAT: bu endpoint endi Paylov to'lov URL'ini QAYTARMAYDI.
    # To'lov jarayoni faqat bot ichida amalga oshiriladi. Bu yerda esa
    # foydalanuvchini bot ichidagi Premium menyusiga olib boradigan
    # Telegram deep-link qaytariladi. Frontend uni ochsa — Mini App yopiladi
    # va bot chati ochilib, tanlangan tarif uchun to'lov usulini tanlash
    # bosqichi ko'rsatiladi.
    #
    # `checkout_url` maydoni backward-compat uchun saqlanadi (eski frontend
    # ham shuni o'qiydi). Yangi frontend `bot_url` ni ustuvor ishlatishi
    # mumkin.
    bot_url: str
    checkout_url: str  # bot_url ning aliasi (backward-compat)
    # Redirect turi — frontend `openTelegramLink`ni ishlatishi kerakligini bilishi uchun.
    redirect: str = "telegram"


@router.post("/checkout", response_model=CheckoutOut)
async def create_checkout(
    body: CheckoutIn,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Tanlangan tarif uchun BOT DEEP-LINK ini qaytaradi.

    Eski xatti-harakat (Paylov to'lov URL'ini yaratib qaytarish) OLIB TASHLANDI.
    To'lov faqat bot ichida amalga oshiriladi — Mini App'dan bu endpoint chaqirilsa,
    foydalanuvchi bot chatiga o'tkaziladi va u yerda odatiy Premium oqimi
    (tarif tasdiqlash → to'lov usulini tanlash → Paylov checkout) davom etadi.

    Sabab: Xavfsizlik va yagona to'lov oqimi. To'lov URL'ini Mini App'da yasash
    va boshqarish murakkab (checkout retry, xato holatlari, hisob-kitob) — bot
    ichida esa allaqachon to'liq oqim mavjud. Bir joyda ushlab turish debug va
    audit qilishni osonlashtiradi.
    """
    # Effective plans (admin override + config default) — plan mavjudligini tekshirish.
    plan = get_plans().get(body.plan)
    if not plan:
        raise HTTPException(400, "Noma'lum tarif.")

    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Avval botda /start bosing.")

    # Deep-link payload: `premium_<plan_key>` — bot /start handleri buni tanib,
    # foydalanuvchini to'g'ridan-to'g'ri o'sha tarifning to'lov usulini tanlash
    # oynasiga olib boradi (uzaytirish oqimi).
    username = (BOT_USERNAME or "intizomAi_bot").lstrip("@")
    payload = f"premium_{body.plan}"
    bot_url = f"https://t.me/{username}?start={payload}"

    return CheckoutOut(
        bot_url=bot_url,
        checkout_url=bot_url,  # eski frontend uchun alias
        redirect="telegram",
    )
