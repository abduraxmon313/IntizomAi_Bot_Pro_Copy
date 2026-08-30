from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 Userlar", callback_data="admin_users"),
            InlineKeyboardButton(text="🛡 Adminlar", callback_data="admin_admins"),
        ],
        [
            InlineKeyboardButton(text="💎 Premium", callback_data="admin_premium"),
        ],
        [
            InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin_broadcast"),
        ],
        [
            InlineKeyboardButton(text="🌐 WebApp imkoniyatlari", callback_data="admin_webapp"),
        ],
        [
            InlineKeyboardButton(text="🔑 To'lov kalitlari (WLCM)", callback_data="admin_keys"),
        ],
        [
            InlineKeyboardButton(text="💳 To'lovni faollashtirish", callback_data="admin_activate_payment"),
        ],
        [
            InlineKeyboardButton(text="🚪 Chiqish", callback_data="home"),
        ]
    ])


def admin_webapp_keyboard() -> InlineKeyboardMarkup:
    """
    "🌐 WebApp imkoniyatlari" menyusi tugmalari.

    Hozircha bu yerda sozlamalar yo'q — kelajakda WebApp'ga global ta'sir
    qiluvchi yangi bayroqlar shu menyuga qo'shiladi. Bo'lim bo'sh bo'lsa
    ham menyuni saqlaymiz (admin infrastruktura tayyor bo'lsin).
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"),
        ],
    ])


def admin_keys_keyboard(enabled: bool = False, has_token: bool = True) -> InlineKeyboardMarkup:
    """
    WLCM to'lov kalitlari bo'limi tugmalari.
      • 🔍 Tokenni tekshirish — token amaldaligini GET orqali tekshiradi (sarflamaydi).
      • 🔑 API key/secret olish — onboarding POST (token SARFLANADI), tasdiqlash bilan.
    """
    rows = []
    # Kalitlar o'rnatilgan bo'lsa — ulanishni tekshirish (/me) birinchi o'rinda.
    if enabled:
        rows.append([
            InlineKeyboardButton(text="🔌 Ulanishni tekshirish (/me)", callback_data="admin_keys_test"),
        ])
    # Token onboarding tugmalari FAQAT kalitlar hali yo'q bo'lganda ko'rsatiladi.
    # Kalitlar bor bo'lsa token allaqachon sarflangan (bir martalik) — bu tugmalar
    # faqat chalkashtiradi (har doim "invalid_or_expired" beradi).
    if has_token and not enabled:
        rows.append([
            InlineKeyboardButton(text="🔍 Tokenni tekshirish", callback_data="admin_keys_check"),
        ])
        rows.append([
            InlineKeyboardButton(text="🔑 API key/secret olish", callback_data="admin_keys_confirm"),
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_keys_confirm_keyboard() -> InlineKeyboardMarkup:
    """Onboarding'ni yakunlash (token sarflanadi) uchun tasdiqlash tugmalari."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, kalit yarat", callback_data="admin_keys_generate")],
        [InlineKeyboardButton(text="❌ Yo'q, bekor", callback_data="admin_keys")],
    ])


def admin_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Premium berish", callback_data="admin_premium_grant"),
            InlineKeyboardButton(text="➖ Premium olib tashlash", callback_data="admin_premium_revoke"),
        ],
        [
            InlineKeyboardButton(text="👥 Premium userlar", callback_data="admin_premium_users"),
        ],
        [
            InlineKeyboardButton(text="📊 Obuna statistikasi", callback_data="admin_premium_stats"),
        ],
        [
            InlineKeyboardButton(text="🎟 Promokod yaratish", callback_data="admin_promo_create"),
            InlineKeyboardButton(text="📋 Promokodlar", callback_data="admin_promo_list"),
        ],
        [
            InlineKeyboardButton(text="🎯 Maxsus promokod", callback_data="admin_promo_discount_create"),
        ],
        [
            InlineKeyboardButton(text="💰 Tariflar narxi", callback_data="admin_plans_prices"),
        ],
        [
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"),
        ]
    ])


def admin_premium_users_list_keyboard(
    records: list, page: int = 0, per_page: int = 8
) -> InlineKeyboardMarkup:
    """
    Premium userlar ro'yxati uchun paginatsiyalangan klaviatura.

    `records` — [(User, Subscription|None, days_left:int, source_emoji:str), ...]
    dan iborat ro'yxat. Har bir tugmada foydalanuvchi ismi, qolgan kun va manba
    emojisi ko'rsatiladi. Bosilganda user.id bilan detail sahifa ochiladi.
    """
    buttons = []
    start = page * per_page
    end = start + per_page
    page_records = records[start:end]

    for rec in page_records:
        user = rec["user"]
        days_left = rec["days_left"]
        emoji = rec["source_emoji"]
        name = (user.display_name or user.full_name or "Noma'lum").strip()
        # ~28 ta belgi Telegram tugmasida yaxshi ko'rinadi
        label = f"{emoji} {name[:22]} · {days_left}k"
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"admin_premium_user_{user.id}",
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"admin_premium_users_page_{page - 1}",
        ))
    if end < len(records):
        nav.append(InlineKeyboardButton(
            text="➡️", callback_data=f"admin_premium_users_page_{page + 1}",
        ))
    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_premium"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_premium_users_keyboard() -> InlineKeyboardMarkup:
    """Bitta user detali'dan ro'yxatga qaytish."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Ro'yxatga", callback_data="admin_premium_users")],
        [InlineKeyboardButton(text="🏠 Premium menyu", callback_data="admin_premium")],
    ])


def admin_plans_prices_keyboard(effective_plans: dict, overrides: dict[str, int]) -> InlineKeyboardMarkup:
    """
    Tariflar ro'yxati — har bir tarif uchun narxni tahrirlash tugmasi.
    `overrides` — DB'dagi override qiymatlar (default narxdan farqli bo'lsa 🔧 belgi ko'rsatiladi).
    """
    from bot.services.premium_service import format_price
    rows = []
    for key, plan in effective_plans.items():
        emoji = plan.get("emoji", "💎")
        title = plan.get("title", key)
        price = plan.get("price", 0)
        is_overridden = key in overrides
        mark = " 🔧" if is_overridden else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{emoji} {title} — {format_price(price)} so'm{mark}",
                callback_data=f"admin_plan_edit_{key}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_premium"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_plan_edit_keyboard(plan_key: str, is_overridden: bool) -> InlineKeyboardMarkup:
    """Bitta tarif ekranidagi tugmalar: default'ga qaytarish + orqaga."""
    rows = []
    if is_overridden:
        rows.append([
            InlineKeyboardButton(text="↺ Default narxga qaytarish", callback_data=f"admin_plan_reset_{plan_key}"),
        ])
    rows.append([
        InlineKeyboardButton(text="🔙 Tariflar", callback_data="admin_plans_prices"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promo_list_keyboard(promos: list) -> InlineKeyboardMarkup:
    """Promokodlar ro'yxati — har bir kod uchun butunlay o'chirish tugmasi."""
    rows = []
    for p in promos:
        rows.append([
            InlineKeyboardButton(
                text=f"🗑 O'chirish: {p.code}",
                callback_data=f"admin_promo_del_{p.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_premium")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_premium")]
    ])


def admin_users_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Barcha userlar", callback_data="admin_users_list"),
            InlineKeyboardButton(text="🔢 Userlar soni", callback_data="admin_users_count"),
        ],
        [
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"),
        ]
    ])


def admin_users_list_keyboard(users: list, page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    """Userlar listini pagination bilan ko'rsatadi"""
    buttons = []
    start = page * per_page
    end = start + per_page
    page_users = users[start:end]

    for user in page_users:
        name = user.full_name or "Noma'lum"
        buttons.append([
            InlineKeyboardButton(
                text=f"👤 {name[:25]}",
                callback_data=f"admin_user_{user.id}"
            )
        ])

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admin_users_page_{page - 1}"))
    if end < len(users):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admin_users_page_{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_admins_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admin_add"),
            InlineKeyboardButton(text="➖ Admin o'chirish", callback_data="admin_remove"),
        ],
        [
            InlineKeyboardButton(text="📋 Adminlar ro'yxati", callback_data="admin_list"),
        ],
        [
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"),
        ]
    ])


def back_to_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")]
    ])


def back_to_users_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_users_list")]
    ])