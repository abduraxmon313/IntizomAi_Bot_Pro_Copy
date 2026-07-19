from sqlalchemy import (
    Column, Integer, BigInteger, DateTime, ForeignKey, UniqueConstraint
)
from datetime import datetime

from database.db import Base


class Referral(Base):
    """
    Taklif (referral) yozuvi — har bir muvaffaqiyatli taklif uchun bitta qator.

    Bitta yangi foydalanuvchi faqat BIR marta taklif qilingan deb hisoblanadi
    (`referred_telegram_id` unikal). Bu takror sanashning oldini oladi.

    `referrer_telegram_id` — taklif qilgan (havolani ulashgan) foydalanuvchi.
    `referred_telegram_id` — havola orqali kelib /start bosgan YANGI foydalanuvchi.
    `rewarded` — shu taklif mukofot to'plamiga (5 talik) qo'shilganmi.
    """
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referred_telegram_id", name="uq_referrals_referred"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    referrer_telegram_id = Column(BigInteger, nullable=False, index=True)
    referred_telegram_id = Column(BigInteger, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    # Taklif qilingan foydalanuvchi birinchi reja/odat bajarganda qo'yiladi.
    # Faqat shundan keyin invitee'ga bonus va referrer'ning sanog'i beriladi
    # (sifatsiz /start-only takliflarni sanamaslik uchun).
    activated_at = Column(DateTime, nullable=True)
