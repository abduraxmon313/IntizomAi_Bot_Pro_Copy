"""
Mobil ilovaga Telegram orqali kirish so'rovlari.

Oqim:
  1) Ilova tasodifiy maxfiy `nonce` yaratadi va
     `https://t.me/<bot>?start=applogin_<nonce>` havolasini ochadi.
  2) Bot so'rovni yozib qo'yadi va foydalanuvchidan "Tasdiqlash" tugmasini
     bosishni so'raydi (begona havola orqali kirib qolmaslik uchun).
  3) Tasdiqlangach `telegram_id` va `approved_at` to'ldiriladi.
  4) Ilova `/api/webapp/app-auth/poll` orqali so'raydi, JWT tokenni oladi —
     yozuv shu zahoti o'chiriladi (bir martalik).

DB'da nonce'ning o'zi emas, SHA-256 xeshi saqlanadi.
"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, String

from database.db import Base


class AppLoginRequest(Base):
    __tablename__ = "app_login_requests"

    nonce_hash = Column(String(64), primary_key=True)
    telegram_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_at = Column(DateTime, nullable=True)
