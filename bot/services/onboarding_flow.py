"""
Onboarding — kafolatlangan BIRINCHI G'ALABA (first win) oqimi.

Muammo (audit): eski onboarding bitta matn edi — "ovozli xabar yuboring".
Ko'p yangi foydalanuvchi birinchi rejani ham yaratmasdan ketib qolardi
(activation past). Yechim: yangi foydalanuvchiga bir tegishda qo'shiladigan,
DARHOL bajarib bo'ladigan namuna rejalar beramiz. Foydalanuvchi 30 soniyada
birinchi rejasini yaratadi va bajaradi → "first win" hissi → retention oshadi.

Namuna rejalar VAQTSIZ yaratiladi (scheduled_time=None) — shuning uchun ular
darhol "bajarildi" deb belgilanishi mumkin (plan_block_reason "future" bermaydi).
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# (key, emoji, title, score) — bir tegishli tezkor rejalar.
QUICKSTART_TEMPLATES: dict[str, dict] = {
    "water":   {"emoji": "💧", "title": "1 stakan suv ichish",        "score": 3},
    "walk":    {"emoji": "🚶", "title": "5 daqiqa yurish",            "score": 3},
    "read":    {"emoji": "📖", "title": "5 daqiqa kitob o'qish",       "score": 5},
    "tidy":    {"emoji": "🧹", "title": "Stolni tartibga keltirish",   "score": 3},
    "breathe": {"emoji": "🧘", "title": "1 daqiqa chuqur nafas olish", "score": 3},
}


def quickstart_keyboard() -> InlineKeyboardMarkup:
    """Yangi foydalanuvchiga 'bir tegishda boshlash' tugmalari."""
    rows = []
    items = list(QUICKSTART_TEMPLATES.items())
    # 2 tadan qatorlab joylaymiz
    for i in range(0, len(items), 2):
        row = []
        for key, t in items[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=f"{t['emoji']} {t['title']}",
                callback_data=f"qs_{key}",
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(
        text="✍️ O'zim yozaman", callback_data="qs_skip",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def first_win_text(user_name: str | None = None) -> str:
    """Birinchi g'alaba tabrigi — kuchli ijobiy tasdiq (identity affirming)."""
    name = user_name or "do'st"
    return (
        f"🎉 <b>Birinchi g'alaba, {name}!</b>\n\n"
        "Siz endi shunchaki 'qilaman' deydigan emas — <b>qiluvchisiz</b>. "
        "Aynan shu kichik qadamlar katta intizomni quradi.\n\n"
        "🔥 Streak boshlandi! Endi har kuni davom eting.\n"
        "💡 Keyingi rejangizni ovoz yoki matn bilan yuboring — "
        "men uni avtomatik tartibga solaman."
    )
