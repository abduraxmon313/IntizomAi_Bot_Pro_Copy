"""
Guruh/supergroup/kanal chatlarda Reply Keyboard ko'rsatilmasligini ta'minlovchi middleware.

Agar chat turi PRIVATE bo'lmasa:
  • Har bir xabar javobida reply_markup sifatida ReplyKeyboardRemove yuboriladi
    (agar handler reply_markup=ReplyKeyboardMarkup bergan bo'lsa).
  • Telegram Menu Button (commands menu) guruh chatlardan olib tashlanadi.

Private chatlarda hech narsa o'zgarmaydi — mavjud funksionallik to'liq saqlanadi.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    TelegramObject,
)

logger = logging.getLogger(__name__)


class GroupKeyboardRemoveMiddleware(BaseMiddleware):
    """
    Message middleware — non-private chatlarda Reply Keyboard'ni olib tashlaydi.

    Ishlash tartibi:
      1. Handler OLDIN — agar chat turi private bo'lmasa, `_group_no_reply_kb`
         flag'ini data'ga qo'yadi.
      2. Handler KEYIN — hech narsa qilmaydi (handler allaqachon ChatType filtriga
         ega bo'lishi kerak).

    Qo'shimcha himoya sifatida: agar handler noto'g'ri tarzda guruhga
    ReplyKeyboardMarkup yubormoqchi bo'lsa ham, `reply_keys.py` ichidagi
    `get_reply_keyboard_for_chat()` helper'i orqali to'g'ri keyboard tanlanadi.

    ASOSIY VAZIFA: guruh chatlarida /start (chat_events.py) yoki boshqa handler
    ishlaganda, bot hech qachon Reply Keyboard ko'rsatmasligi uchun.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Faqat Message turi bilan ishlaymiz
        if not isinstance(event, Message):
            return await handler(event, data)

        chat = event.chat
        if chat and chat.type != ChatType.PRIVATE:
            # Guruh/supergroup/kanal — flag qo'yamiz (handler ichida
            # ishlatilishi mumkin).
            data["_is_group_chat"] = True
        else:
            data["_is_group_chat"] = False

        return await handler(event, data)
