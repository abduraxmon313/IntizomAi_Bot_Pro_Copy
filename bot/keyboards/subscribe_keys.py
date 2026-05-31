from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)

from bot.config import SUBSCRIPTION_PLANS, WEBAPP_URL
from bot.services.premium_service import format_price


def plans_keyboard(bonus_days: int = 0, promo_applied: bool = False, free: bool = False) -> InlineKeyboardMarkup:
    """
    Obuna planlarini tanlash klaviaturasi.
      • free=True (bonus_days=0 promokod) → har bir tarif "BEPUL" ko'rinadi.
      • bonus_days>0 → har bir tarif nomida "+N kun" qo'shiladi.
    """
    rows = []
    for key, plan in SUBSCRIPTION_PLANS.items():
        emoji = plan.get("emoji", "💎")
        tag = plan.get("tag", "")
        tag_str = f" ({tag})" if tag else ""
        if free:
            label = f"🎁 {plan['title']} — BEPUL{tag_str}"
        elif bonus_days > 0:
            label = f"{emoji} {plan['title']} +{bonus_days} kun — {format_price(plan['price'])} so'm"
        else:
            label = f"{emoji} {plan['title']} — {format_price(plan['price'])} so'm{tag_str}"
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"sub_plan_{key}")
        ])

    # Promokod tugmasi — bekor qilishdan tepada
    if promo_applied:
        rows.append([
            InlineKeyboardButton(text="🏷️ Promokodni o'zgartirish", callback_data="sub_promo_enter")
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="🏷️ Promokod kiritish", callback_data="sub_promo_enter")
        ])
    rows.append([
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sub_cancel")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_keyboard(plan_key: str) -> InlineKeyboardMarkup:
    """To'lov oynasi tugmalari (hozircha to'lov simulyatsiya qilinadi)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 To'lovni amalga oshirish", callback_data=f"sub_pay_{plan_key}")],
        [InlineKeyboardButton(text="🔙 Tariflarga qaytish", callback_data="open_subscription")],
    ])


def promocode_keyboard() -> InlineKeyboardMarkup:
    """Promokod kiritish bosqichidagi tugmalar."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Tariflarga qaytish", callback_data="open_subscription")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sub_cancel")],
    ])


def buy_subscription_keyboard() -> InlineKeyboardMarkup:
    """Limit yoki paywall xabarlaridan obuna sahifasiga o'tish."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Obuna sotib olish", callback_data="open_subscription")]
    ])


def premium_active_keyboard() -> InlineKeyboardMarkup:
    """Faol obunaga ega foydalanuvchi uchun (Mini App ochish)."""
    rows = []
    if WEBAPP_URL:
        rows.append([
            InlineKeyboardButton(
                text="✨ Mini App ochish",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ])
    rows.append([
        InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="home")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
