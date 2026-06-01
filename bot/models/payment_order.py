from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey
)
from sqlalchemy.orm import relationship
from datetime import datetime

from database.db import Base


class PaymentOrder(Base):
    """
    Paylov (wlcm.uz) orqali yaratilgan to'lov buyurtmasi.

    Checkout yaratilganda 'pending' holatda saqlanadi. Webhook kelganda
    `external_id` orqali topiladi va 'paid'/'cancelled' ga o'tkaziladi.
    `external_id` kriptografik tasodifiy qism o'z ichiga oladi — shu sabab uni
    taxmin qilib soxta webhook yuborib bo'lmaydi (xavfsizlik).
    """
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id = Column(String(120), unique=True, nullable=False, index=True)

    plan_key = Column(String(16), nullable=False)       # 7d / 1m / 3m / 6m / 12m
    bonus_days = Column(Integer, default=0)             # promokod bonus kunlari
    promocode = Column(String(64), nullable=True)
    amount = Column(BigInteger, nullable=False)         # tiyinda (so'm * 100)

    provider = Column(String(24), default="paylov")
    provider_order_id = Column(String(64), nullable=True)   # Paylov order_id
    payment_id = Column(String(64), nullable=True)          # Paylov payment_id

    status = Column(String(16), default="pending")      # pending | paid | cancelled
    fiscal_done = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)

    # back_populates ishlatmaymiz — User modeliga tegmaslik uchun (xavfsiz)
    user = relationship("User")
