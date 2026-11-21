from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from database.db import Base


class PartnerOrder(Base):
    """
    Mobil ilova backend'i (alohida Railway loyiha) nomidan yaratilgan Paylov buyurtmasi.

    Ilova foydalanuvchilari bu bazadagi `users` jadvalida YO'Q — shuning uchun
    oddiy `payment_orders` o'rniga alohida jadval. Paylov webhooki shu bot
    serveriga keladi (shartnoma va IP'lar shu Railway hisobga bog'langan), bot
    buyurtmani "paid" qiladi va ilova backend'iga imzolangan callback yuboradi.
    """
    __tablename__ = "partner_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    partner = Column(String(16), nullable=False, default="app")
    external_id = Column(String(120), unique=True, nullable=False, index=True)
    # Ilova tomonidagi buyurtma ID'si (idempotentlik uchun).
    client_ref = Column(String(64), unique=True, nullable=False, index=True)
    app_user_id = Column(BigInteger, nullable=False, index=True)
    app_user_label = Column(String(64), nullable=True)  # admin xabarlari uchun (@username)

    plan_key = Column(String(16), nullable=False)
    # Tarif nomi (chek va admin xabari uchun). Narxni ilova backend'i belgilaganda keladi.
    title = Column(String(64), nullable=True)
    days = Column(Integer, nullable=False)              # tarif kunlari + promokod bonusi
    bonus_days = Column(Integer, default=0)
    promocode = Column(String(64), nullable=True)
    amount = Column(BigInteger, nullable=False)         # tiyin (so'm * 100)

    provider = Column(String(24), nullable=False, default="paylov")
    provider_order_id = Column(String(64), nullable=True)
    payment_id = Column(String(64), nullable=True)
    checkout_url = Column(Text, nullable=True)

    status = Column(String(16), nullable=False, default="pending")  # pending | paid | cancelled
    fiscal_done = Column(Boolean, default=False)

    # Ilova backend'iga natija yetkazish (callback) holati.
    notify_status = Column(String(12), nullable=False, default="none")  # none | pending | sent | failed
    notify_attempts = Column(Integer, nullable=False, default=0)
    notify_next_at = Column(DateTime, nullable=True)
    notify_error = Column(String(300), nullable=True)
    notified_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)


class PartnerPromoRedemption(Base):
    """Bepul ("-") promokodni ilova foydalanuvchisi bir martagina ishlatishi uchun."""
    __tablename__ = "partner_promo_redemptions"
    __table_args__ = (UniqueConstraint("code", "customer_ref", name="uq_partner_promo_customer"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), nullable=False)
    customer_ref = Column(String(80), nullable=False)
    app_user_id = Column(BigInteger, nullable=True)
    days = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
