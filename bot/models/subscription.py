from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey
)
from sqlalchemy.orm import relationship
from datetime import datetime

from database.db import Base


class Subscription(Base):
    """
    Bitta obuna xaridi / faollashtirish yozuvi (tarix).

    Har bir obuna sotib olish (yoki promokod orqali faollashtirish) shu
    jadvalda saqlanadi. Foydalanuvchining JORIY premium holati
    `users.is_premium` + `users.premium_until` da denormalizatsiya qilingan,
    bu jadval esa to'liq tarix va audit uchun.
    """
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    plan = Column(String(16), nullable=False)        # 1m | 3m | 6m | 12m
    days = Column(Integer, nullable=False)            # obuna davomiyligi (kun)
    price = Column(Integer, default=0)                # so'mda (ko'rsatish uchun)

    source = Column(String(24), default="promocode")  # promocode | card | admin | gift
    promocode = Column(String(64), nullable=True)     # ishlatilgan promokod (bo'lsa)

    started_at = Column(DateTime, default=datetime.utcnow)   # faollashgan vaqt (UTC)
    expires_at = Column(DateTime, nullable=False)            # tugash vaqti (UTC)
    is_active = Column(Boolean, default=True)               # joriy faol obunami

    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="subscriptions")


class Promocode(Base):
    """
    Promokodlar — sinov bosqichida obunani faollashtirish uchun.

    `code` — kiritiladigan matn (masalan, 'intizom').
    `plan` — agar berilgan bo'lsa, foydalanuvchi tanlovidan qat'i nazar shu
              planni beradi; None bo'lsa foydalanuvchi tanlagan plan qo'llanadi.
    `is_free` — promokod turi:
        • False (`+`) → foydalanuvchi obunani SOTIB OLISHI kerak; `bonus_days`
          tanlangan tarif ustiga qo'shimcha kun sifatida qo'shiladi.
        • True (`-`) → foydalanuvchi obuna sotib olmaydi; `bonus_days` ta kunga
          premium AVTOMATIK (to'lovsiz) ochiladi.
    `bonus_days` —
        • `+` turida: tarif ustiga qo'shiladigan qo'shimcha kunlar.
        • `-` turida: to'lovsiz ochiladigan premium kunlari soni.
    `max_uses` — 0 = cheksiz.
    """
    __tablename__ = "promocodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False)

    plan = Column(String(16), nullable=True)          # 1m | 3m | 6m | 12m | None
    bonus_days = Column(Integer, default=0)
    is_free = Column(Boolean, default=False)          # True (`-`) = to'lovsiz; False (`+`) = sotib olish + bonus

    max_uses = Column(Integer, default=0)             # 0 = cheksiz
    used_count = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)      # promokodning amal qilish muddati
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(BigInteger, nullable=True)    # qaysi admin yaratgan (telegram_id)
