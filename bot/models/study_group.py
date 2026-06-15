from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime, Boolean, ForeignKey,
    UniqueConstraint,
)
from datetime import datetime

from database.db import Base


class StudyGroup(Base):
    """
    O'quv / mas'uliyat guruhi (accountability circle).

    Foydalanuvchilar guruh tuzadi va do'stlarini taklif kod orqali qo'shadi.
    Guruh ichida umumiy reyting (leaderboard) va umumiy streak bo'ladi —
    bu network effect va switching cost yaratadi.
    """
    __tablename__ = "study_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    invite_code = Column(String(16), unique=True, nullable=False, index=True)
    owner_telegram_id = Column(BigInteger, nullable=False, index=True)
    emoji = Column(String(8), default="👥")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GroupMember(Base):
    """Guruh a'zoligi — bitta foydalanuvchi bitta guruhda (joriy)."""
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "telegram_id", name="uq_group_member"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    joined_at = Column(DateTime, default=datetime.utcnow)
