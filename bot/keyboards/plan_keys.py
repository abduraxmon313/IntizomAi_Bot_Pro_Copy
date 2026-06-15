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
    """Rejalar ro'yhati pastidagi tugmalar.

    Eslatma: tahrirlash bot ichida emas — Mini App (WebApp) orqali qilinadi,
    shuning uchun bu yerda "Tahrirlash" tugmasi yo'q.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Reja qo'shish", callback_data="add_plan"),
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
    buttons.append([
        InlineKeyboardButton(text="🔁 Odatlarim", callback_data="my_habits"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def plan_actions_keyboard(plan_id: int, subtasks: list | None = None) -> InlineKeyboardMarkup:
    """Bitta reja ichidagi tugmalar (+ qadamlar/izoh)."""
    rows = [
        [
            InlineKeyboardButton(text="✅ Bajardim", callback_data=f"done_{plan_id}"),
            InlineKeyboardButton(text="❌ Bajara olmadim", callback_data=f"failed_{plan_id}"),
        ],
    ]
    # Mavjud qadamlar — bosib belgilash uchun
    for s in (subtasks or [])[:10]:
        mark = "✅" if s.completed else "⬜️"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {s.title[:30]}", callback_data=f"st_toggle_{s.id}",
        )])
    rows.append([
        InlineKeyboardButton(text="➕ Qadam", callback_data=f"st_add_{plan_id}"),
        InlineKeyboardButton(text="📝 Izoh", callback_data=f"note_add_{plan_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🔁 Kunlik odat", callback_data=f"recur_make_{plan_id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delete_{plan_id}"),
        InlineKeyboardButton(text="🔙 Orqaga", callback_data="my_plans"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recurrence_choice_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    """Takrorlanish turini tanlash."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Har kuni", callback_data=f"recur_set_{plan_id}_daily")],
        [InlineKeyboardButton(text="📆 Ish kunlari (Du–Ju)", callback_data=f"recur_set_{plan_id}_weekdays")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"plan_{plan_id}")],
    ])


def habits_keyboard(templates: list) -> InlineKeyboardMarkup:
    """Takrorlanuvchi odatlar ro'yxati — har biri to'xtatish tugmasi bilan."""
    rows = []
    rec_label = {"daily": "Har kuni", "weekdays": "Ish kunlari", "weekly": "Haftalik"}
    for t in templates:
        tm = f" 🕐{t.scheduled_time}" if t.scheduled_time else ""
        rows.append([InlineKeyboardButton(
            text=f"🔁 {t.title[:28]}{tm} · {rec_label.get(t.recurrence, t.recurrence)}",
            callback_data=f"habit_{t.id}",
        )])
    rows.append([InlineKeyboardButton(text="🔙 Rejalarim", callback_data="my_plans")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def habit_actions_keyboard(template_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Takrorlashni to'xtatish", callback_data=f"habit_stop_{template_id}")],
        [InlineKeyboardButton(text="🔙 Odatlarim", callback_data="my_habits")],
    ])


def back_to_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Rejalarim", callback_data="my_plans")]
    ])


def done_failed_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    """Notification xabarida bajardim/bajara olmadim + kechiktirish (snooze)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Bajardim", callback_data=f"done_{plan_id}"),
            InlineKeyboardButton(text="❌ Bajara olmadim", callback_data=f"failed_{plan_id}"),
        ],
        [
            InlineKeyboardButton(text="😴 10 daq", callback_data=f"snooze_{plan_id}_10"),
            InlineKeyboardButton(text="🕐 30 daq", callback_data=f"snooze_{plan_id}_30"),
            InlineKeyboardButton(text="⏰ 1 soat", callback_data=f"snooze_{plan_id}_60"),
        ],
    ])