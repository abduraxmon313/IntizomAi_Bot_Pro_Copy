"""
WebApp obuna (premium) holati API.

Frontend ushbu endpoint orqali foydalanuvchining premium ekanini tekshiradi.
Premium bo'lmasa — Mini App'da paywall (ogohlantirish) ko'rsatiladi.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import FREE_DAILY_PLAN_LIMIT, SUBSCRIPTION_PLANS, PAYLOV_ENABLED
from webapp.security import resolve_telegram_id
from bot.services.premium_service import get_status, format_price, user_is_premium
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


class SubscriptionOut(BaseModel):
    is_premium: bool
    premium_until: Optional[str] = None
    days_left: int = 0
    plan: Optional[str] = None
    plan_title: Optional[str] = None
    free_daily_plan_limit: int
    plans: list[PlanOut]


def _plans_catalog() -> list[PlanOut]:
    return [
        PlanOut(
            key=key,
            title=p["title"],
            days=p["days"],
            price=p["price"],
            price_label=format_price(p["price"]),
        )
        for key, p in SUBSCRIPTION_PLANS.items()
    ]


@router.get("/subscription", response_model=SubscriptionOut)
async def get_subscription(
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        # Foydalanuvchi hali botda /start bosmagan — premium emas
        return SubscriptionOut(
            is_premium=False,
            days_left=0,
            free_daily_plan_limit=FREE_DAILY_PLAN_LIMIT,
            plans=_plans_catalog(),
        )

    status = await get_status(session, user)
    return SubscriptionOut(
        is_premium=status.is_premium,
        premium_until=status.premium_until.isoformat() if status.premium_until else None,
        days_left=status.days_left,
        plan=status.plan,
        plan_title=status.plan_title,
        free_daily_plan_limit=FREE_DAILY_PLAN_LIMIT,
        plans=_plans_catalog(),
    )



class CheckoutIn(BaseModel):
    plan: str


class CheckoutOut(BaseModel):
    checkout_url: str
    order_id: Optional[str] = None
    external_id: str


@router.post("/checkout", response_model=CheckoutOut)
async def create_checkout(
    body: CheckoutIn,
    telegram_id: int = Depends(resolve_telegram_id),
    session: AsyncSession = Depends(get_session),
):
    """
    Tanlangan tarif uchun Paylov checkout yaratadi va to'lov sahifasi URL'ini
    qaytaradi. To'lov muvaffaqiyatli bo'lsa premium webhook orqali ochiladi.
    """
    if not PAYLOV_ENABLED:
        raise HTTPException(503, "To'lov tizimi hozircha sozlanmagan.")

    plan = SUBSCRIPTION_PLANS.get(body.plan)
    if not plan:
        raise HTTPException(400, "Noma'lum tarif.")

    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        raise HTTPException(404, "Avval botda /start bosing.")
    if user_is_premium(user):
        raise HTTPException(409, "Sizda allaqachon faol obuna bor.")

    from bot.services.payment_service import create_checkout_order
    from bot.services.paylov import PaylovError
    try:
        order, checkout_url = await create_checkout_order(session, user, body.plan)
    except PaylovError as e:
        raise HTTPException(502, f"To'lov tizimi xatosi: {e}")

    if not checkout_url:
        raise HTTPException(502, "Checkout URL olinmadi.")

    try:
        from bot.services.analytics_service import log_event
        await log_event("checkout_started", telegram_id=user.telegram_id, user_id=user.id, props=body.plan)
    except Exception:
        pass

    return CheckoutOut(
        checkout_url=checkout_url,
        order_id=order.provider_order_id,
        external_id=order.external_id,
    )
