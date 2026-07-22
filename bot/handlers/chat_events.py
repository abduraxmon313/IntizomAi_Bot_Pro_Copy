"""
Bot Telegram chatlarga qo'shilgan/chiqarilganini kuzatuvchi handlerlar.

Maqsad: `bot_chats` jadvalini yangilab turish. WebApp guruh egasi
"Statistikani Telegram guruhga yuborish" tugmasini bosgach, bot faqat shu
jadvaldagi chatlarni Telegram guruh nomzodi sifatida ko'radi.

`my_chat_member` update — Telegram Bot API'ning kanonik yo'li. Bot chatga
qo'shilganda, chiqarilganda yoki huquqlari o'zgarganda yuboriladi.

`message` update — chat sarlavhasi o'zgarishi bo'lsa kesh yangilanadi (30
daqiqada bir marta, throttled).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.bot_chat import BotChat

logger = logging.getLogger(__name__)
router = Router()


# Chat sarlavhasi keshini yangilash oralig'i — chatdagi har xabarda emas, 30
# daqiqada bir marta, DB yozuvlari yukini kamaytirish uchun.
_TITLE_REFRESH_MIN = timedelta(minutes=30)


def _extract_can_send(new_member) -> bool:
    """
    Yangi holatdan botning xabar yuborish huquqini aniqlaydi.
      • 'administrator' — `can_post_messages` yoki umumiy huquq berilsa TRUE.
      • 'member' — default; guruh sozlamalari (faqat adminlar) buni to'sishi
        mumkin, ammo Telegram Bot API buni my_chat_member payloadida bermaydi
        — real yuborishda `Forbidden: bot can't send messages to this chat`
        xatosi orqali bilib olamiz.
      • Boshqa statuslar (left/kicked/restricted) — FALSE.
    """
    status = getattr(new_member, "status", None)
    if status in ("member", "creator"):
        return True
    if status == "administrator":
        # Aiogram 3.x ChatMemberAdministrator obyekti — can_send_messages yo'q,
        # can_post_messages faqat kanal uchun. Guruh admini default xabar
        # yuborishi mumkin, shuning uchun TRUE.
        return True
    if status == "restricted":
        # Restricted member — can_send_messages bayrog'i bo'lishi mumkin.
        return bool(getattr(new_member, "can_send_messages", False))
    return False


@router.my_chat_member()
async def on_bot_membership_change(
    event: ChatMemberUpdated, session: AsyncSession,
):
    """
    Bot chatga qo'shildi/chiqarildi/huquqlari o'zgardi.

    Faqat group/supergroup chatlar kuzatiladi — WebApp digest guruh chatlariga
    yuboriladi (channel/private uchun bu funksiya kerak emas).
    """
    chat = event.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    new_status = event.new_chat_member.status if event.new_chat_member else "left"
    can_send = _extract_can_send(event.new_chat_member) if event.new_chat_member else False

    row = await session.get(BotChat, chat.id)
    now = datetime.utcnow()
    if row is None:
        row = BotChat(
            chat_id=chat.id,
            chat_type=chat.type,
            chat_title=(chat.title or "")[:200] or None,
            chat_username=(chat.username or "")[:64] or None,
            bot_status=new_status,
            bot_can_send=can_send,
            added_by=(event.from_user.id if event.from_user else None),
            added_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        session.add(row)
    else:
        row.chat_type = chat.type
        if chat.title:
            row.chat_title = chat.title[:200]
        row.chat_username = (chat.username or "")[:64] or None
        row.bot_status = new_status
        row.bot_can_send = can_send
        row.updated_at = now
        # Bot yangi qo'shilyapti — `added_by` yozuvsiz qolmasin (ilgari left/kicked
        # bo'lgan bo'lishi mumkin).
        if new_status in ("member", "administrator", "creator") and event.from_user:
            row.added_by = event.from_user.id

    try:
        await session.commit()
        logger.info(
            f"bot_chat: chat_id={chat.id} status={new_status} "
            f"title={(chat.title or '')[:40]!r} by={event.from_user.id if event.from_user else '-'}"
        )
    except Exception as e:
        await session.rollback()
        logger.warning(f"bot_chat commit xato: {e}")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def on_group_message(message: Message, session: AsyncSession):
    """
    Guruh xabari — bot_chats.chat_title/username keshini yangilash (throttled).

    Bot boshqa hech nima QILMAYDI (guruhda javob bermaydi). Bu shunchaki chat
    sarlavhasi o'zgarganda yoki bot avval yozib qolinmagan chatda paydo bo'lsa
    kesh to'ldirilishi uchun.
    """
    chat = message.chat
    row = await session.get(BotChat, chat.id)
    now = datetime.utcnow()

    if row is None:
        # my_chat_member bo'yicha yozuv yo'q edi — hozir yaratamiz. Bu ilgari
        # botni qo'shgan xabar o'tkazib yuborilgan holat uchun himoya.
        row = BotChat(
            chat_id=chat.id,
            chat_type=chat.type,
            chat_title=(chat.title or "")[:200] or None,
            chat_username=(chat.username or "")[:64] or None,
            bot_status="member",
            bot_can_send=True,
            added_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        session.add(row)
    else:
        # Throttle: 30 daqiqadan bir marta yozuvni yangilaymiz.
        if row.last_seen_at and (now - row.last_seen_at) < _TITLE_REFRESH_MIN:
            # Sarlavha o'zgargan bo'lsa BARIBIR yangilaymiz (kam uchraydi).
            if chat.title and row.chat_title != chat.title[:200]:
                row.chat_title = chat.title[:200]
            else:
                return
        else:
            row.last_seen_at = now
            if chat.title:
                row.chat_title = chat.title[:200]
            row.chat_username = (chat.username or "")[:64] or None
            row.chat_type = chat.type

    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.debug(f"bot_chat title refresh skip: {e}")
