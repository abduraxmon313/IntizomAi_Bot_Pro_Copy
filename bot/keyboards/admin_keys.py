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
            InlineKeyboardButton(text="🚪 Chiqish", callback_data="home"),
        ]
    ])


def admin_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Premium berish", callback_data="admin_premium_grant"),
            InlineKeyboardButton(text="➖ Premium olib tashlash", callback_data="admin_premium_revoke"),
        ],
        [
            InlineKeyboardButton(text="📊 Obuna statistikasi", callback_data="admin_premium_stats"),
        ],
        [
            InlineKeyboardButton(text="🎟 Promokod yaratish", callback_data="admin_promo_create"),
            InlineKeyboardButton(text="📋 Promokodlar", callback_data="admin_promo_list"),
        ],
        [
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel"),
        ]
    ])


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