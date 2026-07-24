from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Private chat uchun asosiy reply keyboard."""
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


def get_reply_keyboard_for_chat(chat_type: str) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    """
    Chat turiga qarab keyboard qaytaradi:
      • Private chat → main_reply_keyboard (to'liq reply keyboard)
      • Boshqa chatlar (group, supergroup, channel) → ReplyKeyboardRemove
    """
    if chat_type == "private":
        return main_reply_keyboard()
    return ReplyKeyboardRemove()
