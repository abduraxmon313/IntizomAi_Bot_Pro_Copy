from sqlalchemy import Column, BigInteger, String, Integer, DateTime, Boolean, Date
from sqlalchemy.orm import relationship
from datetime import datetime
from database.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    # Foydalanuvchi o'zi tahrirlagan ism (Mini App sozlamalari orqali).
    # full_name har /start da Telegram'dan yangilanadi — shuning uchun maxsus ism
    # alohida ustunda saqlanadi va ustunlik beriladi (Telegram sinxronizatsiyasi
    # uni o'chirib yubormaydi).
    display_name = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)

    # Core score (legacy — kept for back-compat)
    streak = Column(Integer, default=0)
    total_score = Column(Integer, default=0)

    # ── Gamification engine ──────────────────────────────
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    longest_streak = Column(Integer, default=0)
    last_completed_date = Column(Date, nullable=True)
    streak_freezes = Column(Integer, default=0)
    discipline_score = Column(Integer, default=50)  # 0..100
    weekly_xp = Column(Integer, default=0)
    perfect_days = Column(Integer, default=0)

    # ── Identity / monetization ──────────────────────────
    is_premium = Column(Boolean, default=False)
    premium_until = Column(DateTime, nullable=True)
    # Avtomatik sinov (trial) berilganmi — bir foydalanuvchiga faqat bir marta.
    trial_used = Column(Boolean, default=False)
    onboarded = Column(Boolean, default=False)
    rank_title = Column(String(40), nullable=True)
    avatar_emoji = Column(String(8), default="🌱")

    # ── AI Coach suhbat limiti (free-tier) ───────────────
    ai_msgs_date = Column(Date, nullable=True)       # oxirgi hisoblangan kun
    ai_msgs_count = Column(Integer, default=0)        # shu kungi AI xabarlar soni

    # ── Referral (taklif) tizimi ─────────────────────────
    # Kim tomonidan taklif qilingan (taklif qiluvchining telegram_id si).
    referred_by = Column(BigInteger, nullable=True)
    # Muvaffaqiyatli taklif qilingan (yangi start bosgan) do'stlar soni.
    referral_count = Column(Integer, default=0)
    # Allaqachon mukofotlangan takliflar soni (5 talik to'plamlar bo'yicha).
    referral_rewards_given = Column(Integer, default=0)

    # ── System ───────────────────────────────────────────
    is_active = Column(Boolean, default=True)
    # Push eslatmalarni yoqish/o'chirish (Mini App sozlamalari orqali).
    notifications_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)

    plans = relationship("Plan", back_populates="user", cascade="all, delete")
    score_logs = relationship("ScoreLog", back_populates="user", cascade="all, delete")
    goals = relationship("Goal", back_populates="user", cascade="all, delete")
    achievements = relationship("Achievement", back_populates="user", cascade="all, delete")
    checkins = relationship("DailyCheckin", back_populates="user", cascade="all, delete")
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete")
    habits = relationship("Habit", back_populates="user", cascade="all, delete")
