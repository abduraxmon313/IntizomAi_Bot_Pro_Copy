"""
Admin tomonidan o'zgartirilgan obuna tarif narxlari.

`bot/config.py`'dagi `SUBSCRIPTION_PLANS` — bu default katalog (tarif kalitlari,
kunlar soni, emoji, teg). Narxlarni admin `/admin` panel orqali o'zgartirsa,
override qiymati shu jadvalda saqlanadi va `plan_pricing` service u orqali
"effective" narxlarni yig'ib chiqadi.

Muhim: mavjud (allaqachon yaratilgan) `payment_orders` yozuvlaridagi `amount`
o'zgartirilmaydi — ular yaratilgan paytdagi narxni saqlab qoladi. Bu Paylov
webhook'i bilan miqdor moslashuvi buzilmasligi uchun.
"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String

from database.db import Base


class SubscriptionPlanOverride(Base):
    __tablename__ = "subscription_plan_overrides"

    # plan_key — 1m | 3m | 12m (bot/config.py SUBSCRIPTION_PLANS bilan mos)
    plan_key = Column(String(16), primary_key=True)
    # so'mda (Paylov'ga yuborishda service qatlami tiyinga aylantiradi).
    price = Column(Integer, nullable=False)
    # Tugma yozuvi va bezaklarni ham override qilish mumkin — admin narxni
    # o'zgartirsa, tugma matni ham u bilan mos kelishi uchun (nullable — bo'sh
    # bo'lsa config'dagi default ishlatiladi).
    title = Column(String(64), nullable=True)
    emoji = Column(String(8), nullable=True)
    tag = Column(String(64), nullable=True)
    updated_by = Column(BigInteger, nullable=True)   # admin telegram_id
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
