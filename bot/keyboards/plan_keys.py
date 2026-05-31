from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def confirm_plans_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="confirm_plans"),
            InlineKeyboardButton(text="🔄 Qayta yozish", callback_data="retry_plans"),
        ],
        [
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_plans"),
        ]
    ])


def plan_list_actions_keyboard() -> InlineKeyboardMarkup:
    """Rejalar ro'yhati pastidagi tugmalar"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Reja qo'shish", callback_data="add_plan"),
            InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="edit_plans"),
        ],
        [
            InlineKeyboardButton(text="🗑 O'chirish", callback_data="my_plans"),
            InlineKeyboardButton(text="📈 Hisobot", callback_data="report"),
        ]
    ])


def plans_list_keyboard(plans: list) -> InlineKeyboardMarkup:
    """Har bir reja uchun tugma — detail ko'rish uchun"""
    buttons = []
    status_icons = {"pending": "⏳", "done": "✅", "failed": "❌"}

    for plan in plans:
        icon = status_icons.get(plan.status.value, "⏳")
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {plan.title[:35]}",
                callback_data=f"plan_{plan.id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="➕ Qo'shish", callback_data="add_plan"),
        InlineKeyboardButton(text="📈 Hisobot", callback_data="report"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def plan_actions_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    """Bitta reja ichidagi tugmalar"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Bajardim", callback_data=f"done_{plan_id}"),
            InlineKeyboardButton(text="❌ Bajara olmadim", callback_data=f"failed_{plan_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delete_{plan_id}"),
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="my_plans"),
        ]
    ])


def back_to_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Rejalarim", callback_data="my_plans")]
    ])


def done_failed_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    """Notification xabarida bajardim/bajara olmadim"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Bajardim", callback_data=f"done_{plan_id}"),
            InlineKeyboardButton(text="❌ Bajara olmadim", callback_data=f"failed_{plan_id}"),
        ]
    ])