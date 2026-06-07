"""
Premium (custom / animated) emoji yordamchilari.

╔══════════════════════════════════════════════════════════════════════════╗
║ MUHIM SHART                                                                ║
║ Telegram qoidasiga ko'ra BOT custom (premium) emoji YUBORA olishi uchun    ║
║ bot Fragment'da (fragment.com) QO'SHIMCHA USERNAME sotib olgan bo'lishi     ║
║ SHART. Foydalanuvchining shaxsiy Telegram Premium'i botga bu imkonni       ║
║ BERMAYDI. Yuborilgan custom emojini hamma (premium bo'lmaganlar ham) ko'radi.║
╚══════════════════════════════════════════════════════════════════════════╝

Foydalanish (parse_mode=HTML bilan):

    from bot.utils.premium_emoji import tg_emoji, send_with_premium_emoji

    text = f"Salom {tg_emoji('5368324170671202286', '🔥')}!"
    await send_with_premium_emoji(bot, chat_id, text)

`custom_emoji_id` (document_id) ni qanday olish:
  • Custom emoji bor xabarni botga FORWARD qiling va entity.custom_emoji_id ni
    o'qing (extract_custom_emoji_ids), yoki
  • bot.get_sticker_set("<emoji_set_name>") orqali har bir sticker.custom_emoji_id ni oling.
"""
import re
from typing import List

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

# <tg-emoji ...>FALLBACK</tg-emoji> teglarini topish uchun.
_TG_EMOJI_RE = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.IGNORECASE | re.DOTALL)


def tg_emoji(emoji_id: str, fallback: str) -> str:
    """
    HTML custom-emoji tegini qaytaradi (parse_mode='HTML' bilan ishlatiladi).

    fallback — bot Fragment'da username sotib olmagan bo'lsa yoki klient
    ko'rsata olmasa o'rnida ko'rinadigan oddiy emoji (masalan '🔥').
    """
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def strip_tg_emoji(html_text: str) -> str:
    """<tg-emoji> teglarini ichidagi oddiy (fallback) emojiga almashtiradi."""
    return _TG_EMOJI_RE.sub(r"\1", html_text or "")


async def send_with_premium_emoji(bot: Bot, chat_id, text: str, **kwargs):
    """
    Custom (premium) emoji bilan yuborishga harakat qiladi; agar bot eligible
    bo'lmasa (Fragment username yo'q) yoki custom emoji rad etilsa — oddiy
    emojiga tushib QAYTA yuboradi.

    Shu sabab kod Fragment username sotib olinmagan holatda ham BUZILMAYDI.
    """
    kwargs.setdefault("parse_mode", "HTML")
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "custom_emoji" in msg or "custom emoji" in msg or "entities" in msg:
            # Custom emoji ruxsat etilmadi — fallback oddiy emoji bilan yuboramiz.
            return await bot.send_message(chat_id, strip_tg_emoji(text), **kwargs)
        raise


def extract_custom_emoji_ids(message: Message) -> List[str]:
    """
    Xabardagi custom emoji id larini (custom_emoji_id) ro'yxat qilib qaytaradi.

    Custom emoji bor xabarni botga forward qilib, kerakli id larni shu orqali
    yig'ib olish mumkin.
    """
    ids: List[str] = []
    for ent in (message.entities or []):
        if getattr(ent, "type", None) == "custom_emoji" and getattr(ent, "custom_emoji_id", None):
            ids.append(ent.custom_emoji_id)
    return ids
