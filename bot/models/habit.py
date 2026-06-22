from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from database.db import Base
from bot.config import TIMEZONE


def _today_tashkent():
    """Joriy Tashkent sanasi (har chaqirilganda yangidan hisoblanadi)."""
    return datetime.now(TIMEZONE).date()


class Habit(Base):
    """
    Odat (habit) — rejalardan (plans) va maqsadlardan (goals) ALOHIDA tushuncha.

      • Reja  — bir martalik, har kuni har xil bo'ladigan ish (vaqtga bog'liq).
      • Maqsad — uzoq muddatli natija (yillik/oylik/haftalik/kunlik).
      • Odat  — har kuni takrorlanadigan, streak (ketma-ketlik) yig'iladigan amal.

    Har bir odat har kuni "bajarildi" deb belgilanadi (HabitLog yozuvi orqali),
    shu asosda joriy streak va bugungi holat hisoblanadi.
    """
    __tablename__ = "habits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    icon = Column(String(8), default="✅")           # emoji belgi
    sort_order = Column(Integer, default=0)            # ro'yxatdagi tartib
    archived = Column(Boolean, default=False)          # arxivlangan (yashirilgan)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="habits")
    logs = relationship("HabitLog", back_populates="habit", cascade="all, delete")


class HabitLog(Base):
    """Odatning bir kunlik bajarilish yozuvi (kuniga bittadan ko'p emas)."""
    __tablename__ = "habit_logs"
    __table_args__ = (
        UniqueConstraint("habit_id", "log_date", name="uq_habit_log_day"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    habit_id = Column(Integer, ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    log_date = Column(Date, default=_today_tashkent)
    created_at = Column(DateTime, default=datetime.utcnow)

    habit = relationship("Habit", back_populates="logs")
