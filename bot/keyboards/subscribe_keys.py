from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)

from bot.config import WEBAPP_URL, PAYLOV_PROVIDERS
from bot.services.premium_service import format_price, get_plans

# Provayder kodlari → foydalanuvchiga ko'rinadigan nom + emoji.
PROVIDER_LABELS = {
    "payme": "Payme",
    "click": "Click",
    "uzum": "Uzum",
    "paylov": "Paylov",
    "card": "Bank kartasi",
}


def plans_keyboard(bonus_days: int = 0, promo_applied: bool = False) -> InlineKeyboardMarkup:
    """
    Obuna planlarini tanlash klaviaturasi (obuna sotib olish uchun).
      • bonus_days>0 (`+` turidagi promokod) → har bir tarif nomida "+N kun" qo'shiladi.

    Eslatma: bepul (`-`) turdagi promokodlar bu klaviaturaga kelmaydi — ular
    kiritilishi bilan darhol (to'lovsiz) faollashtiriladi.
    """
    rows = []
    # Effective plans — admin o'zgartirgan narxlar keshdan keladi.
    for key, plan in get_plans().items():
        emoji = plan.get("emoji", "💎")
        tag = plan.get("tag", "")
        tag_str = f" ({tag})" if tag else ""
        if bonus_days > 0:
            label = f"{emoji} {plan['title']} +{bonus_days} kun — {format_price(plan['price'])} so'm"
        else:
            label = f"{emoji} {plan['title']} — {format_price(plan['price'])} so'm{tag_str}"
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"sub_plan_{key}")
        ])

    # Promokod tugmasi — bekor qilishdan tepada
    if promo_applied:
        rows.append([
            InlineKeyboardButton(text="🎟️ Promokodni o'zgartirish", callback_data="sub_promo_enter")
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="🎟️ Promokod kiritish", callback_data="sub_promo_enter")
        ])
    rows.append([
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="sub_cancel")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_keyboard(plan_key: str, providers: list[str] | None = None) -> InlineKeyboardMarkup:
    """
    To'lov usulini (provayderni) tanlash klaviaturasi.

    Har bir provayder tugmasi `sub_pay_<plan_key>_<provider>` callback yuboradi.
    Provayderlar 2 ustun qilib joylanadi (config PAYLOV_PROVIDERS dan).
    """
    provs = providers or PAYLOV_PROVIDERS
    rows, row = [], []
    for p in provs:
        label = PROVIDER_LABELS.get(p, p.capitalize())
        row.append(InlineKeyboardButton(
            text=f"💳 {label}", callback_data=f"sub_pay_{plan_key}_{p}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="🔙 Tariflarga qaytish", callback_data="open_subscription")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def premium_promo_keyboard() -> InlineKeyboardMarkup:
    """Obunasiz foydalanuvchi uchun: sotib olish, bepul premium (taklif) yoki Premium haqida."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Obuna sotib olish", callback_data="open_subscription")],
        [InlineKeyboardButton(text="🎁 Bepul premium olish", callback_data="free_premium")],
        [InlineKeyboardButton(text="ℹ️ Premium haqida", url="https://t.me/Intizom_AI")],
    ])


def free_premium_keyboard() -> InlineKeyboardMarkup:
    """«Bepul premium olish» ekrani — taklif havolasini olish tugmasi."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Taklif havolasi", callback_data="referral_link")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="premium_menu")],
    ])


def referral_share_keyboard(link: str) -> InlineKeyboardMarkup:
    """
    Ulashiladigan taklif xabari tagidagi tugma — botga deep-link orqali o'tkazadi.
    Bu xabar forward qilinganda tugma ham saqlanadi.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 IntizomAi'ni ochish", url=link)],
    ])


def contact_keyboard() -> InlineKeyboardMarkup:
    """Bog'lanish: admin + kanal."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💻 Admin bilan bog'lanish", url="https://t.me/Dilshod_Toxirov_adminbot")],
        [InlineKeyboardButton(text="📢 IntizomAI kanali", url="https://t.me/Intizom_AI")],
    ])


def premium_active_keyboard() -> InlineKeyboardMarkup:
    """Faol obunaga ega foydalanuvchi uchun (Mini App ochish + do'st taklif qilish)."""
    rows = []
    if WEBAPP_URL:
        rows.append([
            InlineKeyboardButton(
                text="✨ Mini App ochish",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ])
    rows.append([
        InlineKeyboardButton(text="🎁 Do'st taklif qilib +1 hafta olish", callback_data="free_premium")
    ])
    rows.append([
        InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="home")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
