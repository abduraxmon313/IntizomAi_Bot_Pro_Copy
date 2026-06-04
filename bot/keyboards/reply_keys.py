from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Mening statusim"),
                KeyboardButton(text="📋 Rejalarim"),
            ],
            [
                KeyboardButton(text="📈 Hisobot"),
                KeyboardButton(text="➕ Reja qo'shish"),
            ],
            [
                KeyboardButton(text="💎 Premium"),
                KeyboardButton(text="📞 Bog'lanish"),
            ],
        ],
        resize_keyboard=True,
        persistent=True
    )
