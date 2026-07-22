"""
Botning har bir Telegram chatdagi ishtirokini kuzatuvchi jadval.

Bir foydalanuvchi WebApp guruh sozlamalarida "Statistikani Telegram guruhga
yuborish" tugmasini bosgach, bot uni qaysi guruhga ulash mumkinligini bilishi
uchun barcha o'zi qatnashgan Telegram chatlarni bu jadvalda saqlaydi.

Ma'lumot qanday to'ldiriladi:
  • `my_chat_member` update — bot chatga qo'shildi/chiqarildi (asosiy manba).
  • Chatdagi har xabar (`message`) — chat_title/username keshini yangilash uchun.

Xavfsizlik: bu jadval Telegram foydalanuvchilarining shaxsiy ma'lumotini
saqlamaydi — faqat bot ko'rgan chatlar metadatasi. `added_by` — botni
guruhga qo'shgan foydalanuvchining Telegram id si (audit uchun, ixtiyoriy).
"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, String

from database.db import Base


class BotChat(Base):
    __tablename__ = "bot_chats"

    # Telegram chat id — superguruhda manfiy (masalan -100123...).
    chat_id = Column(BigInteger, primary_key=True)
    # 'group' | 'supergroup' | 'channel' | 'private'
    # (WebApp digest'i uchun faqat group/supergroup ishlatiladi).
    chat_type = Column(String(20), nullable=False)
    chat_title = Column(String(200), nullable=True)
    chat_username = Column(String(64), nullable=True)  # ochiq guruhlar uchun

    # Botning joriy holati chatda:
    #   'member' | 'administrator' | 'creator' | 'left' | 'kicked' | 'restricted'
    # Faqat 'member' yoki 'administrator' bo'lgan chatlarga xabar yuborish
    # mumkin. Boshqa holatda digest yuborilmaydi.
    bot_status = Column(String(20), default="member", nullable=False)
    # Bot chatga xabar yubora oladimi (administrator huquqi yoki default a'zo).
    # Guruh sozlamalarida "faqat adminlar yozadi" yoqilgan bo'lsa, member bot
    # ham yuborolmaydi — bu bayroq shu holatni belgilaydi.
    bot_can_send = Column(Boolean, default=True, nullable=False)

    # Botni qo'shgan foydalanuvchining Telegram id si (my_chat_member.from_user).
    added_by = Column(BigInteger, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
    # Chatdan oxirgi xabar kelgan vaqt — chat_title keshining "yangiligi"
    # ko'rsatkichi. Har xabarga yozmasligimiz uchun 30 daqiqalik throttle bilan
    # yangilanadi (bot/handlers/chat_events.py).
    last_seen_at = Column(DateTime, nullable=True)
