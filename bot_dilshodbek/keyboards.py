"""Dilshodbek bot klaviaturalari."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# /start dan keyin chiqadigan yagona tugma (eski botdagi kabi).
NEWS_BUTTON_TEXT = "Siz uchun yangilik"


def news_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=NEWS_BUTTON_TEXT)]],
        resize_keyboard=True,
    )


def admin_main_keyboard() -> InlineKeyboardMarkup:
    """Dilshodbek bot admin paneli — userlarga xabar yuborish."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Userlarga xabar yuborish", callback_data="dilshod_broadcast")],
        [InlineKeyboardButton(text="🚪 Chiqish", callback_data="dilshod_admin_close")],
    ])


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yuborish", callback_data="dilshod_broadcast_send"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="dilshod_admin_panel"),
        ],
    ])


def back_to_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="dilshod_admin_panel")],
    ])
